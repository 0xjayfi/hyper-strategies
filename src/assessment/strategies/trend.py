"""Profitability Trend strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class TrendStrategy(BaseStrategy):
    name = "Profitability Trend"
    description = "PnL trajectory direction"
    category = "Pattern Quality"

    MIN_SLOPE = -0.5

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        slope = metrics.pnl_trend_slope
        passed = slope >= self.MIN_SLOPE
        score = int(max(0, min(100, (slope + 1) / 2 * 100)))
        if slope > 0:
            explanation = f"PnL improving: second half outperformed first half by {slope:.0%}"
        elif slope >= self.MIN_SLOPE:
            explanation = f"PnL stable: trend slope {slope:.2f} within acceptable range"
        else:
            explanation = f"PnL declining: second half underperformed by {abs(slope):.0%}"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
