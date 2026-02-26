"""Leaderboard router — trader rankings from DataStore or Nansen fallback."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_LEADERBOARD
from backend.dependencies import get_cache, get_datastore, get_nansen_client
from backend.schemas import (
    AntiLuckStatus,
    LeaderboardResponse,
    LeaderboardTrader,
    TimeframeEnum,
    TokenEnum,
)
from src.datastore import DataStore
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leaderboard"])

_TIMEFRAME_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _build_datastore_leaderboard(
    datastore: DataStore,
    limit: int,
    sort_by: str,
) -> list[LeaderboardTrader] | None:
    """Attempt to build leaderboard from DataStore scores.

    Returns ``None`` if no scores are available.
    """
    scores = datastore.get_latest_scores()
    if not scores:
        return None

    allocations = datastore.get_latest_allocations()

    traders: list[LeaderboardTrader] = []
    for address, score_data in scores.items():
        trader_row = datastore.get_trader(address)
        label = trader_row["label"] if trader_row else None

        # Get trade metrics for win_rate, profit_factor, num_trades
        metrics = datastore.get_latest_metrics(address, window_days=30)
        win_rate = metrics.win_rate if metrics else None
        pf = metrics.profit_factor if metrics else None
        profit_factor = pf if pf is not None and pf != float("inf") else None
        num_trades = metrics.total_trades if metrics else 0
        total_pnl = metrics.total_pnl if metrics else 0.0
        roi_pct = metrics.roi_proxy if metrics else 0.0

        # Anti-luck status
        passes = bool(score_data.get("passes_anti_luck", 0))
        anti_luck = AntiLuckStatus(
            passed=passes,
            failures=[] if passes else ["Did not pass anti-luck filter"],
        )

        traders.append(
            LeaderboardTrader(
                rank=0,  # assigned after sorting
                address=address,
                label=label,
                pnl_usd=total_pnl,
                roi_pct=roi_pct,
                win_rate=win_rate,
                profit_factor=profit_factor,
                num_trades=num_trades,
                score=score_data.get("final_score"),
                allocation_weight=allocations.get(address),
                anti_luck_status=anti_luck,
                is_blacklisted=datastore.is_blacklisted(address),
            )
        )

    # Sort
    if sort_by == "pnl":
        traders.sort(key=lambda t: t.pnl_usd, reverse=True)
    elif sort_by == "roi":
        traders.sort(key=lambda t: t.roi_pct, reverse=True)
    else:  # default: score
        traders.sort(key=lambda t: t.score or 0.0, reverse=True)

    traders = traders[:limit]
    for i, t in enumerate(traders, start=1):
        t.rank = i

    return traders


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    token: TokenEnum | None = None,
    timeframe: TimeframeEnum = TimeframeEnum.d30,
    limit: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="score"),
    nansen_client: NansenClient = Depends(get_nansen_client),
    datastore: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> LeaderboardResponse:
    """Return trader leaderboard from DataStore scores or Nansen fallback."""
    token_val = token.value if token else "all"
    cache_key = f"leaderboard:{token_val}:{timeframe.value}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Path 1: DataStore
    ds_traders = _build_datastore_leaderboard(datastore, limit, sort_by)
    if ds_traders is not None:
        response = LeaderboardResponse(
            timeframe=timeframe.value,
            traders=ds_traders,
            source="datastore",
        )
        cache.set(cache_key, response, ttl=CACHE_TTL_LEADERBOARD)
        return response

    # Path 2: Nansen fallback
    days = _TIMEFRAME_DAYS.get(timeframe.value, 30)
    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        if token is not None:
            raw = await nansen_client.fetch_pnl_leaderboard(
                token_symbol=token.value,
                date_from=date_from,
                date_to=date_to,
                pagination={"page": 1, "per_page": limit},
            )
            traders = []
            for i, entry in enumerate(raw[:limit], start=1):
                pnl = entry.pnl_usd_total or 0.0
                roi = entry.roi_percent_total or 0.0
                label = entry.trader_address_label
                smart = bool(label and "smart money" in label.lower())
                traders.append(
                    LeaderboardTrader(
                        rank=i,
                        address=entry.trader_address,
                        label=label,
                        pnl_usd=pnl,
                        roi_pct=roi,
                        num_trades=entry.nof_trades or 0,
                        is_smart_money=smart,
                    )
                )
        else:
            raw = await nansen_client.fetch_leaderboard(
                date_from=date_from,
                date_to=date_to,
                pagination={"page": 1, "per_page": limit},
            )
            traders = []
            for i, entry in enumerate(raw[:limit], start=1):
                label = entry.trader_address_label
                smart = bool(label and "smart money" in label.lower())
                traders.append(
                    LeaderboardTrader(
                        rank=i,
                        address=entry.trader_address,
                        label=label,
                        pnl_usd=entry.total_pnl,
                        roi_pct=entry.roi,
                        num_trades=0,
                        is_smart_money=smart,
                    )
                )

        # Sort Nansen results by pnl
        traders.sort(key=lambda t: t.pnl_usd, reverse=True)
        for i, t in enumerate(traders, start=1):
            t.rank = i

        response = LeaderboardResponse(
            timeframe=timeframe.value,
            traders=traders,
            source="nansen_api",
        )
        cache.set(cache_key, response, ttl=CACHE_TTL_LEADERBOARD)
        return response

    except NansenRateLimitError:
        raise HTTPException(status_code=429, detail="Nansen rate limit exceeded. Try again later.")
    except NansenAPIError as exc:
        logger.error("Nansen API error fetching leaderboard: %s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream API error: {exc.detail}")
