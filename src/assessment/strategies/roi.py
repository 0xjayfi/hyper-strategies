"""ROI Performance strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class ROIStrategy(BaseStrategy):
    name = "ROI Performance"
    description = "Raw returns relative to capital"
    category = "Core Performance"

    PASS_THRESHOLD = 0.0  # ROI >= 0%
    MAX_ROI = 10.0        # 10%+ maps to score 100

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        roi = metrics.roi_proxy
        passed = roi >= self.PASS_THRESHOLD
        score = int(min(100, max(0, roi / self.MAX_ROI * 100))) if roi > 0 else 0
        explanation = f"30d ROI of {roi:.1f}%, {'above' if passed else 'below'} {self.PASS_THRESHOLD}% threshold"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
