"""Pydantic models for Nansen API responses and internal data structures.

These models provide strict validation and serialisation for the three Nansen
endpoints used by the system:

1. Perp Leaderboard  (POST /api/v1/perp-leaderboard)
2. Address Perp Positions (POST /api/v1/profiler/perp-positions)
3. Address Perp Trades (POST /api/v1/profiler/perp-trades)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ===========================================================================
# Pagination (shared across endpoints)
# ===========================================================================


class PaginationInfo(BaseModel):
    """Pagination metadata returned by all paginated Nansen endpoints."""

    page: int
    per_page: int
    is_last_page: bool


# ===========================================================================
# Perp Leaderboard
# ===========================================================================


class LeaderboardEntry(BaseModel):
    """A single trader row from the perp-leaderboard response.

    Maps to: POST /api/v1/perp-leaderboard -> data[]
    """

    trader_address: str
    trader_address_label: str = ""
    total_pnl: float
    roi: float
    account_value: float


class LeaderboardResponse(BaseModel):
    """Top-level response wrapper for the perp-leaderboard endpoint."""

    data: list[LeaderboardEntry]
    pagination: PaginationInfo


# ===========================================================================
# Address Perp Positions
# ===========================================================================


class PerpPosition(BaseModel):
    """A single perpetual position from the perp-positions response.

    The Nansen API returns numeric fields as strings; we coerce them to float
    via Pydantic validators (using ``Field`` with default coercion).  The
    ``size`` field is signed: negative means short, positive means long.

    Maps to: POST /api/v1/profiler/perp-positions -> data.asset_positions[].position
    """

    token_symbol: str
    entry_price_usd: float
    leverage_type: str  # "cross" or "isolated"
    leverage_value: float
    liquidation_price_usd: float
    margin_used_usd: float
    position_value_usd: float
    size: float  # negative = short, positive = long
    unrealized_pnl_usd: float

    # Optional fields present in the API response but not always needed
    cumulative_funding_all_time_usd: Optional[float] = None
    cumulative_funding_since_change_usd: Optional[float] = None
    cumulative_funding_since_open_usd: Optional[float] = None
    max_leverage_value: Optional[float] = None
    return_on_equity: Optional[float] = None

    @property
    def side(self) -> str:
        """Derive trade side from the sign of size."""
        return "Short" if self.size < 0 else "Long"


class AssetPosition(BaseModel):
    """Wrapper around a position with its type metadata.

    Maps to: data.asset_positions[]
    """

    position: PerpPosition
    position_type: str = "oneWay"


class PerpPositionsData(BaseModel):
    """The ``data`` object inside the perp-positions response.

    Contains both the list of positions and account-level margin summaries.
    """

    asset_positions: list[AssetPosition] = Field(default_factory=list)
    margin_summary_account_value_usd: float

    # Additional margin fields (kept as optional for forward compatibility)
    cross_maintenance_margin_used_usd: Optional[float] = None
    cross_margin_summary_account_value_usd: Optional[float] = None
    cross_margin_summary_total_margin_used_usd: Optional[float] = None
    cross_margin_summary_total_net_liquidation_position_on_usd: Optional[float] = None
    cross_margin_summary_total_raw_usd: Optional[float] = None
    margin_summary_total_margin_used_usd: Optional[float] = None
    margin_summary_total_net_liquidation_position_usd: Optional[float] = None
    margin_summary_total_raw_usd: Optional[float] = None
    timestamp: Optional[int] = None
    withdrawable_usd: Optional[float] = None


class PerpPositionsResponse(BaseModel):
    """Top-level response wrapper for the perp-positions endpoint.

    Maps to: POST /api/v1/profiler/perp-positions
    """

    data: PerpPositionsData


# ===========================================================================
# Address Perp Trades
# ===========================================================================


class PerpTrade(BaseModel):
    """A single perpetual trade from the perp-trades response.

    Maps to: POST /api/v1/profiler/perp-trades -> data[]
    """

    action: str  # "Open", "Close", "Add", "Reduce"
    closed_pnl: float
    fee_usd: float
    price: float
    side: str  # "Long" or "Short"
    size: float
    timestamp: datetime
    token_symbol: str
    value_usd: float

    # Optional fields present in the API but not always needed by our system
    block_number: Optional[int] = None
    crossed: Optional[bool] = None
    fee_token_symbol: Optional[str] = None
    oid: Optional[int] = None
    start_position: Optional[float] = None
    transaction_hash: Optional[str] = None
    user: Optional[str] = None


class PerpTradesResponse(BaseModel):
    """Top-level response wrapper for the perp-trades endpoint.

    Maps to: POST /api/v1/profiler/perp-trades
    """

    data: list[PerpTrade]
    pagination: PaginationInfo
