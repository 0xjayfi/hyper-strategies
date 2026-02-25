"""Consistency strategy -- multi-timeframe profitability."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class ConsistencyStrategy(BaseStrategy):
    name = "Consistency"
    description = "Profitability across multiple time windows"
    category = "Behavioral Quality"

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        checks_passed = 0
        total_checks = 2

        if metrics.roi_proxy > 0:
            checks_passed += 1
        if metrics.total_pnl > 0:
            checks_passed += 1

        passed = checks_passed >= 2
        score = int(checks_passed / total_checks * 100)
        explanation = f"{checks_passed}/{total_checks} profitability checks passed (ROI {'>' if metrics.roi_proxy > 0 else '<='} 0%, PnL {'>' if metrics.total_pnl > 0 else '<='} $0)"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
