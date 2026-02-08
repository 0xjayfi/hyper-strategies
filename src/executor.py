"""Order execution engine for Hyperliquid copy-trading.

Implements Phase 6 (Track 5): translates approved Signals into on-chain
orders via the hyperliquid-python-sdk, places protective stop-loss orders,
and records positions in the local database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from src.config import settings
from src.models import ExecutionResult, Signal
from src import db

log = structlog.get_logger()

# Maximum leverage allowed regardless of what the signal requests.
MAX_LEVERAGE = 5

# Precision table for converting USD to token size.  Maps token symbol to the
# number of decimal places the exchange accepts for order size.  Tokens not
# listed here default to 4 decimals.
_SIZE_DECIMALS: dict[str, int] = {
    "BTC": 5,
    "ETH": 4,
    "SOL": 2,
    "HYPE": 1,
    "DOGE": 0,
    "XRP": 1,
    "ARB": 1,
    "AVAX": 2,
    "MATIC": 1,
    "LINK": 2,
    "OP": 1,
    "SUI": 1,
}

_DEFAULT_SIZE_DECIMALS = 4

# Price rounding decimals per token for limit / trigger prices.
_PRICE_DECIMALS: dict[str, int] = {
    "BTC": 1,
    "ETH": 2,
    "SOL": 3,
    "HYPE": 4,
    "DOGE": 5,
    "XRP": 4,
    "ARB": 4,
    "AVAX": 3,
    "MATIC": 4,
    "LINK": 3,
    "OP": 4,
    "SUI": 4,
}

_DEFAULT_PRICE_DECIMALS = 4


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def usd_to_size(usd_value: float, token: str, mark_price: float) -> float:
    """Convert a USD notional value to a token quantity.

    Rounds to the exchange-accepted precision for the given token.

    Args:
        usd_value: Notional value in US dollars.
        token: Token symbol (e.g. ``"BTC"``).
        mark_price: Current mark price in USD.

    Returns:
        Token quantity rounded to the appropriate number of decimals.
    """
    if mark_price <= 0:
        return 0.0
    raw = usd_value / mark_price
    decimals = _SIZE_DECIMALS.get(token, _DEFAULT_SIZE_DECIMALS)
    return round(raw, decimals)


def _round_price(price: float, token: str) -> float:
    """Round a price to exchange-appropriate precision for the token."""
    decimals = _PRICE_DECIMALS.get(token, _DEFAULT_PRICE_DECIMALS)
    return round(price, decimals)


def compute_stop_price(entry_price: float, side: str) -> float:
    """Compute the hard stop-loss trigger price.

    For longs the stop sits *below* entry; for shorts it sits *above*.

    Args:
        entry_price: The fill price of the entry order.
        side: ``"Long"`` or ``"Short"``.

    Returns:
        The trigger price for the stop-loss order.
    """
    pct = settings.STOP_LOSS_PERCENT / 100.0
    if side == "Long":
        return entry_price * (1.0 - pct)
    return entry_price * (1.0 + pct)


def compute_trailing_stop_initial(entry_price: float, side: str) -> float:
    """Compute the initial trailing-stop price at entry time.

    The trailing stop is wider than the hard stop and will be dynamically
    ratcheted as PnL grows (handled by the position-monitor loop).

    Args:
        entry_price: The fill price of the entry order.
        side: ``"Long"`` or ``"Short"``.

    Returns:
        The initial trailing-stop trigger price.
    """
    pct = settings.TRAILING_STOP_PERCENT / 100.0
    if side == "Long":
        return entry_price * (1.0 - pct)
    return entry_price * (1.0 + pct)


def compute_limit_price(side: str, current_price: float, max_slippage: float) -> float:
    """Adjust a price by the maximum allowed slippage percentage.

    For buys the limit price is *above* current price (willing to pay more);
    for sells it is *below* (willing to receive less).

    Args:
        side: ``"Long"`` (buy) or ``"Short"`` (sell).
        current_price: The current mark / mid price.
        max_slippage: Maximum slippage as a percentage (e.g. ``0.5`` for 0.5 %).

    Returns:
        The slippage-adjusted limit price.
    """
    factor = max_slippage / 100.0
    if side == "Long":
        return current_price * (1.0 + factor)
    return current_price * (1.0 - factor)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class HyperLiquidExecutor:
    """Translates approved :class:`Signal` objects into Hyperliquid orders.

    Wraps the synchronous *hyperliquid-python-sdk* client so every SDK call
    is run in a thread-pool executor to keep the async event loop responsive.

    In **paper mode** (``settings.PAPER_MODE``) no real orders are sent;
    instead the executor simulates fills at the current mark price and still
    records positions in the database for downstream monitoring.
    """

    def __init__(self, sdk_client: object) -> None:
        self.client = sdk_client

    # -- SDK wrappers (sync -> async) ----------------------------------------

    async def _place_order(
        self,
        coin: str,
        is_buy: bool,
        sz: float,
        limit_px: float,
        order_type: dict,
        reduce_only: bool = False,
    ) -> dict:
        """Place an order via the SDK, wrapped for async."""
        return await asyncio.to_thread(
            self.client.order,
            coin,
            is_buy,
            sz,
            limit_px,
            order_type,
            reduce_only,
        )

    async def _set_leverage(self, leverage: int, coin: str) -> None:
        """Set isolated-margin leverage for a coin."""
        await asyncio.to_thread(
            self.client.update_leverage,
            leverage,
            coin,
            False,  # is_cross=False -> isolated margin
        )

    async def get_mark_price(self, token: str) -> float:
        """Fetch the current mid-market price for *token*.

        Returns:
            The mark price as a float, or ``0.0`` if the token is not found.
        """
        all_mids: dict = await asyncio.to_thread(self.client.info.all_mids)
        price_str = all_mids.get(token)
        if price_str is None:
            log.warning("mark_price_not_found", token=token, available_count=len(all_mids))
            return 0.0
        return float(price_str)

    # -- Paper-mode helpers --------------------------------------------------

    @staticmethod
    def _paper_fill(
        signal: Signal,
        mark_price: float,
        size: float,
    ) -> ExecutionResult:
        """Simulate a fill for paper trading."""
        return ExecutionResult(
            success=True,
            order_id=f"paper-{signal.id}",
            fill_price=mark_price,
            fill_size=size,
        )

    # -- Response parsing ----------------------------------------------------

    @staticmethod
    def _parse_order_response(response: dict) -> ExecutionResult:
        """Parse the SDK order response into an :class:`ExecutionResult`.

        Expected success shape::

            {
                "status": "ok",
                "response": {
                    "type": "order",
                    "data": {
                        "statuses": [
                            {"filled": {"totalSz": "0.5", "avgPx": "67000.0"}}
                        ]
                    }
                }
            }

        Any other shape is treated as a failure.
        """
        if response.get("status") != "ok":
            error_msg = str(response)
            return ExecutionResult(success=False, error=error_msg)

        try:
            statuses = (
                response["response"]["data"]["statuses"]
            )
            first = statuses[0]

            # Check for a "filled" status.
            if "filled" in first:
                filled = first["filled"]
                return ExecutionResult(
                    success=True,
                    order_id=None,
                    fill_price=float(filled["avgPx"]),
                    fill_size=float(filled["totalSz"]),
                )

            # Check for a "resting" status (limit order accepted but not yet filled).
            if "resting" in first:
                resting = first["resting"]
                return ExecutionResult(
                    success=True,
                    order_id=str(resting.get("oid", "")),
                    fill_price=None,
                    fill_size=None,
                )

            # Check for an explicit error status.
            if "error" in first:
                return ExecutionResult(success=False, error=first["error"])

            return ExecutionResult(success=False, error=f"unexpected status: {first}")

        except (KeyError, IndexError, TypeError) as exc:
            return ExecutionResult(
                success=False,
                error=f"response_parse_error: {exc} | raw={response}",
            )

    # -- Core execution ------------------------------------------------------

    async def execute_signal(self, signal: Signal) -> ExecutionResult:
        """Execute an approved signal: place entry + stop orders atomically.

        Steps:
            1. Fetch current mark price.
            2. Determine leverage (capped at :data:`MAX_LEVERAGE`).
            3. Set isolated margin leverage on the exchange.
            4. Place the entry order (market IOC or limit GTC).
            5. On successful fill, place a hard stop-loss trigger order.
            6. Record the new position in the database.

        If ``settings.PAPER_MODE`` is ``True``, no real orders are placed.
        The method simulates a fill at mark price and still records the
        position in the database so downstream monitoring can operate normally.

        Args:
            signal: An approved :class:`Signal` with ``decision == "EXECUTE"``.

        Returns:
            An :class:`ExecutionResult` describing the outcome.
        """
        token = signal.token_symbol
        is_buy = signal.side == "Long"

        log.info(
            "execute_signal_start",
            signal_id=signal.id,
            token=token,
            side=signal.side,
            copy_size_usd=signal.copy_size_usd,
            order_type=signal.order_type,
            paper_mode=settings.PAPER_MODE,
        )

        # 1. Mark price
        try:
            mark_price = await self.get_mark_price(token)
        except Exception:
            log.exception("mark_price_fetch_failed", token=token)
            return ExecutionResult(success=False, error="mark_price_fetch_failed")

        if mark_price <= 0:
            log.error("mark_price_zero_or_negative", token=token, mark_price=mark_price)
            return ExecutionResult(success=False, error="mark_price_zero_or_negative")

        # 2. Leverage (cap at MAX_LEVERAGE, default to 1x)
        leverage = signal.leverage if signal.leverage is not None else 1.0
        leverage = int(min(leverage, MAX_LEVERAGE))
        leverage = max(leverage, 1)

        # 3. Order size
        size = usd_to_size(signal.copy_size_usd, token, mark_price)
        if size <= 0:
            log.error("computed_size_zero", token=token, copy_size_usd=signal.copy_size_usd)
            return ExecutionResult(success=False, error="computed_size_zero")

        # -- Paper mode: simulate fill, skip real orders ----------------------
        if settings.PAPER_MODE:
            log.info(
                "paper_mode_simulated_fill",
                signal_id=signal.id,
                token=token,
                side=signal.side,
                size=size,
                mark_price=mark_price,
                leverage=leverage,
            )
            entry_result = self._paper_fill(signal, mark_price, size)
            fill_price = mark_price
            fill_size = size

            # Record in DB (same as live path).
            stop_price = compute_stop_price(fill_price, signal.side)
            trailing_stop = compute_trailing_stop_initial(fill_price, signal.side)

            await self._record_position(
                signal=signal,
                fill_price=fill_price,
                fill_size=fill_size,
                stop_price=stop_price,
                trailing_stop=trailing_stop,
                leverage=leverage,
            )
            return entry_result

        # -- Live execution ---------------------------------------------------
        # 3b. Set leverage (isolated margin).
        try:
            await self._set_leverage(leverage, token)
            log.info("leverage_set", token=token, leverage=leverage)
        except Exception:
            log.exception("set_leverage_failed", token=token, leverage=leverage)
            return ExecutionResult(success=False, error="set_leverage_failed")

        # 4. Build order type payload and limit price.
        if signal.order_type == "market":
            limit_px = _round_price(
                compute_limit_price(signal.side, mark_price, signal.max_slippage),
                token,
            )
            ot_payload: dict = {"limit": {"tif": "Ioc"}}
        else:
            # Limit / GTC
            limit_px = _round_price(
                compute_limit_price(signal.side, mark_price, signal.max_slippage),
                token,
            )
            ot_payload = {"limit": {"tif": "Gtc"}}

        # 5. Place entry order.
        try:
            raw_response = await self._place_order(
                coin=token,
                is_buy=is_buy,
                sz=size,
                limit_px=limit_px,
                order_type=ot_payload,
            )
            log.info(
                "entry_order_placed",
                signal_id=signal.id,
                token=token,
                side=signal.side,
                size=size,
                limit_px=limit_px,
                order_type=signal.order_type,
            )
        except Exception:
            log.exception("entry_order_failed", signal_id=signal.id, token=token)
            return ExecutionResult(success=False, error="entry_order_failed")

        entry_result = self._parse_order_response(raw_response)

        if not entry_result.success:
            log.error(
                "entry_order_rejected",
                signal_id=signal.id,
                token=token,
                error=entry_result.error,
            )
            return entry_result

        # Determine fill price — may be None for resting limit orders.
        fill_price = entry_result.fill_price if entry_result.fill_price else mark_price
        fill_size = entry_result.fill_size if entry_result.fill_size else size

        # 6. Place hard stop-loss order on the opposite side.
        stop_trigger = _round_price(
            compute_stop_price(fill_price, signal.side),
            token,
        )
        stop_ot: dict = {
            "trigger": {
                "triggerPx": str(stop_trigger),
                "isMarket": True,
                "tpsl": "sl",
            },
        }
        stop_is_buy = not is_buy  # Opposite side to close.

        try:
            stop_response = await self._place_order(
                coin=token,
                is_buy=stop_is_buy,
                sz=fill_size,
                limit_px=stop_trigger,
                order_type=stop_ot,
                reduce_only=True,
            )
            stop_result = self._parse_order_response(stop_response)
            if not stop_result.success:
                log.error(
                    "stop_order_rejected",
                    signal_id=signal.id,
                    token=token,
                    error=stop_result.error,
                )
            else:
                log.info(
                    "stop_order_placed",
                    signal_id=signal.id,
                    token=token,
                    trigger_price=stop_trigger,
                )
        except Exception:
            log.exception("stop_order_failed", signal_id=signal.id, token=token)
            # Entry succeeded — continue to record position even if stop fails.
            # The position monitor will detect the missing stop and re-place it.

        # 7. Record position in database.
        trailing_stop = compute_trailing_stop_initial(fill_price, signal.side)

        await self._record_position(
            signal=signal,
            fill_price=fill_price,
            fill_size=fill_size,
            stop_price=stop_trigger,
            trailing_stop=trailing_stop,
            leverage=leverage,
        )

        log.info(
            "execute_signal_complete",
            signal_id=signal.id,
            token=token,
            side=signal.side,
            fill_price=fill_price,
            fill_size=fill_size,
            stop_price=stop_trigger,
        )

        return entry_result

    # -- Position management (used by position_monitor) ----------------------

    async def close_position_on_exchange(
        self,
        token: str,
        side: str,
        size: float,
    ) -> ExecutionResult:
        """Market-close a position (or reduce by *size*).

        Args:
            token: Token symbol (e.g. ``"BTC"``).
            side: Original position side (``"Long"`` or ``"Short"``).
            size: Number of tokens to close.

        Returns:
            :class:`ExecutionResult` describing the outcome.
        """
        is_buy = side == "Short"  # Close a Long by selling, close a Short by buying.

        if settings.PAPER_MODE:
            mark_price = await self.get_mark_price(token)
            log.info(
                "paper_mode_close",
                token=token,
                side=side,
                size=size,
                mark_price=mark_price,
            )
            return ExecutionResult(
                success=True,
                order_id=f"paper-close-{token}",
                fill_price=mark_price,
                fill_size=size,
            )

        mark_price = await self.get_mark_price(token)
        if mark_price <= 0:
            return ExecutionResult(success=False, error="mark_price_zero_or_negative")

        limit_px = _round_price(
            compute_limit_price("Long" if is_buy else "Short", mark_price, 0.5),
            token,
        )
        ot_payload: dict = {"limit": {"tif": "Ioc"}}

        try:
            raw = await self._place_order(
                coin=token,
                is_buy=is_buy,
                sz=size,
                limit_px=limit_px,
                order_type=ot_payload,
                reduce_only=True,
            )
            return self._parse_order_response(raw)
        except Exception:
            log.exception("close_position_on_exchange_failed", token=token, side=side)
            return ExecutionResult(success=False, error="close_order_failed")

    async def cancel_stop_orders(self, token: str) -> None:
        """Cancel all open trigger (stop) orders for *token*.

        Uses the SDK ``cancel_by_cloid`` approach: fetch open orders, filter
        for trigger orders matching *token*, and cancel each one.
        """
        if settings.PAPER_MODE:
            log.info("paper_mode_cancel_stops", token=token)
            return

        try:
            open_orders = await asyncio.to_thread(
                self.client.info.frontend_open_orders,
                self.client.wallet.address,
            )
            for order in open_orders:
                if order.get("coin") == token and order.get("orderType") == "trigger":
                    oid = order.get("oid")
                    if oid is not None:
                        await asyncio.to_thread(
                            self.client.cancel, token, oid,
                        )
                        log.info("stop_order_cancelled", token=token, oid=oid)
        except Exception:
            log.exception("cancel_stop_orders_failed", token=token)

    async def place_stop_order(
        self,
        token: str,
        side: str,
        size: float,
        trigger_price: float,
    ) -> None:
        """Place a new stop-loss trigger order.

        Args:
            token: Token symbol.
            side: Position side (``"Long"`` or ``"Short"``).
                  The stop order will be on the *opposite* side (reduce-only).
            size: Number of tokens.
            trigger_price: Price at which the stop triggers.
        """
        if settings.PAPER_MODE:
            log.info("paper_mode_place_stop", token=token, trigger_price=trigger_price)
            return

        is_buy = side == "Short"
        rounded_trigger = _round_price(trigger_price, token)
        ot_payload: dict = {
            "trigger": {
                "triggerPx": str(rounded_trigger),
                "isMarket": True,
                "tpsl": "sl",
            },
        }
        try:
            await self._place_order(
                coin=token,
                is_buy=is_buy,
                sz=size,
                limit_px=rounded_trigger,
                order_type=ot_payload,
                reduce_only=True,
            )
            log.info("stop_order_placed", token=token, trigger_price=rounded_trigger)
        except Exception:
            log.exception(
                "place_stop_order_failed",
                token=token,
                trigger_price=rounded_trigger,
            )

    # -- DB recording --------------------------------------------------------

    @staticmethod
    async def _record_position(
        signal: Signal,
        fill_price: float,
        fill_size: float,
        stop_price: float,
        trailing_stop: float,
        leverage: int,
    ) -> None:
        """Persist a newly opened position to the database."""
        value_usd = fill_price * fill_size

        try:
            row_id = await db.insert_our_position(
                token_symbol=signal.token_symbol,
                side=signal.side,
                entry_price=fill_price,
                size=fill_size,
                value_usd=value_usd,
                stop_price=stop_price,
                trailing_stop_price=trailing_stop,
                highest_price=fill_price if signal.side == "Long" else None,
                lowest_price=fill_price if signal.side == "Short" else None,
                opened_at=datetime.now(timezone.utc).isoformat(),
                source_trader=signal.trader_address,
                source_signal_id=signal.id,
                status="open",
            )
            log.info(
                "position_recorded",
                row_id=row_id,
                token=signal.token_symbol,
                side=signal.side,
                entry_price=fill_price,
                size=fill_size,
                value_usd=round(value_usd, 2),
            )
        except Exception:
            log.exception(
                "position_record_failed",
                signal_id=signal.id,
                token=signal.token_symbol,
            )
