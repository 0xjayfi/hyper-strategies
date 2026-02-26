"""Daily feature snapshot job for ongoing ML data collection."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from snap.ml.features import FEATURE_COLUMNS, extract_all_trader_features
from snap.ml.dataset import compute_forward_pnl

logger = logging.getLogger(__name__)


def snapshot_trader_features(
    conn: sqlite3.Connection,
    as_of: datetime | None = None,
) -> int:
    """Snapshot current features for all traders into ml_feature_snapshots.

    Inserts one row per trader with forward_pnl_7d = NULL (to be backfilled later).
    Returns count of rows inserted.
    """
    if as_of is None:
        as_of = datetime.utcnow()

    snapshot_date = as_of.strftime("%Y-%m-%d")
    features_list = extract_all_trader_features(conn, as_of)

    count = 0
    for feat in features_list:
        addr = feat.pop("address", None)
        if addr is None:
            continue
        cols = ["address", "snapshot_date"] + FEATURE_COLUMNS
        vals = [addr, snapshot_date] + [feat.get(c, None) for c in FEATURE_COLUMNS]
        placeholders = ", ".join(["?"] * len(vals))
        col_str = ", ".join(cols)
        conn.execute(
            f"INSERT INTO ml_feature_snapshots ({col_str}) VALUES ({placeholders})",
            vals,
        )
        count += 1

    conn.commit()
    return count


def backfill_forward_pnl(
    conn: sqlite3.Connection,
    as_of: datetime | None = None,
    forward_days: int = 7,
) -> int:
    """Backfill forward_pnl_7d for snapshots that are old enough.

    Finds snapshots where forward_pnl_7d IS NULL and snapshot_date is at
    least forward_days ago, then computes and fills in the actual PnL.
    Returns count of rows updated.
    """
    if as_of is None:
        as_of = datetime.utcnow()

    cutoff = (as_of - timedelta(days=forward_days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT id, address, snapshot_date FROM ml_feature_snapshots
           WHERE forward_pnl_7d IS NULL AND snapshot_date <= ?""",
        (cutoff,),
    ).fetchall()

    count = 0
    for row_id, address, snap_date in rows:
        snap_dt = datetime.fromisoformat(snap_date)
        pnl = compute_forward_pnl(conn, address, snap_dt, forward_days)
        if pnl is not None:
            # Normalize by account value
            acct_row = conn.execute(
                "SELECT account_value FROM traders WHERE address = ?", (address,)
            ).fetchone()
            acct_val = float(acct_row[0]) if acct_row and acct_row[0] else 100_000.0
            if not (acct_row and acct_row[0]):
                logger.warning(
                    "Using $100K fallback account value for %s (no account_value in traders table)",
                    address,
                )
            normalized = pnl / acct_val if acct_val > 0 else 0.0
            conn.execute(
                "UPDATE ml_feature_snapshots SET forward_pnl_7d = ? WHERE id = ?",
                (normalized, row_id),
            )
            count += 1

    conn.commit()
    return count
