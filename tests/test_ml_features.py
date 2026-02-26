"""Tests for ML feature extraction."""

import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from snap.database import init_db
from snap.ml.features import (
    FEATURE_COLUMNS,
    compute_pnl_volatility,
    compute_position_concentration,
    compute_max_drawdown,
    extract_trader_features,
    extract_all_trader_features,
)
from snap.scoring import compute_recency_decay


def _insert_trades(conn, address, trades):
    """Helper: insert trade rows into trade_history."""
    for t in trades:
        conn.execute(
            """INSERT INTO trade_history
               (address, token_symbol, action, side, size, price, value_usd,
                closed_pnl, fee_usd, timestamp, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                address,
                t.get("token", "BTC"),
                t.get("action", "Close"),
                t.get("side", "Long"),
                t.get("size", 1.0),
                t.get("price", 50000.0),
                t.get("value_usd", 50000.0),
                t.get("closed_pnl", 100.0),
                t.get("fee_usd", 5.0),
                t["timestamp"],
                "2026-02-25T00:00:00Z",
            ),
        )
    conn.commit()


def _insert_trader(conn, address, account_value=100000.0, label=""):
    conn.execute(
        "INSERT OR REPLACE INTO traders (address, account_value, label) VALUES (?, ?, ?)",
        (address, account_value, label),
    )
    conn.commit()


def _insert_positions(conn, address, snapshot_batch, positions):
    """Helper: insert position snapshot rows."""
    for p in positions:
        conn.execute(
            """INSERT INTO position_snapshots
               (snapshot_batch, address, token_symbol, side, size, entry_price,
                mark_price, position_value_usd, leverage_value, leverage_type,
                liquidation_price, unrealized_pnl, margin_used, account_value, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_batch,
                address,
                p.get("token", "BTC"),
                p.get("side", "Long"),
                p.get("size", 1.0),
                p.get("entry_price", 50000.0),
                p.get("mark_price", 51000.0),
                p.get("position_value_usd", 50000.0),
                p.get("leverage", 5.0),
                "cross",
                0.0,
                p.get("unrealized_pnl", 1000.0),
                10000.0,
                100000.0,
                p.get("captured_at", "2026-02-20T00:00:00Z"),
            ),
        )
    conn.commit()


class TestFeatureColumns:
    def test_feature_columns_count(self):
        """FEATURE_COLUMNS should have exactly 18 items after dead feature removal."""
        assert isinstance(FEATURE_COLUMNS, list)
        assert len(FEATURE_COLUMNS) == 18

    def test_includes_existing_scoring_features(self):
        for col in ["roi_7d", "roi_30d", "win_rate", "profit_factor", "pseudo_sharpe"]:
            assert col in FEATURE_COLUMNS

    def test_includes_retained_new_features(self):
        """pnl_volatility_7d and max_drawdown_30d should still be present."""
        for col in ["pnl_volatility_7d", "max_drawdown_30d"]:
            assert col in FEATURE_COLUMNS

    def test_dead_features_removed(self):
        """Removed features must not appear in FEATURE_COLUMNS."""
        removed = [
            "market_correlation",
            "position_concentration",
            "num_open_positions",
            "avg_leverage",
            "risk_mgmt_score",
        ]
        for col in removed:
            assert col not in FEATURE_COLUMNS, f"{col} should have been removed"


class TestPnlVolatility:
    def test_empty_returns_zero(self):
        assert compute_pnl_volatility([]) == 0.0

    def test_single_trade_returns_zero(self):
        assert compute_pnl_volatility([100.0]) == 0.0

    def test_varied_pnl(self):
        pnls = [100.0, -50.0, 200.0, -100.0, 50.0]
        vol = compute_pnl_volatility(pnls)
        assert vol > 0.0


class TestPositionConcentration:
    def test_empty_returns_zero(self):
        assert compute_position_concentration([]) == 0.0

    def test_single_position(self):
        assert compute_position_concentration([50000.0]) == 1.0

    def test_equal_positions(self):
        result = compute_position_concentration([25000.0, 25000.0])
        assert abs(result - 0.5) < 0.01

    def test_concentrated(self):
        result = compute_position_concentration([90000.0, 5000.0, 5000.0])
        assert result == 0.9


class TestMaxDrawdown:
    def test_empty(self):
        assert compute_max_drawdown([]) == 0.0

    def test_no_drawdown(self):
        assert compute_max_drawdown([100.0, 200.0, 300.0]) == 0.0

    def test_simple_drawdown(self):
        # cumulative: 100, 50, 150 -> peak 100, trough 50 -> dd = 50%
        dd = compute_max_drawdown([100.0, -50.0, 100.0])
        assert abs(dd - 0.5) < 0.01


class TestRecencyDecayAsOf:
    """Test that compute_recency_decay with as_of avoids data leakage."""

    def test_as_of_produces_correct_decay(self):
        """With as_of exactly 30 days after trade, decay should be exp(-1)."""
        trade_ts = "2025-06-01T12:00:00Z"
        as_of = datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        decay = compute_recency_decay(trade_ts, as_of=as_of)
        expected = math.exp(-1.0)
        assert abs(decay - expected) < 0.01

    def test_as_of_differs_from_wall_clock(self):
        """Historical as_of should produce a different result than wall-clock now."""
        # A trade from 2024 -- wall clock is ~2026, but as_of is 1 day later
        trade_ts = "2024-01-01T00:00:00Z"
        as_of_near = datetime(2024, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
        decay_near = compute_recency_decay(trade_ts, as_of=as_of_near)
        decay_now = compute_recency_decay(trade_ts)  # uses wall clock
        # decay_near should be much higher (closer to 1) because as_of is only 1 day later
        # decay_now should be very small because wall clock is ~2 years later
        assert decay_near > 0.9, f"Expected near-1 decay, got {decay_near}"
        assert decay_now < 0.01, f"Expected near-0 decay, got {decay_now}"
        assert decay_near != decay_now

    def test_as_of_none_uses_wall_clock(self):
        """Default (as_of=None) should behave the same as the original function."""
        # Very recent trade -- both should give high decay
        now = datetime.now(timezone.utc)
        trade_ts = now.isoformat()
        decay = compute_recency_decay(trade_ts, as_of=None)
        assert decay > 0.9

    def test_as_of_naive_datetime_treated_as_utc(self):
        """A naive as_of datetime should be treated as UTC."""
        trade_ts = "2025-06-01T00:00:00Z"
        as_of_naive = datetime(2025, 6, 1, 0, 0, 0)  # no tzinfo
        decay = compute_recency_decay(trade_ts, as_of=as_of_naive)
        # 0 days since trade -> exp(0) = 1.0
        assert abs(decay - 1.0) < 0.01


class TestExtractTraderFeatures:
    def test_returns_dict_with_all_columns(self):
        conn = init_db(":memory:")
        addr = "0xtest1"
        _insert_trader(conn, addr)
        base = datetime(2026, 1, 15)
        trades = []
        for i in range(50):
            ts = base - timedelta(days=i % 30, hours=i)
            pnl = 100.0 if i % 3 != 0 else -50.0
            trades.append({
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000"),
                "closed_pnl": pnl,
                "action": "Close",
                "side": "Long",
                "token": "BTC" if i % 2 == 0 else "ETH",
                "price": 50000.0,
                "value_usd": 50000.0,
            })
        _insert_trades(conn, addr, trades)
        as_of = datetime(2026, 1, 15)
        features = extract_trader_features(conn, addr, as_of)
        assert features is not None
        for col in FEATURE_COLUMNS:
            assert col in features, f"Missing feature: {col}"
        # Verify removed features are NOT in the dict
        for col in ["market_correlation", "position_concentration",
                     "num_open_positions", "avg_leverage", "risk_mgmt_score"]:
            assert col not in features, f"Dead feature {col} should not be in output"
        conn.close()

    def test_returns_none_for_trader_with_no_trades(self):
        conn = init_db(":memory:")
        _insert_trader(conn, "0xempty")
        features = extract_trader_features(conn, "0xempty", datetime(2026, 1, 15))
        assert features is None
        conn.close()


class TestExtractAllTraderFeatures:
    def test_extracts_multiple_traders(self):
        conn = init_db(":memory:")
        base = datetime(2026, 1, 15)
        for addr_idx in range(3):
            addr = f"0xtrader{addr_idx}"
            _insert_trader(conn, addr)
            trades = []
            for i in range(30):
                ts = base - timedelta(days=i % 20, hours=i)
                trades.append({
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000"),
                    "closed_pnl": 50.0,
                    "token": "BTC",
                })
            _insert_trades(conn, addr, trades)

        results = extract_all_trader_features(conn, as_of=base)
        assert len(results) == 3
        conn.close()
