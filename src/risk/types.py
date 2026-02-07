from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "Long"
    SHORT = "Short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class MarginType(str, Enum):
    ISOLATED = "isolated"
    CROSS = "cross"


class RiskAction(str, Enum):
    NONE = "none"
    REDUCE = "reduce"
    EMERGENCY_CLOSE = "emergency_close"


@dataclass
class SizingRequest:
    """Input from upstream strategy."""
    base_position_usd: float
    token: str
    side: Side
    trader_leverage: Optional[float] = None
    trader_position_value_usd: Optional[float] = None
    trader_margin_used_usd: Optional[float] = None


@dataclass
class AccountState:
    """Current account snapshot."""
    account_value_usd: float
    total_open_positions_usd: float = 0.0
    total_long_exposure_usd: float = 0.0
    total_short_exposure_usd: float = 0.0
    token_exposure_usd: dict[str, float] = field(default_factory=dict)


@dataclass
class SizingResult:
    """Output to execution layer."""
    final_position_usd: float
    effective_leverage: float
    margin_type: MarginType
    order_type: OrderType
    max_slippage_pct: float
    rejected: bool = False
    rejection_reason: Optional[str] = None
    sizing_breakdown: dict = field(default_factory=dict)


@dataclass
class PositionSnapshot:
    """For liquidation monitoring."""
    token: str
    side: Side
    mark_price: float
    liquidation_price: float
    position_value_usd: float
    entry_price: float


@dataclass
class MonitorResult:
    """Output from liquidation buffer check."""
    action: RiskAction
    buffer_pct: float
    reduce_pct: Optional[float]
    order_type: OrderType


@dataclass
class RiskAlert:
    """Structured alert event for notification layer."""
    timestamp: str
    token: str
    side: Side
    action: RiskAction
    buffer_pct: float
    position_value_usd: float
    mark_price: float
    liquidation_price: float
