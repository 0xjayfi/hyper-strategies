"""Pydantic v2 response models for the Hyper-Signals API."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TokenEnum(str, Enum):
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    HYPE = "HYPE"


class SideEnum(str, Enum):
    Long = "Long"
    Short = "Short"


class LabelTypeEnum(str, Enum):
    smart_money = "smart_money"
    whale = "whale"
    public_figure = "public_figure"
    all_traders = "all_traders"


class TimeframeEnum(str, Enum):
    d7 = "7d"
    d30 = "30d"
    d90 = "90d"


# ---------------------------------------------------------------------------
# Position models
# ---------------------------------------------------------------------------

class TokenPerpPosition(BaseModel):
    """A single token perpetual position from the TGM endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    address_label: str | None = None
    side: str
    position_value_usd: float
    position_size: float
    leverage: float
    leverage_type: str | None = None
    entry_price: float
    mark_price: float
    liquidation_price: float | None = None
    funding_usd: float | None = None
    upnl_usd: float | None = None
    rank: int = 0
    is_smart_money: bool = False
    smart_money_labels: list[str] = []


class PositionMeta(BaseModel):
    """Aggregate metadata for a set of positions."""

    model_config = ConfigDict(populate_by_name=True)

    total_long_value: float
    total_short_value: float
    long_short_ratio: float
    smart_money_count: int
    fetched_at: datetime


class PositionResponse(BaseModel):
    """Response envelope for the positions endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    token: str
    positions: list[TokenPerpPosition]
    meta: PositionMeta


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Market overview models
# ---------------------------------------------------------------------------

class TokenOverview(BaseModel):
    """Per-token summary for the market overview."""

    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    long_short_ratio: float
    total_position_value: float
    top_trader_label: str | None
    top_trader_side: str
    top_trader_size_usd: float
    funding_rate: float
    smart_money_net_direction: str
    smart_money_confidence_pct: float
    open_interest_usd: float | None = None
    volume_24h_usd: float | None = None


class ConsensusEntry(BaseModel):
    """Smart-money directional consensus for a single token."""

    model_config = ConfigDict(populate_by_name=True)

    direction: str  # "Bullish", "Bearish", "Neutral"
    confidence: float


class SmartMoneyFlow(BaseModel):
    """Aggregate smart-money flow across all tokens."""

    model_config = ConfigDict(populate_by_name=True)

    net_long_usd: float
    net_short_usd: float
    direction: str  # "Net Long", "Net Short", "Neutral"


class MarketOverviewResponse(BaseModel):
    """Response envelope for the market overview endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    tokens: list[TokenOverview]
    consensus: dict[str, ConsensusEntry]
    smart_money_flow: SmartMoneyFlow
    fetched_at: str


# ---------------------------------------------------------------------------
# Leaderboard models
# ---------------------------------------------------------------------------

class AntiLuckStatus(BaseModel):
    """Anti-luck filter status for a trader."""

    model_config = ConfigDict(populate_by_name=True)

    passed: bool
    failures: list[str]


class LeaderboardTrader(BaseModel):
    """A single trader entry in the leaderboard response."""

    model_config = ConfigDict(populate_by_name=True)

    rank: int
    address: str
    label: str | None = None
    pnl_usd: float
    roi_pct: float
    win_rate: float | None = None
    profit_factor: float | None = None
    num_trades: int
    score: float | None = None
    allocation_weight: float | None = None
    anti_luck_status: AntiLuckStatus | None = None
    is_blacklisted: bool = False
    is_smart_money: bool = False

    # Score breakdown (available when from DataStore)
    score_roi: float | None = None
    score_sharpe: float | None = None
    score_win_rate: float | None = None
    score_consistency: float | None = None
    score_smart_money: float | None = None
    score_risk_mgmt: float | None = None


class LeaderboardResponse(BaseModel):
    """Response envelope for the leaderboard endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    timeframe: str
    traders: list[LeaderboardTrader]
    source: str  # "datastore" or "nansen_api"


# ---------------------------------------------------------------------------
# Screener models
# ---------------------------------------------------------------------------

class ScreenerEntry(BaseModel):
    """A single token entry from the perp screener."""

    model_config = ConfigDict(populate_by_name=True)

    token_symbol: str
    buy_sell_pressure: float | None = None
    buy_volume: float | None = None
    sell_volume: float | None = None
    volume: float | None = None
    funding: float | None = None
    mark_price: float | None = None
    open_interest: float | None = None
    previous_price_usd: float | None = None
    trader_count: int | None = None
    smart_money_volume: float | None = None
    smart_money_buy_volume: float | None = None
    smart_money_sell_volume: float | None = None
    smart_money_longs_count: int | None = None
    smart_money_shorts_count: int | None = None
    current_smart_money_position_longs_usd: float | None = None
    current_smart_money_position_shorts_usd: float | None = None
    net_position_change: float | None = None


class ScreenerResponse(BaseModel):
    """Response envelope for the screener endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    entries: list[ScreenerEntry]
    fetched_at: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Response model for the health check endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    status: str
    db_connected: bool
    nansen_key_set: bool


# ---------------------------------------------------------------------------
# Trader detail models
# ---------------------------------------------------------------------------

class TraderPosition(BaseModel):
    """A single position in the trader detail response."""

    model_config = ConfigDict(populate_by_name=True)

    token_symbol: str
    side: str
    position_value_usd: float
    entry_price: float
    leverage_value: float
    liquidation_price: float | None = None
    unrealized_pnl_usd: float | None = None


class TimeframeMetrics(BaseModel):
    """Metrics for a specific timeframe window."""

    model_config = ConfigDict(populate_by_name=True)

    pnl: float
    roi: float
    win_rate: float | None = None
    trades: int


class ScoreBreakdown(BaseModel):
    """Breakdown of a trader's composite score components."""

    model_config = ConfigDict(populate_by_name=True)

    roi: float
    sharpe: float
    win_rate: float
    consistency: float
    smart_money: float
    risk_mgmt: float
    style_multiplier: float
    recency_decay: float
    final_score: float


class TraderDetailResponse(BaseModel):
    """Full detail response for a single trader."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    label: str | None = None
    is_smart_money: bool = False
    trading_style: str | None = None
    last_active: str | None = None
    positions: list[TraderPosition]
    account_value_usd: float | None = None
    metrics: dict[str, TimeframeMetrics] | None = None
    score_breakdown: ScoreBreakdown | None = None
    allocation_weight: float | None = None
    anti_luck_status: AntiLuckStatus | None = None
    is_blacklisted: bool = False


class TradeItem(BaseModel):
    """A single trade entry for the trades endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: str
    token_symbol: str
    action: str
    side: str | None = None
    size: float
    value_usd: float
    price: float
    closed_pnl: float
    fee_usd: float


class TradesResponse(BaseModel):
    """Response envelope for the trades endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    trades: list[TradeItem]
    total: int


class PnlPoint(BaseModel):
    """A single point on the cumulative PnL curve."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: str
    cumulative_pnl: float


class PnlCurveResponse(BaseModel):
    """Response envelope for the PnL curve endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    points: list[PnlPoint]


# ---------------------------------------------------------------------------
# Allocation & strategy models
# ---------------------------------------------------------------------------


class AllocationEntry(BaseModel):
    """A single trader's allocation weight."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    label: str | None = None
    weight: float
    roi_tier: float = 1.0


class RiskCapStatus(BaseModel):
    """Current vs. maximum for a single risk cap dimension."""

    model_config = ConfigDict(populate_by_name=True)

    current: float
    max: float


class RiskCaps(BaseModel):
    """Aggregate risk cap utilisation."""

    model_config = ConfigDict(populate_by_name=True)

    position_count: RiskCapStatus
    max_token_exposure: RiskCapStatus
    directional_long: RiskCapStatus
    directional_short: RiskCapStatus


class CapViolation(BaseModel):
    """A single risk cap violation flagged for advisory purposes."""

    model_config = ConfigDict(populate_by_name=True)

    cap: str  # e.g. "directional_short", "max_token_exposure"
    current: float
    limit: float
    severity: str  # "warning" or "critical"
    message: str


class AllocationsResponse(BaseModel):
    """Response envelope for the allocations endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    allocations: list[AllocationEntry]
    softmax_temperature: float
    total_allocated_traders: int
    risk_caps: RiskCaps
    computed_at: str | None = None
    cap_violations: list[CapViolation] = []


class AllocationHistoryEntry(BaseModel):
    """A single trader's weight at a point in time."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    final_weight: float
    label: str | None = None


class AllocationSnapshot(BaseModel):
    """All allocations computed at a single timestamp."""

    model_config = ConfigDict(populate_by_name=True)

    computed_at: str
    allocations: list[AllocationHistoryEntry]


class AllocationHistoryResponse(BaseModel):
    """Response envelope for the allocation history endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    snapshots: list[AllocationSnapshot]
    days: int


class IndexPortfolioEntry(BaseModel):
    """A single token target in the index portfolio strategy."""

    model_config = ConfigDict(populate_by_name=True)

    token: str
    side: str
    target_weight: float
    target_usd: float


class ConsensusToken(BaseModel):
    """Consensus signal for a single token."""

    model_config = ConfigDict(populate_by_name=True)

    direction: str
    confidence: float
    voter_count: int


class SizingEntry(BaseModel):
    """Per-trader sizing parameters."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    weight: float
    roi_tier: float
    max_size_usd: float


class StrategiesResponse(BaseModel):
    """Response envelope for the strategies endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    index_portfolio: list[IndexPortfolioEntry]
    consensus: dict[str, ConsensusToken]
    sizing_params: list[SizingEntry]


# ---------------------------------------------------------------------------
# Assessment models
# ---------------------------------------------------------------------------


class AssessmentStrategyResult(BaseModel):
    """Result from a single assessment strategy."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    category: str
    score: int
    passed: bool
    explanation: str


class AssessmentConfidence(BaseModel):
    """Overall confidence from the assessment."""

    model_config = ConfigDict(populate_by_name=True)

    passed: int
    total: int
    tier: str


class AssessmentResponse(BaseModel):
    """Response envelope for the trader assessment endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    address: str
    is_cached: bool
    window_days: int
    trade_count: int
    confidence: AssessmentConfidence
    strategies: list[AssessmentStrategyResult]
    computed_at: str
