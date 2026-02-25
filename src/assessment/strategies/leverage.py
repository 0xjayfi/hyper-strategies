"""Leverage Discipline strategy."""
from src.assessment.base import BaseStrategy, StrategyResult
from src.models import TradeMetrics


class LeverageStrategy(BaseStrategy):
    name = "Leverage Discipline"
    description = "Consistency of leverage use, no extreme bets"
    category = "Risk Discipline"

    AVG_LEVERAGE_MAX = 20.0
    SINGLE_TRADE_MAX = 50.0
    HIGH_STD_THRESHOLD = 8.0

    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        max_lev = metrics.max_leverage
        lev_std = metrics.leverage_std
        failures = []
        if max_lev > self.SINGLE_TRADE_MAX:
            failures.append(f"Max leverage {max_lev:.1f}x exceeds {self.SINGLE_TRADE_MAX:.0f}x cap")
        if max_lev > self.AVG_LEVERAGE_MAX:
            failures.append(f"Max leverage {max_lev:.1f}x exceeds {self.AVG_LEVERAGE_MAX:.0f}x avg threshold")

        passed = len(failures) == 0
        if max_lev <= 0:
            score = 100
        else:
            # Base score from max leverage (0-70 range)
            lev_score = max(0, min(70, (1 - max_lev / self.SINGLE_TRADE_MAX) * 70))
            # Consistency bonus from low std dev (0-30 range)
            std_score = max(0, min(30, (1 - lev_std / self.HIGH_STD_THRESHOLD) * 30))
            score = int(lev_score + std_score)
        explanation = f"Max leverage {max_lev:.1f}x, std dev {lev_std:.1f}x — {'within safe bounds' if passed else '; '.join(failures)}"
        return StrategyResult(
            name=self.name, category=self.category,
            score=score, passed=passed, explanation=explanation,
        )
