"""Position Sizing strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class PositionSizingStrategy(BaseStrategy):
    name = "Position Sizing"
    description = "No single trade dominates total PnL"
    category = "Risk Discipline"

    MAX_RATIO = 0.40

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        ratio = metrics.largest_trade_pnl_ratio
        passed = ratio <= self.MAX_RATIO
        score = int(max(0, min(100, (1 - ratio) * 100)))
        explanation = f"Largest trade is {ratio:.0%} of total PnL, {'within' if passed else 'exceeds'} {self.MAX_RATIO:.0%} limit"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
