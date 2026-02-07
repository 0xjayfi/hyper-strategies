import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.risk.constants import REDUCE_POSITION_PCT
from src.risk.monitoring import MonitoringLoop, check_liquidation_buffer, _build_alert
from src.risk.types import (
    MonitorResult,
    OrderType,
    PositionSnapshot,
    RiskAction,
    RiskAlert,
    Side,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _long_position(mark: float, liq: float) -> PositionSnapshot:
    return PositionSnapshot(
        token="ETH", side=Side.LONG,
        mark_price=mark, liquidation_price=liq,
        position_value_usd=10_000, entry_price=95.0,
    )


def _short_position(mark: float, liq: float) -> PositionSnapshot:
    return PositionSnapshot(
        token="ETH", side=Side.SHORT,
        mark_price=mark, liquidation_price=liq,
        position_value_usd=10_000, entry_price=105.0,
    )


# ---------------------------------------------------------------------------
# 9.4 Liquidation Buffer Calculations
# ---------------------------------------------------------------------------

def test_long_buffer_healthy():
    """Long: mark=100, liq=70 -> buffer = 30%."""
    result = check_liquidation_buffer(_long_position(100, 70))
    assert result.buffer_pct == pytest.approx(30.0)
    assert result.action == RiskAction.NONE


def test_short_buffer_healthy():
    """Short: mark=100, liq=140 -> buffer = 40%."""
    result = check_liquidation_buffer(_short_position(100, 140))
    assert result.buffer_pct == pytest.approx(40.0)
    assert result.action == RiskAction.NONE


def test_long_buffer_reduce_zone():
    """Long: mark=100, liq=85 -> buffer = 15% -> REDUCE."""
    result = check_liquidation_buffer(_long_position(100, 85))
    assert result.buffer_pct == pytest.approx(15.0)
    assert result.action == RiskAction.REDUCE
    assert result.reduce_pct == 50.0
    assert result.order_type == OrderType.MARKET


def test_short_buffer_reduce_zone():
    """Short: mark=100, liq=115 -> buffer = 15% -> REDUCE."""
    result = check_liquidation_buffer(_short_position(100, 115))
    assert result.buffer_pct == pytest.approx(15.0)
    assert result.action == RiskAction.REDUCE


def test_long_buffer_emergency():
    """Long: mark=100, liq=95 -> buffer = 5% -> EMERGENCY CLOSE."""
    result = check_liquidation_buffer(_long_position(100, 95))
    assert result.buffer_pct == pytest.approx(5.0)
    assert result.action == RiskAction.EMERGENCY_CLOSE
    assert result.order_type == OrderType.MARKET


def test_short_buffer_emergency():
    """Short: mark=100, liq=105 -> buffer = 5% -> EMERGENCY CLOSE."""
    result = check_liquidation_buffer(_short_position(100, 105))
    assert result.buffer_pct == pytest.approx(5.0)
    assert result.action == RiskAction.EMERGENCY_CLOSE


def test_buffer_exactly_at_boundary_10():
    """Exactly 10% is NOT emergency (< 10 triggers)."""
    result = check_liquidation_buffer(_long_position(100, 90))
    assert result.buffer_pct == pytest.approx(10.0)
    assert result.action == RiskAction.REDUCE


def test_buffer_exactly_at_boundary_20():
    """Exactly 20% is NOT reduce (< 20 triggers)."""
    result = check_liquidation_buffer(_long_position(100, 80))
    assert result.buffer_pct == pytest.approx(20.0)
    assert result.action == RiskAction.NONE


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def test_raises_on_zero_mark_price():
    pos = _long_position(0, 70)
    with pytest.raises(ValueError, match="mark_price"):
        check_liquidation_buffer(pos)


def test_raises_on_zero_liquidation_price():
    pos = _long_position(100, 0)
    with pytest.raises(ValueError, match="liquidation_price"):
        check_liquidation_buffer(pos)


def test_raises_on_negative_mark_price():
    pos = _long_position(-10, 70)
    with pytest.raises(ValueError, match="mark_price"):
        check_liquidation_buffer(pos)


# ---------------------------------------------------------------------------
# RiskAlert Building
# ---------------------------------------------------------------------------

def test_build_alert_fields():
    pos = _long_position(100, 85)
    result = check_liquidation_buffer(pos)
    alert = _build_alert(pos, result)
    assert isinstance(alert, RiskAlert)
    assert alert.token == "ETH"
    assert alert.side == Side.LONG
    assert alert.action == RiskAction.REDUCE
    assert alert.buffer_pct == pytest.approx(15.0)
    assert alert.position_value_usd == 10_000
    assert alert.mark_price == 100
    assert alert.liquidation_price == 85
    assert alert.timestamp  # non-empty ISO string


# ---------------------------------------------------------------------------
# MonitoringLoop — Cooldown Logic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cooldown_skips_position():
    """After a reduce, the same position is skipped for cooldown_s."""
    reduce_pos = _long_position(100, 85)  # 15% -> REDUCE

    fetch = AsyncMock(return_value=[reduce_pos])
    on_alert = AsyncMock()
    on_action = AsyncMock()

    loop = MonitoringLoop(
        fetch_positions=fetch,
        on_alert=on_alert,
        on_action=on_action,
        cooldown_s=60.0,
    )

    # First poll: should trigger reduce + set cooldown
    alerts = await loop._poll_once()
    assert len(alerts) == 1
    assert alerts[0].action == RiskAction.REDUCE
    assert on_action.call_count == 1

    # Second poll: position should be on cooldown, skipped
    alerts = await loop._poll_once()
    assert len(alerts) == 0
    assert on_action.call_count == 1  # no additional call


@pytest.mark.asyncio
async def test_cooldown_expires():
    """After cooldown expires, position is checked again."""
    reduce_pos = _long_position(100, 85)

    fetch = AsyncMock(return_value=[reduce_pos])
    on_action = AsyncMock()

    loop = MonitoringLoop(
        fetch_positions=fetch,
        on_action=on_action,
        cooldown_s=0.1,  # very short for test
    )

    await loop._poll_once()
    assert on_action.call_count == 1

    # Wait for cooldown to expire
    await asyncio.sleep(0.15)

    await loop._poll_once()
    assert on_action.call_count == 2


@pytest.mark.asyncio
async def test_emergency_close_no_cooldown():
    """Emergency close does NOT set cooldown (position will be gone)."""
    emergency_pos = _long_position(100, 95)  # 5% -> EMERGENCY

    fetch = AsyncMock(return_value=[emergency_pos])
    on_action = AsyncMock()

    loop = MonitoringLoop(
        fetch_positions=fetch,
        on_action=on_action,
        cooldown_s=60.0,
    )

    await loop._poll_once()
    assert on_action.call_count == 1

    # No cooldown set — if position somehow still exists, check it again
    assert not loop._is_on_cooldown(emergency_pos)


@pytest.mark.asyncio
async def test_healthy_position_no_alert():
    """Healthy position (>= 20% buffer) produces no alerts."""
    healthy_pos = _long_position(100, 70)  # 30%

    fetch = AsyncMock(return_value=[healthy_pos])
    on_alert = AsyncMock()

    loop = MonitoringLoop(
        fetch_positions=fetch,
        on_alert=on_alert,
    )

    alerts = await loop._poll_once()
    assert len(alerts) == 0
    assert on_alert.call_count == 0


@pytest.mark.asyncio
async def test_multiple_positions_mixed():
    """Multiple positions: one healthy, one reduce, one emergency."""
    positions = [
        _long_position(100, 70),   # 30% healthy
        _long_position(100, 85),   # 15% reduce
        PositionSnapshot(
            token="BTC", side=Side.SHORT,
            mark_price=100, liquidation_price=105,
            position_value_usd=20_000, entry_price=110,
        ),  # 5% emergency
    ]

    fetch = AsyncMock(return_value=positions)
    on_alert = AsyncMock()
    on_action = AsyncMock()

    loop = MonitoringLoop(
        fetch_positions=fetch,
        on_alert=on_alert,
        on_action=on_action,
    )

    alerts = await loop._poll_once()
    assert len(alerts) == 2  # reduce + emergency
    assert on_alert.call_count == 2
    assert on_action.call_count == 2


@pytest.mark.asyncio
async def test_poll_once_returns_alerts():
    """_poll_once returns list of RiskAlert objects."""
    pos = _long_position(100, 95)  # emergency
    fetch = AsyncMock(return_value=[pos])

    loop = MonitoringLoop(fetch_positions=fetch)
    alerts = await loop._poll_once()
    assert len(alerts) == 1
    assert isinstance(alerts[0], RiskAlert)
    assert alerts[0].action == RiskAction.EMERGENCY_CLOSE
