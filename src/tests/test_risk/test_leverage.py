import pytest

from src.risk.leverage import infer_leverage
from src.risk.constants import MAX_ALLOWED_LEVERAGE


def test_infer_leverage_from_notional_margin():
    """position_value=50000, margin=10000 -> 5x."""
    lev = infer_leverage(50000.0, 10000.0)
    assert lev == pytest.approx(5.0)


def test_infer_leverage_zero_margin_fallback():
    """Zero margin -> fallback to MAX_ALLOWED_LEVERAGE."""
    lev = infer_leverage(50000.0, 0.0)
    assert lev == MAX_ALLOWED_LEVERAGE


def test_infer_leverage_missing_data():
    lev = infer_leverage(0.0, 0.0)
    assert lev == MAX_ALLOWED_LEVERAGE


def test_infer_leverage_negative_margin():
    lev = infer_leverage(50000.0, -100.0)
    assert lev == MAX_ALLOWED_LEVERAGE


def test_infer_leverage_negative_position():
    lev = infer_leverage(-1000.0, 500.0)
    assert lev == MAX_ALLOWED_LEVERAGE


def test_infer_leverage_fractional():
    """position_value=10000, margin=3000 -> ~3.3x."""
    lev = infer_leverage(10000.0, 3000.0)
    assert lev == pytest.approx(3.3)


def test_infer_leverage_1x():
    """position_value=10000, margin=10000 -> 1x."""
    lev = infer_leverage(10000.0, 10000.0)
    assert lev == pytest.approx(1.0)
