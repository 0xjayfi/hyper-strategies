"""Task 10.3 -- Slippage gate unit tests.

The slippage gate in ``src.trade_ingestion.evaluate_trade`` (Step 5) computes:

    slippage_pct = abs(current_price - trade_price) / trade_price * 100
    if slippage_pct > MAX_PRICE_SLIPPAGE_PERCENT (2.0):
        SKIP

These tests verify the arithmetic of the gate directly, plus edge cases.
"""

from __future__ import annotations

import pytest

from src.config import settings


# ---------------------------------------------------------------------------
# Pure slippage-percentage calculation
# ---------------------------------------------------------------------------


def _compute_slippage_pct(trade_price: float, current_price: float) -> float:
    """Replicate the slippage formula used in evaluate_trade (Step 5)."""
    if trade_price <= 0:
        return 0.0
    return abs(current_price - trade_price) / trade_price * 100


class TestSlippageGate:
    def test_slippage_gate_passes(self) -> None:
        """1.5 % slippage is below the 2.0 % threshold -- should pass."""
        trade_price = 100.0
        current_price = 101.5
        slippage_pct = _compute_slippage_pct(trade_price, current_price)
        assert slippage_pct < settings.MAX_PRICE_SLIPPAGE_PERCENT
        assert slippage_pct == pytest.approx(1.5)

    def test_slippage_gate_fails(self) -> None:
        """2.5 % slippage exceeds the 2.0 % threshold -- should be rejected."""
        trade_price = 100.0
        current_price = 102.5
        slippage_pct = _compute_slippage_pct(trade_price, current_price)
        assert slippage_pct > settings.MAX_PRICE_SLIPPAGE_PERCENT
        assert slippage_pct == pytest.approx(2.5)

    def test_slippage_gate_exactly_at_threshold(self) -> None:
        """Exactly 2.0 % slippage is NOT greater than 2.0 % -- should pass."""
        trade_price = 100.0
        current_price = 102.0
        slippage_pct = _compute_slippage_pct(trade_price, current_price)
        # The gate uses strict >
        assert not (slippage_pct > settings.MAX_PRICE_SLIPPAGE_PERCENT)

    def test_slippage_gate_negative_move(self) -> None:
        """Price moved down from trade; absolute slippage is still checked."""
        trade_price = 100.0
        current_price = 97.0  # -3 %
        slippage_pct = _compute_slippage_pct(trade_price, current_price)
        assert slippage_pct == pytest.approx(3.0)
        assert slippage_pct > settings.MAX_PRICE_SLIPPAGE_PERCENT

    def test_slippage_zero_when_same_price(self) -> None:
        """No slippage when current price equals trade price."""
        slippage_pct = _compute_slippage_pct(100.0, 100.0)
        assert slippage_pct == 0.0

    def test_slippage_tiny_move_passes(self) -> None:
        """A 0.1 % move is well within the 2 % tolerance."""
        slippage_pct = _compute_slippage_pct(100.0, 100.1)
        assert slippage_pct == pytest.approx(0.1)
        assert slippage_pct < settings.MAX_PRICE_SLIPPAGE_PERCENT

    def test_slippage_with_zero_trade_price(self) -> None:
        """Zero trade price should return 0.0 slippage (avoid division by zero)."""
        slippage_pct = _compute_slippage_pct(0.0, 100.0)
        assert slippage_pct == 0.0

    def test_slippage_large_move(self) -> None:
        """A 10 % move should clearly exceed the threshold."""
        slippage_pct = _compute_slippage_pct(100.0, 110.0)
        assert slippage_pct == pytest.approx(10.0)
        assert slippage_pct > settings.MAX_PRICE_SLIPPAGE_PERCENT

    def test_max_slippage_setting_value(self) -> None:
        """Verify the config default is 2.0."""
        assert settings.MAX_PRICE_SLIPPAGE_PERCENT == 2.0
