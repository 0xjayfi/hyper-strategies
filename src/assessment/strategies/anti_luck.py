"""Anti-Luck Filter strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class AntiLuckStrategy(BaseStrategy):
    name = "Anti-Luck Filter"
    description = "Statistical significance checks"
    category = "Behavioral Quality"

    MIN_TRADES = 10
    MIN_PNL = 500.0
    WR_LOW = 0.25
    WR_HIGH = 0.90

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        failures = []
        if metrics.total_trades < self.MIN_TRADES:
            failures.append(f"{metrics.total_trades} trades < {self.MIN_TRADES} minimum")
        if metrics.total_pnl < self.MIN_PNL:
            failures.append(f"PnL ${metrics.total_pnl:.0f} < ${self.MIN_PNL:.0f} minimum")
        if not (self.WR_LOW <= metrics.win_rate <= self.WR_HIGH):
            failures.append(f"Win rate {metrics.win_rate:.0%} outside [{self.WR_LOW:.0%}, {self.WR_HIGH:.0%}]")

        passed = len(failures) == 0
        score = max(0, 100 - len(failures) * 33)
        explanation = "All significance checks passed" if passed else "; ".join(failures)
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
