"""Win Rate Quality strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class WinRateStrategy(BaseStrategy):
    name = "Win Rate Quality"
    description = "Trade success rate within healthy bounds"
    category = "Behavioral Quality"

    LOW_BOUND = 0.30
    HIGH_BOUND = 0.85
    OPTIMAL = 0.55

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        wr = metrics.win_rate
        passed = self.LOW_BOUND <= wr <= self.HIGH_BOUND
        if not passed:
            score = 0
            explanation = f"Win rate {wr:.0%} outside healthy range [{self.LOW_BOUND:.0%}, {self.HIGH_BOUND:.0%}]"
        else:
            distance = abs(wr - self.OPTIMAL)
            max_distance = max(self.OPTIMAL - self.LOW_BOUND, self.HIGH_BOUND - self.OPTIMAL)
            score = int(max(0, (1 - distance / max_distance) * 100))
            explanation = f"Win rate {wr:.0%} within healthy range, {abs(wr - self.OPTIMAL):.0%} from optimal {self.OPTIMAL:.0%}"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
