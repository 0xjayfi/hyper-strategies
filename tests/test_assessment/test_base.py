import pytest
from src.assessment.base import BaseStrategy, StrategyResult


def test_strategy_result_creation():
    r = StrategyResult(name="Test", category="Core", score=75, passed=True, explanation="Good")
    assert r.score == 75


def test_strategy_result_score_bounds():
    r = StrategyResult(name="T", category="C", score=150, passed=True, explanation="")
    assert r.score == 100
    r2 = StrategyResult(name="T", category="C", score=-10, passed=False, explanation="")
    assert r2.score == 0


def test_base_strategy_cannot_instantiate():
    with pytest.raises(TypeError):
        BaseStrategy()
