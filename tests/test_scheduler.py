"""Tests for the scheduler & orchestration (Phase 6).

Covers:
1. System state DB helpers (get/set)
2. Cadence checks (should_refresh, should_rebalance, etc.)
3. State transitions
4. Startup recovery from DB
5. Graceful shutdown
6. Integration: simulated multi-cycle operation with mocked APIs
7. Scheduler runs jobs in correct priority order
8. Rebalance cycle end-to-end with scheduler
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snap.database import get_connection, init_db
from snap.execution import PaperTradeClient
from snap.scheduler import (
    SchedulerState,
    SystemScheduler,
    get_system_state,
    set_system_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scheduler(db_path: str, **kwargs) -> SystemScheduler:
    """Create a scheduler with mocked clients."""
    client = PaperTradeClient({"BTC": 50_000.0, "ETH": 3_000.0})
    nansen_client = MagicMock()
    return SystemScheduler(
        client=client,
        nansen_client=nansen_client,
        db_path=db_path,
        **kwargs,
    )


def _seed_eligible_trader(db_path: str, address: str = "0xABC", score: float = 0.8):
    """Insert a trader and eligible score for testing."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO traders (address, label, account_value) VALUES (?, ?, ?)",
                (address, "Smart Money", 100_000.0),
            )
            conn.execute(
                """INSERT INTO trader_scores
                   (address, composite_score, is_eligible, passes_tier1, passes_quality)
                   VALUES (?, ?, 1, 1, 1)""",
                (address, score),
            )
    finally:
        conn.close()


# ===========================================================================
# 1. System State Helpers
# ===========================================================================


class TestSystemState:
    """Tests for get_system_state / set_system_state."""

    def test_get_nonexistent_key(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        assert get_system_state(db_path, "missing_key") is None

    def test_set_and_get(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        set_system_state(db_path, "test_key", "test_value")
        assert get_system_state(db_path, "test_key") == "test_value"

    def test_upsert(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        set_system_state(db_path, "key1", "v1")
        set_system_state(db_path, "key1", "v2")
        assert get_system_state(db_path, "key1") == "v2"

    def test_multiple_keys(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        set_system_state(db_path, "a", "1")
        set_system_state(db_path, "b", "2")
        assert get_system_state(db_path, "a") == "1"
        assert get_system_state(db_path, "b") == "2"


# ===========================================================================
# 2. Cadence Checks
# ===========================================================================


class TestCadenceChecks:
    """Tests for the _should_* cadence methods."""

    def test_should_refresh_traders_first_run(self, tmp_path):
        """First run (no previous refresh) -> should refresh."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        now = datetime.now(timezone.utc)
        assert sched._should_refresh_traders(now) is True

    def test_should_not_refresh_traders_recently_done(self, tmp_path):
        """Recently refreshed (1h ago) -> should NOT refresh."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched._last_trader_refresh = datetime.now(timezone.utc) - timedelta(hours=1)
        now = datetime.now(timezone.utc)
        assert sched._should_refresh_traders(now) is False

    def test_should_refresh_traders_after_24h(self, tmp_path):
        """Refreshed 25h ago -> should refresh."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched._last_trader_refresh = datetime.now(timezone.utc) - timedelta(hours=25)
        now = datetime.now(timezone.utc)
        assert sched._should_refresh_traders(now) is True

    def test_should_rebalance_first_run(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        now = datetime.now(timezone.utc)
        assert sched._should_rebalance(now) is True

    def test_should_not_rebalance_recently_done(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched._last_rebalance = datetime.now(timezone.utc) - timedelta(hours=2)
        now = datetime.now(timezone.utc)
        assert sched._should_rebalance(now) is False

    def test_should_rebalance_after_4h(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched._last_rebalance = datetime.now(timezone.utc) - timedelta(hours=5)
        now = datetime.now(timezone.utc)
        assert sched._should_rebalance(now) is True

    def test_should_ingest_trades_first_run(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        now = datetime.now(timezone.utc)
        assert sched._should_ingest_trades(now) is True

    def test_should_not_ingest_trades_recently_done(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched._last_trade_ingestion = datetime.now(timezone.utc) - timedelta(minutes=2)
        now = datetime.now(timezone.utc)
        assert sched._should_ingest_trades(now) is False

    def test_should_monitor_first_run(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        now = datetime.now(timezone.utc)
        assert sched._should_monitor(now) is True


# ===========================================================================
# 3. State Transitions
# ===========================================================================


class TestStateTransitions:
    """Tests for state machine transitions."""

    def test_initial_state_is_idle(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        assert sched.state == SchedulerState.IDLE

    def test_set_state(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched._set_state(SchedulerState.REBALANCING)
        assert sched.state == SchedulerState.REBALANCING

    def test_shutdown_state(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched.request_shutdown()
        assert sched.state == SchedulerState.SHUTTING_DOWN


# ===========================================================================
# 4. Startup Recovery
# ===========================================================================


class TestStartupRecovery:
    """Tests for recover_state()."""

    def test_recover_empty_db(self, tmp_path):
        """No previous state -> all timestamps remain None."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)
        sched.recover_state()
        assert sched._last_trader_refresh is None
        assert sched._last_rebalance is None
        assert sched._last_trade_ingestion is None

    def test_recover_from_db(self, tmp_path):
        """Recover previously stored timestamps."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        ts = "2026-02-07T10:00:00Z"
        set_system_state(db_path, "last_trader_refresh_at", ts)
        set_system_state(db_path, "last_rebalance_at", ts)
        set_system_state(db_path, "last_trade_ingestion_at", ts)

        sched = _make_scheduler(db_path)
        sched.recover_state()

        expected = datetime(2026, 2, 7, 10, 0, 0, tzinfo=timezone.utc)
        assert sched._last_trader_refresh == expected
        assert sched._last_rebalance == expected
        assert sched._last_trade_ingestion == expected

    def test_recover_partial(self, tmp_path):
        """Only some state exists."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        set_system_state(db_path, "last_rebalance_at", "2026-02-07T08:00:00Z")

        sched = _make_scheduler(db_path)
        sched.recover_state()

        assert sched._last_trader_refresh is None
        assert sched._last_rebalance == datetime(2026, 2, 7, 8, 0, 0, tzinfo=timezone.utc)

    def test_recover_invalid_timestamp(self, tmp_path):
        """Invalid timestamp -> gracefully ignored."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        set_system_state(db_path, "last_rebalance_at", "not-a-date")

        sched = _make_scheduler(db_path)
        sched.recover_state()
        assert sched._last_rebalance is None


# ===========================================================================
# 5. Graceful Shutdown
# ===========================================================================


class TestGracefulShutdown:
    """Tests for shutdown mechanics."""

    async def test_shutdown_stops_loop(self, tmp_path):
        """Scheduler stops when shutdown is requested."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        # Prevent any real jobs from running
        sched._last_trader_refresh = datetime.now(timezone.utc)
        sched._last_rebalance = datetime.now(timezone.utc)
        sched._last_trade_ingestion = datetime.now(timezone.utc)
        sched._last_monitor = datetime.now(timezone.utc)

        async def stop_after_delay():
            await asyncio.sleep(0.1)
            sched.request_shutdown()

        asyncio.create_task(stop_after_delay())
        await asyncio.wait_for(
            sched.run(tick_interval_s=0.05), timeout=5.0
        )
        assert sched.state == SchedulerState.SHUTTING_DOWN

    async def test_shutdown_method(self, tmp_path):
        """shutdown() sets state and clears tasks."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        await sched.shutdown()
        assert sched.state == SchedulerState.SHUTTING_DOWN
        assert sched._stop_event.is_set()


# ===========================================================================
# 6. Scheduler Loop with max_ticks
# ===========================================================================


class TestSchedulerLoop:
    """Tests for the main run() loop."""

    async def test_max_ticks(self, tmp_path):
        """Loop stops after max_ticks."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        # Suppress all jobs so ticks pass quickly
        sched._last_trader_refresh = datetime.now(timezone.utc)
        sched._last_rebalance = datetime.now(timezone.utc)
        sched._last_trade_ingestion = datetime.now(timezone.utc)
        sched._last_monitor = datetime.now(timezone.utc)

        await sched.run(tick_interval_s=0, max_ticks=5)

    async def test_trader_refresh_priority(self, tmp_path):
        """Trader refresh runs before rebalance when both are due."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        refresh_called = False
        rebalance_called = False

        original_refresh = sched._run_trader_refresh
        original_rebalance = sched._run_rebalance

        async def mock_refresh():
            nonlocal refresh_called
            refresh_called = True
            sched._last_trader_refresh = datetime.now(timezone.utc)
            sched._set_state(SchedulerState.IDLE)

        async def mock_rebalance():
            nonlocal rebalance_called
            rebalance_called = True
            sched._last_rebalance = datetime.now(timezone.utc)
            sched._set_state(SchedulerState.IDLE)

        sched._run_trader_refresh = mock_refresh
        sched._run_rebalance = mock_rebalance
        # Suppress trades and monitor
        sched._last_trade_ingestion = datetime.now(timezone.utc)
        sched._last_monitor = datetime.now(timezone.utc)

        # Both trader refresh and rebalance are due
        # Run 1 tick -> should do trader refresh first
        await sched.run(tick_interval_s=0, max_ticks=1)
        assert refresh_called is True
        assert rebalance_called is False

    async def test_monitor_runs_when_due(self, tmp_path):
        """Monitor runs when other jobs are not due."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        monitor_called = False

        async def mock_monitor():
            nonlocal monitor_called
            monitor_called = True
            sched._last_monitor = datetime.now(timezone.utc)
            sched._set_state(SchedulerState.IDLE)

        sched._run_monitor = mock_monitor
        sched._last_trader_refresh = datetime.now(timezone.utc)
        sched._last_rebalance = datetime.now(timezone.utc)
        sched._last_trade_ingestion = datetime.now(timezone.utc)

        await sched.run(tick_interval_s=0, max_ticks=1)
        assert monitor_called is True


# ===========================================================================
# 7. Rebalance cycle integration
# ===========================================================================


class TestRebalanceCycle:
    """Integration test for rebalance cycle via scheduler."""

    async def test_rebalance_no_traders(self, tmp_path):
        """Rebalance with no tracked traders -> no actions."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        await sched._run_rebalance()
        assert sched.state == SchedulerState.IDLE

    async def test_rebalance_updates_system_state(self, tmp_path):
        """Rebalance records timestamp in system_state."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Seed a trader
        _seed_eligible_trader(db_path)

        # Mock nansen_client.get_perp_positions to return empty positions
        sched = _make_scheduler(db_path)
        sched.nansen_client.get_perp_positions = AsyncMock(
            return_value={"asset_positions": [], "margin_summary_account_value_usd": 100_000}
        )

        await sched._run_rebalance()

        ts = get_system_state(db_path, "last_rebalance_at")
        assert ts is not None


# ===========================================================================
# 8. Trade ingestion integration
# ===========================================================================


class TestTradeIngestion:
    """Integration test for trade ingestion via scheduler."""

    async def test_ingestion_no_traders(self, tmp_path):
        """No tracked traders -> ingestion skips."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        sched = _make_scheduler(db_path)

        await sched._run_trade_ingestion()
        assert sched.state == SchedulerState.IDLE

    async def test_ingestion_updates_system_state(self, tmp_path):
        """Ingestion records timestamp in system_state."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _seed_eligible_trader(db_path)

        sched = _make_scheduler(db_path)
        sched.nansen_client.get_perp_trades = AsyncMock(return_value=[])

        await sched._run_trade_ingestion()

        ts = get_system_state(db_path, "last_trade_ingestion_at")
        assert ts is not None
