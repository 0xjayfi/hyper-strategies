"""Execution engine for placing, tracking, and reconciling orders.

Implements Phase 4 of the specification:

1. ``HyperliquidClient`` — Abstract protocol for exchange interaction.
2. ``PaperTradeClient`` — Simulated fills for backtesting / paper mode.
3. Order-type selection, slippage calculation, stop-price helpers.
4. ``poll_for_fill`` — Polling loop for limit-order fills.
5. ``execute_rebalance`` — Main orchestrator that turns RebalanceActions
   into database-tracked orders with position and PnL bookkeeping.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

from snap.config import (
    MAX_LEVERAGE,
    MAX_POSITION_DURATION_HOURS,
    MARGIN_TYPE,
    SLIPPAGE_BPS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.database import get_connection, init_db
from snap.portfolio import RebalanceAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. HyperliquidClient Protocol (ABC)
# ---------------------------------------------------------------------------


class HyperliquidClient(ABC):
    """Abstract interface for interacting with the Hyperliquid exchange."""

    @abstractmethod
    async def place_order(
        self,
        token: str,
        side: str,
        size: float,
        order_type: str,
        price: float | None = None,
        leverage: int = MAX_LEVERAGE,
        margin_type: str = MARGIN_TYPE,
    ) -> dict:
        """Place an order and return ``{"order_id": str, "status": str}``."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.  Returns ``True`` on success."""
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict:
        """Return ``{"status": str, "filled_size": float, "avg_price": float, "fee": float}``."""
        ...

    @abstractmethod
    async def get_mark_price(self, token: str) -> float:
        """Return the current mark price for *token*."""
        ...


# ---------------------------------------------------------------------------
# 2. PaperTradeClient
# ---------------------------------------------------------------------------


class PaperTradeClient(HyperliquidClient):
    """Simulated exchange client for paper-trading / backtesting.

    All orders are filled immediately at mark_price +/- slippage.

    Parameters
    ----------
    mark_prices:
        Mapping of token symbol to its current mark price.
    """

    def __init__(
        self, mark_prices: dict[str, float], *, live_prices: bool = False
    ) -> None:
        self._mark_prices = dict(mark_prices)
        self._live_prices = live_prices
        # Track the last order for get_order_status lookups
        self._orders: dict[str, dict] = {}

    # -- helpers ----------------------------------------------------------

    def set_mark_price(self, token: str, price: float) -> None:
        """Update the mark price for a token."""
        self._mark_prices[token] = price

    async def refresh_mark_prices(self) -> int:
        """Fetch live mark prices from Hyperliquid public API.

        Only runs when ``live_prices=True`` was passed to the constructor.
        Returns the number of prices updated.
        """
        if not self._live_prices:
            return 0

        import httpx

        url = "https://api.hyperliquid.xyz/info"
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.post(url, json={"type": "metaAndAssetCtxs"})
                resp.raise_for_status()
            data = resp.json()
            universe = data[0]["universe"]
            ctxs = data[1]
            count = 0
            for asset, ctx in zip(universe, ctxs):
                name = asset["name"]
                mark = float(ctx.get("markPx", 0))
                if mark > 0:
                    self._mark_prices[name] = mark
                    count += 1
            return count
        except Exception:
            logger.warning("Failed to fetch Hyperliquid mark prices", exc_info=True)
            return 0

    def _simulate_fill_price(
        self, token: str, side: str, order_type: str, is_close: bool
    ) -> float:
        """Compute simulated fill price with slippage applied."""
        mark = self._mark_prices.get(token, 0.0)
        bps = get_slippage_bps(token)

        if is_close:
            # Closing: slippage works against us in the opposite direction
            if side == "Long":
                # Closing a long = selling -> price slips down
                return mark * (1 - bps / 10_000)
            else:
                # Closing a short = buying -> price slips up
                return mark * (1 + bps / 10_000)
        else:
            # Opening / increasing
            if side == "Long":
                # Buying -> price slips up
                return mark * (1 + bps / 10_000)
            else:
                # Selling short -> price slips down
                return mark * (1 - bps / 10_000)

    # -- ABC implementation -----------------------------------------------

    async def place_order(
        self,
        token: str,
        side: str,
        size: float,
        order_type: str,
        price: float | None = None,
        leverage: int = MAX_LEVERAGE,
        margin_type: str = MARGIN_TYPE,
        is_close: bool = False,
    ) -> dict:
        """Immediately fill the order at simulated price."""
        order_id = str(uuid.uuid4())
        fill_price = self._simulate_fill_price(token, side, order_type, is_close)
        fee = abs(size * fill_price) * 0.0005  # 5 bps fee simulation

        info: dict[str, Any] = {
            "order_id": order_id,
            "status": "FILLED",
            "filled_size": size,
            "avg_price": fill_price,
            "fee": fee,
        }
        self._orders[order_id] = info
        return info

    async def cancel_order(self, order_id: str) -> bool:
        """Always succeeds in paper mode."""
        return True

    async def get_order_status(self, order_id: str) -> dict:
        """Return stored fill info for the given order."""
        if order_id in self._orders:
            return self._orders[order_id]
        return {
            "status": "CANCELLED",
            "filled_size": 0.0,
            "avg_price": 0.0,
            "fee": 0.0,
        }

    async def get_mark_price(self, token: str) -> float:
        """Return the configured mark price for *token*."""
        return self._mark_prices.get(token, 0.0)


# ---------------------------------------------------------------------------
# 3. Order Type Selection
# ---------------------------------------------------------------------------


def select_order_type(action: RebalanceAction) -> str:
    """Decide MARKET vs LIMIT based on the rebalance action.

    Rules
    -----
    - CLOSE / DECREASE -> always MARKET (urgency to reduce risk).
    - OPEN (current_usd == 0) -> always MARKET (delta > 0.20 * 0 is true).
    - INCREASE with ``|delta_usd| > 0.20 * current_usd`` -> MARKET.
    - INCREASE with ``|delta_usd| <= 0.20 * current_usd`` -> LIMIT.
    """
    if action.action in ("CLOSE", "DECREASE"):
        return "MARKET"

    # OPEN or INCREASE
    if action.current_usd == 0:
        return "MARKET"

    if abs(action.delta_usd) > 0.20 * action.current_usd:
        return "MARKET"

    return "LIMIT"


# ---------------------------------------------------------------------------
# 4. Slippage Calculation
# ---------------------------------------------------------------------------


def get_slippage_bps(token_symbol: str) -> int:
    """Return the slippage budget in basis points for *token_symbol*."""
    return SLIPPAGE_BPS.get(token_symbol, SLIPPAGE_BPS["DEFAULT"])


def compute_limit_price(mark_price: float, side: str, token_symbol: str) -> float:
    """Compute the limit price including slippage for a new/increase order.

    For Long (buy): price is *above* mark → ``mark * (1 + bps / 10_000)``.
    For Short (sell): price is *below* mark → ``mark * (1 - bps / 10_000)``.
    """
    bps = get_slippage_bps(token_symbol)
    if side == "Long":
        return mark_price * (1 + bps / 10_000)
    else:
        return mark_price * (1 - bps / 10_000)


# ---------------------------------------------------------------------------
# 5. Stop Price Calculators
# ---------------------------------------------------------------------------


def compute_stop_loss_price(entry_price: float, side: str) -> float:
    """Compute the fixed stop-loss price.

    Long: ``entry * (1 - STOP_LOSS_PERCENT / 100)``
    Short: ``entry * (1 + STOP_LOSS_PERCENT / 100)``
    """
    if side == "Long":
        return entry_price * (1 - STOP_LOSS_PERCENT / 100)
    else:
        return entry_price * (1 + STOP_LOSS_PERCENT / 100)


def compute_initial_trailing_stop(entry_price: float, side: str) -> float:
    """Compute the initial trailing-stop price.

    Long: ``entry * (1 - TRAILING_STOP_PERCENT / 100)``
    Short: ``entry * (1 + TRAILING_STOP_PERCENT / 100)``
    """
    if side == "Long":
        return entry_price * (1 - TRAILING_STOP_PERCENT / 100)
    else:
        return entry_price * (1 + TRAILING_STOP_PERCENT / 100)


# ---------------------------------------------------------------------------
# 6. Fill Polling Loop
# ---------------------------------------------------------------------------


async def poll_for_fill(
    client: HyperliquidClient,
    order_id: str,
    timeout_s: float = 300,
    interval_s: float = 30,
) -> dict:
    """Poll for an order fill until filled, timeout, or cancellation.

    Parameters
    ----------
    client:
        Exchange client implementing ``get_order_status`` and ``cancel_order``.
    order_id:
        The exchange order ID to poll.
    timeout_s:
        Maximum time to wait in seconds (default 300 = 5 minutes).
    interval_s:
        Polling interval in seconds (default 30).

    Returns
    -------
    dict
        ``{"status": "FILLED"/"PARTIAL"/"CANCELLED",
           "filled_size": float, "avg_price": float, "fee": float}``
    """
    deadline = asyncio.get_event_loop().time() + timeout_s

    while True:
        status = await client.get_order_status(order_id)

        if status["status"] == "FILLED":
            return status

        now = asyncio.get_event_loop().time()
        if now >= deadline:
            # Timeout — cancel remaining
            await client.cancel_order(order_id)
            # Re-check in case of partial fill
            status = await client.get_order_status(order_id)
            if status.get("filled_size", 0.0) > 0:
                status["status"] = "PARTIAL"
            else:
                status["status"] = "CANCELLED"
            return status

        await asyncio.sleep(interval_s)


# ---------------------------------------------------------------------------
# 7. execute_rebalance() Orchestrator
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _max_close_at() -> str:
    """Return the max close-at timestamp (now + MAX_POSITION_DURATION_HOURS)."""
    dt = datetime.now(timezone.utc) + timedelta(hours=MAX_POSITION_DURATION_HOURS)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def execute_rebalance(
    client: HyperliquidClient,
    rebalance_id: str,
    actions: list[RebalanceAction],
    db_path: str,
) -> dict:
    """Execute a list of rebalance actions, tracking everything in the DB.

    For each :class:`RebalanceAction`:

    1. Select order type (MARKET / LIMIT).
    2. Compute limit price if LIMIT order.
    3. Compute order size ``= |delta_usd| / mark_price``.
    4. Insert an ``orders`` row (status=PENDING).
    5. Place order via *client* -> update to SENT.
    6. Wait for fill (immediate for MARKET / paper; poll for LIMIT).
    7. On fill, update ``orders``, ``our_positions``, and ``pnl_ledger``.

    Parameters
    ----------
    client:
        Exchange client (real or paper).
    rebalance_id:
        UUID string for this rebalance cycle.
    actions:
        Ordered list of rebalance actions to execute.
    db_path:
        Path to the SQLite database.

    Returns
    -------
    dict
        Summary: ``{"orders_sent": int, "orders_filled": int,
                     "orders_failed": int, "total_slippage_bps": float}``
    """
    summary = {
        "orders_sent": 0,
        "orders_filled": 0,
        "orders_failed": 0,
        "total_slippage_bps": 0.0,
    }

    for action in actions:
        try:
            await _execute_single_action(client, rebalance_id, action, db_path, summary)
        except Exception:
            logger.exception(
                "Failed to execute action %s %s %s",
                action.action,
                action.token_symbol,
                action.side,
            )
            summary["orders_failed"] += 1

    return summary


async def _execute_single_action(
    client: HyperliquidClient,
    rebalance_id: str,
    action: RebalanceAction,
    db_path: str,
    summary: dict,
) -> None:
    """Process one RebalanceAction end-to-end."""
    token = action.token_symbol
    side = action.side

    # 1. Select order type
    order_type = select_order_type(action)

    # 2. Get mark price and compute limit price
    mark_price = action.mark_price
    if mark_price <= 0:
        mark_price = await client.get_mark_price(token)

    # Feed resolved mark price into paper client for accurate fills
    if isinstance(client, PaperTradeClient) and mark_price > 0:
        client.set_mark_price(token, mark_price)

    limit_price: float | None = None
    if order_type == "LIMIT":
        limit_price = compute_limit_price(mark_price, side, token)

    # 3. Compute order size
    if mark_price <= 0:
        logger.error("Mark price is 0 for %s, skipping", token)
        summary["orders_failed"] += 1
        return

    size = abs(action.delta_usd) / mark_price

    # 4. Insert order row as PENDING
    now = _now_utc()
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO orders
                   (rebalance_id, token_symbol, side, order_type,
                    intended_usd, intended_size, limit_price, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                (
                    rebalance_id,
                    token,
                    side,
                    order_type,
                    abs(action.delta_usd),
                    size,
                    limit_price,
                    now,
                ),
            )
            order_row_id = cur.lastrowid
    finally:
        conn.close()

    # 5. Place order via client
    is_close = action.action in ("CLOSE", "DECREASE")
    place_kwargs: dict[str, Any] = {
        "token": token,
        "side": side,
        "size": size,
        "order_type": order_type,
    }
    if limit_price is not None:
        place_kwargs["price"] = limit_price

    # Pass is_close to PaperTradeClient (duck-typed extra kwarg)
    if isinstance(client, PaperTradeClient):
        place_kwargs["is_close"] = is_close

    result = await client.place_order(**place_kwargs)
    hl_order_id = result.get("order_id", "")

    # Update status to SENT
    sent_at = _now_utc()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """UPDATE orders SET status = 'SENT', hl_order_id = ?, sent_at = ?
                   WHERE id = ?""",
                (hl_order_id, sent_at, order_row_id),
            )
    finally:
        conn.close()

    summary["orders_sent"] += 1

    # 6. Wait for fill
    if result.get("status") == "FILLED":
        fill_info = result
    elif order_type == "MARKET":
        # For real market orders, assume immediate fill from placement result
        fill_info = result
    else:
        # LIMIT order — poll
        fill_info = await poll_for_fill(client, hl_order_id)

    # 7. Process fill result
    fill_status = fill_info.get("status", "FAILED")
    filled_size = fill_info.get("filled_size", 0.0)
    filled_avg_price = fill_info.get("avg_price", 0.0)
    fee_usd = fill_info.get("fee", 0.0)
    filled_usd = filled_size * filled_avg_price

    # Compute actual slippage
    if mark_price > 0 and filled_avg_price > 0:
        actual_slippage = abs(filled_avg_price - mark_price) / mark_price * 10_000
    else:
        actual_slippage = 0.0

    # Update orders row
    filled_at = _now_utc()
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """UPDATE orders
                   SET status = ?, filled_at = ?, filled_size = ?,
                       filled_avg_price = ?, filled_usd = ?,
                       slippage_bps = ?, fee_usd = ?
                   WHERE id = ?""",
                (
                    fill_status,
                    filled_at,
                    filled_size,
                    filled_avg_price,
                    filled_usd,
                    actual_slippage,
                    fee_usd,
                    order_row_id,
                ),
            )
    finally:
        conn.close()

    if fill_status in ("FILLED", "PARTIAL"):
        summary["orders_filled"] += 1
        summary["total_slippage_bps"] += actual_slippage

        # Position and PnL bookkeeping
        if action.action in ("OPEN", "INCREASE"):
            _upsert_position(
                db_path=db_path,
                token=token,
                side=side,
                size=filled_size,
                entry_price=filled_avg_price,
                mark_price=mark_price,
                action_type=action.action,
                leverage=MAX_LEVERAGE,
            )
        elif action.action == "CLOSE":
            _close_position(
                db_path=db_path,
                token=token,
                side=side,
                exit_price=filled_avg_price,
                exit_size=filled_size,
                fee_usd=fee_usd,
            )
        elif action.action == "DECREASE":
            _decrease_position(
                db_path=db_path,
                token=token,
                decrease_size=filled_size,
                current_price=filled_avg_price,
            )
    else:
        # CANCELLED / FAILED
        summary["orders_failed"] += 1
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE orders SET error_msg = ? WHERE id = ?",
                    (f"Order {fill_status}", order_row_id),
                )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Position bookkeeping helpers
# ---------------------------------------------------------------------------


def _upsert_position(
    db_path: str,
    token: str,
    side: str,
    size: float,
    entry_price: float,
    mark_price: float,
    action_type: str,
    leverage: int = 5,
) -> None:
    """Insert or update a row in our_positions for OPEN / INCREASE."""
    now = _now_utc()
    max_close = _max_close_at()
    position_usd = size * entry_price
    stop_loss = compute_stop_loss_price(entry_price, side)
    trailing_stop = compute_initial_trailing_stop(entry_price, side)

    conn = get_connection(db_path)
    try:
        with conn:
            existing = conn.execute(
                "SELECT * FROM our_positions WHERE token_symbol = ?",
                (token,),
            ).fetchone()

            if existing and action_type == "INCREASE":
                # Weighted-average entry price
                old_size = existing["size"]
                old_entry = existing["entry_price"]
                new_total_size = old_size + size
                if new_total_size > 0:
                    new_entry = (old_size * old_entry + size * entry_price) / new_total_size
                else:
                    new_entry = entry_price
                new_position_usd = new_total_size * new_entry
                new_stop_loss = compute_stop_loss_price(new_entry, side)
                new_trailing_stop = compute_initial_trailing_stop(new_entry, side)

                conn.execute(
                    """UPDATE our_positions
                       SET size = ?, entry_price = ?, current_price = ?,
                           position_usd = ?, stop_loss_price = ?,
                           trailing_stop_price = ?, trailing_high = ?,
                           leverage = ?, updated_at = ?
                       WHERE token_symbol = ?""",
                    (
                        new_total_size,
                        new_entry,
                        mark_price,
                        new_position_usd,
                        new_stop_loss,
                        new_trailing_stop,
                        mark_price,
                        leverage,
                        now,
                        token,
                    ),
                )
            else:
                # Fresh OPEN (or INCREASE on non-existent — treat as OPEN)
                conn.execute(
                    """INSERT OR REPLACE INTO our_positions
                       (token_symbol, side, size, entry_price, current_price,
                        position_usd, unrealized_pnl, stop_loss_price,
                        trailing_stop_price, trailing_high, opened_at,
                        max_close_at, leverage, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        token,
                        side,
                        size,
                        entry_price,
                        mark_price,
                        position_usd,
                        stop_loss,
                        trailing_stop,
                        mark_price,
                        now,
                        max_close,
                        leverage,
                        now,
                    ),
                )
    finally:
        conn.close()


def _close_position(
    db_path: str,
    token: str,
    side: str,
    exit_price: float,
    exit_size: float,
    fee_usd: float,
) -> None:
    """Remove a position from our_positions and write a pnl_ledger entry."""
    now = _now_utc()
    conn = get_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT * FROM our_positions WHERE token_symbol = ?",
                (token,),
            ).fetchone()

            entry_price = row["entry_price"] if row else exit_price
            pos_size = row["size"] if row else exit_size
            pos_side = row["side"] if row else side
            opened_at = row["opened_at"] if row else now

            # Compute realized PnL
            if pos_side == "Long":
                realized_pnl = (exit_price - entry_price) * pos_size
            else:
                realized_pnl = (entry_price - exit_price) * pos_size

            # Compute hold hours
            hold_hours = 0.0
            if opened_at:
                try:
                    opened_dt = datetime.strptime(opened_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    hold_hours = (
                        datetime.now(timezone.utc) - opened_dt
                    ).total_seconds() / 3600
                except (ValueError, TypeError):
                    pass

            # Write PnL ledger
            conn.execute(
                """INSERT INTO pnl_ledger
                   (token_symbol, side, entry_price, exit_price, size,
                    realized_pnl, fees_total, hold_hours, exit_reason, closed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'REBALANCE', ?)""",
                (
                    token,
                    pos_side,
                    entry_price,
                    exit_price,
                    pos_size,
                    realized_pnl,
                    fee_usd,
                    hold_hours,
                    now,
                ),
            )

            # Remove from our_positions
            conn.execute(
                "DELETE FROM our_positions WHERE token_symbol = ?",
                (token,),
            )
    finally:
        conn.close()


def _decrease_position(
    db_path: str,
    token: str,
    decrease_size: float,
    current_price: float,
) -> None:
    """Reduce a position's size.  If size reaches 0, remove it."""
    now = _now_utc()
    conn = get_connection(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT * FROM our_positions WHERE token_symbol = ?",
                (token,),
            ).fetchone()

            if not row:
                return

            new_size = row["size"] - decrease_size
            if new_size <= 0:
                conn.execute(
                    "DELETE FROM our_positions WHERE token_symbol = ?",
                    (token,),
                )
            else:
                new_position_usd = new_size * row["entry_price"]
                conn.execute(
                    """UPDATE our_positions
                       SET size = ?, position_usd = ?, current_price = ?,
                           updated_at = ?
                       WHERE token_symbol = ?""",
                    (new_size, new_position_usd, current_price, now, token),
                )
    finally:
        conn.close()
