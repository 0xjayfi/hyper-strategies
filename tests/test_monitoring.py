"""Tests for the monitoring & stop system (Phase 5).

Covers:
1. Stop-loss trigger for long and short
2. Trailing stop ratchet: price rises, trailing_high updates, then drops to trigger
3. Time-stop: position opened 73h ago -> closed
4. Monitoring pauses during rebalance (mutex)
5. Emergency close flow
6. Full monitor_positions loop integration
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from snap.config import STOP_LOSS_PERCENT, TRAILING_STOP_PERCENT
from snap.database import get_connection, init_db
from snap.execution import PaperTradeClient
from snap.monitoring import (
    _monitor_once,
    check_stop_loss,
    check_time_stop,
    close_position_market,
    monitor_positions,
    rebalance_lock,
    update_trailing_stop,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_position(
    db_path: str,
    token: str = "BTC",
    side: str = "Long",
    size: float = 1.0,
    entry_price: float = 50_000.0,
    current_price: float = 50_000.0,
    stop_loss_price: float | None = None,
    trailing_stop_price: float | None = None,
    trailing_high: float | None = None,
    opened_at: str | None = None,
    max_close_at: str | None = None,
) -> None:
    """Insert a test position into our_positions."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if stop_loss_price is None:
        if side == "Long":
            stop_loss_price = entry_price * (1 - STOP_LOSS_PERCENT / 100)
        else:
            stop_loss_price = entry_price * (1 + STOP_LOSS_PERCENT / 100)

    if trailing_high is None:
        trailing_high = entry_price

    if trailing_stop_price is None:
        if side == "Long":
            trailing_stop_price = trailing_high * (1 - TRAILING_STOP_PERCENT / 100)
        else:
            trailing_stop_price = trailing_high * (1 + TRAILING_STOP_PERCENT / 100)

    if opened_at is None:
        opened_at = now_str

    if max_close_at is None:
        dt = datetime.now(timezone.utc) + timedelta(hours=72)
        max_close_at = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    position_usd = size * entry_price

    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO our_positions
                   (token_symbol, side, size, entry_price, current_price,
                    position_usd, unrealized_pnl, stop_loss_price,
                    trailing_stop_price, trailing_high, opened_at,
                    max_close_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?, ?)""",
                (
                    token, side, size, entry_price, current_price,
                    position_usd, stop_loss_price, trailing_stop_price,
                    trailing_high, opened_at, max_close_at, now_str,
                ),
            )
    finally:
        conn.close()


def _get_positions(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM our_positions").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_pnl_ledger(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM pnl_ledger").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ===========================================================================
# 1. Stop-Loss Check
# ===========================================================================


class TestCheckStopLoss:
    """Tests for check_stop_loss()."""

    def test_long_triggered(self):
        """Long stop-loss: mark <= stop -> triggered."""
        assert check_stop_loss(mark_price=47_000, stop_loss_price=47_500, side="Long") is True

    def test_long_not_triggered(self):
        """Long stop-loss: mark > stop -> not triggered."""
        assert check_stop_loss(mark_price=48_000, stop_loss_price=47_500, side="Long") is False

    def test_long_at_boundary(self):
        """Long stop-loss: mark == stop -> triggered (<=)."""
        assert check_stop_loss(mark_price=47_500, stop_loss_price=47_500, side="Long") is True

    def test_short_triggered(self):
        """Short stop-loss: mark >= stop -> triggered."""
        assert check_stop_loss(mark_price=53_000, stop_loss_price=52_500, side="Short") is True

    def test_short_not_triggered(self):
        """Short stop-loss: mark < stop -> not triggered."""
        assert check_stop_loss(mark_price=51_000, stop_loss_price=52_500, side="Short") is False

    def test_short_at_boundary(self):
        """Short stop-loss: mark == stop -> triggered (>=)."""
        assert check_stop_loss(mark_price=52_500, stop_loss_price=52_500, side="Short") is True


# ===========================================================================
# 2. Trailing Stop
# ===========================================================================


class TestUpdateTrailingStop:
    """Tests for update_trailing_stop()."""

    def test_long_price_rises_ratchets_up(self):
        """When mark > trailing_high for long, ratchet up."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=55_000,
            trailing_high=50_000,
            trailing_stop_price=46_000,  # old
            side="Long",
        )
        assert new_high == 55_000
        expected_stop = 55_000 * (1 - TRAILING_STOP_PERCENT / 100)
        assert new_stop == pytest.approx(expected_stop)
        assert triggered is False

    def test_long_price_falls_no_ratchet(self):
        """When mark < trailing_high for long, no update."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=48_000,
            trailing_high=50_000,
            trailing_stop_price=46_000,
            side="Long",
        )
        assert new_high == 50_000
        assert new_stop == 46_000
        assert triggered is False

    def test_long_trailing_triggered(self):
        """Long trailing stop triggered when mark drops to stop."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=45_900,
            trailing_high=50_000,
            trailing_stop_price=46_000,
            side="Long",
        )
        assert triggered is True

    def test_long_trailing_at_boundary(self):
        """Long trailing at exact boundary -> triggered."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=46_000,
            trailing_high=50_000,
            trailing_stop_price=46_000,
            side="Long",
        )
        assert triggered is True

    def test_short_price_falls_ratchets_down(self):
        """When mark < trailing_high (low) for short, ratchet down."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=45_000,
            trailing_high=50_000,
            trailing_stop_price=54_000,
            side="Short",
        )
        assert new_high == 45_000
        expected_stop = 45_000 * (1 + TRAILING_STOP_PERCENT / 100)
        assert new_stop == pytest.approx(expected_stop)
        assert triggered is False

    def test_short_price_rises_no_ratchet(self):
        """When mark > trailing_high (low) for short, no update."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=52_000,
            trailing_high=50_000,
            trailing_stop_price=54_000,
            side="Short",
        )
        assert new_high == 50_000
        assert new_stop == 54_000
        assert triggered is False

    def test_short_trailing_triggered(self):
        """Short trailing stop triggered when mark rises to stop."""
        new_high, new_stop, triggered = update_trailing_stop(
            mark_price=54_100,
            trailing_high=50_000,
            trailing_stop_price=54_000,
            side="Short",
        )
        assert triggered is True

    def test_ratchet_then_trigger_sequence(self):
        """Simulate: price rises, ratchets up, then drops to trigger."""
        # Initial: entry=50k, trailing_high=50k, stop=46k
        trailing_high = 50_000
        trailing_stop = 50_000 * (1 - TRAILING_STOP_PERCENT / 100)

        # Price rises to 55k -> ratchet
        trailing_high, trailing_stop, trig = update_trailing_stop(
            55_000, trailing_high, trailing_stop, "Long",
        )
        assert trailing_high == 55_000
        assert trig is False

        # Price rises to 60k -> ratchet again
        trailing_high, trailing_stop, trig = update_trailing_stop(
            60_000, trailing_high, trailing_stop, "Long",
        )
        assert trailing_high == 60_000
        expected_stop = 60_000 * (1 - TRAILING_STOP_PERCENT / 100)
        assert trailing_stop == pytest.approx(expected_stop)
        assert trig is False

        # Price drops to trailing stop -> trigger
        trailing_high, trailing_stop, trig = update_trailing_stop(
            expected_stop - 1, trailing_high, trailing_stop, "Long",
        )
        assert trig is True


# ===========================================================================
# 3. Time-Stop Check
# ===========================================================================


class TestCheckTimeStop:
    """Tests for check_time_stop()."""

    def test_position_expired(self):
        """Position opened 73h ago (max 72h) -> triggered."""
        now = datetime(2026, 2, 7, 12, 0, 0, tzinfo=timezone.utc)
        max_close = "2026-02-07T11:00:00Z"  # 1h ago
        assert check_time_stop(max_close, now) is True

    def test_position_not_expired(self):
        """Position opened 10h ago -> not triggered."""
        now = datetime(2026, 2, 7, 12, 0, 0, tzinfo=timezone.utc)
        max_close = "2026-02-08T12:00:00Z"  # 24h from now
        assert check_time_stop(max_close, now) is False

    def test_at_exact_deadline(self):
        """At exact deadline -> triggered (>=)."""
        now = datetime(2026, 2, 7, 12, 0, 0, tzinfo=timezone.utc)
        max_close = "2026-02-07T12:00:00Z"
        assert check_time_stop(max_close, now) is True

    def test_invalid_timestamp(self):
        """Invalid timestamp -> not triggered (safe fallback)."""
        now = datetime(2026, 2, 7, 12, 0, 0, tzinfo=timezone.utc)
        assert check_time_stop("not-a-date", now) is False

    def test_empty_timestamp(self):
        """Empty string -> not triggered."""
        now = datetime(2026, 2, 7, 12, 0, 0, tzinfo=timezone.utc)
        assert check_time_stop("", now) is False


# ===========================================================================
# 4. Emergency Close Flow
# ===========================================================================


class TestClosePositionMarket:
    """Tests for close_position_market()."""

    async def test_successful_close(self, tmp_path):
        """Close fills, position removed, PnL recorded."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_position(db_path, token="ETH", side="Long",
                         size=10.0, entry_price=3_000.0)

        client = PaperTradeClient({"ETH": 3_200.0})

        ok = await close_position_market(
            client, db_path, "ETH", "Long", 10.0, 3_000.0,
            exit_reason="STOP_LOSS",
        )
        assert ok is True

        # Position removed
        assert _get_positions(db_path) == []

        # PnL recorded
        ledger = _get_pnl_ledger(db_path)
        assert len(ledger) == 1
        assert ledger[0]["exit_reason"] == "STOP_LOSS"
        assert ledger[0]["token_symbol"] == "ETH"
        assert ledger[0]["side"] == "Long"

    async def test_close_short_pnl(self, tmp_path):
        """Close a short position, verify PnL calculation."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_position(db_path, token="SOL", side="Short",
                         size=100.0, entry_price=200.0)

        # Price dropped -> profitable short
        client = PaperTradeClient({"SOL": 180.0})

        ok = await close_position_market(
            client, db_path, "SOL", "Short", 100.0, 200.0,
            exit_reason="TRAILING_STOP",
        )
        assert ok is True

        ledger = _get_pnl_ledger(db_path)
        assert len(ledger) == 1
        assert ledger[0]["realized_pnl"] > 0  # Profitable close


# ===========================================================================
# 5. Single-Pass Monitor (_monitor_once)
# ===========================================================================


class TestMonitorOnce:
    """Tests for _monitor_once()."""

    async def test_no_positions(self, tmp_path):
        """No positions -> no actions."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        client = PaperTradeClient({})

        summary = await _monitor_once(client, db_path)
        assert summary["positions_checked"] == 0

    async def test_stop_loss_triggers(self, tmp_path):
        """Price drops below stop-loss -> position closed."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Entry at 50k, stop-loss at 47.5k (5%)
        _insert_position(db_path, token="BTC", side="Long",
                         size=1.0, entry_price=50_000.0)

        # Mark price below stop
        client = PaperTradeClient({"BTC": 47_000.0})

        summary = await _monitor_once(client, db_path)
        assert summary["stop_loss_triggered"] == 1
        assert _get_positions(db_path) == []
        assert len(_get_pnl_ledger(db_path)) == 1
        assert _get_pnl_ledger(db_path)[0]["exit_reason"] == "STOP_LOSS"

    async def test_trailing_stop_triggers(self, tmp_path):
        """Price drops to trailing stop -> position closed."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Entry at 50k, trailing_high=55k, trailing_stop=50.6k (55k * 0.92)
        trailing_stop = 55_000 * (1 - TRAILING_STOP_PERCENT / 100)
        _insert_position(
            db_path, token="BTC", side="Long",
            size=1.0, entry_price=50_000.0,
            trailing_high=55_000.0,
            trailing_stop_price=trailing_stop,
            # Set stop-loss far away so it doesn't interfere
            stop_loss_price=40_000.0,
        )

        # Mark below trailing stop but above stop-loss
        client = PaperTradeClient({"BTC": trailing_stop - 100})

        summary = await _monitor_once(client, db_path)
        assert summary["trailing_stop_triggered"] == 1
        assert _get_positions(db_path) == []
        assert _get_pnl_ledger(db_path)[0]["exit_reason"] == "TRAILING_STOP"

    async def test_trailing_high_updates(self, tmp_path):
        """Price rises above trailing_high -> ratchet up."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_position(
            db_path, token="BTC", side="Long",
            size=1.0, entry_price=50_000.0,
            trailing_high=50_000.0,
            trailing_stop_price=50_000.0 * (1 - TRAILING_STOP_PERCENT / 100),
            stop_loss_price=40_000.0,
        )

        # Price rises to 60k
        client = PaperTradeClient({"BTC": 60_000.0})

        summary = await _monitor_once(client, db_path)
        assert summary["trailing_high_updated"] == 1
        assert summary["stop_loss_triggered"] == 0

        positions = _get_positions(db_path)
        assert len(positions) == 1
        assert positions[0]["trailing_high"] == 60_000.0
        expected_stop = 60_000.0 * (1 - TRAILING_STOP_PERCENT / 100)
        assert positions[0]["trailing_stop_price"] == pytest.approx(expected_stop)

    async def test_time_stop_triggers(self, tmp_path):
        """Position expired -> closed with TIME_STOP."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # max_close_at in the past
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _insert_position(
            db_path, token="BTC", side="Long",
            size=1.0, entry_price=50_000.0,
            stop_loss_price=40_000.0,  # far away
            trailing_stop_price=40_000.0,  # far away
            max_close_at=past,
        )

        client = PaperTradeClient({"BTC": 52_000.0})

        summary = await _monitor_once(client, db_path)
        assert summary["time_stop_triggered"] == 1
        assert _get_positions(db_path) == []
        assert _get_pnl_ledger(db_path)[0]["exit_reason"] == "TIME_STOP"

    async def test_no_trigger_updates_price(self, tmp_path):
        """No stop triggered -> current_price and unrealized_pnl updated."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _insert_position(
            db_path, token="BTC", side="Long",
            size=1.0, entry_price=50_000.0,
            stop_loss_price=40_000.0,
            trailing_stop_price=40_000.0,
        )

        client = PaperTradeClient({"BTC": 51_000.0})
        summary = await _monitor_once(client, db_path)

        assert summary["positions_checked"] == 1
        assert summary["stop_loss_triggered"] == 0
        assert summary["trailing_stop_triggered"] == 0
        assert summary["time_stop_triggered"] == 0

        positions = _get_positions(db_path)
        assert positions[0]["current_price"] == 51_000.0
        assert positions[0]["unrealized_pnl"] == pytest.approx(1_000.0)

    async def test_multiple_positions(self, tmp_path):
        """Multiple positions: one triggers stop-loss, others don't."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # BTC: will trigger stop-loss
        _insert_position(db_path, token="BTC", side="Long",
                         size=1.0, entry_price=50_000.0)
        # ETH: safe
        _insert_position(db_path, token="ETH", side="Long",
                         size=10.0, entry_price=3_000.0,
                         stop_loss_price=2_000.0,
                         trailing_stop_price=2_000.0)

        client = PaperTradeClient({"BTC": 46_000.0, "ETH": 3_500.0})
        summary = await _monitor_once(client, db_path)

        assert summary["positions_checked"] == 2
        assert summary["stop_loss_triggered"] == 1

        positions = _get_positions(db_path)
        assert len(positions) == 1
        assert positions[0]["token_symbol"] == "ETH"

    async def test_short_stop_loss(self, tmp_path):
        """Short position: price rises above stop-loss -> closed."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Short entry at 50k, stop-loss at 52.5k (5%)
        _insert_position(db_path, token="BTC", side="Short",
                         size=1.0, entry_price=50_000.0)

        client = PaperTradeClient({"BTC": 53_000.0})
        summary = await _monitor_once(client, db_path)

        assert summary["stop_loss_triggered"] == 1
        assert _get_positions(db_path) == []


# ===========================================================================
# 6. Monitoring Loop
# ===========================================================================


class TestMonitorPositionsLoop:
    """Tests for monitor_positions() loop."""

    async def test_max_iterations(self, tmp_path):
        """Loop respects max_iterations parameter."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        client = PaperTradeClient({})

        # Should complete without hanging
        await monitor_positions(client, db_path, interval_s=0, max_iterations=3)

    async def test_stop_event(self, tmp_path):
        """Loop exits when stop_event is set."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        client = PaperTradeClient({})
        stop_event = asyncio.Event()
        stop_event.set()  # Set immediately

        await monitor_positions(
            client, db_path, interval_s=0,
            max_iterations=None, stop_event=stop_event,
        )
        # Should exit immediately without error

    async def test_mutex_with_rebalance(self, tmp_path):
        """Monitoring pauses when rebalance_lock is held."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        client = PaperTradeClient({})

        monitor_started = asyncio.Event()
        monitor_done = asyncio.Event()

        async def run_monitor():
            monitor_started.set()
            await monitor_positions(
                client, db_path, interval_s=0, max_iterations=1,
            )
            monitor_done.set()

        # Acquire lock before starting monitor
        async with rebalance_lock:
            task = asyncio.create_task(run_monitor())
            # Give the monitor a moment to start and block on lock
            await asyncio.sleep(0.1)
            # Monitor should NOT have completed yet because lock is held
            assert not monitor_done.is_set()

        # Lock released, monitor should complete
        await asyncio.wait_for(task, timeout=5.0)
        assert monitor_done.is_set()

    async def test_stop_loss_priority_over_trailing_stop(self, tmp_path):
        """When both stop-loss and trailing stop would trigger, stop-loss wins."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Entry at 50k, stop-loss at 47.5k, trailing_stop at 48k
        # Mark at 47k -> both would trigger, but stop-loss is checked first
        _insert_position(
            db_path, token="BTC", side="Long",
            size=1.0, entry_price=50_000.0,
            stop_loss_price=47_500.0,
            trailing_stop_price=48_000.0,
            trailing_high=50_000.0,
        )

        client = PaperTradeClient({"BTC": 47_000.0})
        summary = await _monitor_once(client, db_path)

        assert summary["stop_loss_triggered"] == 1
        assert summary["trailing_stop_triggered"] == 0
        ledger = _get_pnl_ledger(db_path)
        assert ledger[0]["exit_reason"] == "STOP_LOSS"
