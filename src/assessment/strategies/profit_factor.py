"""Profit Factor strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class ProfitFactorStrategy(BaseStrategy):
    name = "Profit Factor"
    description = "Gross profit / gross loss ratio"
    category = "Core Performance"

    PASS_THRESHOLD = 1.1
    MIN_PF = 1.0
    MAX_PF = 3.0

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        pf = metrics.profit_factor
        passed = pf >= self.PASS_THRESHOLD
        if pf == float("inf"):
            score = 100
            pf_display = ">3.0 (no losses)"
        else:
            score = int(min(100, max(0, (pf - self.MIN_PF) / (self.MAX_PF - self.MIN_PF) * 100)))
            pf_display = f"{pf:.2f}"
        explanation = f"Profit factor of {pf_display}, {'above' if passed else 'below'} {self.PASS_THRESHOLD} threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
