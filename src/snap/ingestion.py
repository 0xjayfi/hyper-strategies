"""Ingestion services for fetching Nansen data and storing it in SQLite.

Three ingestion functions correspond to the three Nansen API endpoints:

1. ``ingest_leaderboard`` - Perp Leaderboard across 3 timeframes (7d, 30d, 90d)
2. ``ingest_positions``   - Current perp positions per trader address
3. ``ingest_trades``      - Historical perp trades per trader address

Each function accepts a ``NansenClient`` instance and a database path, fetches
data from the API, and upserts results into the appropriate SQLite tables.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

from snap.config import MIN_ACCOUNT_VALUE
from snap.database import get_connection

logger = logging.getLogger(__name__)

# Per-timeframe leaderboard config: (days, min_total_pnl).
# 30d/90d thresholds tighten initial screening from ~3000 to ~1500 traders.
_LEADERBOARD_RANGES: dict[str, tuple[int, float]] = {
    "7d": (7, 0),
    "30d": (30, 10_000),
    "90d": (90, 50_000),
}


async def ingest_leaderboard(client, db_path: str) -> int:
    """Fetch Perp Leaderboard for 3 date ranges (7d, 30d, 90d) and merge by trader.

    For each date range the function:
    - Computes ``date_from = today - N days`` and ``date_to = today``.
    - Applies filters: ``account_value.min = 100_000``, ``total_pnl.min`` per-timeframe (0 / 10k / 50k).
    - Paginates through all pages via ``client.get_leaderboard``.

    Results are merged by ``trader_address``:
    - ``roi`` and ``pnl`` are stored per-timeframe (``roi_7d``, ``roi_30d``, etc.).
    - ``account_value`` is the maximum seen across timeframes.
    - ``label`` is taken from whichever response has a non-empty value.

    The merged traders are then upserted (INSERT OR REPLACE) into the ``traders``
    table.

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    db_path:
        Filesystem path to the SQLite database.

    Returns
    -------
    int
        Count of traders upserted.
    """
    today = datetime.now(timezone.utc).date()

    # Keyed by trader_address
    merged: dict[str, dict] = {}

    for label, (days, min_pnl) in _LEADERBOARD_RANGES.items():
        date_from = (today - timedelta(days=days)).isoformat()
        date_to = today.isoformat()

        logger.info(
            "Ingesting leaderboard range=%s date_from=%s date_to=%s min_pnl=%.0f",
            label,
            date_from,
            date_to,
            min_pnl,
        )

        entries = await client.get_leaderboard(
            date_from=date_from,
            date_to=date_to,
            min_account_value=MIN_ACCOUNT_VALUE,
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

            # Store timeframe-specific metrics
            roi_key = f"roi_{label}"
            pnl_key = f"pnl_{label}"
            trader[roi_key] = entry.get("roi", 0.0)
            trader[pnl_key] = entry.get("total_pnl", 0.0)

            # Keep max account value across timeframes
            entry_account_value = entry.get("account_value", 0.0)
            if entry_account_value > trader["account_value"]:
                trader["account_value"] = entry_account_value

            # Keep label from whichever response has a non-empty one
            entry_label = entry.get("trader_address_label", "")
            if entry_label and not trader["label"]:
                trader["label"] = entry_label

    # Upsert into traders table
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            for trader in merged.values():
                conn.execute(
                    """INSERT OR REPLACE INTO traders
                       (address, label, account_value, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (
                        trader["address"],
                        trader["label"],
                        trader["account_value"],
                        now_utc,
                    ),
                )
    finally:
        conn.close()

    count = len(merged)
    logger.info("Leaderboard ingestion complete: %d traders upserted", count)
    return count


async def ingest_positions(
    client,
    db_path: str,
    addresses: list[str],
    snapshot_batch: str,
) -> int:
    """Fetch current perp positions for each address and store snapshots.

    For each address, ``client.get_perp_positions`` is called.  Each position
    in the response is inserted into the ``position_snapshots`` table with the
    provided ``snapshot_batch`` UUID.

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    db_path:
        Filesystem path to the SQLite database.
    addresses:
        List of trader wallet addresses to fetch positions for.
    snapshot_batch:
        UUID string grouping this set of snapshots (one per rebalance cycle).

    Returns
    -------
    int
        Count of position snapshot rows stored.
    """
    total_stored = 0
    conn = get_connection(db_path)

    try:
        for address in addresses:
            logger.info("Fetching positions for address=%s", address)
            try:
                data = await client.get_perp_positions(address)
            except Exception:
                logger.exception(
                    "Failed to fetch positions for address=%s, skipping",
                    address,
                )
                continue

            asset_positions = data.get("asset_positions", [])
            account_value_raw = data.get("margin_summary_account_value_usd", 0)
            account_value = float(account_value_raw)

            for ap in asset_positions:
                pos = ap.get("position", {})

                size_raw = float(pos.get("size", 0))
                side = "Short" if size_raw < 0 else "Long"
                size = abs(size_raw)

                entry_price = float(pos.get("entry_price_usd") or 0)
                position_value_usd = float(pos.get("position_value_usd") or 0)
                leverage_value = pos.get("leverage_value")
                if leverage_value is not None:
                    leverage_value = float(leverage_value)
                leverage_type = pos.get("leverage_type", "")
                liquidation_price = float(pos.get("liquidation_price_usd") or 0)
                unrealized_pnl = float(pos.get("unrealized_pnl_usd") or 0)
                margin_used = float(pos.get("margin_used_usd") or 0)
                token_symbol = pos.get("token_symbol", "")

                # Compute mark_price from position_value / abs(size) if size > 0
                mark_price = None
                if size > 0:
                    mark_price = position_value_usd / size

                with conn:
                    conn.execute(
                        """INSERT INTO position_snapshots
                           (snapshot_batch, address, token_symbol, side, size,
                            entry_price, mark_price, position_value_usd,
                            leverage_value, leverage_type, liquidation_price,
                            unrealized_pnl, margin_used, account_value)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            snapshot_batch,
                            address,
                            token_symbol,
                            side,
                            size,
                            entry_price,
                            mark_price,
                            position_value_usd,
                            leverage_value,
                            leverage_type,
                            liquidation_price,
                            unrealized_pnl,
                            margin_used,
                            account_value,
                        ),
                    )
                total_stored += 1

            logger.info(
                "Stored %d position snapshots for address=%s",
                len(asset_positions),
                address,
            )
    finally:
        conn.close()

    logger.info(
        "Position ingestion complete: %d snapshots stored (batch=%s)",
        total_stored,
        snapshot_batch,
    )
    return total_stored


async def ingest_trades(
    client,
    db_path: str,
    addresses: list[str],
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    """Fetch perp trades for each address and store in trade_history.

    Uses INSERT OR IGNORE to prevent duplicates (the ``trade_history`` table
    has a UNIQUE constraint on ``(address, token_symbol, timestamp, action)``).

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    db_path:
        Filesystem path to the SQLite database.
    addresses:
        List of trader wallet addresses to fetch trades for.
    date_from:
        Start date in ``YYYY-MM-DD`` format.  Defaults to 90 days ago.
    date_to:
        End date in ``YYYY-MM-DD`` format.  Defaults to today.

    Returns
    -------
    int
        Count of new trades inserted (excludes duplicates that were ignored).
    """
    today = datetime.now(timezone.utc).date()

    if date_from is None:
        date_from = (today - timedelta(days=90)).isoformat()
    if date_to is None:
        date_to = today.isoformat()

    total_inserted = 0
    conn = get_connection(db_path)

    try:
        for address in addresses:
            logger.info(
                "Fetching trades for address=%s date_from=%s date_to=%s",
                address,
                date_from,
                date_to,
            )
            try:
                trades = await client.get_perp_trades(
                    address=address,
                    date_from=date_from,
                    date_to=date_to,
                )
            except Exception:
                logger.exception(
                    "Failed to fetch trades for address=%s, skipping",
                    address,
                )
                continue

            logger.info(
                "Fetched %d trades for address=%s",
                len(trades),
                address,
            )

            address_inserted = 0
            with conn:
                for trade in trades:
                    # Parse the timestamp.  The API returns ISO 8601 format
                    # such as "2025-10-08T18:46:11.452000".
                    timestamp_raw = trade.get("timestamp", "")
                    if isinstance(timestamp_raw, datetime):
                        timestamp_str = timestamp_raw.strftime(
                            "%Y-%m-%dT%H:%M:%S.%f"
                        )
                    else:
                        timestamp_str = str(timestamp_raw)

                    cursor = conn.execute(
                        """INSERT OR IGNORE INTO trade_history
                           (address, token_symbol, action, side, size,
                            price, value_usd, closed_pnl, fee_usd, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            address,
                            trade.get("token_symbol", ""),
                            trade.get("action", ""),
                            trade.get("side", ""),
                            trade.get("size", 0),
                            trade.get("price", 0),
                            trade.get("value_usd", 0),
                            trade.get("closed_pnl", 0),
                            trade.get("fee_usd", 0),
                            timestamp_str,
                        ),
                    )
                    if cursor.rowcount > 0:
                        address_inserted += 1

            total_inserted += address_inserted
            logger.info(
                "Inserted %d new trades for address=%s (of %d fetched)",
                address_inserted,
                address,
                len(trades),
            )
    finally:
        conn.close()

    logger.info(
        "Trade ingestion complete: %d new trades inserted",
        total_inserted,
    )
    return total_inserted
