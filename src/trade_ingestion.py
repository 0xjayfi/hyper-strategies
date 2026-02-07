"""Trade ingestion pipeline: polling, signal evaluation, and deferred signal queue.

Implements Phase 4 (Tasks 4.1-4.3) of the entry-only signal generator.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable
from uuid import uuid4

import structlog

from src.config import settings
from src import db
from src.models import Signal, TraderRow
from src.nansen_client import NansenClient
from src.sizing import compute_copy_size, get_leverage_from_positions

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Task 4.3 — DeferredSignal dataclass & priority queue
# ---------------------------------------------------------------------------


@dataclass
class DeferredSignal:
    """A signal that is too fresh to execute and must wait for the copy delay."""

    trade: dict
    trader: TraderRow
    check_at: datetime

    def __lt__(self, other: DeferredSignal) -> bool:
        """Required for PriorityQueue ordering."""
        return self.check_at < other.check_at


_deferred_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()


async def enqueue_deferred(deferred: DeferredSignal) -> None:
    """Add a deferred signal to the priority queue, keyed by check_at timestamp."""
    await _deferred_queue.put((deferred.check_at.timestamp(), deferred))
    log.info(
        "deferred_signal_enqueued",
        trader=deferred.trader.address,
        token=deferred.trade.get("token_symbol"),
        check_at=deferred.check_at.isoformat(),
    )


async def process_deferred_signals(
    client: NansenClient,
    execute_callback: Callable[[Signal], Awaitable[Any]],
) -> None:
    """Background loop: pop deferred signals when their check_at time arrives,
    re-evaluate from Step 4 onward, and execute if approved.

    Runs forever alongside the main polling loop.
    """
    log.info("deferred_signal_processor_started")

    while True:
        try:
            # Block until a deferred signal is available.
            priority, deferred = await _deferred_queue.get()

            # Wait until the check_at time if it hasn't arrived yet.
            now_ts = datetime.now(timezone.utc).timestamp()
            wait_seconds = deferred.check_at.timestamp() - now_ts
            if wait_seconds > 0:
                log.debug(
                    "deferred_signal_waiting",
                    wait_seconds=round(wait_seconds, 1),
                    token=deferred.trade.get("token_symbol"),
                )
                await asyncio.sleep(wait_seconds)

            # Re-evaluate the trade.  Because enough time has now elapsed,
            # Step 4's age check will pass and proceed to position verification.
            log.info(
                "deferred_signal_re_evaluating",
                trader=deferred.trader.address,
                token=deferred.trade.get("token_symbol"),
            )
            result = await evaluate_trade(deferred.trade, deferred.trader, client)

            if isinstance(result, DeferredSignal):
                # Shouldn't happen after waiting, but guard against it.
                await enqueue_deferred(result)
            elif result is not None and result.decision == "EXECUTE":
                await execute_callback(result)

        except Exception:
            log.exception("deferred_signal_processing_error")
            # Avoid tight loop on persistent errors.
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Task 4.1 — Polling loop
# ---------------------------------------------------------------------------


async def poll_trader_trades(
    client: NansenClient,
    execute_callback: Callable[[Signal], Awaitable[Any]],
) -> None:
    """Continuously poll primary traders for new perp trades and evaluate them.

    Args:
        client: Nansen API client.
        execute_callback: Async callable invoked with a Signal when decision is EXECUTE.
    """
    log.info("trade_polling_loop_started")

    while True:
        try:
            trader_dicts = await db.get_primary_traders()
            log.info("polling_cycle_start", trader_count=len(trader_dicts))

            total_new_trades = 0

            for trader_dict in trader_dicts:
                try:
                    trader = TraderRow(**trader_dict)

                    now_utc = datetime.now(timezone.utc)
                    date_from = (now_utc - timedelta(hours=1)).isoformat()
                    date_to = now_utc.isoformat()

                    trades = await client.get_address_perp_trades(
                        address=trader.address,
                        date_from=date_from,
                        date_to=date_to,
                    )

                    new_count = 0
                    for trade in trades:
                        tx_hash = trade.get("transaction_hash", "")
                        if not tx_hash:
                            continue

                        if await db.is_seen(tx_hash):
                            continue

                        await db.mark_seen(
                            tx_hash,
                            seen_at=datetime.now(timezone.utc).isoformat(),
                        )
                        new_count += 1

                        result = await evaluate_trade(trade, trader, client)

                        if isinstance(result, DeferredSignal):
                            await enqueue_deferred(result)
                        elif result is not None and result.decision == "EXECUTE":
                            await execute_callback(result)

                    if new_count > 0:
                        log.info(
                            "trader_new_trades",
                            trader=trader.address,
                            new_trades=new_count,
                        )
                    total_new_trades += new_count

                except Exception:
                    log.exception(
                        "trader_polling_error",
                        trader=trader_dict.get("address", "unknown"),
                    )

            log.info("polling_cycle_complete", total_new_trades=total_new_trades)

        except Exception:
            log.exception("polling_cycle_error")

        await asyncio.sleep(settings.POLLING_INTERVAL_ADDRESS_TRADES_SEC)


# ---------------------------------------------------------------------------
# Task 4.2 — Signal evaluation pipeline helpers
# ---------------------------------------------------------------------------


async def get_current_price(client: NansenClient, token: str) -> float:
    """Placeholder: fetch current mark price for token.

    Will be replaced by Hyperliquid SDK or screener endpoint.
    """
    return 0.0


async def _get_our_account_value() -> float:
    """Placeholder: fetch our account value from Hyperliquid.

    Will be implemented with the HL SDK.
    """
    return 100_000.0


async def _find_original_open(
    client: NansenClient,
    address: str,
    token: str,
    side: str,
) -> datetime | None:
    """Search the last 24h of a trader's trades for the most recent 'Open'
    matching the given token and side.

    Returns:
        The timestamp of the original Open, or None if not found.
    """
    now_utc = datetime.now(timezone.utc)
    date_from = (now_utc - timedelta(hours=24)).isoformat()
    date_to = now_utc.isoformat()

    try:
        trades = await client.get_address_perp_trades(
            address=address,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception:
        log.exception("find_original_open_fetch_error", address=address, token=token)
        return None

    # Walk trades looking for the most recent Open with matching token+side.
    best_open_ts: datetime | None = None
    for t in trades:
        if (
            t.get("action") == "Open"
            and t.get("token_symbol") == token
            and t.get("side") == side
        ):
            ts = _parse_timestamp(t.get("timestamp", ""))
            if ts is not None:
                if best_open_ts is None or ts > best_open_ts:
                    best_open_ts = ts

    return best_open_ts


async def _count_consensus(token: str, side: str) -> int:
    """Count how many tracked traders currently hold a position in the same
    token and direction.

    Placeholder implementation that queries the trader_positions table.
    """
    try:
        from src.db import _get_db

        conn = await _get_db()
        try:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM trader_positions WHERE token_symbol = ? AND side = ?",
                (token, side),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
        finally:
            await conn.close()
    except Exception:
        log.exception("consensus_count_error", token=token, side=side)
        return 0


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime.

    If the parsed datetime is naive, it is assumed to be UTC.
    Returns None on failure.
    """
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        log.warning("timestamp_parse_error", raw=ts_str)
        return None


def _build_skip_signal(
    trade: dict,
    trader: TraderRow,
    reason: str,
    *,
    position_weight: float = 0.0,
    slippage_check: bool = False,
    age_seconds: float = 0.0,
    order_type: str = "market",
    max_slippage: float = 0.0,
) -> Signal:
    """Build a Signal with a SKIP decision for audit logging."""
    trade_time = _parse_timestamp(trade.get("timestamp", ""))
    return Signal(
        id=str(uuid4()),
        trader_address=trader.address,
        token_symbol=trade.get("token_symbol", ""),
        side=trade.get("side", ""),
        action=trade.get("action", ""),
        value_usd=float(trade.get("value_usd", 0)),
        position_weight=position_weight,
        timestamp=trade_time or datetime.now(timezone.utc),
        age_seconds=age_seconds,
        slippage_check=slippage_check,
        trader_score=trader.score,
        trader_roi_7d=trader.roi_7d,
        copy_size_usd=0.0,
        leverage=None,
        order_type=order_type,
        max_slippage=max_slippage,
        decision=reason,
    )


async def _log_and_record_skip(
    trade: dict,
    trader: TraderRow,
    reason: str,
    **kwargs: Any,
) -> None:
    """Log a skip decision and insert an audit record into the signals table."""
    signal = _build_skip_signal(trade, trader, reason, **kwargs)
    log.info(
        "signal_skipped",
        decision=reason,
        trader=trader.address,
        token=trade.get("token_symbol"),
        side=trade.get("side"),
        action=trade.get("action"),
        value_usd=trade.get("value_usd"),
    )
    try:
        await db.insert_signal(
            id=signal.id,
            trader_address=signal.trader_address,
            token_symbol=signal.token_symbol,
            side=signal.side,
            action=signal.action,
            value_usd=signal.value_usd,
            position_weight=signal.position_weight,
            timestamp=signal.timestamp.isoformat(),
            age_seconds=signal.age_seconds,
            slippage_check_passed=int(signal.slippage_check),
            trader_score=signal.trader_score,
            copy_size_usd=signal.copy_size_usd,
            decision=signal.decision,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        log.exception("skip_signal_insert_error", signal_id=signal.id)


# ---------------------------------------------------------------------------
# Task 4.2 — Signal evaluation pipeline (9-step)
# ---------------------------------------------------------------------------


async def evaluate_trade(
    trade: dict,
    trader: TraderRow,
    client: NansenClient,
) -> Signal | DeferredSignal | None:
    """Run the full 9-step evaluation pipeline on a raw trade dict.

    Returns:
        - A Signal with decision="EXECUTE" if all gates pass.
        - A DeferredSignal if the trade is too fresh (Step 4).
        - None for any skip condition (audit record written internally).
    """

    action = trade.get("action", "")
    token = trade.get("token_symbol", "")
    side = trade.get("side", "")
    value_usd = float(trade.get("value_usd", 0))
    trade_price = float(trade.get("price", 0))
    trade_time = _parse_timestamp(trade.get("timestamp", ""))

    if trade_time is None:
        await _log_and_record_skip(trade, trader, "SKIP_INVALID_TIMESTAMP")
        return None

    now_utc = datetime.now(timezone.utc)
    age_seconds = (now_utc - trade_time).total_seconds()

    # ── Step 1: Action Filter ──────────────────────────────────────────────
    if action == "Open":
        pass  # Always valid.
    elif action == "Add":
        original_open_ts = await _find_original_open(client, trader.address, token, side)
        if original_open_ts is None:
            await _log_and_record_skip(trade, trader, "SKIP_ADD_NO_OPEN", age_seconds=age_seconds)
            return None
        hours_since_open = (trade_time - original_open_ts).total_seconds() / 3600
        if hours_since_open > settings.ADD_MAX_AGE_HOURS:
            await _log_and_record_skip(trade, trader, "SKIP_ADD_TOO_OLD", age_seconds=age_seconds)
            return None
    else:
        # "Close", "Reduce", or any other action — skip.
        await _log_and_record_skip(trade, trader, "SKIP_ACTION_TYPE", age_seconds=age_seconds)
        return None

    # ── Step 2: Asset Minimum Size ─────────────────────────────────────────
    min_size = settings.MIN_TRADE_VALUE_USD.get(token, settings.MIN_TRADE_VALUE_USD["_default"])
    if value_usd < min_size:
        await _log_and_record_skip(trade, trader, "SKIP_SIZE_TOO_SMALL", age_seconds=age_seconds)
        return None

    # ── Step 3: Position Weight ────────────────────────────────────────────
    account_value = trader.account_value
    position_weight = value_usd / account_value if account_value > 0 else 0.0

    if position_weight < settings.MIN_POSITION_WEIGHT:
        await _log_and_record_skip(
            trade, trader, "SKIP_LOW_WEIGHT",
            age_seconds=age_seconds, position_weight=position_weight,
        )
        return None

    if position_weight < 0.05:
        await _log_and_record_skip(
            trade, trader, "SKIP_LOW_CONFIDENCE",
            age_seconds=age_seconds, position_weight=position_weight,
        )
        return None

    # ── Step 4: Time Decay Confirmation ────────────────────────────────────
    if age_seconds < settings.COPY_DELAY_MINUTES * 60:
        check_at = trade_time + timedelta(minutes=settings.COPY_DELAY_MINUTES)
        log.info(
            "signal_deferred",
            trader=trader.address,
            token=token,
            side=side,
            age_seconds=round(age_seconds, 1),
            check_at=check_at.isoformat(),
        )
        return DeferredSignal(trade=trade, trader=trader, check_at=check_at)

    # After the delay period, verify the trader still holds the position.
    positions: dict = {}
    try:
        positions = await client.get_address_perp_positions(trader.address)
    except Exception:
        log.exception("position_fetch_error", trader=trader.address)
        await _log_and_record_skip(
            trade, trader, "SKIP_POSITION_FETCH_ERROR",
            age_seconds=age_seconds, position_weight=position_weight,
        )
        return None

    asset_positions = positions.get("data", {}).get("asset_positions", [])
    still_open = any(
        p.get("position", {}).get("token_symbol") == token
        and ((float(p.get("position", {}).get("size", 0)) > 0) == (side == "Long"))
        for p in asset_positions
    )
    if not still_open:
        await _log_and_record_skip(
            trade, trader, "SKIP_REVERSED_AFTER_DELAY",
            age_seconds=age_seconds, position_weight=position_weight,
        )
        return None

    # ── Step 5: Slippage Gate ──────────────────────────────────────────────
    current_price = await get_current_price(client, token)
    slippage_pct = 0.0
    slippage_check = True

    if current_price > 0 and trade_price > 0:
        slippage_pct = abs(current_price - trade_price) / trade_price * 100
        if slippage_pct > settings.MAX_PRICE_SLIPPAGE_PERCENT:
            slippage_check = False
            await _log_and_record_skip(
                trade, trader, "SKIP_SLIPPAGE_EXCEEDED",
                age_seconds=age_seconds, position_weight=position_weight,
                slippage_check=False,
            )
            return None

    # ── Step 6: Execution Timing ───────────────────────────────────────────
    age_minutes = age_seconds / 60

    if age_minutes < 2:
        order_type = "market"
        max_slippage = 0.5
    elif age_minutes < 10:
        if slippage_pct < 0.3:
            order_type = "limit"
            max_slippage = 0.3
        else:
            await _log_and_record_skip(
                trade, trader, "SKIP_STALE_HIGH_SLIPPAGE",
                age_seconds=age_seconds, position_weight=position_weight,
                slippage_check=slippage_check,
            )
            return None
    else:
        if trader.score > 0.8 and position_weight > 0.25:
            order_type = "limit"
            max_slippage = 0.3
        else:
            await _log_and_record_skip(
                trade, trader, "SKIP_TOO_OLD",
                age_seconds=age_seconds, position_weight=position_weight,
                slippage_check=slippage_check,
            )
            return None

    # ── Step 7: Consensus Check (optional) ─────────────────────────────────
    if settings.REQUIRE_CONSENSUS:
        same_direction = await _count_consensus(token, side)
        if same_direction < settings.CONSENSUS_MIN_TRADERS:
            await _log_and_record_skip(
                trade, trader, "SKIP_NO_CONSENSUS",
                age_seconds=age_seconds, position_weight=position_weight,
                slippage_check=slippage_check,
            )
            return None

    # ── Step 8: Portfolio Limits ───────────────────────────────────────────
    our_positions = await db.get_open_positions()

    if len(our_positions) >= settings.MAX_TOTAL_POSITIONS:
        await _log_and_record_skip(
            trade, trader, "SKIP_MAX_POSITIONS",
            age_seconds=age_seconds, position_weight=position_weight,
            slippage_check=slippage_check,
        )
        return None

    total_exposure = sum(p["value_usd"] for p in our_positions)
    our_account_value = await _get_our_account_value()

    if total_exposure >= our_account_value * settings.MAX_TOTAL_OPEN_POSITIONS_USD_RATIO:
        await _log_and_record_skip(
            trade, trader, "SKIP_MAX_EXPOSURE",
            age_seconds=age_seconds, position_weight=position_weight,
            slippage_check=slippage_check,
        )
        return None

    token_exposure = sum(
        p["value_usd"] for p in our_positions if p["token_symbol"] == token
    )
    if token_exposure >= our_account_value * settings.MAX_EXPOSURE_PER_TOKEN:
        await _log_and_record_skip(
            trade, trader, "SKIP_TOKEN_EXPOSURE",
            age_seconds=age_seconds, position_weight=position_weight,
            slippage_check=slippage_check,
        )
        return None

    # ── Step 9: Compute Copy Size ──────────────────────────────────────────
    leverage = get_leverage_from_positions(positions, token)
    copy_size_usd = compute_copy_size(
        trader_position_value=value_usd,
        trader_account_value=account_value,
        our_account_value=our_account_value,
        trader_roi_7d=trader.roi_7d,
        leverage=leverage,
    )
    if copy_size_usd <= 0:
        await _log_and_record_skip(
            trade, trader, "SKIP_SIZE_ZERO",
            age_seconds=age_seconds, position_weight=position_weight,
            slippage_check=slippage_check,
        )
        return None

    # ── Build & return EXECUTE Signal ──────────────────────────────────────
    signal = Signal(
        id=str(uuid4()),
        trader_address=trader.address,
        token_symbol=token,
        side=side,
        action=action,
        value_usd=value_usd,
        position_weight=position_weight,
        timestamp=trade_time,
        age_seconds=age_seconds,
        slippage_check=slippage_check,
        trader_score=trader.score,
        trader_roi_7d=trader.roi_7d,
        copy_size_usd=copy_size_usd,
        leverage=leverage,
        order_type=order_type,
        max_slippage=max_slippage,
        decision="EXECUTE",
    )

    log.info(
        "signal_execute",
        signal_id=signal.id,
        trader=signal.trader_address,
        token=signal.token_symbol,
        side=signal.side,
        action=signal.action,
        value_usd=signal.value_usd,
        copy_size_usd=signal.copy_size_usd,
        order_type=signal.order_type,
        position_weight=round(signal.position_weight, 4),
        leverage=signal.leverage,
    )

    # Insert audit record for the EXECUTE decision.
    try:
        await db.insert_signal(
            id=signal.id,
            trader_address=signal.trader_address,
            token_symbol=signal.token_symbol,
            side=signal.side,
            action=signal.action,
            value_usd=signal.value_usd,
            position_weight=signal.position_weight,
            timestamp=signal.timestamp.isoformat(),
            age_seconds=signal.age_seconds,
            slippage_check_passed=int(signal.slippage_check),
            trader_score=signal.trader_score,
            copy_size_usd=signal.copy_size_usd,
            decision=signal.decision,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception:
        log.exception("execute_signal_insert_error", signal_id=signal.id)

    return signal
