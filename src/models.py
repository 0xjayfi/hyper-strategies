"""Pydantic models for Nansen API responses and internal data structures.

All models use Pydantic v2 conventions with snake_case field names matching
the Nansen API response format. Models marked with ConfigDict(populate_by_name=True)
support instantiation via both field name and alias where applicable.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Leaderboard — POST /api/v1/perp-leaderboard
# ---------------------------------------------------------------------------

class LeaderboardEntry(BaseModel):
    """A single row from the perpetual trading leaderboard.

    Returned inside the ``data`` array of the leaderboard response.
    """

    model_config = ConfigDict(populate_by_name=True)

    trader_address: str
    trader_address_label: str | None = None
    total_pnl: float
    roi: float
    account_value: float


# ---------------------------------------------------------------------------
# Address Perp Trades — POST /api/v1/profiler/perp-trades
# ---------------------------------------------------------------------------

class Trade(BaseModel):
    """A single perpetual trade for an address.

    ``action`` is one of Open / Close / Add / Reduce.
    ``side`` is Long or Short.
    ``closed_pnl`` is the realized PnL for this trade (0 for opens/adds).
    """

    model_config = ConfigDict(populate_by_name=True)

    action: str
    closed_pnl: float
    price: float
    side: str | None = None
    size: float
    timestamp: str
    token_symbol: str
    value_usd: float
    fee_usd: float
    start_position: float

    # Optional fields — present in full API responses but not always required
    block_number: int | None = None
    crossed: bool | None = None
    fee_token_symbol: str | None = None
    oid: int | None = None
    transaction_hash: str | None = None
    user: str | None = None


# ---------------------------------------------------------------------------
# Address Perp Positions — POST /api/v1/profiler/perp-positions
# ---------------------------------------------------------------------------

class Position(BaseModel):
    """A single perpetual position within an asset_positions entry.

    Most numeric values are returned as strings by the Nansen API and
    should be cast to float downstream when needed for calculations.
    ``size`` is negative for short positions, positive for long.
    """

    model_config = ConfigDict(populate_by_name=True)

    cumulative_funding_all_time_usd: str | None = None
    cumulative_funding_since_change_usd: str | None = None
    cumulative_funding_since_open_usd: str | None = None
    entry_price_usd: str
    leverage_type: str
    leverage_value: float
    liquidation_price_usd: str | None = None
    margin_used_usd: str | None = None
    max_leverage_value: float | None = None
    position_value_usd: str
    return_on_equity: str | None = None
    size: str
    token_symbol: str
    unrealized_pnl_usd: str | None = None


class AssetPosition(BaseModel):
    """Wrapper around a single Position with an optional position_type tag."""

    model_config = ConfigDict(populate_by_name=True)

    position: Position
    position_type: str | None = None


class PositionSnapshot(BaseModel):
    """Top-level ``data`` object from the perp-positions endpoint.

    Contains a list of asset positions plus account-level margin summaries.
    All margin/account values are strings in the API response.
    ``timestamp`` is a Unix epoch in milliseconds.
    """

    model_config = ConfigDict(populate_by_name=True)

    asset_positions: list[AssetPosition]
    margin_summary_account_value_usd: str | None = None
    margin_summary_total_margin_used_usd: str | None = None
    margin_summary_total_raw_usd: str | None = None
    cross_margin_summary_account_value_usd: str | None = None
    timestamp: int | None = None
    withdrawable_usd: str | None = None


# ---------------------------------------------------------------------------
# Perp PnL Leaderboard — POST /api/v1/tgm/perp-pnl-leaderboard
# ---------------------------------------------------------------------------

class PnlLeaderboardEntry(BaseModel):
    """A single row from the per-token PnL leaderboard.

    Provides both realized and unrealized PnL, ROI percentages, and
    trade counts for a specific perpetual contract.
    """

    model_config = ConfigDict(populate_by_name=True)

    trader_address: str
    trader_address_label: str | None = None
    price_usd: float | None = None
    pnl_usd_realised: float | None = None
    pnl_usd_unrealised: float | None = None
    holding_amount: float | None = None
    position_value_usd: float | None = None
    max_balance_held: float | None = None
    max_balance_held_usd: float | None = None
    still_holding_balance_ratio: float | None = None
    netflow_amount_usd: float | None = None
    netflow_amount: float | None = None
    roi_percent_total: float | None = None
    roi_percent_realised: float | None = None
    roi_percent_unrealised: float | None = None
    pnl_usd_total: float | None = None
    nof_trades: int | None = None


# ---------------------------------------------------------------------------
# Token Perp Positions — POST /api/v1/tgm/perp-positions
# ---------------------------------------------------------------------------

class TokenPerpPositionEntry(BaseModel):
    """A single position from the TGM perp-positions endpoint.

    ``leverage`` is returned as a string like ``"5X"`` by the API.
    """

    model_config = ConfigDict(populate_by_name=True)

    address: str
    address_label: str | None = None
    side: str
    position_value_usd: float
    position_size: float
    leverage: str  # e.g. "5X"
    leverage_type: str | None = None
    entry_price: float
    mark_price: float
    liquidation_price: float | None = None
    funding_usd: float | None = None
    upnl_usd: float | None = None


# ---------------------------------------------------------------------------
# Perp Screener — POST /api/v1/perp-screener
# ---------------------------------------------------------------------------

class PerpScreenerEntry(BaseModel):
    """A single row from the perp-screener endpoint."""

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
    # Smart money fields (present when label_type=smart_money)
    smart_money_volume: float | None = None
    smart_money_buy_volume: float | None = None
    smart_money_sell_volume: float | None = None
    smart_money_longs_count: int | None = None
    smart_money_shorts_count: int | None = None
    current_smart_money_position_longs_usd: float | None = None
    current_smart_money_position_shorts_usd: float | None = None
    net_position_change: float | None = None


# ---------------------------------------------------------------------------
# Shared pagination response
# ---------------------------------------------------------------------------

class PaginationResponse(BaseModel):
    """Pagination metadata returned alongside all paginated Nansen responses."""

    model_config = ConfigDict(populate_by_name=True)

    page: int
    per_page: int
    is_last_page: bool


# ---------------------------------------------------------------------------
# Computed trade metrics (internal, used by metrics engine & downstream)
# ---------------------------------------------------------------------------

class TradeMetrics(BaseModel):
    """Derived metrics computed from a window of closed trades.

    Used by the scoring engine (Phase 4), anti-luck filters (Phase 5),
    and stored in the ``trade_metrics`` SQLite table.
    """

    model_config = ConfigDict(populate_by_name=True)

    window_days: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    avg_return: float
    std_return: float
    pseudo_sharpe: float
    total_pnl: float
    roi_proxy: float
    max_drawdown_proxy: float

    # Extended fields for assessment strategies
    max_leverage: float = 0.0
    leverage_std: float = 0.0
    largest_trade_pnl_ratio: float = 0.0
    pnl_trend_slope: float = 0.0

    @classmethod
    def empty(cls, window_days: int) -> TradeMetrics:
        """Return a TradeMetrics instance with all numeric fields zeroed out.

        Useful when there are no trades in the given window.
        """
        return cls(
            window_days=window_days,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            profit_factor=0.0,
            avg_return=0.0,
            std_return=0.0,
            pseudo_sharpe=0.0,
            total_pnl=0.0,
            roi_proxy=0.0,
            max_drawdown_proxy=0.0,
            max_leverage=0.0,
            leverage_std=0.0,
            largest_trade_pnl_ratio=0.0,
            pnl_trend_slope=0.0,
        )
