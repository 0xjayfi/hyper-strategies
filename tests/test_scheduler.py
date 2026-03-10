"""Tests for scheduler task lifecycle management."""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch
from backend.main import lifespan, app


@pytest.mark.asyncio
async def test_scheduler_task_restarts_on_crash():
    """If run_scheduler raises, the done-callback should log and restart."""
    call_count = 0
    original_error = RuntimeError("simulated crash")

    async def fake_scheduler(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise original_error
        # Second call: just return (simulates successful restart)
        await asyncio.sleep(0.1)

    # Override TESTING=0 so the scheduler branch runs (test_routers.py sets TESTING=1)
    with patch.dict(os.environ, {"TESTING": "0"}):
        with patch("backend.main.SCHEDULER_RESTART_DELAY_S", 0.0):
            with patch("backend.main.run_scheduler", side_effect=fake_scheduler):
                with patch("backend.main.NansenClient") as mock_nc:
                    mock_nc.return_value = AsyncMock()
                    mock_nc.return_value.close = AsyncMock()
                    async with lifespan(app) as _:
                        # Give the restart callback time to fire (no delay needed with 0s)
                        await asyncio.sleep(0.3)

    assert call_count >= 2, "Scheduler should have been restarted after crash"


@pytest.mark.asyncio
async def test_scheduler_task_logs_exception_on_crash():
    """The done-callback should log the exception from the crashed task."""
    async def crashing_scheduler(*args, **kwargs):
        raise ValueError("test error")

    # Override TESTING=0 so the scheduler branch runs (test_routers.py sets TESTING=1)
    with patch.dict(os.environ, {"TESTING": "0"}):
        with patch("backend.main.SCHEDULER_RESTART_DELAY_S", 0.0):
            with patch("backend.main.run_scheduler", side_effect=crashing_scheduler):
                with patch("backend.main.NansenClient") as mock_nc:
                    mock_nc.return_value = AsyncMock()
                    mock_nc.return_value.close = AsyncMock()
                    with patch("backend.main.logger") as mock_logger:
                        async with lifespan(app) as _:
                            await asyncio.sleep(0.3)

                        # Verify that logger.error was called with the crash message
                        calls = [str(c) for c in mock_logger.error.call_args_list]
                        matched = any("Scheduler task died unexpectedly" in c for c in calls)
                        assert matched, (
                            f"Expected logger.error to be called with 'Scheduler task died unexpectedly', "
                            f"but got calls: {calls}"
                        )


@pytest.mark.asyncio
async def test_scoring_cycle_continues_after_single_trader_error():
    """If one trader's scoring fails, other traders should still be scored."""
    from src.scheduler import position_scoring_cycle
    from src.allocation import RiskConfig
    from src.datastore import DataStore
    from datetime import datetime, timedelta, timezone

    ds = DataStore(":memory:")
    risk_config = RiskConfig(max_total_open_usd=50_000.0)

    # Set up two traders
    addr_good = "0x" + "a" * 40
    addr_bad = "0x" + "b" * 40
    ds.upsert_trader(addr_good, label=None)
    ds.upsert_trader(addr_bad, label=None)

    # Insert enough position data for both traders (need ≥2 account series points)
    base_time = datetime.now(timezone.utc) - timedelta(hours=10)
    for i in range(10):
        positions = [{
            "token_symbol": "BTC", "side": "Long",
            "position_value_usd": 50000, "entry_price": 50000,
            "leverage_value": 3.0, "leverage_type": "cross",
            "liquidation_price": 35000, "unrealized_pnl": i * 100,
            "account_value": 100000 + i * 500,
        }]
        ds.insert_position_snapshot(addr_good, positions)
        ds.insert_position_snapshot(addr_bad, positions)

    # Make compute_position_metrics raise for the first call only
    original_compute = __import__("src.position_metrics", fromlist=["compute_position_metrics"]).compute_position_metrics

    def patched_compute(account_series, position_snapshots, *, _addr=[None]):
        if _addr[0] is None:
            _addr[0] = "first"
            raise ValueError("simulated metric computation failure")
        return original_compute(account_series, position_snapshots)

    nansen_client = AsyncMock()

    with patch("src.scheduler.compute_position_metrics", side_effect=patched_compute):
        result = await position_scoring_cycle(nansen_client, ds, risk_config)

    # At least one trader should have been scored despite the other failing
    scores = ds.get_latest_scores()
    assert len(scores) >= 1, "At least one trader should have been scored"
