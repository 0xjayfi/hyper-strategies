"""Leverage Discipline strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class LeverageStrategy(BaseStrategy):
    name = "Leverage Discipline"
    description = "Consistency of leverage use, no extreme bets"
    category = "Risk Discipline"

    AVG_LEVERAGE_MAX = 20.0
    SINGLE_TRADE_MAX = 50.0

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        max_lev = metrics.max_leverage
        lev_std = metrics.leverage_std
        failures = []
        if max_lev > self.SINGLE_TRADE_MAX:
            failures.append(f"Max leverage {max_lev:.1f}x exceeds {self.SINGLE_TRADE_MAX:.0f}x cap")
        if max_lev > self.AVG_LEVERAGE_MAX:
            failures.append(f"Leverage {max_lev:.1f}x exceeds {self.AVG_LEVERAGE_MAX:.0f}x threshold")

        passed = len(failures) == 0
        if max_lev <= 0:
            score = 100
        else:
            score = int(max(0, min(100, (1 - max_lev / self.SINGLE_TRADE_MAX) * 100)))
        explanation = "Leverage within safe bounds" if passed else "; ".join(failures)
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
