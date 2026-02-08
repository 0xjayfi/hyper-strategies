"""Position monitoring service — stop-loss, trailing stop, and time-stop enforcement.

Implements Algorithm 4.5 from the specification:

1. ``check_stop_loss``      — Fixed stop-loss trigger check.
2. ``update_trailing_stop``  — Ratchet trailing high/low and check trigger.
3. ``check_time_stop``       — Close positions exceeding MAX_POSITION_DURATION_HOURS.
4. ``close_position_market`` — Emergency close via exchange client.
5. ``monitor_positions``     — Main monitoring loop (60s cadence).
6. Rebalance mutex           — asyncio.Lock shared with execution engine.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from snap.config import (
    MONITOR_INTERVAL_SECONDS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.database import get_connection
from snap.execution import HyperliquidClient

logger = logging.getLogger(__name__)

# Module-level lock shared between monitoring and rebalancing.
rebalance_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# 1. Stop-Loss Check
# ---------------------------------------------------------------------------


def check_stop_loss(
    mark_price: float,
    stop_loss_price: float,
    side: str,
) -> bool:
    """Return ``True`` if the stop-loss has been triggered.

    Long:  triggered when ``mark_price <= stop_loss_price``.
    Short: triggered when ``mark_price >= stop_loss_price``.
    """
    if side == "Long":
        return mark_price <= stop_loss_price
    else:
        return mark_price >= stop_loss_price


# ---------------------------------------------------------------------------
# 2. Trailing Stop Update + Check
# ---------------------------------------------------------------------------


def update_trailing_stop(
    mark_price: float,
    trailing_high: float,
    trailing_stop_price: float,
    side: str,
    trailing_pct: float = TRAILING_STOP_PERCENT,
) -> tuple[float, float, bool]:
    """Update trailing high/low and check if trailing stop is triggered.

    For **Long** positions:
    - If ``mark_price > trailing_high``, ratchet ``trailing_high`` up and
      recompute ``trailing_stop_price = trailing_high * (1 - pct / 100)``.
    - Triggered when ``mark_price <= trailing_stop_price``.

    For **Short** positions:
    - If ``mark_price < trailing_high`` (trailing_low), ratchet down and
      recompute ``trailing_stop_price = trailing_low * (1 + pct / 100)``.
    - Triggered when ``mark_price >= trailing_stop_price``.

    Parameters
    ----------
    mark_price:
        Current mark price.
    trailing_high:
        Current trailing high (for longs) or trailing low (for shorts).
    trailing_stop_price:
        Current trailing stop trigger price.
    side:
        ``"Long"`` or ``"Short"``.
    trailing_pct:
        Trailing stop percentage (default from config).

    Returns
    -------
    tuple[float, float, bool]
        ``(new_trailing_high, new_trailing_stop_price, triggered)``
    """
    if side == "Long":
        if mark_price > trailing_high:
            trailing_high = mark_price
            trailing_stop_price = trailing_high * (1 - trailing_pct / 100)
        triggered = mark_price <= trailing_stop_price
    else:
        # Short: trailing_high is actually the trailing low
        if mark_price < trailing_high:
            trailing_high = mark_price
            trailing_stop_price = trailing_high * (1 + trailing_pct / 100)
        triggered = mark_price >= trailing_stop_price
    return trailing_high, trailing_stop_price, triggered


# ---------------------------------------------------------------------------
# 3. Time-Stop Check
# ---------------------------------------------------------------------------


def check_time_stop(max_close_at: str, now: datetime | None = None) -> bool:
    """Return ``True`` if the position has exceeded its maximum duration.

    Parameters
    ----------
    max_close_at:
        ISO-8601 UTC timestamp string (``YYYY-MM-DDTHH:MM:SSZ``).
    now:
        Current UTC datetime. Defaults to ``datetime.now(timezone.utc)``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        deadline = datetime.strptime(max_close_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return False
    return now >= deadline


# ---------------------------------------------------------------------------
# 4. Emergency Close via Exchange Client
# ---------------------------------------------------------------------------


async def close_position_market(
    client: HyperliquidClient,
    db_path: str,
    token_symbol: str,
    side: str,
    size: float,
    entry_price: float,
    exit_reason: str,
    opened_at: str | None = None,
) -> bool:
    """Close a position at market and record the result in the database.

    1. Place a MARKET close order via *client*.
    2. Update ``orders`` table.
    3. Remove from ``our_positions``.
    4. Write a ``pnl_ledger`` entry with the given ``exit_reason``.

    Returns ``True`` on successful fill, ``False`` otherwise.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        result = await client.place_order(
            token=token_symbol,
            side=side,
            size=size,
            order_type="MARKET",
        )
    except Exception:
        logger.exception("Failed to place close order for %s", token_symbol)
        return False

    fill_status = result.get("status", "FAILED")
    filled_size = result.get("filled_size", 0.0)
    filled_price = result.get("avg_price", 0.0)
    fee_usd = result.get("fee", 0.0)

    if fill_status not in ("FILLED", "PARTIAL"):
        logger.error("Close order not filled for %s: %s", token_symbol, fill_status)
        return False

    # Compute realized PnL
    if side == "Long":
        realized_pnl = (filled_price - entry_price) * filled_size
    else:
        realized_pnl = (entry_price - filled_price) * filled_size

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

    conn = get_connection(db_path)
    try:
        with conn:
            # Record order
            conn.execute(
                """INSERT INTO orders
                   (rebalance_id, token_symbol, side, order_type,
                    intended_usd, intended_size, status,
                    filled_size, filled_avg_price, filled_usd, fee_usd,
                    created_at, filled_at)
                   VALUES (?, ?, ?, 'MARKET', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"monitor_{exit_reason.lower()}",
                    token_symbol,
                    side,
                    size * entry_price,
                    size,
                    fill_status,
                    filled_size,
                    filled_price,
                    filled_size * filled_price,
                    fee_usd,
                    now_str,
                    now_str,
                ),
            )

            # Write PnL ledger
            conn.execute(
                """INSERT INTO pnl_ledger
                   (token_symbol, side, entry_price, exit_price, size,
                    realized_pnl, fees_total, hold_hours, exit_reason, closed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    token_symbol,
                    side,
                    entry_price,
                    filled_price,
                    filled_size,
                    realized_pnl,
                    fee_usd,
                    hold_hours,
                    exit_reason,
                    now_str,
                ),
            )

            # Remove from our_positions
            conn.execute(
                "DELETE FROM our_positions WHERE token_symbol = ?",
                (token_symbol,),
            )
    finally:
        conn.close()

    logger.info(
        "Closed %s %s position: exit_reason=%s pnl=%.2f",
        token_symbol,
        side,
        exit_reason,
        realized_pnl,
    )
    return True


# ---------------------------------------------------------------------------
# 5. Single-Pass Monitor (checks all positions once)
# ---------------------------------------------------------------------------


async def _monitor_once(
    client: HyperliquidClient,
    db_path: str,
    now: datetime | None = None,
) -> dict:
    """Run one monitoring pass over all open positions.

    Returns a summary dict with counts of actions taken.
    """
    summary = {
        "positions_checked": 0,
        "stop_loss_triggered": 0,
        "trailing_stop_triggered": 0,
        "time_stop_triggered": 0,
        "trailing_high_updated": 0,
        "errors": 0,
    }

    if now is None:
        now = datetime.now(timezone.utc)

    # Read all positions
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM our_positions").fetchall()
        positions = [dict(r) for r in rows]
    finally:
        conn.close()

    if not positions:
        return summary

    for pos in positions:
        summary["positions_checked"] += 1
        token = pos["token_symbol"]
        side = pos["side"]
        size = pos["size"]
        entry_price = pos["entry_price"]
        stop_loss_price = pos["stop_loss_price"]
        trailing_stop_price = pos["trailing_stop_price"]
        trailing_high = pos["trailing_high"]
        max_close_at = pos.get("max_close_at", "")
        opened_at = pos.get("opened_at")

        # Fetch current mark price
        try:
            mark_price = await client.get_mark_price(token)
        except Exception:
            logger.exception("Failed to get mark price for %s", token)
            summary["errors"] += 1
            continue

        if mark_price <= 0:
            logger.warning("Invalid mark price (%.4f) for %s, skipping", mark_price, token)
            continue

        # Check 1: Stop-loss
        if check_stop_loss(mark_price, stop_loss_price, side):
            logger.warning(
                "STOP_LOSS triggered for %s %s: mark=%.4f stop=%.4f",
                token, side, mark_price, stop_loss_price,
            )
            ok = await close_position_market(
                client, db_path, token, side, size, entry_price,
                exit_reason="STOP_LOSS", opened_at=opened_at,
            )
            if ok:
                summary["stop_loss_triggered"] += 1
            else:
                summary["errors"] += 1
            continue

        # Check 2: Trailing stop update + trigger
        new_high, new_stop, trailing_triggered = update_trailing_stop(
            mark_price, trailing_high, trailing_stop_price, side,
        )

        if trailing_triggered:
            logger.warning(
                "TRAILING_STOP triggered for %s %s: mark=%.4f trailing_stop=%.4f",
                token, side, mark_price, new_stop,
            )
            ok = await close_position_market(
                client, db_path, token, side, size, entry_price,
                exit_reason="TRAILING_STOP", opened_at=opened_at,
            )
            if ok:
                summary["trailing_stop_triggered"] += 1
            else:
                summary["errors"] += 1
            continue

        # Update trailing high/stop if they changed
        if new_high != trailing_high or new_stop != trailing_stop_price:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(db_path)
            try:
                with conn:
                    conn.execute(
                        """UPDATE our_positions
                           SET trailing_high = ?, trailing_stop_price = ?,
                               current_price = ?, updated_at = ?
                           WHERE token_symbol = ?""",
                        (new_high, new_stop, mark_price, now_str, token),
                    )
            finally:
                conn.close()
            summary["trailing_high_updated"] += 1

        # Check 3: Time-stop
        if max_close_at and check_time_stop(max_close_at, now):
            logger.warning(
                "TIME_STOP triggered for %s %s: max_close_at=%s",
                token, side, max_close_at,
            )
            ok = await close_position_market(
                client, db_path, token, side, size, entry_price,
                exit_reason="TIME_STOP", opened_at=opened_at,
            )
            if ok:
                summary["time_stop_triggered"] += 1
            else:
                summary["errors"] += 1
            continue

        # Update current price even if no stop triggered
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if side == "Long":
            unrealized_pnl = (mark_price - entry_price) * size
        else:
            unrealized_pnl = (entry_price - mark_price) * size
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """UPDATE our_positions
                       SET current_price = ?, unrealized_pnl = ?, updated_at = ?
                       WHERE token_symbol = ?""",
                    (mark_price, unrealized_pnl, now_str, token),
                )
        finally:
            conn.close()

    return summary


# ---------------------------------------------------------------------------
# 6. Continuous Monitoring Loop
# ---------------------------------------------------------------------------


async def monitor_positions(
    client: HyperliquidClient,
    db_path: str,
    interval_s: int = MONITOR_INTERVAL_SECONDS,
    max_iterations: int | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Continuously monitor positions at the configured cadence.

    Acquires ``rebalance_lock`` for each check cycle so that monitoring
    pauses while a rebalance is in progress.

    Parameters
    ----------
    client:
        Exchange client for mark prices and order placement.
    db_path:
        Path to the SQLite database.
    interval_s:
        Seconds between monitoring passes (default 60).
    max_iterations:
        If set, stop after this many iterations (for testing).
    stop_event:
        If set, stop when this event is set (for graceful shutdown).
    """
    iteration = 0
    while True:
        if stop_event and stop_event.is_set():
            logger.info("Monitor stop event received, exiting loop")
            break
        if max_iterations is not None and iteration >= max_iterations:
            break

        async with rebalance_lock:
            try:
                summary = await _monitor_once(client, db_path)
                logger.info(
                    "Monitor pass #%d: checked=%d stop_loss=%d trailing=%d time=%d errors=%d",
                    iteration + 1,
                    summary["positions_checked"],
                    summary["stop_loss_triggered"],
                    summary["trailing_stop_triggered"],
                    summary["time_stop_triggered"],
                    summary["errors"],
                )
            except Exception:
                logger.exception("Monitoring pass #%d failed", iteration + 1)

        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            break
        await asyncio.sleep(interval_s)
