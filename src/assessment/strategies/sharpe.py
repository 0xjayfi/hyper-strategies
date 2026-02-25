"""Risk-Adjusted Returns (Sharpe) strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class SharpeStrategy(BaseStrategy):
    name = "Risk-Adjusted Returns"
    description = "Pseudo-Sharpe ratio (return per unit volatility)"
    category = "Core Performance"

    PASS_THRESHOLD = 0.5
    MAX_SHARPE = 3.0

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        sharpe = metrics.pseudo_sharpe
        passed = sharpe >= self.PASS_THRESHOLD
        score = int(min(100, max(0, sharpe / self.MAX_SHARPE * 100)))
        explanation = f"Pseudo-Sharpe of {sharpe:.2f}, {'above' if passed else 'below'} {self.PASS_THRESHOLD} threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
