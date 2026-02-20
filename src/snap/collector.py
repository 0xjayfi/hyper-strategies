"""Data collector module for the Snap copytrading system.

Separates data fetching from scoring so data can be collected once and
reused across multiple scoring strategy experiments.

Three-phase collection:

1. Fetch leaderboard (7d, 30d, 90d) -> merge -> store in traders table
2. Fetch trades (90d lookback) for qualifying traders -> store in trade_history
3. Fetch current positions for qualifying traders -> store in position_snapshots
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from snap.config import MIN_ACCOUNT_VALUE, MIN_PNL_30D, TRADE_CACHE_TTL_HOURS
from snap.database import get_connection
from snap.ingestion import ingest_positions

logger = logging.getLogger(__name__)

# Per-timeframe leaderboard config: (days, min_total_pnl).
_LEADERBOARD_RANGES: dict[str, tuple[int, float]] = {
    "7d": (7, 0),
    "30d": (30, 0),
    "90d": (90, 0),
}


@dataclass
class CollectionSummary:
    """Summary of a data collection run."""

    traders_fetched: int
    trades_cached: int  # reused from cache
    trades_fetched: int  # fetched from API
    positions_fetched: int
    errors: int
    duration_seconds: float


# ---------------------------------------------------------------------------
# Phase 1: Leaderboard fetch & merge
# ---------------------------------------------------------------------------


async def fetch_and_merge_leaderboard(
    client,
    min_account_value: float = MIN_ACCOUNT_VALUE,
) -> dict[str, dict]:
    """Fetch leaderboard data for 3 timeframes and merge by address.

    For each of the 7d, 30d, and 90d windows this function calls
    ``client.get_leaderboard`` (with standard filters) and merges
    the results by ``trader_address``.

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    min_account_value:
        Minimum account value filter for the leaderboard API.

    Returns
    -------
    dict[str, dict]
        Mapping of address -> merged trader record with keys:
        ``address``, ``label``, ``account_value``, ``roi_7d``, ``roi_30d``,
        ``roi_90d``, ``pnl_7d``, ``pnl_30d``, ``pnl_90d``.
    """
    today = datetime.now(timezone.utc).date()
    merged: dict[str, dict] = {}

    for label, (days, min_pnl) in _LEADERBOARD_RANGES.items():
        date_from = (today - timedelta(days=days)).isoformat()
        date_to = today.isoformat()

        logger.info(
            "Fetching leaderboard range=%s date_from=%s date_to=%s min_pnl=%.0f",
            label,
            date_from,
            date_to,
            min_pnl,
        )

        entries = await client.get_leaderboard(
            date_from=date_from,
            date_to=date_to,
            min_account_value=min_account_value,
            min_total_pnl=min_pnl,
        )

        logger.info("Leaderboard range=%s returned %d entries", label, len(entries))

        for entry in entries:
            addr = entry.get("trader_address", "")
            if not addr:
                continue

            if addr not in merged:
                merged[addr] = {
                    "address": addr,
                    "label": "",
                    "account_value": 0.0,
                    "roi_7d": None,
                    "roi_30d": None,
                    "roi_90d": None,
                    "pnl_7d": None,
                    "pnl_30d": None,
                    "pnl_90d": None,
                }

            trader = merged[addr]
            trader[f"roi_{label}"] = entry.get("roi", 0.0)
            trader[f"pnl_{label}"] = entry.get("total_pnl", 0.0)

            entry_account_value = entry.get("account_value", 0.0)
            if entry_account_value > trader["account_value"]:
                trader["account_value"] = entry_account_value

            entry_label = entry.get("trader_address_label", "")
            if entry_label and not trader["label"]:
                trader["label"] = entry_label

    return merged


# ---------------------------------------------------------------------------
# Phase 2: Trade cache helpers
# ---------------------------------------------------------------------------


def _get_cached_trades(
    db_path: str, address: str, ttl_hours: int
) -> list[dict] | None:
    """Return cached trades from ``trade_history`` if fresh enough.

    Returns ``None`` if no cached data or if all rows are older than
    *ttl_hours*.
    """
    conn = get_connection(db_path)
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            """SELECT token_symbol, action, side, size, price, value_usd,
                      closed_pnl, fee_usd, timestamp
               FROM trade_history
               WHERE address = ? AND fetched_at >= ?
               ORDER BY timestamp""",
            (address, cutoff),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _cache_trades(db_path: str, address: str, trades: list[dict]) -> None:
    """Store fetched trades into the ``trade_history`` table."""
    if not trades:
        return
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            for t in trades:
                conn.execute(
                    """INSERT OR IGNORE INTO trade_history
                       (address, token_symbol, action, side, size, price,
                        value_usd, closed_pnl, fee_usd, timestamp, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        address,
                        t.get("token_symbol"),
                        t.get("action"),
                        t.get("side"),
                        t.get("size"),
                        t.get("price"),
                        t.get("value_usd"),
                        t.get("closed_pnl"),
                        t.get("fee_usd"),
                        t.get("timestamp"),
                        now_utc,
                    ),
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_traders(db_path: str, merged: dict[str, dict]) -> None:
    """Upsert merged leaderboard traders into the traders table."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            for trader in merged.values():
                conn.execute(
                    """INSERT OR REPLACE INTO traders
                       (address, label, account_value,
                        roi_7d, roi_30d, roi_90d,
                        pnl_7d, pnl_30d, pnl_90d,
                        updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trader["address"],
                        trader["label"],
                        trader["account_value"],
                        trader.get("roi_7d"),
                        trader.get("roi_30d"),
                        trader.get("roi_90d"),
                        trader.get("pnl_7d"),
                        trader.get("pnl_30d"),
                        trader.get("pnl_90d"),
                        now_utc,
                    ),
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def collect_trader_data(
    client,
    db_path: str,
    min_account_value: float = MIN_ACCOUNT_VALUE,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> CollectionSummary:
    """Fetch all trader data from Nansen and cache in SQLite.

    Phase 1: Fetch leaderboard (7d, 30d, 90d) -> merge -> store in traders table
    Phase 2: For ALL traders with account_value >= min_account_value,
             fetch trades (90d lookback) -> store in trade_history
             (skip if cached within TRADE_CACHE_TTL_HOURS)
    Phase 3: Fetch current positions for qualifying traders -> store in
             position_snapshots

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    db_path:
        Filesystem path to the SQLite database.
    min_account_value:
        Minimum account value filter for the leaderboard API and
        qualifying threshold for trade/position fetching.
    on_progress:
        Optional callback ``(current, total)`` invoked after each trader
        is processed in Phase 2.  Used by the TUI to show progress.

    Returns
    -------
    CollectionSummary
        Stats about the collection run.
    """
    start = time.monotonic()
    errors = 0
    trades_cached = 0
    trades_fetched = 0

    # ------------------------------------------------------------------
    # Phase 1: Fetch and merge leaderboard across 3 timeframes
    # ------------------------------------------------------------------
    logger.info("Phase 1: Fetching leaderboard data...")
    merged = await fetch_and_merge_leaderboard(client, min_account_value)
    logger.info("Phase 1 complete: %d unique traders merged", len(merged))

    _store_traders(db_path, merged)

    # ------------------------------------------------------------------
    # Phase 2: Fetch trades for all qualifying traders
    # ------------------------------------------------------------------
    logger.info("Phase 2: Fetching trade history...")
    today = datetime.now(timezone.utc).date()
    date_from_90d = (today - timedelta(days=90)).isoformat()
    date_to = today.isoformat()

    qualifying = [
        addr
        for addr, t in merged.items()
        if t.get("account_value", 0) >= min_account_value
        and (t.get("pnl_30d") or 0) >= MIN_PNL_30D
    ]
    logger.info(
        "Phase 2: %d traders qualify (account_value >= %.0f, pnl_30d >= %.0f)",
        len(qualifying),
        min_account_value,
        MIN_PNL_30D,
    )

    total_qualifying = len(qualifying)
    for i, addr in enumerate(qualifying, 1):
        cached = _get_cached_trades(db_path, addr, TRADE_CACHE_TTL_HOURS)
        if cached is not None:
            trades_cached += 1
            if on_progress:
                on_progress(i, total_qualifying)
            if i % 100 == 0 or i == total_qualifying:
                logger.info(
                    "Phase 2 progress: %d/%d (cached=%d, fetched=%d, errors=%d)",
                    i,
                    total_qualifying,
                    trades_cached,
                    trades_fetched,
                    errors,
                )
            continue

        try:
            trades = await client.get_perp_trades(
                address=addr,
                date_from=date_from_90d,
                date_to=date_to,
            )
            _cache_trades(db_path, addr, trades)
            trades_fetched += 1
        except Exception:
            logger.warning(
                "Failed to fetch trades for address=%s, skipping",
                addr,
                exc_info=True,
            )
            errors += 1

        if on_progress:
            on_progress(i, total_qualifying)
        if i % 50 == 0 or i == total_qualifying:
            logger.info(
                "Phase 2 progress: %d/%d (cached=%d, fetched=%d, errors=%d)",
                i,
                total_qualifying,
                trades_cached,
                trades_fetched,
                errors,
            )

    logger.info(
        "Phase 2 complete: cached=%d, fetched=%d, errors=%d",
        trades_cached,
        trades_fetched,
        errors,
    )

    # ------------------------------------------------------------------
    # Phase 3: Fetch current positions for qualifying traders
    # ------------------------------------------------------------------
    logger.info("Phase 3: Fetching current positions...")
    snapshot_batch = str(uuid.uuid4())
    positions_fetched = await ingest_positions(
        client,
        db_path,
        qualifying,
        snapshot_batch,
    )
    logger.info(
        "Phase 3 complete: %d position snapshots stored (batch=%s)",
        positions_fetched,
        snapshot_batch,
    )

    duration = time.monotonic() - start
    summary = CollectionSummary(
        traders_fetched=len(merged),
        trades_cached=trades_cached,
        trades_fetched=trades_fetched,
        positions_fetched=positions_fetched,
        errors=errors,
        duration_seconds=round(duration, 2),
    )
    logger.info("Collection complete: %s", summary)
    return summary
