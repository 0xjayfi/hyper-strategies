"""Task 10.1 -- Stop-loss and trailing-stop unit tests.

Tests for:
  - src.executor.compute_stop_price
  - src.executor.compute_trailing_stop_initial
  - src.position_monitor.update_trailing_stop
  - src.position_monitor.trailing_stop_triggered
"""

from __future__ import annotations

import pytest

from src.executor import compute_stop_price, compute_trailing_stop_initial
from src.models import OurPosition
from src.position_monitor import trailing_stop_triggered, update_trailing_stop


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
    stop_price: float | None = None,
    trailing_stop_price: float | None = None,
    highest_price: float | None = None,
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
# compute_stop_price (hard stop)
# ---------------------------------------------------------------------------


class TestComputeStopPrice:
    def test_stop_price_long(self) -> None:
        """Long stop sits 5 % below entry."""
        stop = compute_stop_price(entry_price=100.0, side="Long")
        assert stop == 95.0  # 100 * (1 - 5/100)

    def test_stop_price_short(self) -> None:
        """Short stop sits 5 % above entry."""
        stop = compute_stop_price(entry_price=100.0, side="Short")
        assert stop == 105.0  # 100 * (1 + 5/100)

    def test_stop_price_long_high_entry(self) -> None:
        stop = compute_stop_price(entry_price=50_000.0, side="Long")
        assert stop == pytest.approx(47_500.0)

    def test_stop_price_short_high_entry(self) -> None:
        stop = compute_stop_price(entry_price=50_000.0, side="Short")
        assert stop == pytest.approx(52_500.0)


# ---------------------------------------------------------------------------
# compute_trailing_stop_initial
# ---------------------------------------------------------------------------


class TestComputeTrailingStopInitial:
    def test_trailing_stop_initial_long(self) -> None:
        """Initial trailing stop is 8 % below entry for longs."""
        trail = compute_trailing_stop_initial(entry_price=100.0, side="Long")
        assert trail == pytest.approx(92.0)  # 100 * (1 - 8/100)

    def test_trailing_stop_initial_short(self) -> None:
        """Initial trailing stop is 8 % above entry for shorts."""
        trail = compute_trailing_stop_initial(entry_price=100.0, side="Short")
        assert trail == pytest.approx(108.0)  # 100 * (1 + 8/100)


# ---------------------------------------------------------------------------
# update_trailing_stop
# ---------------------------------------------------------------------------


class TestUpdateTrailingStop:
    def test_trailing_stop_updates_on_new_high_long(self) -> None:
        """When mark price makes a new high, the trailing stop ratchets up."""
        pos = make_position(
            side="Long",
            entry_price=100.0,
            highest_price=110.0,
            trailing_stop_price=101.2,
        )
        updates = update_trailing_stop(pos, mark_price=115.0)
        assert updates is not None
        assert updates["highest_price"] == 115.0
        assert updates["trailing_stop_price"] == pytest.approx(115.0 * (1 - 8 / 100))

    def test_trailing_stop_does_not_lower_long(self) -> None:
        """When mark drops below the high-water mark, no update occurs."""
        pos = make_position(
            side="Long",
            entry_price=100.0,
            highest_price=115.0,
            trailing_stop_price=105.8,
        )
        updates = update_trailing_stop(pos, mark_price=112.0)
        assert updates is None  # price dropped, no new high

    def test_trailing_stop_uses_entry_when_no_highest(self) -> None:
        """If highest_price is None, entry_price is used as the baseline."""
        pos = make_position(
            side="Long",
            entry_price=100.0,
            highest_price=None,
            trailing_stop_price=92.0,
        )
        # Mark at 105 is above entry -> new high
        updates = update_trailing_stop(pos, mark_price=105.0)
        assert updates is not None
        assert updates["highest_price"] == 105.0
        assert updates["trailing_stop_price"] == pytest.approx(105.0 * 0.92)

    def test_trailing_stop_updates_on_new_low_short(self) -> None:
        """For shorts, a new low ratchets the trailing stop downward."""
        pos = make_position(
            side="Short",
            entry_price=100.0,
            lowest_price=90.0,
            trailing_stop_price=97.2,
        )
        updates = update_trailing_stop(pos, mark_price=85.0)
        assert updates is not None
        assert updates["lowest_price"] == 85.0
        assert updates["trailing_stop_price"] == pytest.approx(85.0 * (1 + 8 / 100))

    def test_trailing_stop_does_not_widen_short(self) -> None:
        """For shorts, mark going up does not widen the trail."""
        pos = make_position(
            side="Short",
            entry_price=100.0,
            lowest_price=85.0,
            trailing_stop_price=91.8,
        )
        updates = update_trailing_stop(pos, mark_price=90.0)
        assert updates is None

    def test_trailing_stop_only_updates_highest_if_trail_not_higher(self) -> None:
        """Edge case: new high but computed trail is not higher than existing."""
        pos = make_position(
            side="Long",
            entry_price=100.0,
            highest_price=109.0,
            trailing_stop_price=110.0,  # artificially high trail
        )
        # mark_price=110 > highest_price=109, new trail = 110*0.92 = 101.2 < 110
        updates = update_trailing_stop(pos, mark_price=110.0)
        assert updates is not None
        assert updates["highest_price"] == 110.0
        assert "trailing_stop_price" not in updates  # trail not raised


# ---------------------------------------------------------------------------
# trailing_stop_triggered
# ---------------------------------------------------------------------------


class TestTrailingStopTriggered:
    def test_triggered_long_at_stop(self) -> None:
        pos = make_position(side="Long", trailing_stop_price=95.0)
        assert trailing_stop_triggered(pos, mark_price=95.0) is True

    def test_triggered_long_below_stop(self) -> None:
        pos = make_position(side="Long", trailing_stop_price=95.0)
        assert trailing_stop_triggered(pos, mark_price=90.0) is True

    def test_not_triggered_long_above_stop(self) -> None:
        pos = make_position(side="Long", trailing_stop_price=95.0)
        assert trailing_stop_triggered(pos, mark_price=96.0) is False

    def test_triggered_short_at_stop(self) -> None:
        pos = make_position(side="Short", trailing_stop_price=105.0)
        assert trailing_stop_triggered(pos, mark_price=105.0) is True

    def test_triggered_short_above_stop(self) -> None:
        pos = make_position(side="Short", trailing_stop_price=105.0)
        assert trailing_stop_triggered(pos, mark_price=110.0) is True

    def test_not_triggered_short_below_stop(self) -> None:
        pos = make_position(side="Short", trailing_stop_price=105.0)
        assert trailing_stop_triggered(pos, mark_price=104.0) is False

    def test_not_triggered_when_no_trailing_stop(self) -> None:
        pos = make_position(trailing_stop_price=None)
        assert trailing_stop_triggered(pos, mark_price=50.0) is False
