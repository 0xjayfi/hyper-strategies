"""Leaderboard router — trader rankings from DataStore or Nansen fallback."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_LEADERBOARD
from backend.dependencies import get_cache, get_datastore, get_nansen_client
from backend.schemas import (
    LeaderboardResponse,
    LeaderboardTrader,
)
from src.datastore import DataStore
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["leaderboard"])


def _build_datastore_leaderboard(
    datastore: DataStore,
    limit: int,
) -> tuple[list[LeaderboardTrader], str | None] | None:
    """Attempt to build leaderboard from DataStore scores.

    Returns ``(traders, scored_at)`` or ``None`` if no scores are available.
    """
    scores = datastore.get_latest_scores()
    if not scores:
        return None

    allocations = datastore.get_latest_allocations()
    scored_at: str | None = None

    traders: list[LeaderboardTrader] = []
    for address, score_data in scores.items():
        trader_row = datastore.get_trader(address)
        label = trader_row["label"] if trader_row else None

        # Capture scored_at from first entry that has it
        if scored_at is None and score_data.get("computed_at"):
            scored_at = score_data["computed_at"]

        traders.append(
            LeaderboardTrader(
                rank=0,  # assigned after sorting
                address=address,
                label=label,
                score=score_data.get("final_score"),
                allocation_weight=allocations.get(address),
                is_blacklisted=datastore.is_blacklisted(address),
                is_smart_money=bool(score_data.get("smart_money_bonus", 0)),
                # Position-based score components (DB → API field):
                score_growth=score_data.get("normalized_roi"),
                score_drawdown=score_data.get("normalized_sharpe"),
                score_leverage=score_data.get("normalized_win_rate"),
                score_liq_distance=score_data.get("risk_management_score"),
                score_diversity=score_data.get("style_multiplier"),
                score_consistency=score_data.get("consistency_score"),
                score_smart_money=score_data.get("smart_money_bonus"),
            )
        )

    # Sort by score (only meaningful sort for position-based scoring)
    traders.sort(key=lambda t: t.score or 0.0, reverse=True)
    traders = traders[:limit]
    for i, t in enumerate(traders, start=1):
        t.rank = i

    return traders, scored_at


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    limit: int = Query(default=100, ge=1, le=200),
    nansen_client: NansenClient = Depends(get_nansen_client),
    datastore: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> LeaderboardResponse:
    """Return trader leaderboard from DataStore scores or Nansen fallback."""
    cache_key = "leaderboard:position_scores"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Path 1: DataStore (position-based scores)
    result = _build_datastore_leaderboard(datastore, limit)
    if result is not None:
        ds_traders, scored_at = result
        response = LeaderboardResponse(
            traders=ds_traders,
            source="datastore",
            scored_at=scored_at,
        )
        cache.set(cache_key, response, ttl=CACHE_TTL_LEADERBOARD)
        return response

    # Path 2: Nansen fallback (basic ranking, no scores)
    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
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
                    is_smart_money=smart,
                )
            )

        response = LeaderboardResponse(
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
