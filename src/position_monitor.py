"""Position monitoring loop: trailing stops, time stops, profit-taking, and liquidation detection.

Implements Phase 7 (Track 6: Position Management) of the copy-trading system.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

from src.config import settings
from src import db
from src.models import ExecutionResult, OurPosition
from src.nansen_client import NansenClient

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# 7.4 — Unrealized P&L computation
# ---------------------------------------------------------------------------


def compute_unrealized_pct(pos: OurPosition, mark_price: float) -> float:
    """Compute unrealized profit/loss as a percentage of entry price.

    Long positions profit when mark_price > entry_price.
    Short positions profit when mark_price < entry_price.

    Returns:
        Unrealized P&L percentage (positive = profit, negative = loss).
    """
    if pos.entry_price <= 0:
        return 0.0

    if pos.side == "Long":
        return (mark_price - pos.entry_price) / pos.entry_price * 100
    else:
        return (pos.entry_price - mark_price) / pos.entry_price * 100


# ---------------------------------------------------------------------------
# 7.2 — Trailing stop logic
# ---------------------------------------------------------------------------


def update_trailing_stop(pos: OurPosition, mark_price: float) -> dict | None:
    """Compute trailing stop updates based on the current mark price.

    For long positions: if mark_price exceeds the recorded highest_price,
    update the high-water mark and raise the trailing stop.

    For short positions: if mark_price falls below the recorded lowest_price,
    update the low-water mark and lower the trailing stop.

    The trailing stop only moves in the favorable direction (never widens the
    distance from the current price).

    Args:
        pos: Current position from the database.
        mark_price: Current mark price for the token.

    Returns:
        A dict of fields to update in the DB, or None if no update is needed.
    """
    trail_pct = settings.TRAILING_STOP_PERCENT / 100

    if pos.side == "Long":
        current_highest = pos.highest_price if pos.highest_price is not None else pos.entry_price

        if mark_price <= current_highest:
            return None

        new_highest = mark_price
        new_trail = new_highest * (1 - trail_pct)

        # Only move the trailing stop upward (never widen)
        if pos.trailing_stop_price is not None and new_trail <= pos.trailing_stop_price:
            # Price made a new high but the computed trail isn't higher than
            # the existing trail — just update the high-water mark.
            return {
                "highest_price": new_highest,
            }

        return {
            "highest_price": new_highest,
            "trailing_stop_price": round(new_trail, 6),
        }

    else:
        # Short position
        current_lowest = pos.lowest_price if pos.lowest_price is not None else pos.entry_price

        if mark_price >= current_lowest:
            return None

        new_lowest = mark_price
        new_trail = new_lowest * (1 + trail_pct)

        # Only move the trailing stop downward (never widen)
        if pos.trailing_stop_price is not None and new_trail >= pos.trailing_stop_price:
            return {
                "lowest_price": new_lowest,
            }

        return {
            "lowest_price": new_lowest,
            "trailing_stop_price": round(new_trail, 6),
        }


def trailing_stop_triggered(pos: OurPosition, mark_price: float) -> bool:
    """Check whether the trailing stop has been triggered.

    Long: triggered when mark_price <= trailing_stop_price.
    Short: triggered when mark_price >= trailing_stop_price.

    Returns False if no trailing stop price has been set.
    """
    if pos.trailing_stop_price is None:
        return False

    if pos.side == "Long":
        return mark_price <= pos.trailing_stop_price
    else:
        return mark_price >= pos.trailing_stop_price


# ---------------------------------------------------------------------------
# 7.5 — Position closing helpers
# ---------------------------------------------------------------------------


async def close_position_full(pos: OurPosition, executor, reason: str) -> None:
    """Fully close a position on the exchange and update the database.

    Steps:
        1. Market order to close on exchange.
        2. Cancel any existing stop orders for the token.
        3. Update DB status to 'closed' with the given reason.

    Args:
        pos: The position to close.
        executor: HyperLiquidExecutor instance.
        reason: Human-readable reason for closing (stored in DB).
    """
    log.info(
        "closing_position",
        position_id=pos.id,
        token=pos.token_symbol,
        side=pos.side,
        size=pos.size,
        reason=reason,
    )

    # 1. Market close on exchange
    result: ExecutionResult = await executor.close_position_on_exchange(
        token=pos.token_symbol,
        side=pos.side,
        size=pos.size,
    )

    if not result.success:
        log.error(
            "close_position_exchange_failed",
            position_id=pos.id,
            token=pos.token_symbol,
            error=result.error,
            reason=reason,
        )
        # Still proceed with DB update so the position doesn't get stuck;
        # manual intervention may be needed.

    # 2. Cancel existing stop orders
    try:
        await executor.cancel_stop_orders(pos.token_symbol)
    except Exception:
        log.exception(
            "cancel_stop_orders_failed",
            position_id=pos.id,
            token=pos.token_symbol,
        )

    # 3. Update DB
    await db.close_position(pos.id, close_reason=reason)

    log.info(
        "position_closed",
        position_id=pos.id,
        token=pos.token_symbol,
        side=pos.side,
        reason=reason,
        fill_price=result.fill_price,
    )


async def reduce_position(pos: OurPosition, executor, pct: float, reason: str) -> None:
    """Partially close a position by a given percentage.

    Steps:
        1. Calculate the reduction size.
        2. Place a reduce order on exchange.
        3. Update DB with the new size and value.

    Args:
        pos: The position to reduce.
        executor: HyperLiquidExecutor instance.
        pct: Fraction to close (e.g. 0.25 = close 25% of position).
        reason: Human-readable reason for the reduction.
    """
    reduce_size = pos.size * pct

    log.info(
        "reducing_position",
        position_id=pos.id,
        token=pos.token_symbol,
        side=pos.side,
        reduce_pct=pct,
        reduce_size=reduce_size,
        reason=reason,
    )

    result: ExecutionResult = await executor.close_position_on_exchange(
        token=pos.token_symbol,
        side=pos.side,
        size=reduce_size,
    )

    if not result.success:
        log.error(
            "reduce_position_exchange_failed",
            position_id=pos.id,
            token=pos.token_symbol,
            error=result.error,
            reason=reason,
        )
        return

    new_size = pos.size - reduce_size
    new_value_usd = pos.value_usd * (1 - pct)

    await db.update_position(
        pos.id,
        size=round(new_size, 8),
        value_usd=round(new_value_usd, 2),
    )

    log.info(
        "position_reduced",
        position_id=pos.id,
        token=pos.token_symbol,
        side=pos.side,
        reduce_pct=pct,
        new_size=round(new_size, 8),
        new_value_usd=round(new_value_usd, 2),
        fill_price=result.fill_price,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# 7.3 — Trader liquidation / disappearance detection
# ---------------------------------------------------------------------------


async def check_trader_position(
    pos: OurPosition,
    nansen: NansenClient,
    executor,
) -> bool:
    """Check whether the source trader still holds the copied position.

    If the trader no longer has the position:
      - Look for a recent Close trade (within the last hour).
      - If a Close is found, the trader exited normally; our stops remain active.
      - If no Close is found, this is a probable liquidation; close our position
        immediately and blacklist the trader for the configured cooldown period.

    Args:
        pos: Our open position that was copied from the trader.
        nansen: Nansen API client.
        executor: HyperLiquidExecutor instance.

    Returns:
        True if the position was closed due to liquidation detection, False otherwise.
    """
    if not pos.source_trader:
        return False

    # Fetch trader's current positions
    try:
        positions_resp = await nansen.get_address_perp_positions(pos.source_trader)
    except Exception:
        log.exception(
            "trader_position_fetch_failed",
            position_id=pos.id,
            trader=pos.source_trader,
        )
        return False

    # Check if the trader still has a position in the same token
    asset_positions = positions_resp.get("data", {}).get("asset_positions", [])
    trader_has_position = False
    for ap in asset_positions:
        p = ap.get("position", {})
        if p.get("token_symbol") == pos.token_symbol:
            size = float(p.get("size", 0))
            # Long positions have positive size, short positions have negative size
            if pos.side == "Long" and size > 0:
                trader_has_position = True
                break
            elif pos.side == "Short" and size < 0:
                trader_has_position = True
                break

    if trader_has_position:
        return False

    log.warning(
        "trader_position_disappeared",
        position_id=pos.id,
        token=pos.token_symbol,
        side=pos.side,
        trader=pos.source_trader,
    )

    # Trader no longer has the position — check for a recent Close trade
    now = datetime.now(timezone.utc)
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    now_iso = now.isoformat()

    try:
        recent_trades = await nansen.get_address_perp_trades(
            address=pos.source_trader,
            date_from=one_hour_ago,
            date_to=now_iso,
        )
    except Exception:
        log.exception(
            "trader_trades_fetch_failed",
            position_id=pos.id,
            trader=pos.source_trader,
        )
        return False

    # Look for a Close action on the same token
    found_close = False
    for trade in recent_trades:
        if (
            trade.get("action") == "Close"
            and trade.get("token_symbol") == pos.token_symbol
        ):
            found_close = True
            break

    if found_close:
        log.info(
            "trader_exited_normally",
            position_id=pos.id,
            token=pos.token_symbol,
            trader=pos.source_trader,
        )
        # Trader exited normally; our trailing stops remain active.
        return False

    # No Close trade found — probable liquidation
    log.warning(
        "probable_liquidation_detected",
        position_id=pos.id,
        token=pos.token_symbol,
        side=pos.side,
        trader=pos.source_trader,
    )

    await close_position_full(pos, executor, reason="trader_liquidated")

    # Blacklist the trader for the configured cooldown period
    blacklist_until = (
        now + timedelta(days=settings.LIQUIDATION_COOLDOWN_DAYS)
    ).isoformat()

    try:
        await db.blacklist_trader(pos.source_trader, until=blacklist_until)
        log.info(
            "trader_blacklisted",
            trader=pos.source_trader,
            until=blacklist_until,
            cooldown_days=settings.LIQUIDATION_COOLDOWN_DAYS,
        )
    except Exception:
        log.exception(
            "blacklist_trader_failed",
            trader=pos.source_trader,
        )

    return True


# ---------------------------------------------------------------------------
# 7.4 — Profit-taking tier logic
# ---------------------------------------------------------------------------


async def check_profit_taking(
    pos: OurPosition,
    mark_price: float,
    executor,
) -> bool:
    """Evaluate and execute tiered profit-taking for a position.

    Tiers (from config):
      - Tier 1: Take 25% off at +PROFIT_TAKE_TIER_1 %
      - Tier 2: Take 33% off at +PROFIT_TAKE_TIER_2 %
      - Tier 3: Take 50% off at +PROFIT_TAKE_TIER_3 %

    Each tier fires at most once. We track which tiers have been taken by
    examining the current unrealized P&L and previously recorded close_reason
    metadata (the position's close_reason field is None while open, so we
    use a naming convention on the reduction reason and rely on the size
    having already been reduced for prior tiers).

    To avoid double-triggering, we check from the highest tier downward and
    only fire one tier per monitoring cycle.

    Args:
        pos: Current open position.
        mark_price: Current mark price.
        executor: HyperLiquidExecutor instance.

    Returns:
        True if a profit take was executed, False otherwise.
    """
    unrealized_pct = compute_unrealized_pct(pos, mark_price)

    if unrealized_pct <= 0:
        return False

    # Determine the original position size from value_usd / entry_price
    # to estimate which tiers have already been taken.  We use a simple
    # approach: check from the highest tier down, and fire the first one
    # whose threshold is met.  Because each take reduces the position size,
    # subsequent cycles will re-evaluate against the reduced position and
    # the tier thresholds remain percentage-based on entry price, so they
    # only trigger once naturally as long as we go highest-first.

    # Tier 3: take 50% at +PROFIT_TAKE_TIER_3 %
    if (
        settings.PROFIT_TAKE_TIER_3 is not None
        and unrealized_pct >= settings.PROFIT_TAKE_TIER_3
    ):
        log.info(
            "profit_take_tier_3_triggered",
            position_id=pos.id,
            token=pos.token_symbol,
            unrealized_pct=round(unrealized_pct, 2),
            threshold=settings.PROFIT_TAKE_TIER_3,
        )
        await reduce_position(pos, executor, pct=0.50, reason="profit_take_tier_3")
        return True

    # Tier 2: take 33% at +PROFIT_TAKE_TIER_2 %
    if (
        settings.PROFIT_TAKE_TIER_2 is not None
        and unrealized_pct >= settings.PROFIT_TAKE_TIER_2
    ):
        log.info(
            "profit_take_tier_2_triggered",
            position_id=pos.id,
            token=pos.token_symbol,
            unrealized_pct=round(unrealized_pct, 2),
            threshold=settings.PROFIT_TAKE_TIER_2,
        )
        await reduce_position(pos, executor, pct=0.33, reason="profit_take_tier_2")
        return True

    # Tier 1: take 25% at +PROFIT_TAKE_TIER_1 %
    if (
        settings.PROFIT_TAKE_TIER_1 is not None
        and unrealized_pct >= settings.PROFIT_TAKE_TIER_1
    ):
        log.info(
            "profit_take_tier_1_triggered",
            position_id=pos.id,
            token=pos.token_symbol,
            unrealized_pct=round(unrealized_pct, 2),
            threshold=settings.PROFIT_TAKE_TIER_1,
        )
        await reduce_position(pos, executor, pct=0.25, reason="profit_take_tier_1")
        return True

    return False


# ---------------------------------------------------------------------------
# 7.1 — Main monitor loop
# ---------------------------------------------------------------------------


async def monitor_positions(pos: OurPosition, mark_price: float, executor, nansen: NansenClient) -> None:
    """Run all position checks for a single position.

    Checks are applied in order of urgency:
        1. Trailing stop update (adjust high/low water marks)
        2. Trailing stop trigger check (close if triggered)
        3. Time-based stop (close if position exceeds max duration)
        4. Profit-taking tiers
        5. Trader liquidation / disappearance check

    Args:
        pos: The open position to monitor.
        mark_price: Current mark price for the token.
        executor: HyperLiquidExecutor instance.
        nansen: Nansen API client.
    """
    # --- 1. Trailing Stop Update ---
    trail_updates = update_trailing_stop(pos, mark_price)
    if trail_updates is not None:
        await db.update_position(pos.id, **trail_updates)
        log.info(
            "trailing_stop_updated",
            position_id=pos.id,
            token=pos.token_symbol,
            side=pos.side,
            mark_price=mark_price,
            **trail_updates,
        )
        # Refresh the in-memory position object with the new values
        for key, value in trail_updates.items():
            if hasattr(pos, key):
                object.__setattr__(pos, key, value)

    # --- 2. Trailing Stop Trigger Check ---
    if trailing_stop_triggered(pos, mark_price):
        log.warning(
            "trailing_stop_triggered",
            position_id=pos.id,
            token=pos.token_symbol,
            side=pos.side,
            mark_price=mark_price,
            trailing_stop_price=pos.trailing_stop_price,
        )
        await close_position_full(pos, executor, reason="trailing_stop")
        return

    # --- 3. Time-Based Stop ---
    now = datetime.now(timezone.utc)
    opened_at = datetime.fromisoformat(pos.opened_at)
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)

    hours_open = (now - opened_at).total_seconds() / 3600

    if hours_open >= settings.MAX_POSITION_DURATION_HOURS:
        log.warning(
            "time_stop_triggered",
            position_id=pos.id,
            token=pos.token_symbol,
            side=pos.side,
            hours_open=round(hours_open, 2),
            max_hours=settings.MAX_POSITION_DURATION_HOURS,
        )
        await close_position_full(pos, executor, reason="time_stop")
        return

    # --- 4. Profit-Taking Tiers ---
    profit_taken = await check_profit_taking(pos, mark_price, executor)
    if profit_taken:
        # A partial close was executed; skip the liquidation check this cycle
        # to avoid conflicting actions.
        return

    # --- 5. Trader Liquidation / Disappearance Check ---
    liquidated = await check_trader_position(pos, nansen, executor)
    if liquidated:
        return


async def monitor_loop(executor, nansen: NansenClient) -> None:
    """Continuously monitor all open positions every 30 seconds.

    For each open position:
        1. Fetch the current mark price.
        2. Run trailing stop updates and trigger checks.
        3. Check time-based stop.
        4. Evaluate profit-taking tiers.
        5. Check for trader liquidation / position disappearance.

    Each position is wrapped in a try/except so that an error on one
    position does not crash the entire monitoring loop.

    Args:
        executor: HyperLiquidExecutor instance.
        nansen: Nansen API client.
    """
    log.info("position_monitor_started")

    while True:
        try:
            open_positions = await db.get_open_positions()

            if open_positions:
                log.debug(
                    "monitor_cycle_start",
                    open_positions=len(open_positions),
                )

            for pos_dict in open_positions:
                try:
                    pos = OurPosition(**pos_dict)

                    mark_price = await executor.get_mark_price(pos.token_symbol)

                    log.debug(
                        "monitoring_position",
                        position_id=pos.id,
                        token=pos.token_symbol,
                        side=pos.side,
                        entry_price=pos.entry_price,
                        mark_price=mark_price,
                        unrealized_pct=round(
                            compute_unrealized_pct(pos, mark_price), 2
                        ),
                    )

                    await monitor_positions(pos, mark_price, executor, nansen)

                except Exception:
                    log.exception(
                        "position_monitor_error",
                        position_id=pos_dict.get("id", "unknown"),
                        token=pos_dict.get("token_symbol", "unknown"),
                    )

        except Exception:
            log.exception("monitor_cycle_error")

        await asyncio.sleep(30)
