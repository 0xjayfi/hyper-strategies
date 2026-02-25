import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.trend import TrendStrategy


class TestTrendStrategy:
    def test_positive_trend_passes(self):
        m = make_metrics(pnl_trend_slope=0.3)
        r = TrendStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_declining_trend_fails(self):
        m = make_metrics(pnl_trend_slope=-0.6)
        r = TrendStrategy().evaluate(m, [])
        assert r.passed is False

    def test_flat_trend_passes(self):
        m = make_metrics(pnl_trend_slope=0.0)
        r = TrendStrategy().evaluate(m, [])
        assert r.passed is True

    def test_name_and_category(self):
        s = TrendStrategy()
        assert s.name == "Profitability Trend"
        assert s.category == "Pattern Quality"
