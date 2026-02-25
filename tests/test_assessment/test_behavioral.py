import pytest
from tests.conftest import make_metrics
from src.assessment.strategies.win_rate import WinRateStrategy
from src.assessment.strategies.anti_luck import AntiLuckStrategy
from src.assessment.strategies.consistency import ConsistencyStrategy


class TestWinRateStrategy:
    def test_healthy_win_rate_passes(self):
        m = make_metrics(win_rate=0.55)
        r = WinRateStrategy().evaluate(m, [])
        assert r.passed is True
        assert r.score > 50

    def test_too_low_fails(self):
        m = make_metrics(win_rate=0.20)
        r = WinRateStrategy().evaluate(m, [])
        assert r.passed is False

    def test_too_high_fails(self):
        m = make_metrics(win_rate=0.90)
        r = WinRateStrategy().evaluate(m, [])
        assert r.passed is False


class TestAntiLuckStrategy:
    def test_sufficient_trades_passes(self):
        m = make_metrics(total_trades=50, total_pnl=1000, win_rate=0.55)
        r = AntiLuckStrategy().evaluate(m, [])
        assert r.passed is True

    def test_insufficient_trades_fails(self):
        m = make_metrics(total_trades=5, total_pnl=1000)
        r = AntiLuckStrategy().evaluate(m, [])
        assert r.passed is False

    def test_low_pnl_fails(self):
        m = make_metrics(total_trades=50, total_pnl=100)
        r = AntiLuckStrategy().evaluate(m, [])
        assert r.passed is False


class TestConsistencyStrategy:
    def test_multi_window_positive_passes(self):
        m = make_metrics(roi_proxy=10.0, total_pnl=5000)
        r = ConsistencyStrategy().evaluate(m, [])
        assert r.passed is True

    def test_negative_pnl_fails(self):
        m = make_metrics(roi_proxy=-5.0, total_pnl=-500)
        r = ConsistencyStrategy().evaluate(m, [])
        assert r.passed is False
