"""Assessment router — evaluate any trader address across 10 strategies."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.dependencies import get_cache, get_datastore, get_nansen_client
from backend.schemas import (
    AssessmentConfidence,
    AssessmentResponse,
    AssessmentStrategyResult,
)
from src.assessment.engine import AssessmentEngine
from src.datastore import DataStore
from src.metrics import compute_trade_metrics
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["assessment"])

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

CACHE_STALENESS_HOURS = 6
# For on-demand assessment, accept DB metrics up to 30 days old to avoid
# slow Nansen re-fetches.  Background recompute still uses the 6-hour window.
ASSESS_STALENESS_HOURS = 30 * 24


@router.get("/assess/{address}", response_model=AssessmentResponse)
async def assess_trader(
    address: str,
    window_days: int = Query(default=30, ge=7, le=90),
    nansen_client: NansenClient = Depends(get_nansen_client),
    datastore: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> AssessmentResponse:
    """Assess a trader address across 10 independent scoring strategies."""
    if not _ADDRESS_RE.match(address):
        raise HTTPException(status_code=400, detail="Invalid address format. Expected 0x followed by 40 hex characters.")

    cache_key = f"assess:{address}:{window_days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    is_cached = False
    metrics = None

    # Try datastore cache for leaderboard addresses
    cached_metrics = datastore.get_latest_metrics(address, window_days=window_days)
    if cached_metrics is not None:
        last_trade_time = datastore.get_last_trade_time(address)
        if last_trade_time:
            computed = datetime.fromisoformat(last_trade_time).replace(tzinfo=timezone.utc)
            if now - computed < timedelta(hours=ASSESS_STALENESS_HOURS):
                metrics = cached_metrics
                is_cached = True

    # Only fetch positions from Nansen when we need live data.
    # When metrics are cached, skip the slow positions API call.
    pos_snapshot = None
    if metrics is None:
        try:
            pos_snapshot = await nansen_client.fetch_address_positions(address)
        except Exception:
            logger.warning("Could not fetch positions for %s during assessment", address)

    # Live fetch from Nansen if no cached data
    if metrics is None:
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=window_days)).strftime("%Y-%m-%d")

        try:
            raw_trades = await nansen_client.fetch_address_trades(
                address=address,
                date_from=date_from,
                date_to=date_to,
                order_by=[{"field": "timestamp", "direction": "DESC"}],
            )
        except NansenRateLimitError:
            raise HTTPException(status_code=429, detail="Nansen rate limit exceeded. Try again in a few seconds.")
        except NansenAPIError as exc:
            logger.error("Nansen API error assessing %s: %s", address, exc)
            raise HTTPException(status_code=502, detail="Failed to fetch trade data from upstream API. Please try again.")

        account_value = 0.0
        if pos_snapshot is not None:
            av_str = pos_snapshot.margin_summary_account_value_usd
            account_value = float(av_str) if av_str else 0.0

        metrics = compute_trade_metrics(raw_trades, account_value, window_days)

    # Extract positions list for strategy evaluation
    positions = []
    if pos_snapshot is not None:
        for ap in pos_snapshot.asset_positions:
            p = ap.position
            positions.append({
                "token_symbol": p.token_symbol,
                "leverage_value": p.leverage_value,
                "leverage_type": p.leverage_type,
                "position_value_usd": float(p.position_value_usd) if p.position_value_usd else 0.0,
            })

    engine = AssessmentEngine()
    result = engine.assess(metrics, positions)

    response = AssessmentResponse(
        address=address,
        is_cached=is_cached,
        window_days=window_days,
        trade_count=metrics.total_trades,
        confidence=AssessmentConfidence(**result["confidence"]),
        strategies=[AssessmentStrategyResult(**s) for s in result["strategies"]],
        computed_at=now.isoformat(),
    )

    cache.set(cache_key, response, ttl=600)
    return response
