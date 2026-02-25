"""Drawdown Resilience strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class DrawdownStrategy(BaseStrategy):
    name = "Drawdown Resilience"
    description = "Worst peak-to-trough decline"
    category = "Risk Discipline"

    MAX_DD_THRESHOLD = 0.30  # 30% of peak

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        dd = metrics.max_drawdown_proxy
        passed = dd < self.MAX_DD_THRESHOLD
        score = int(max(0, (1 - dd / self.MAX_DD_THRESHOLD) * 100)) if dd < self.MAX_DD_THRESHOLD else 0
        explanation = f"Max drawdown {dd:.0%}, {'below' if passed else 'exceeds'} {self.MAX_DD_THRESHOLD:.0%} threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
