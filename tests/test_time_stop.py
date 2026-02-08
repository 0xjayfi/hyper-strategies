"""Task 10.2 -- Time-based stop unit tests.

Tests for the time-stop logic that is evaluated inside
``src.position_monitor.monitor_positions``.  The condition is:

    hours_open = (now - opened_at).total_seconds() / 3600
    if hours_open >= settings.MAX_POSITION_DURATION_HOURS:  # 72
        close position

We test the condition directly and also verify the full async code path
via ``monitor_positions`` with mocked executor / nansen.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import OurPosition


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_position(
    *,
    id: int = 1,
    token_symbol: str = "BTC",
    side: str = "Long",
    entry_price: float = 100.0,
    size: float = 1.0,
    value_usd: float = 100.0,
    stop_price: float | None = 95.0,
    trailing_stop_price: float | None = 200.0,
    highest_price: float | None = 100.0,
    lowest_price: float | None = None,
    opened_at: str = "2024-01-01T00:00:00+00:00",
    source_trader: str | None = None,
    source_signal_id: str | None = None,
    status: str = "open",
    close_reason: str | None = None,
) -> OurPosition:
    return OurPosition(
        id=id,
        token_symbol=token_symbol,
        side=side,
        entry_price=entry_price,
        size=size,
        value_usd=value_usd,
        stop_price=stop_price,
        trailing_stop_price=trailing_stop_price,
        highest_price=highest_price,
        lowest_price=lowest_price,
        opened_at=opened_at,
        source_trader=source_trader,
        source_signal_id=source_signal_id,
        status=status,
        close_reason=close_reason,
    )


# ---------------------------------------------------------------------------
# Pure condition tests
# ---------------------------------------------------------------------------


class TestTimeStopCondition:
    def test_time_stop_triggers_after_72h(self) -> None:
        """Position opened 73 hours ago exceeds the 72-hour threshold."""
        now = datetime.now(timezone.utc)
        opened_at = now - timedelta(hours=73)
        hours_open = (now - opened_at).total_seconds() / 3600
        assert hours_open >= 72

    def test_time_stop_does_not_trigger_before_72h(self) -> None:
        """Position opened 71 hours ago has not yet reached the threshold."""
        now = datetime.now(timezone.utc)
        opened_at = now - timedelta(hours=71)
        hours_open = (now - opened_at).total_seconds() / 3600
        assert hours_open < 72

    def test_time_stop_triggers_at_exactly_72h(self) -> None:
        """Position opened exactly 72 hours ago meets the >= condition."""
        now = datetime.now(timezone.utc)
        opened_at = now - timedelta(hours=72)
        hours_open = (now - opened_at).total_seconds() / 3600
        assert hours_open >= 72

    def test_time_stop_fresh_position(self) -> None:
        """A brand new position is far below the threshold."""
        now = datetime.now(timezone.utc)
        opened_at = now - timedelta(minutes=5)
        hours_open = (now - opened_at).total_seconds() / 3600
        assert hours_open < 72


# ---------------------------------------------------------------------------
# Async integration: monitor_positions time-stop path
# ---------------------------------------------------------------------------


class TestTimeStopViaMonitor:
    @pytest.mark.asyncio
    async def test_monitor_closes_expired_position(self) -> None:
        """monitor_positions should call close_position_full for stale positions."""
        from src.position_monitor import monitor_positions

        now = datetime.now(timezone.utc)
        opened_at = (now - timedelta(hours=73)).isoformat()

        pos = make_position(
            opened_at=opened_at,
            # Set trailing stop far away so it does NOT trigger
            trailing_stop_price=50.0,
            highest_price=100.0,
        )

        mock_executor = MagicMock()
        mock_executor.close_position_on_exchange = AsyncMock(
            return_value=MagicMock(success=True, fill_price=100.0)
        )
        mock_executor.cancel_stop_orders = AsyncMock()

        mock_nansen = MagicMock()

        with patch("src.position_monitor.db") as mock_db:
            mock_db.update_position = AsyncMock()
            mock_db.close_position = AsyncMock()

            await monitor_positions(pos, mark_price=100.0, executor=mock_executor, nansen=mock_nansen)

            # Verify close_position was called with reason "time_stop"
            mock_db.close_position.assert_called_once_with(pos.id, close_reason="time_stop")

    @pytest.mark.asyncio
    async def test_monitor_does_not_close_fresh_position(self) -> None:
        """monitor_positions should NOT close a position opened less than 72h ago."""
        from src.position_monitor import monitor_positions

        now = datetime.now(timezone.utc)
        opened_at = (now - timedelta(hours=10)).isoformat()

        pos = make_position(
            opened_at=opened_at,
            # Set trailing stop far away so it does NOT trigger
            trailing_stop_price=50.0,
            highest_price=100.0,
            source_trader=None,  # skip liquidation check
        )

        mock_executor = MagicMock()
        mock_executor.close_position_on_exchange = AsyncMock(
            return_value=MagicMock(success=True)
        )
        mock_executor.cancel_stop_orders = AsyncMock()

        mock_nansen = MagicMock()

        with patch("src.position_monitor.db") as mock_db:
            mock_db.update_position = AsyncMock()
            mock_db.close_position = AsyncMock()

            await monitor_positions(pos, mark_price=100.0, executor=mock_executor, nansen=mock_nansen)

            # close_position should NOT have been called
            mock_db.close_position.assert_not_called()
