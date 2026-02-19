"""Screener router — perp screener data pass-through from Nansen."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_POSITIONS
from backend.dependencies import get_cache, get_nansen_client
from backend.schemas import ScreenerEntry, ScreenerResponse
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["screener"])


@router.get("/screener", response_model=ScreenerResponse)
async def get_screener(
    token: str | None = Query(default=None, description="Filter by token symbol"),
    nansen_client: NansenClient = Depends(get_nansen_client),
    cache: CacheLayer = Depends(get_cache),
) -> ScreenerResponse:
    """Return perp screener data, optionally filtered by token."""
    cache_key = f"screener:{token or 'all'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        filters = None
        if token:
            filters = {"token_symbol": token.upper()}

        raw = await nansen_client.fetch_perp_screener(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
        )

        entries = [
            ScreenerEntry(
                token_symbol=e.token_symbol,
                buy_sell_pressure=e.buy_sell_pressure,
                buy_volume=e.buy_volume,
                sell_volume=e.sell_volume,
                volume=e.volume,
                funding=e.funding,
                mark_price=e.mark_price,
                open_interest=e.open_interest,
                previous_price_usd=e.previous_price_usd,
                trader_count=e.trader_count,
                smart_money_volume=e.smart_money_volume,
                smart_money_buy_volume=e.smart_money_buy_volume,
                smart_money_sell_volume=e.smart_money_sell_volume,
                smart_money_longs_count=e.smart_money_longs_count,
                smart_money_shorts_count=e.smart_money_shorts_count,
                current_smart_money_position_longs_usd=e.current_smart_money_position_longs_usd,
                current_smart_money_position_shorts_usd=e.current_smart_money_position_shorts_usd,
                net_position_change=e.net_position_change,
            )
            for e in raw
        ]

        response = ScreenerResponse(
            entries=entries,
            fetched_at=now.isoformat(),
        )
        cache.set(cache_key, response, ttl=CACHE_TTL_POSITIONS)
        return response

    except NansenRateLimitError:
        raise HTTPException(status_code=429, detail="Nansen rate limit exceeded. Try again later.")
    except NansenAPIError as exc:
        logger.error("Nansen API error fetching screener: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream API error: {exc.detail}")
