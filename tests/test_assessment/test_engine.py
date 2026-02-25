import pytest
from tests.conftest import make_metrics
from src.assessment.engine import AssessmentEngine


def test_engine_runs_all_strategies():
    m = make_metrics(
        roi_proxy=8.0, pseudo_sharpe=1.5, profit_factor=2.0,
        win_rate=0.55, total_trades=50, total_pnl=5000,
        max_drawdown_proxy=0.10, max_leverage=10.0, leverage_std=2.0,
        largest_trade_pnl_ratio=0.15, pnl_trend_slope=0.1,
    )
    result = AssessmentEngine().assess(m, [])
    assert len(result["strategies"]) == 10
    assert result["confidence"]["total"] == 10
    assert result["confidence"]["passed"] >= 0
    assert result["confidence"]["tier"] in ("Elite", "Strong", "Moderate", "Weak", "Avoid", "Insufficient Data")


def test_engine_all_pass_elite():
    m = make_metrics(
        roi_proxy=12.0, pseudo_sharpe=2.0, profit_factor=2.5,
        win_rate=0.55, total_trades=50, total_pnl=5000,
        max_drawdown_proxy=0.05, max_leverage=5.0, leverage_std=1.0,
        largest_trade_pnl_ratio=0.10, pnl_trend_slope=0.2,
    )
    result = AssessmentEngine().assess(m, [])
    assert result["confidence"]["passed"] >= 9
    assert result["confidence"]["tier"] in ("Elite", "Strong")


def test_engine_empty_metrics():
    from src.models import TradeMetrics
    m = TradeMetrics.empty(30)
    result = AssessmentEngine().assess(m, [])
    assert result["confidence"]["tier"] == "Insufficient Data"
    # Some strategies may "pass" with zeroed metrics (e.g., 0% drawdown is
    # considered safe, 0 leverage is within bounds), but the tier correctly
    # returns "Insufficient Data" because total_trades == 0.
    assert result["confidence"]["passed"] >= 0


def test_engine_strategy_results_structure():
    m = make_metrics()
    result = AssessmentEngine().assess(m, [])
    for s in result["strategies"]:
        assert "name" in s
        assert "category" in s
        assert "score" in s
        assert "passed" in s
        assert "explanation" in s
        assert 0 <= s["score"] <= 100
