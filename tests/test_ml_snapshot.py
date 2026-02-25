"""Tests for daily ML feature snapshot job."""

from datetime import datetime, timedelta

import pytest

from snap.database import init_db
from snap.ml.daily_snapshot import (
    snapshot_trader_features,
    backfill_forward_pnl,
)


def _seed_db(conn, num_traders=3, days=30):
    base = datetime(2026, 2, 15)
    for t in range(num_traders):
        addr = f"0xsnap{t:04d}"
        conn.execute(
            "INSERT OR REPLACE INTO traders (address, account_value, label) VALUES (?, ?, ?)",
            (addr, 100000.0, ""),
        )
        for d in range(days):
            for h in range(3):
                ts = (base - timedelta(days=d, hours=h * 8)).strftime("%Y-%m-%dT%H:%M:%S.000000")
                conn.execute(
                    """INSERT INTO trade_history
                       (address, token_symbol, action, side, size, price,
                        value_usd, closed_pnl, fee_usd, timestamp, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (addr, "BTC", "Close", "Long", 0.1, 50000.0,
                     5000.0, 100.0, 2.0, ts, "2026-02-25T00:00:00Z"),
                )
    conn.commit()


class TestSnapshotTraderFeatures:
    def test_inserts_snapshots(self):
        conn = init_db(":memory:")
        _seed_db(conn)
        count = snapshot_trader_features(conn, as_of=datetime(2026, 2, 15))
        assert count >= 1
        rows = conn.execute("SELECT COUNT(*) FROM ml_feature_snapshots").fetchone()[0]
        assert rows == count
        conn.close()

    def test_snapshot_has_null_forward_pnl(self):
        conn = init_db(":memory:")
        _seed_db(conn)
        snapshot_trader_features(conn, as_of=datetime(2026, 2, 15))
        row = conn.execute(
            "SELECT forward_pnl_7d FROM ml_feature_snapshots LIMIT 1"
        ).fetchone()
        assert row[0] is None
        conn.close()


class TestBackfillForwardPnl:
    def test_fills_forward_pnl(self):
        conn = init_db(":memory:")
        _seed_db(conn, days=30)
        # Snapshot at day 10 (should have 7 days of forward data)
        as_of = datetime(2026, 2, 5)
        snapshot_trader_features(conn, as_of=as_of)
        filled = backfill_forward_pnl(conn, as_of=datetime(2026, 2, 15))
        assert filled >= 1
        row = conn.execute(
            "SELECT forward_pnl_7d FROM ml_feature_snapshots WHERE forward_pnl_7d IS NOT NULL LIMIT 1"
        ).fetchone()
        assert row is not None
        conn.close()
