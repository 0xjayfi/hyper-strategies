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
