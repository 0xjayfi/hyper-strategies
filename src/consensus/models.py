"""Core data structures for the consensus trading strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TraderStyle(Enum):
    HFT = "HFT"
    SWING = "SWING"
    POSITION = "POSITION"


class ConsensusSide(Enum):
    STRONG_LONG = "STRONG_LONG"
    STRONG_SHORT = "STRONG_SHORT"
    MIXED = "MIXED"


class SignalStrength(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class TrackedTrader:
    address: str
    label: str
    score: float
    style: TraderStyle
    cluster_id: int
    account_value_usd: float
    roi_7d: float
    roi_30d: float
    roi_90d: float
    trade_count: int
    last_scored_at: datetime
    is_active: bool = True
    blacklisted_until: datetime | None = None


@dataclass
class TradeRecord:
    """Ingested from Address Perp Trades endpoint."""

    trader_address: str
    token_symbol: str
    side: str  # "Long" or "Short"
    action: str  # "Open", "Add", "Close", "Reduce"
    size: float
    price_usd: float
    value_usd: float
    timestamp: datetime
    fee_usd: float
    closed_pnl: float
    transaction_hash: str


@dataclass
class InferredPosition:
    """Reconstructed from trade stream or from Address Perp Positions."""

    trader_address: str
    token_symbol: str
    side: str  # "Long" or "Short"
    entry_price_usd: float
    current_value_usd: float
    size: float
    leverage_value: int
    leverage_type: str
    liquidation_price_usd: float | None
    unrealized_pnl_usd: float
    position_weight: float
    signal_strength: SignalStrength
    first_open_at: datetime
    last_action_at: datetime
    freshness_weight: float


@dataclass
class TokenConsensus:
    """Per-token consensus snapshot."""

    token_symbol: str
    timestamp: datetime
    long_traders: set[str] = field(default_factory=set)
    short_traders: set[str] = field(default_factory=set)
    long_volume_usd: float = 0.0
    short_volume_usd: float = 0.0
    weighted_long_volume: float = 0.0
    weighted_short_volume: float = 0.0
    consensus: ConsensusSide = ConsensusSide.MIXED
    long_cluster_count: int = 0
    short_cluster_count: int = 0


@dataclass
class OurPosition:
    """Position we hold."""

    token_symbol: str
    side: str
    entry_price_usd: float
    current_price_usd: float
    size_usd: float
    leverage: int
    margin_type: str
    stop_loss_price: float
    trailing_stop_price: float | None
    highest_price_since_entry: float
    opened_at: datetime
    consensus_side_at_entry: ConsensusSide
    order_id: str | None = None


@dataclass
class PendingSignal:
    """Signal waiting in confirmation window."""

    token_symbol: str
    consensus: ConsensusSide
    detected_at: datetime
    avg_entry_price_at_detection: float
    confirmed: bool = False


@dataclass
class ExitSignal:
    """Signal to exit or reduce a position."""

    token_symbol: str
    reason: str  # "stop_loss", "trailing_stop", "time_stop", "consensus_break", "emergency_close", "reduce_50"
    priority: int  # Lower = higher priority
    reduce_fraction: float = 1.0  # 1.0 = full close, 0.5 = reduce half
