"""Base class and result dataclass for assessment strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.models import TradeMetrics


@dataclass
class StrategyResult:
    """Result from a single assessment strategy."""

    name: str
    category: str
    score: int  # 0-100
    passed: bool
    explanation: str

    def __post_init__(self):
        self.score = max(0, min(100, self.score))


class BaseStrategy(ABC):
    """Abstract base for all assessment strategies."""

    name: str = ""
    description: str = ""
    category: str = ""

    @abstractmethod
    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult:
        ...
