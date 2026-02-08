"""Task 10.4 -- Position sizing unit tests.

Tests for ``src.sizing.compute_copy_size`` covering:
  - ROI tier multipliers (hot / lukewarm / cold)
  - Leverage penalty (table lookup + interpolation)
  - Maximum cap (min of 10 % of account, MAX_SINGLE_POSITION_USD)
  - Floor ($100 minimum)
"""

from __future__ import annotations

import pytest

from src.sizing import compute_copy_size


class TestSizingHotTrader:
    """Trader with 7d ROI > 10 % => multiplier 1.00."""

    def test_sizing_hot_trader(self) -> None:
        """Base: 100k * (100k/500k) * 0.5 * 1.00 = 10,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=None,
        )
        assert size == 10_000

    def test_sizing_hot_trader_different_allocation(self) -> None:
        """Trader puts 50 % of account in one position."""
        size = compute_copy_size(
            trader_position_value=250_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=None,
        )
        # base = 100k * 0.5 * 0.5 = 25,000
        # cap = min(100k*0.10, 50k) = 10,000
        assert size == 10_000


class TestSizingLukewarmTrader:
    """Trader with 0 <= 7d ROI <= 10 % => multiplier 0.75."""

    def test_sizing_lukewarm_trader(self) -> None:
        """Base: 100k * 0.20 * 0.5 * 0.75 = 7,500."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=5.0,
            leverage=None,
        )
        assert size == 7_500

    def test_sizing_lukewarm_at_zero_roi(self) -> None:
        """ROI exactly 0 => lukewarm tier (>= 0)."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=0.0,
            leverage=None,
        )
        assert size == 7_500

    def test_sizing_lukewarm_at_ten_roi(self) -> None:
        """ROI exactly 10 => lukewarm tier (not > 10)."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=10.0,
            leverage=None,
        )
        assert size == 7_500


class TestSizingColdTrader:
    """Trader with 7d ROI < 0 => multiplier 0.50."""

    def test_sizing_cold_trader(self) -> None:
        """Base: 100k * 0.20 * 0.5 * 0.50 = 5,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=-2.0,
            leverage=None,
        )
        assert size == 5_000


class TestSizingLeveragePenalty:
    """Leverage penalty reduces position size according to the table."""

    def test_sizing_with_leverage_20x(self) -> None:
        """20x leverage => penalty 0.20, so 10,000 * 0.20 = 2,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=20,
        )
        assert size == 2_000

    def test_sizing_with_leverage_10x(self) -> None:
        """10x leverage => penalty 0.40, so 10,000 * 0.40 = 4,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=10,
        )
        assert size == 4_000

    def test_sizing_with_leverage_5x(self) -> None:
        """5x leverage => penalty 0.60, so 10,000 * 0.60 = 6,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=5,
        )
        assert size == 6_000

    def test_sizing_with_leverage_3x(self) -> None:
        """3x leverage => penalty 0.80, so 10,000 * 0.80 = 8,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=3,
        )
        assert size == 8_000

    def test_sizing_with_leverage_2x(self) -> None:
        """2x leverage => penalty 0.90, so 10,000 * 0.90 = 9,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=2,
        )
        assert size == 9_000

    def test_sizing_with_leverage_over_20x(self) -> None:
        """Leverage > 20 => penalty 0.10, so 10,000 * 0.10 = 1,000."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=50,
        )
        assert size == 1_000

    def test_sizing_with_leverage_1x(self) -> None:
        """1x leverage with leverage not None => not > 1, no penalty applied."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=1,
        )
        # leverage=1 is not > 1, so no penalty branch entered
        assert size == 10_000


class TestSizingCaps:
    """Test maximum cap: min(our_account * 0.10, MAX_SINGLE_POSITION_USD=50k)."""

    def test_sizing_respects_max_cap(self) -> None:
        """Large position should be capped at $50,000."""
        size = compute_copy_size(
            trader_position_value=2_000_000,
            trader_account_value=4_000_000,
            our_account_value=500_000,
            trader_roi_7d=15.0,
            leverage=None,
        )
        # base = 500k * (2M/4M) * 0.5 * 1.0 = 125,000
        # cap = min(500k * 0.10, 50k) = 50,000
        assert size == 50_000

    def test_sizing_cap_uses_account_10pct_when_lower(self) -> None:
        """When 10% of account is lower than 50k, that's the effective cap."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=200_000,
            our_account_value=20_000,
            trader_roi_7d=15.0,
            leverage=None,
        )
        # base = 20k * 0.5 * 0.5 * 1.0 = 5,000
        # cap = min(20k * 0.10, 50k) = 2,000
        assert size == 2_000


class TestSizingFloor:
    """Positions below $100 are dropped to avoid dust orders."""

    def test_sizing_below_floor_returns_zero(self) -> None:
        """Computed size below $100 returns 0."""
        size = compute_copy_size(
            trader_position_value=500,
            trader_account_value=500_000,
            our_account_value=100_000,
            trader_roi_7d=-5.0,
            leverage=50,
        )
        # base = 100k * (500/500k) * 0.5 * 0.50 = 25
        # penalty = 0.10 => 2.50
        # below $100 -> 0
        assert size == 0

    def test_sizing_zero_trader_account(self) -> None:
        """Zero trader account value => fallback 5 % allocation."""
        size = compute_copy_size(
            trader_position_value=100_000,
            trader_account_value=0,
            our_account_value=100_000,
            trader_roi_7d=15.0,
            leverage=None,
        )
        # alloc = 0.05, base = 100k * 0.05 * 0.5 * 1.0 = 2,500
        assert size == 2_500
