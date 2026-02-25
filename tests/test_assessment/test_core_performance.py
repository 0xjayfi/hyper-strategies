import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.roi import ROIStrategy
from src.assessment.strategies.sharpe import SharpeStrategy
from src.assessment.strategies.profit_factor import ProfitFactorStrategy


class TestROIStrategy:
    def test_high_roi_passes(self):
        m = make_metrics(roi_proxy=8.0)
        r = ROIStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_negative_roi_fails(self):
        m = make_metrics(roi_proxy=-5.0)
        r = ROIStrategy().evaluate(m, [])
        assert r.passed is False
        assert r.score == 0

    def test_max_score_at_10_plus(self):
        m = make_metrics(roi_proxy=15.0)
        r = ROIStrategy().evaluate(m, [])
        assert r.score == 100

    def test_name_and_category(self):
        s = ROIStrategy()
        assert s.name == "ROI Performance"
        assert s.category == "Core Performance"


class TestSharpeStrategy:
    def test_good_sharpe_passes(self):
        m = make_metrics(pseudo_sharpe=1.5)
        r = SharpeStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score == 50

    def test_low_sharpe_fails(self):
        m = make_metrics(pseudo_sharpe=0.3)
        r = SharpeStrategy().evaluate(m, [])
        assert r.passed is False

    def test_max_sharpe(self):
        m = make_metrics(pseudo_sharpe=3.5)
        r = SharpeStrategy().evaluate(m, [])
        assert r.score == 100


class TestProfitFactorStrategy:
    def test_good_pf_passes(self):
        m = make_metrics(profit_factor=2.0)
        r = ProfitFactorStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 0

    def test_low_pf_fails(self):
        m = make_metrics(profit_factor=0.8)
        r = ProfitFactorStrategy().evaluate(m, [])
        assert r.passed is False

    def test_pf_at_threshold(self):
        m = make_metrics(profit_factor=1.1)
        r = ProfitFactorStrategy().evaluate(m, [])
        assert r.passed is True
