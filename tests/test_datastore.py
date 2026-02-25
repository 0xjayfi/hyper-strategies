"""Comprehensive unit tests for the SQLite DataStore.

Tests cover all CRUD operations, foreign key constraints, time-based
queries, data retention, blacklist expiry logic, and edge cases on an
empty database.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.datastore import DataStore
from src.models import TradeMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_metrics(window_days: int = 30, **overrides) -> TradeMetrics:
    """Return a TradeMetrics instance with sensible defaults."""
    defaults = dict(
        window_days=window_days,
        total_trades=50,
        winning_trades=30,
        losing_trades=20,
        win_rate=0.6,
        gross_profit=15000.0,
        gross_loss=5000.0,
        profit_factor=3.0,
        avg_return=0.05,
        std_return=0.03,
        pseudo_sharpe=1.67,
        total_pnl=10000.0,
        roi_proxy=20.0,
        max_drawdown_proxy=0.05,
    )
    defaults.update(overrides)
    return TradeMetrics(**defaults)


def make_score_data(**overrides) -> dict:
    """Return a score data dict with sensible defaults."""
    defaults = dict(
        normalized_roi=0.5,
        normalized_sharpe=0.6,
        normalized_win_rate=0.4,
        consistency_score=0.7,
        smart_money_bonus=0.0,
        risk_management_score=0.8,
        style_multiplier=1.0,
        recency_decay=0.95,
        raw_composite_score=0.55,
        final_score=0.52,
        roi_tier_multiplier=1.0,
        passes_anti_luck=1,
    )
    defaults.update(overrides)
    return defaults


def _iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _iso_future(days: int = 30) -> str:
    """Return a future ISO-8601 datetime string."""
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def _iso_past(days: int = 1) -> str:
    """Return a past ISO-8601 datetime string."""
    return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def _make_position(token_symbol="BTC", side="Long", **overrides):
    """Return a position dict suitable for insert_position_snapshot."""
    defaults = dict(
        token_symbol=token_symbol,
        side=side,
        position_value_usd=50000.0,
        entry_price=42000.0,
        leverage_value=5.0,
        leverage_type="isolated",
        liquidation_price=35000.0,
        unrealized_pnl=1200.0,
        account_value=100000.0,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ds():
    """Yield an in-memory DataStore, then close it."""
    store = DataStore(db_path=":memory:")
    yield store
    store.close()


# ===================================================================
# Trader CRUD
# ===================================================================


class TestTraderCRUD:
    """Tests for trader insert / update / query operations."""

    def test_upsert_trader_new(self, ds: DataStore) -> None:
        """Inserting a new trader should be retrievable via get_trader()."""
        ds.upsert_trader("0xAAA", label="Alpha Trader")
        trader = ds.get_trader("0xAAA")

        assert trader is not None
        assert trader["address"] == "0xAAA"
        assert trader["label"] == "Alpha Trader"
        assert trader["is_active"] == 1
        assert "first_seen" in trader

    def test_upsert_trader_update(self, ds: DataStore) -> None:
        """Updating an existing trader should change label but preserve first_seen."""
        ds.upsert_trader("0xBBB", label="Original Label")
        original = ds.get_trader("0xBBB")
        original_first_seen = original["first_seen"]

        ds.upsert_trader("0xBBB", label="Updated Label")
        updated = ds.get_trader("0xBBB")

        assert updated["label"] == "Updated Label"
        assert updated["first_seen"] == original_first_seen

    def test_get_active_traders(self, ds: DataStore) -> None:
        """get_active_traders() should return only addresses with is_active=1."""
        ds.upsert_trader("0x001", label="Trader 1")
        ds.upsert_trader("0x002", label="Trader 2")
        ds.upsert_trader("0x003", label="Trader 3")

        # Deactivate one trader
        ds._conn.execute(
            "UPDATE traders SET is_active = 0 WHERE address = ?", ("0x002",)
        )
        ds._conn.commit()

        active = ds.get_active_traders()

        assert len(active) == 2
        assert "0x001" in active
        assert "0x003" in active
        assert "0x002" not in active

    def test_get_trader_label(self, ds: DataStore) -> None:
        """get_trader_label() should return the label for a known trader."""
        ds.upsert_trader("0xLBL", label="Smart Money Whale")
        label = ds.get_trader_label("0xLBL")
        assert label == "Smart Money Whale"

    def test_get_trader_not_found(self, ds: DataStore) -> None:
        """get_trader() should return None for a nonexistent address."""
        result = ds.get_trader("0xNONEXISTENT")
        assert result is None


# ===================================================================
# Leaderboard Snapshots
# ===================================================================


class TestLeaderboardSnapshots:
    """Tests for leaderboard snapshot storage."""

    def test_insert_leaderboard_snapshot(self, ds: DataStore) -> None:
        """A leaderboard snapshot should be persisted and queryable."""
        ds.upsert_trader("0xLB1")
        ds.insert_leaderboard_snapshot(
            address="0xLB1",
            date_from="2026-01-01",
            date_to="2026-01-31",
            total_pnl=50000.0,
            roi=25.0,
            account_value=200000.0,
        )

        row = ds._conn.execute(
            "SELECT * FROM leaderboard_snapshots WHERE address = ?", ("0xLB1",)
        ).fetchone()

        assert row is not None
        assert row["total_pnl"] == 50000.0
        assert row["roi"] == 25.0
        assert row["account_value"] == 200000.0

    def test_multiple_leaderboard_snapshots(self, ds: DataStore) -> None:
        """Multiple snapshots for the same address on different dates should all be stored."""
        ds.upsert_trader("0xLB2")

        ds.insert_leaderboard_snapshot(
            address="0xLB2",
            date_from="2026-01-01",
            date_to="2026-01-15",
            total_pnl=10000.0,
            roi=10.0,
            account_value=100000.0,
        )
        ds.insert_leaderboard_snapshot(
            address="0xLB2",
            date_from="2026-01-15",
            date_to="2026-01-31",
            total_pnl=20000.0,
            roi=18.0,
            account_value=120000.0,
        )

        rows = ds._conn.execute(
            "SELECT * FROM leaderboard_snapshots WHERE address = ?", ("0xLB2",)
        ).fetchall()

        assert len(rows) == 2


# ===================================================================
# Trade Metrics
# ===================================================================


class TestTradeMetrics:
    """Tests for trade metrics insert and retrieval."""

    def test_insert_and_get_trade_metrics(self, ds: DataStore) -> None:
        """insert_trade_metrics + get_latest_metrics should round-trip all fields."""
        ds.upsert_trader("0xTM1")
        metrics = make_metrics(window_days=30, total_trades=42, win_rate=0.65)

        ds.insert_trade_metrics("0xTM1", metrics)
        retrieved = ds.get_latest_metrics("0xTM1", window_days=30)

        assert retrieved is not None
        assert retrieved.window_days == 30
        assert retrieved.total_trades == 42
        assert retrieved.win_rate == pytest.approx(0.65)
        assert retrieved.winning_trades == 30
        assert retrieved.losing_trades == 20
        assert retrieved.gross_profit == pytest.approx(15000.0)
        assert retrieved.gross_loss == pytest.approx(5000.0)
        assert retrieved.profit_factor == pytest.approx(3.0)
        assert retrieved.avg_return == pytest.approx(0.05)
        assert retrieved.std_return == pytest.approx(0.03)
        assert retrieved.pseudo_sharpe == pytest.approx(1.67)
        assert retrieved.total_pnl == pytest.approx(10000.0)
        assert retrieved.roi_proxy == pytest.approx(20.0)
        assert retrieved.max_drawdown_proxy == pytest.approx(0.05)

    def test_get_latest_metrics_returns_most_recent(self, ds: DataStore) -> None:
        """When multiple metrics exist for the same address+window, only the latest is returned."""
        ds.upsert_trader("0xTM2")

        old_metrics = make_metrics(window_days=30, total_trades=20)
        new_metrics = make_metrics(window_days=30, total_trades=60)

        # Insert old metrics with an earlier computed_at
        ds._conn.execute(
            """INSERT INTO trade_metrics
               (address, computed_at, window_days, total_trades, winning_trades,
                losing_trades, win_rate, gross_profit, gross_loss, profit_factor,
                avg_return, std_return, pseudo_sharpe, total_pnl, roi_proxy,
                max_drawdown_proxy)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "0xTM2", "2026-01-01T00:00:00", old_metrics.window_days,
                old_metrics.total_trades, old_metrics.winning_trades,
                old_metrics.losing_trades, old_metrics.win_rate,
                old_metrics.gross_profit, old_metrics.gross_loss,
                old_metrics.profit_factor, old_metrics.avg_return,
                old_metrics.std_return, old_metrics.pseudo_sharpe,
                old_metrics.total_pnl, old_metrics.roi_proxy,
                old_metrics.max_drawdown_proxy,
            ),
        )
        ds._conn.commit()

        # Insert newer metrics via the normal API (uses current time)
        ds.insert_trade_metrics("0xTM2", new_metrics)

        retrieved = ds.get_latest_metrics("0xTM2", window_days=30)
        assert retrieved is not None
        assert retrieved.total_trades == 60

    def test_get_latest_metrics_not_found(self, ds: DataStore) -> None:
        """get_latest_metrics should return None for a nonexistent address."""
        result = ds.get_latest_metrics("0xNONE", window_days=30)
        assert result is None

    def test_get_latest_metrics_different_windows(self, ds: DataStore) -> None:
        """Metrics for different windows should be stored and queried independently."""
        ds.upsert_trader("0xTM3")

        m7 = make_metrics(window_days=7, total_trades=10)
        m30 = make_metrics(window_days=30, total_trades=50)

        ds.insert_trade_metrics("0xTM3", m7)
        ds.insert_trade_metrics("0xTM3", m30)

        r7 = ds.get_latest_metrics("0xTM3", window_days=7)
        r30 = ds.get_latest_metrics("0xTM3", window_days=30)

        assert r7 is not None
        assert r7.window_days == 7
        assert r7.total_trades == 10

        assert r30 is not None
        assert r30.window_days == 30
        assert r30.total_trades == 50

    def test_insert_and_get_extended_metrics(self, ds: DataStore) -> None:
        """Extended assessment fields should round-trip through insert/get."""
        ds.upsert_trader("0xEXT")
        m = make_metrics(max_leverage=15.0, leverage_std=3.5, largest_trade_pnl_ratio=0.28, pnl_trend_slope=0.04)
        ds.insert_trade_metrics("0xEXT", m)
        result = ds.get_latest_metrics("0xEXT", window_days=30)
        assert result is not None
        assert result.max_leverage == 15.0
        assert result.leverage_std == 3.5
        assert result.largest_trade_pnl_ratio == 0.28
        assert result.pnl_trend_slope == 0.04


# ===================================================================
# Scores
# ===================================================================


class TestScores:
    """Tests for trader score insert and retrieval."""

    def test_insert_and_get_score(self, ds: DataStore) -> None:
        """insert_score + get_latest_score should round-trip all score fields."""
        ds.upsert_trader("0xSC1")
        score_data = make_score_data(final_score=0.72, normalized_roi=0.85)

        ds.insert_score("0xSC1", score_data)
        retrieved = ds.get_latest_score("0xSC1")

        assert retrieved is not None
        assert retrieved["final_score"] == pytest.approx(0.72)
        assert retrieved["normalized_roi"] == pytest.approx(0.85)
        assert retrieved["normalized_sharpe"] == pytest.approx(0.6)
        assert retrieved["normalized_win_rate"] == pytest.approx(0.4)
        assert retrieved["consistency_score"] == pytest.approx(0.7)
        assert retrieved["smart_money_bonus"] == pytest.approx(0.0)
        assert retrieved["risk_management_score"] == pytest.approx(0.8)
        assert retrieved["style_multiplier"] == pytest.approx(1.0)
        assert retrieved["recency_decay"] == pytest.approx(0.95)
        assert retrieved["raw_composite_score"] == pytest.approx(0.55)
        assert retrieved["roi_tier_multiplier"] == pytest.approx(1.0)
        assert retrieved["passes_anti_luck"] == 1

    def test_get_latest_score_not_found(self, ds: DataStore) -> None:
        """get_latest_score should return None for an unknown address."""
        result = ds.get_latest_score("0xUNKNOWN")
        assert result is None


# ===================================================================
# Allocations
# ===================================================================


class TestAllocations:
    """Tests for allocation batch insert and retrieval."""

    def test_insert_allocations_and_get_latest(self, ds: DataStore) -> None:
        """insert_allocations should store a batch, and get_latest_allocations should return it."""
        ds.upsert_trader("0xA")
        ds.upsert_trader("0xB")
        ds.upsert_trader("0xC")

        alloc_map = {"0xA": 0.5, "0xB": 0.3, "0xC": 0.2}
        ds.insert_allocations(alloc_map)

        latest = ds.get_latest_allocations()
        assert latest == pytest.approx(alloc_map)

    def test_allocations_latest_batch(self, ds: DataStore) -> None:
        """When two batches are inserted at different times, only the latest batch is returned."""
        ds.upsert_trader("0xD")
        ds.upsert_trader("0xE")
        ds.upsert_trader("0xF")

        # Insert first batch with an older timestamp
        old_time = "2026-01-01T00:00:00"
        for addr, weight in [("0xD", 0.4), ("0xE", 0.6)]:
            ds._conn.execute(
                """INSERT INTO allocations (computed_at, address, raw_weight, capped_weight, final_weight)
                   VALUES (?, ?, ?, ?, ?)""",
                (old_time, addr, weight, weight, weight),
            )
        ds._conn.commit()

        # Insert second (newer) batch via the API
        new_allocs = {"0xD": 0.3, "0xE": 0.3, "0xF": 0.4}
        ds.insert_allocations(new_allocs)

        latest = ds.get_latest_allocations()
        assert latest == pytest.approx(new_allocs)
        assert "0xF" in latest

    def test_insert_single_allocation(self, ds: DataStore) -> None:
        """insert_allocation (singular) should add one row that is retrievable."""
        ds.upsert_trader("0xSINGLE")
        ts = _iso_now()
        ds.insert_allocation(
            computed_at=ts,
            address="0xSINGLE",
            raw_weight=0.8,
            capped_weight=0.4,
            final_weight=0.4,
        )

        # Verify via direct query
        row = ds._conn.execute(
            "SELECT * FROM allocations WHERE address = ?", ("0xSINGLE",)
        ).fetchone()

        assert row is not None
        assert row["raw_weight"] == pytest.approx(0.8)
        assert row["capped_weight"] == pytest.approx(0.4)
        assert row["final_weight"] == pytest.approx(0.4)


# ===================================================================
# Blacklist
# ===================================================================


class TestBlacklist:
    """Tests for blacklist add / check / expiry operations."""

    def test_add_to_blacklist_and_check(self, ds: DataStore) -> None:
        """A blacklisted trader should be detected by is_blacklisted()."""
        ds.upsert_trader("0xBL1")
        expires = _iso_future(days=14)
        ds.add_to_blacklist("0xBL1", reason="liquidation", expires_at=expires)

        assert ds.is_blacklisted("0xBL1") is True

    def test_blacklist_expired(self, ds: DataStore) -> None:
        """A blacklist entry whose expires_at is in the past should not block the trader."""
        ds.upsert_trader("0xBL2")
        past = _iso_past(days=1)
        ds.add_to_blacklist("0xBL2", reason="liquidation", expires_at=past)

        assert ds.is_blacklisted("0xBL2") is False

    def test_get_blacklist_entry(self, ds: DataStore) -> None:
        """get_blacklist_entry should return the reason and expires_at for a blacklisted trader."""
        ds.upsert_trader("0xBL3")
        future = _iso_future(days=14)
        ds.add_to_blacklist("0xBL3", reason="manual", expires_at=future)

        entry = ds.get_blacklist_entry("0xBL3")
        assert entry is not None
        assert entry["reason"] == "manual"
        assert entry["expires_at"] == future

    def test_cleanup_expired_blacklist(self, ds: DataStore) -> None:
        """cleanup_expired_blacklist should remove expired entries and keep active ones."""
        ds.upsert_trader("0xBL4")
        ds.upsert_trader("0xBL5")

        # Expired entry
        ds.add_to_blacklist("0xBL4", reason="liquidation", expires_at=_iso_past(days=2))
        # Active entry
        ds.add_to_blacklist("0xBL5", reason="manual", expires_at=_iso_future(days=10))

        ds.cleanup_expired_blacklist()

        # Expired entry should be gone
        row_expired = ds._conn.execute(
            "SELECT * FROM blacklist WHERE address = ?", ("0xBL4",)
        ).fetchone()
        assert row_expired is None

        # Active entry should remain
        row_active = ds._conn.execute(
            "SELECT * FROM blacklist WHERE address = ?", ("0xBL5",)
        ).fetchone()
        assert row_active is not None

    def test_blacklist_default_expiry(self, ds: DataStore) -> None:
        """When no explicit expires_at is given, expiry should default to ~14 days from now."""
        ds.upsert_trader("0xBL6")
        ds.add_to_blacklist("0xBL6", reason="liquidation")

        entry = ds.get_blacklist_entry("0xBL6")
        assert entry is not None

        expires = datetime.fromisoformat(entry["expires_at"])
        expected = datetime.utcnow() + timedelta(days=14)

        # Allow 60 seconds of slack for test execution time
        delta = abs((expires - expected).total_seconds())
        assert delta < 60, f"Expected ~14 days from now, got delta={delta:.1f}s"


# ===================================================================
# Position Snapshots
# ===================================================================


class TestPositionSnapshots:
    """Tests for position snapshot insert and retrieval."""

    def test_insert_and_get_position_snapshot(self, ds: DataStore) -> None:
        """Inserting position snapshots should be retrievable via get_latest_position_snapshot."""
        ds.upsert_trader("0xPS1")

        positions = [
            _make_position("BTC", "Long", position_value_usd=50000.0, entry_price=42000.0),
            _make_position("ETH", "Short", position_value_usd=20000.0, entry_price=3000.0,
                           leverage_value=3.0, leverage_type="cross",
                           liquidation_price=4000.0, unrealized_pnl=-300.0),
        ]
        ds.insert_position_snapshot("0xPS1", positions)

        result = ds.get_latest_position_snapshot("0xPS1")
        assert result is not None
        assert len(result) == 2

        tokens = {p["token_symbol"] for p in result}
        assert tokens == {"BTC", "ETH"}

    def test_get_latest_position_snapshot_returns_most_recent(
        self, ds: DataStore
    ) -> None:
        """When snapshots exist at two different captured_at times, only the latest batch is returned."""
        ds.upsert_trader("0xPS2")

        old_time = "2026-01-01T00:00:00"
        new_time = "2026-02-01T00:00:00"

        # Insert old snapshot via direct SQL (to control captured_at)
        ds._conn.execute(
            """INSERT INTO position_snapshots
               (address, captured_at, token_symbol, side, position_value_usd,
                entry_price, leverage_value, leverage_type, liquidation_price,
                unrealized_pnl, account_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("0xPS2", old_time, "BTC", "Long", 10000.0, 40000.0, 2.0,
             "cross", 30000.0, 0.0, 50000.0),
        )
        ds._conn.commit()

        # Insert new snapshot via direct SQL
        ds._conn.execute(
            """INSERT INTO position_snapshots
               (address, captured_at, token_symbol, side, position_value_usd,
                entry_price, leverage_value, leverage_type, liquidation_price,
                unrealized_pnl, account_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("0xPS2", new_time, "ETH", "Short", 25000.0, 3200.0, 4.0,
             "isolated", 4000.0, -500.0, 60000.0),
        )
        ds._conn.commit()

        positions = ds.get_latest_position_snapshot("0xPS2")
        assert positions is not None
        assert len(positions) == 1
        assert positions[0]["token_symbol"] == "ETH"
        assert positions[0]["captured_at"] == new_time

    def test_get_position_history(self, ds: DataStore) -> None:
        """get_position_history should respect the lookback window for time filtering."""
        ds.upsert_trader("0xPS3")

        # Insert a snapshot from 2 hours ago
        recent_time = (datetime.utcnow() - timedelta(hours=2)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        # Insert a snapshot from 48 hours ago
        old_time = (datetime.utcnow() - timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )

        # Use direct SQL to control captured_at timestamps
        ds._conn.execute(
            """INSERT INTO position_snapshots
               (address, captured_at, token_symbol, side, position_value_usd,
                entry_price, leverage_value, leverage_type, liquidation_price,
                unrealized_pnl, account_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("0xPS3", old_time, "BTC", "Long", 10000.0, 40000.0, 2.0,
             "cross", 30000.0, 0.0, 50000.0),
        )
        ds._conn.execute(
            """INSERT INTO position_snapshots
               (address, captured_at, token_symbol, side, position_value_usd,
                entry_price, leverage_value, leverage_type, liquidation_price,
                unrealized_pnl, account_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("0xPS3", recent_time, "BTC", "Long", 12000.0, 40500.0, 2.0,
             "cross", 30500.0, 500.0, 52000.0),
        )
        ds._conn.commit()

        # Query with a 6-hour lookback -- should only include the recent one
        history = ds.get_position_history("0xPS3", "BTC", lookback_hours=6)
        assert len(history) == 1
        assert history[0]["position_value_usd"] == pytest.approx(12000.0)

        # Query with a 72-hour lookback -- should include both
        history_all = ds.get_position_history("0xPS3", "BTC", lookback_hours=72)
        assert len(history_all) == 2


# ===================================================================
# Data Retention
# ===================================================================


class TestDataRetention:
    """Tests for enforce_retention() cleanup of old data."""

    def test_enforce_retention(self, ds: DataStore) -> None:
        """Data older than 90 days should be deleted; recent data should be kept."""
        ds.upsert_trader("0xRET")

        old_date = "2025-01-01T00:00:00"  # >90 days ago from 2026-02-07
        recent_date = _iso_now()

        # Insert old leaderboard snapshot via direct SQL
        ds._conn.execute(
            """INSERT INTO leaderboard_snapshots
               (captured_at, date_from, date_to, address, total_pnl, roi, account_value)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (old_date, "2024-12-01", "2024-12-31", "0xRET", 1000.0, 5.0, 50000.0),
        )
        ds._conn.commit()

        # Insert recent leaderboard snapshot
        ds.insert_leaderboard_snapshot(
            address="0xRET",
            date_from="2026-01-01",
            date_to="2026-01-31",
            total_pnl=2000.0,
            roi=10.0,
            account_value=60000.0,
        )

        # Insert old trade metrics
        ds._conn.execute(
            """INSERT INTO trade_metrics
               (address, computed_at, window_days, total_trades, winning_trades,
                losing_trades, win_rate, gross_profit, gross_loss, profit_factor,
                avg_return, std_return, pseudo_sharpe, total_pnl, roi_proxy,
                max_drawdown_proxy)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "0xRET", old_date, 30, 10, 5, 5, 0.5,
                1000.0, 1000.0, 1.0, 0.01, 0.01, 1.0, 0.0, 0.0, 0.0,
            ),
        )
        ds._conn.commit()

        # Insert recent trade metrics
        ds.insert_trade_metrics("0xRET", make_metrics())

        # Insert old position snapshot via direct SQL
        ds._conn.execute(
            """INSERT INTO position_snapshots
               (address, captured_at, token_symbol, side, position_value_usd,
                entry_price, leverage_value, leverage_type, liquidation_price,
                unrealized_pnl, account_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("0xRET", old_date, "BTC", "Long", 5000.0, 40000.0, 2.0,
             "cross", 30000.0, 0.0, 50000.0),
        )
        ds._conn.commit()

        # Insert recent position snapshot
        ds.insert_position_snapshot(
            "0xRET",
            [_make_position("ETH", "Short", position_value_usd=10000.0)],
        )

        ds.enforce_retention()

        # Old leaderboard snapshot should be deleted
        old_lb = ds._conn.execute(
            "SELECT * FROM leaderboard_snapshots WHERE captured_at = ?", (old_date,)
        ).fetchone()
        assert old_lb is None

        # Recent leaderboard snapshot should remain
        recent_lb = ds._conn.execute(
            "SELECT * FROM leaderboard_snapshots WHERE captured_at > ?",
            (old_date,),
        ).fetchone()
        assert recent_lb is not None

        # Old trade metrics should be deleted
        old_tm = ds._conn.execute(
            "SELECT * FROM trade_metrics WHERE computed_at = ?", (old_date,)
        ).fetchone()
        assert old_tm is None

        # Recent trade metrics should remain
        recent_tm = ds._conn.execute(
            "SELECT * FROM trade_metrics WHERE computed_at > ?", (old_date,)
        ).fetchone()
        assert recent_tm is not None

        # Old position snapshot should be deleted
        old_ps = ds._conn.execute(
            "SELECT * FROM position_snapshots WHERE captured_at = ?", (old_date,)
        ).fetchone()
        assert old_ps is None

        # Recent position snapshot should remain
        recent_ps = ds._conn.execute(
            "SELECT * FROM position_snapshots WHERE captured_at > ?",
            (old_date,),
        ).fetchone()
        assert recent_ps is not None


# ===================================================================
# Edge Cases
# ===================================================================


class TestEdgeCases:
    """Tests for empty database queries -- no errors should be raised."""

    def test_empty_database_queries(self, ds: DataStore) -> None:
        """All get_* methods should return empty/None on a fresh DB without errors."""
        assert ds.get_trader("0x000") is None
        assert ds.get_trader_label("0x000") is None
        assert ds.get_latest_metrics("0x000", window_days=30) is None
        assert ds.get_latest_score("0x000") is None
        assert ds.is_blacklisted("0x000") is False
        assert ds.get_blacklist_entry("0x000") is None

        active = ds.get_active_traders()
        assert active == []

        allocations = ds.get_latest_allocations()
        assert allocations == {}

        positions = ds.get_latest_position_snapshot("0x000")
        assert positions == []

        history = ds.get_position_history("0x000", "BTC", lookback_hours=24)
        assert history == []
