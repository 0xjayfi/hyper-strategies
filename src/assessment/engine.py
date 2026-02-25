"""Assessment engine — orchestrates all 10 scoring strategies."""
from __future__ import annotations

from dataclasses import asdict

from src.assessment.base import StrategyResult
from src.assessment.strategies.roi import ROIStrategy
from src.assessment.strategies.sharpe import SharpeStrategy
from src.assessment.strategies.profit_factor import ProfitFactorStrategy
from src.assessment.strategies.win_rate import WinRateStrategy
from src.assessment.strategies.anti_luck import AntiLuckStrategy
from src.assessment.strategies.consistency import ConsistencyStrategy
from src.assessment.strategies.drawdown import DrawdownStrategy
from src.assessment.strategies.leverage import LeverageStrategy
from src.assessment.strategies.position_sizing import PositionSizingStrategy
from src.assessment.strategies.trend import TrendStrategy
from src.models import TradeMetrics

ALL_STRATEGIES = [
    ROIStrategy(),
    SharpeStrategy(),
    ProfitFactorStrategy(),
    WinRateStrategy(),
    AntiLuckStrategy(),
    ConsistencyStrategy(),
    DrawdownStrategy(),
    LeverageStrategy(),
    PositionSizingStrategy(),
    TrendStrategy(),
]

TIERS = {
    (9, 10): "Elite",
    (7, 8): "Strong",
    (5, 6): "Moderate",
    (3, 4): "Weak",
    (0, 2): "Avoid",
}


def _get_tier(passed: int, total_trades: int) -> str:
    if total_trades == 0:
        return "Insufficient Data"
    for (lo, hi), tier in TIERS.items():
        if lo <= passed <= hi:
            return tier
    return "Avoid"


class AssessmentEngine:
    """Runs all assessment strategies and aggregates results."""

    def __init__(self, strategies=None):
        self.strategies = strategies or ALL_STRATEGIES

    def assess(self, metrics: TradeMetrics, positions: list) -> dict:
        results: list[StrategyResult] = []
        for strategy in self.strategies:
            result = strategy.evaluate(metrics, positions)
            results.append(result)

        passed_count = sum(1 for r in results if r.passed)
        total = len(results)
        tier = _get_tier(passed_count, metrics.total_trades)

        return {
            "strategies": [asdict(r) for r in results],
            "confidence": {
                "passed": passed_count,
                "total": total,
                "tier": tier,
            },
        }
