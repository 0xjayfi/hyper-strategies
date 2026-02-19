"""Allocations & strategy router — allocation weights and strategy signals."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_ALLOCATIONS, MOCK_STRATEGY_DATA
from backend.dependencies import get_cache, get_datastore
from backend.mock_data import (
    generate_mock_allocations,
    generate_mock_consensus,
    generate_mock_index_portfolio,
)
from backend.schemas import (
    AllocationEntry,
    AllocationsResponse,
    ConsensusToken,
    IndexPortfolioEntry,
    RiskCapStatus,
    RiskCaps,
    SizingEntry,
    StrategiesResponse,
)
from src.config import (
    MAX_EXPOSURE_PER_TOKEN,
    MAX_LONG_EXPOSURE,
    MAX_SHORT_EXPOSURE,
    MAX_TOTAL_POSITIONS,
    SOFTMAX_TEMPERATURE,
)
from src.datastore import DataStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["allocations"])

# Default account value used for mock sizing calculations.
_DEFAULT_ACCOUNT_VALUE = 100_000.0


def _build_allocations_from_db(ds: DataStore) -> tuple[list[dict], str | None]:
    """Fetch latest allocations from DataStore and enrich with labels.

    Returns (list_of_entry_dicts, computed_at_str | None).
    """
    raw = ds.get_latest_allocations()  # {address: final_weight}
    if not raw:
        return [], None

    # Retrieve roi_tier from latest scores when available.
    scores = ds.get_latest_scores()

    entries: list[dict] = []
    for addr, weight in raw.items():
        label = ds.get_trader_label(addr)
        roi_tier = 1.0
        score_data = scores.get(addr)
        if score_data and score_data.get("roi_tier_multiplier") is not None:
            roi_tier = score_data["roi_tier_multiplier"]

        entries.append({
            "address": addr,
            "label": label,
            "weight": weight,
            "roi_tier": roi_tier,
        })

    # Sort by weight descending for readability.
    entries.sort(key=lambda e: e["weight"], reverse=True)
    return entries, None  # computed_at not exposed by get_latest_allocations


def _build_risk_caps(entries: list[dict]) -> RiskCaps:
    """Compute risk cap utilisation from allocation entries."""
    n_positions = len(entries)
    max_weight = max((e["weight"] for e in entries), default=0.0)

    # Estimate directional exposure: assume equal long/short split as default.
    total_weight = sum(e["weight"] for e in entries)
    long_est = total_weight * 0.5
    short_est = total_weight * 0.5

    return RiskCaps(
        position_count=RiskCapStatus(current=n_positions, max=MAX_TOTAL_POSITIONS),
        max_token_exposure=RiskCapStatus(current=max_weight, max=MAX_EXPOSURE_PER_TOKEN),
        directional_long=RiskCapStatus(current=round(long_est, 4), max=MAX_LONG_EXPOSURE),
        directional_short=RiskCapStatus(current=round(short_est, 4), max=MAX_SHORT_EXPOSURE),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/allocations
# ---------------------------------------------------------------------------


@router.get("/allocations", response_model=AllocationsResponse)
async def get_allocations(
    ds: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> AllocationsResponse:
    """Return current trader allocation weights and risk cap utilisation."""
    cache_key = "allocations:latest"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    entries, computed_at = _build_allocations_from_db(ds)

    if not entries and MOCK_STRATEGY_DATA:
        entries = generate_mock_allocations()
        computed_at = datetime.now(timezone.utc).isoformat()

    risk_caps = _build_risk_caps(entries)

    response = AllocationsResponse(
        allocations=[AllocationEntry(**e) for e in entries],
        softmax_temperature=SOFTMAX_TEMPERATURE,
        total_allocated_traders=len(entries),
        risk_caps=risk_caps,
        computed_at=computed_at,
    )

    cache.set(cache_key, response, ttl=CACHE_TTL_ALLOCATIONS)
    return response


# ---------------------------------------------------------------------------
# GET /api/v1/allocations/strategies
# ---------------------------------------------------------------------------


@router.get("/allocations/strategies", response_model=StrategiesResponse)
async def get_strategies(
    ds: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> StrategiesResponse:
    """Return strategy signals: index portfolio, consensus, and sizing params."""
    cache_key = "allocations:strategies"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    entries, _ = _build_allocations_from_db(ds)
    use_mock = not entries and MOCK_STRATEGY_DATA

    # -- Strategy #2: Index Portfolio --
    if use_mock:
        index_raw = generate_mock_index_portfolio()
    else:
        # Attempt to build from real data via strategy_interface.
        index_raw = _try_build_index_portfolio(entries, ds)

    index_portfolio = [IndexPortfolioEntry(**e) for e in index_raw]

    # -- Strategy #3: Consensus --
    if use_mock:
        consensus_raw = generate_mock_consensus()
    else:
        consensus_raw = _try_build_consensus(entries, ds)

    consensus = {
        token: ConsensusToken(**data)
        for token, data in consensus_raw.items()
    }

    # -- Strategy #5: Sizing --
    sizing_params = _build_sizing_params(entries, _DEFAULT_ACCOUNT_VALUE)

    response = StrategiesResponse(
        index_portfolio=index_portfolio,
        consensus=consensus,
        sizing_params=sizing_params,
    )

    cache.set(cache_key, response, ttl=CACHE_TTL_ALLOCATIONS)
    return response


# ---------------------------------------------------------------------------
# Helpers for strategies endpoint
# ---------------------------------------------------------------------------


def _try_build_index_portfolio(entries: list[dict], ds: DataStore) -> list[dict]:
    """Build index portfolio from real allocations and positions.

    Falls back to mock data if trader positions are unavailable.
    """
    try:
        from src.strategy_interface import build_index_portfolio

        allocations = {e["address"]: e["weight"] for e in entries}
        trader_positions: dict[str, list] = {}
        for addr in allocations:
            snaps = ds.get_latest_position_snapshot(addr)
            if snaps:
                trader_positions[addr] = snaps

        if not trader_positions:
            return generate_mock_index_portfolio()

        raw_portfolio = build_index_portfolio(
            allocations, trader_positions, _DEFAULT_ACCOUNT_VALUE
        )

        # Convert {token: signed_usd} into list[dict] for schema.
        total_abs = sum(abs(v) for v in raw_portfolio.values()) or 1.0
        result = []
        for token, target_usd in raw_portfolio.items():
            side = "Long" if target_usd >= 0 else "Short"
            result.append({
                "token": token,
                "side": side,
                "target_weight": round(abs(target_usd) / total_abs, 4),
                "target_usd": round(abs(target_usd), 2),
            })
        return result or generate_mock_index_portfolio()
    except Exception:
        logger.exception("Failed to build index portfolio from live data")
        return generate_mock_index_portfolio()


def _try_build_consensus(entries: list[dict], ds: DataStore) -> dict:
    """Build consensus from real allocations and positions.

    Falls back to mock data if trader positions are unavailable.
    """
    try:
        from src.strategy_interface import weighted_consensus

        allocations = {e["address"]: e["weight"] for e in entries}
        trader_positions: dict[str, list] = {}
        for addr in allocations:
            snaps = ds.get_latest_position_snapshot(addr)
            if snaps:
                trader_positions[addr] = snaps

        if not trader_positions:
            return generate_mock_consensus()

        # Gather unique tokens from positions.
        tokens: set[str] = set()
        for snaps in trader_positions.values():
            for p in snaps:
                tokens.add(p["token_symbol"])

        consensus: dict[str, dict] = {}
        for token in sorted(tokens):
            result = weighted_consensus(token, allocations, trader_positions)
            total = result["long_weight"] + result["short_weight"]
            if total > 0:
                direction = "Long" if result["long_weight"] >= result["short_weight"] else "Short"
                confidence = round(max(result["long_weight"], result["short_weight"]) / total, 2)
            else:
                direction = "Long"
                confidence = 0.5
            consensus[token] = {
                "direction": direction,
                "confidence": confidence,
                "voter_count": result["participating_traders"],
            }
        return consensus or generate_mock_consensus()
    except Exception:
        logger.exception("Failed to build consensus from live data")
        return generate_mock_consensus()


def _build_sizing_params(entries: list[dict], account_value: float) -> list[SizingEntry]:
    """Build per-trader sizing parameters from allocation entries."""
    return [
        SizingEntry(
            address=e["address"],
            weight=e["weight"],
            roi_tier=e["roi_tier"],
            max_size_usd=round(e["weight"] * account_value, 2),
        )
        for e in entries
    ]
