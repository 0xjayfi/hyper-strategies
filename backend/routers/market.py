"""Market overview router — aggregated token data from Nansen."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_POSITIONS
from backend.dependencies import get_cache, get_nansen_client
from backend.schemas import (
    ConsensusEntry,
    MarketOverviewResponse,
    SmartMoneyFlow,
    TokenOverview,
)
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["market"])

_TOKENS = ["BTC", "ETH", "SOL", "HYPE"]


def _compute_consensus(
    long_value: float, short_value: float,
) -> tuple[str, float]:
    """Return (direction, confidence_pct) for a token's smart-money positions."""
    total = long_value + short_value
    if total == 0:
        return "Neutral", 0.0
    confidence = abs(long_value - short_value) / total * 100
    if confidence < 5:
        return "Neutral", round(confidence, 2)
    direction = "Bullish" if long_value > short_value else "Bearish"
    return direction, round(confidence, 2)


@router.get("/market-overview", response_model=MarketOverviewResponse)
async def get_market_overview(
    nansen_client: NansenClient = Depends(get_nansen_client),
    cache: CacheLayer = Depends(get_cache),
) -> MarketOverviewResponse:
    """Return aggregated market overview for BTC, ETH, SOL, HYPE."""
    cache_key = "market-overview"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # Fetch all data concurrently: smart_money + all_traders per token + screener
        tasks = []
        for token in _TOKENS:
            tasks.append(
                nansen_client.fetch_token_perp_positions(
                    token_symbol=token,
                    label_type="smart_money",
                    pagination={"page": 1, "per_page": 100},
                )
            )
            tasks.append(
                nansen_client.fetch_token_perp_positions(
                    token_symbol=token,
                    label_type="all_traders",
                    pagination={"page": 1, "per_page": 100},
                )
            )
        tasks.append(
            nansen_client.fetch_perp_screener(date_from=date_from, date_to=date_to)
        )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for fatal errors in results
        for r in results:
            if isinstance(r, NansenRateLimitError):
                raise HTTPException(status_code=429, detail="Nansen rate limit exceeded. Try again later.")
            if isinstance(r, NansenAPIError):
                raise HTTPException(status_code=502, detail=f"Upstream API error: {r.detail}")
            if isinstance(r, Exception):
                logger.error("Unexpected error in market overview gather: %s", r)
                raise HTTPException(status_code=502, detail="Upstream API error")

        # Unpack: for each token we have (smart_money, all_traders) pairs
        screener_entries = results[-1]
        screener_map = {e.token_symbol: e for e in screener_entries}

        token_overviews: list[TokenOverview] = []
        consensus_map: dict[str, ConsensusEntry] = {}
        total_sm_long = 0.0
        total_sm_short = 0.0

        for i, token in enumerate(_TOKENS):
            sm_positions = results[i * 2]       # smart_money positions
            all_positions = results[i * 2 + 1]  # all_traders positions

            # Smart money long/short aggregation
            sm_long = sum(p.position_value_usd for p in sm_positions if p.side == "Long")
            sm_short = sum(p.position_value_usd for p in sm_positions if p.side == "Short")
            total_sm_long += sm_long
            total_sm_short += sm_short

            # Consensus
            direction, confidence = _compute_consensus(sm_long, sm_short)
            consensus_map[token] = ConsensusEntry(direction=direction, confidence=confidence)

            # Smart money net direction for this token
            if sm_long > sm_short:
                sm_net_dir = "Net Long"
            elif sm_short > sm_long:
                sm_net_dir = "Net Short"
            else:
                sm_net_dir = "Neutral"

            # All traders long/short ratio
            all_long = sum(p.position_value_usd for p in all_positions if p.side == "Long")
            all_short = sum(p.position_value_usd for p in all_positions if p.side == "Short")
            ls_ratio = all_long / all_short if all_short > 0 else (float("inf") if all_long > 0 else 0.0)
            total_pos_value = all_long + all_short

            # Top trader (largest position by value)
            top_trader = max(all_positions, key=lambda p: p.position_value_usd) if all_positions else None

            # Screener data
            screener = screener_map.get(token)
            funding_rate = screener.funding if screener and screener.funding is not None else 0.0
            oi = screener.open_interest if screener else None
            vol = screener.volume if screener else None

            token_overviews.append(
                TokenOverview(
                    symbol=token,
                    long_short_ratio=round(ls_ratio, 4),
                    total_position_value=total_pos_value,
                    top_trader_label=top_trader.address_label if top_trader else None,
                    top_trader_side=top_trader.side if top_trader else "Long",
                    top_trader_size_usd=top_trader.position_value_usd if top_trader else 0.0,
                    funding_rate=funding_rate,
                    smart_money_net_direction=sm_net_dir,
                    smart_money_confidence_pct=confidence,
                    open_interest_usd=oi,
                    volume_24h_usd=vol,
                )
            )

        # Aggregate smart money flow
        if total_sm_long > total_sm_short:
            flow_dir = "Net Long"
        elif total_sm_short > total_sm_long:
            flow_dir = "Net Short"
        else:
            flow_dir = "Neutral"

        response = MarketOverviewResponse(
            tokens=token_overviews,
            consensus=consensus_map,
            smart_money_flow=SmartMoneyFlow(
                net_long_usd=total_sm_long,
                net_short_usd=total_sm_short,
                direction=flow_dir,
            ),
            fetched_at=now.isoformat(),
        )

        cache.set(cache_key, response, ttl=CACHE_TTL_POSITIONS)
        return response

    except HTTPException:
        raise
    except NansenRateLimitError:
        raise HTTPException(status_code=429, detail="Nansen rate limit exceeded. Try again later.")
    except NansenAPIError as exc:
        logger.error("Nansen API error fetching market overview: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream API error: {exc.detail}")
