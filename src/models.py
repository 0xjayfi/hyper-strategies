from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Signal(BaseModel):
    id: str
    trader_address: str
    token_symbol: str
    side: str
    action: str
    value_usd: float
    position_weight: float
    timestamp: datetime
    age_seconds: float
    slippage_check: bool
    trader_score: float
    trader_roi_7d: float
    copy_size_usd: float
    leverage: float | None = None
    order_type: str
    max_slippage: float
    decision: str


class TraderRow(BaseModel):
    address: str
    label: str | None = None
    score: float = 0.0
    style: str | None = None
    tier: str | None = None
    roi_7d: float = 0.0
    roi_30d: float = 0.0
    account_value: float = 0.0
    nof_trades: int = 0
    last_scored_at: str | None = None
    blacklisted_until: str | None = None


class RawTrade(BaseModel):
    action: str
    side: str
    token_symbol: str
    value_usd: float
    price: float
    timestamp: str
    tx_hash: str
    start_position: float | None = None
    size: float | None = None


class TraderPositionSnapshot(BaseModel):
    token_symbol: str
    position_value_usd: float
    entry_price: float
    leverage: float | None = None
    leverage_type: str | None = None
    liquidation_price: float | None = None
    size: float | None = None
    account_value: float | None = None


class ExecutionResult(BaseModel):
    success: bool
    order_id: str | None = None
    fill_price: float | None = None
    fill_size: float | None = None
    error: str | None = None


class OurPosition(BaseModel):
    id: int
    token_symbol: str
    side: str
    entry_price: float
    size: float
    value_usd: float
    stop_price: float | None = None
    trailing_stop_price: float | None = None
    highest_price: float | None = None
    lowest_price: float | None = None
    opened_at: str
    source_trader: str | None = None
    source_signal_id: str | None = None
    status: str = "open"
    close_reason: str | None = None
