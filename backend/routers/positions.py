"""Positions router — token-level perpetual position data from Nansen TGM."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_POSITIONS
from backend.dependencies import get_cache, get_nansen_client
from backend.schemas import (
    LabelTypeEnum,
    PositionMeta,
    PositionResponse,
    SideEnum,
    TokenEnum,
    TokenPerpPosition,
)
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["positions"])


def _parse_leverage(leverage_str: str) -> float:
    """Convert leverage string like ``'5X'`` to a float."""
    cleaned = leverage_str.strip().upper().rstrip("X")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


@router.get("/positions", response_model=PositionResponse)
async def get_positions(
    token: TokenEnum,
    label_type: LabelTypeEnum = LabelTypeEnum.all_traders,
    side: SideEnum | None = None,
    min_position_usd: float = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    nansen_client: NansenClient = Depends(get_nansen_client),
    cache: CacheLayer = Depends(get_cache),
) -> PositionResponse:
    """Return perpetual positions for a token, enriched with metadata."""
    cache_key = f"positions:{token.value}:{label_type.value}"
    cached = cache.get(cache_key)

    if cached is not None:
        positions_data = cached
    else:
        try:
            raw_positions = await nansen_client.fetch_token_perp_positions(
                token_symbol=token.value,
                label_type=label_type.value,
                pagination={"page": 1, "per_page": 100},
            )
            positions_data = raw_positions
            cache.set(cache_key, positions_data, ttl=CACHE_TTL_POSITIONS)
        except NansenRateLimitError:
            raise HTTPException(status_code=429, detail="Nansen rate limit exceeded. Try again later.")
        except NansenAPIError as exc:
            logger.error("Nansen API error fetching positions: %s", exc)
            raise HTTPException(status_code=502, detail=f"Upstream API error: {exc.detail}")

    # Build response positions with parsed leverage and metadata
    result_positions: list[TokenPerpPosition] = []
    for entry in positions_data:
        leverage_val = _parse_leverage(entry.leverage)

        # Apply client-side filters
        if side is not None and entry.side != side.value:
            continue
        if entry.position_value_usd < min_position_usd:
            continue

        # Determine smart money status
        is_sm = label_type == LabelTypeEnum.smart_money
        sm_labels = [entry.address_label] if is_sm and entry.address_label else []

        result_positions.append(
            TokenPerpPosition(
                address=entry.address,
                address_label=entry.address_label,
                side=entry.side,
                position_value_usd=entry.position_value_usd,
                position_size=entry.position_size,
                leverage=leverage_val,
                leverage_type=entry.leverage_type,
                entry_price=entry.entry_price,
                mark_price=entry.mark_price,
                liquidation_price=entry.liquidation_price,
                funding_usd=entry.funding_usd,
                upnl_usd=entry.upnl_usd,
                rank=0,  # set below
                is_smart_money=is_sm,
                smart_money_labels=sm_labels,
            )
        )

    # Apply limit and assign ranks
    result_positions = result_positions[:limit]
    for i, pos in enumerate(result_positions, start=1):
        pos.rank = i

    # Compute meta
    total_long = sum(p.position_value_usd for p in result_positions if p.side == "Long")
    total_short = sum(p.position_value_usd for p in result_positions if p.side == "Short")
    ls_ratio = total_long / total_short if total_short > 0 else 0.0
    sm_count = sum(1 for p in result_positions if p.is_smart_money)

    meta = PositionMeta(
        total_long_value=total_long,
        total_short_value=total_short,
        long_short_ratio=round(ls_ratio, 4),
        smart_money_count=sm_count,
        fetched_at=datetime.now(timezone.utc),
    )

    return PositionResponse(
        token=token.value,
        positions=result_positions,
        meta=meta,
    )
