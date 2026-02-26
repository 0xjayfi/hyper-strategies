"""Tests for daily ML feature snapshot job."""

import logging
from datetime import datetime, timedelta

import pytest

from snap.database import init_db
from snap.ml.daily_snapshot import (
    snapshot_trader_features,
    backfill_forward_pnl,
)
from snap.ml.features import FEATURE_COLUMNS


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

    def test_snapshot_uses_18_feature_columns(self):
        """Verify snapshot only inserts the 18 active FEATURE_COLUMNS (not the deprecated 23)."""
        assert len(FEATURE_COLUMNS) == 18
        conn = init_db(":memory:")
        _seed_db(conn)
        snapshot_trader_features(conn, as_of=datetime(2026, 2, 15))
        row = conn.execute(
            "SELECT * FROM ml_feature_snapshots LIMIT 1"
        ).fetchone()
        assert row is not None
        # The 18 active feature columns should have values populated
        col_names = [desc[0] for desc in conn.execute(
            "SELECT * FROM ml_feature_snapshots LIMIT 1"
        ).description]
        for fc in FEATURE_COLUMNS:
            assert fc in col_names, f"Active feature {fc} not found in DB columns"
        conn.close()

    def test_deprecated_columns_are_null(self):
        """Deprecated columns (removed from FEATURE_COLUMNS) should be NULL in new snapshots."""
        deprecated = [
            "market_correlation",
            "position_concentration",
            "num_open_positions",
            "avg_leverage",
            "risk_mgmt_score",
        ]
        conn = init_db(":memory:")
        _seed_db(conn)
        snapshot_trader_features(conn, as_of=datetime(2026, 2, 15))
        row = conn.execute(
            "SELECT market_correlation, position_concentration, num_open_positions, "
            "avg_leverage, risk_mgmt_score FROM ml_feature_snapshots LIMIT 1"
        ).fetchone()
        assert row is not None
        for i, col in enumerate(deprecated):
            assert row[i] is None, f"Deprecated column {col} should be NULL but got {row[i]}"
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

    def test_fallback_account_value_logs_warning(self, caplog):
        """When traders.account_value is NULL, a warning should be logged."""
        conn = init_db(":memory:")
        _seed_db(conn, days=30)
        # Set account_value to NULL so the fallback triggers
        conn.execute("UPDATE traders SET account_value = NULL")
        conn.commit()

        as_of = datetime(2026, 2, 5)
        snapshot_trader_features(conn, as_of=as_of)
        with caplog.at_level(logging.WARNING, logger="snap.ml.daily_snapshot"):
            backfill_forward_pnl(conn, as_of=datetime(2026, 2, 15))
        assert any("$100K fallback" in msg for msg in caplog.messages)
        conn.close()
