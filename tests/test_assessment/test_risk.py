import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.drawdown import DrawdownStrategy
from src.assessment.strategies.leverage import LeverageStrategy
from src.assessment.strategies.position_sizing import PositionSizingStrategy


class TestDrawdownStrategy:
    def test_low_drawdown_passes(self):
        m = make_metrics(max_drawdown_proxy=0.10)
        r = DrawdownStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_high_drawdown_fails(self):
        m = make_metrics(max_drawdown_proxy=0.40)
        r = DrawdownStrategy().evaluate(m, [])
        assert r.passed is False

    def test_zero_drawdown_max_score(self):
        m = make_metrics(max_drawdown_proxy=0.0)
        r = DrawdownStrategy().evaluate(m, [])
        assert r.score == 100


class TestLeverageStrategy:
    def test_low_leverage_passes(self):
        m = make_metrics(max_leverage=5.0, leverage_std=1.0)
        r = LeverageStrategy().evaluate(m, [])
        assert r.passed is True

    def test_high_leverage_fails(self):
        m = make_metrics(max_leverage=60.0, leverage_std=10.0)
        r = LeverageStrategy().evaluate(m, [])
        assert r.passed is False

    def test_moderate_leverage(self):
        m = make_metrics(max_leverage=15.0, leverage_std=3.0)
        r = LeverageStrategy().evaluate(m, [])
        assert r.passed is True
        assert 30 < r.score < 80

    def test_leverage_std_affects_score(self):
        """Higher leverage_std should produce a lower score for same max_leverage."""
        m_low_std = make_metrics(max_leverage=10.0, leverage_std=1.0)
        m_high_std = make_metrics(max_leverage=10.0, leverage_std=7.0)
        r_low = LeverageStrategy().evaluate(m_low_std, [])
        r_high = LeverageStrategy().evaluate(m_high_std, [])
        assert r_low.score > r_high.score


class TestPositionSizingStrategy:
    def test_diversified_passes(self):
        m = make_metrics(largest_trade_pnl_ratio=0.15)
        r = PositionSizingStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_concentrated_fails(self):
        m = make_metrics(largest_trade_pnl_ratio=0.60)
        r = PositionSizingStrategy().evaluate(m, [])
        assert r.passed is False

    def test_at_threshold(self):
        m = make_metrics(largest_trade_pnl_ratio=0.40)
        r = PositionSizingStrategy().evaluate(m, [])
        assert r.passed is True
