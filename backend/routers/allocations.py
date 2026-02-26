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
    AllocationHistoryEntry,
    AllocationHistoryResponse,
    AllocationSnapshot,
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

    # Sort by weight descending and enforce the position cap.
    entries.sort(key=lambda e: e["weight"], reverse=True)
    entries = entries[:MAX_TOTAL_POSITIONS]

    # Renormalise weights so they sum to 1.0 after truncation.
    total = sum(e["weight"] for e in entries)
    if total > 0:
        for e in entries:
            e["weight"] = e["weight"] / total

    computed_at = ds.get_latest_allocation_timestamp()
    return entries, computed_at


def _build_risk_caps(
    entries: list[dict], ds: DataStore | None = None
) -> RiskCaps:
    """Compute risk cap utilisation from allocation entries.

    When a *ds* (DataStore) is provided, directional exposure is computed
    from real position snapshots.  For each trader we sum
    ``position_value_usd`` grouped by side ("Long" / "Short"), then weight
    by the trader's allocation weight.  If no position data exists for
    *any* trader we fall back to a naive 50/50 split.
    """
    n_positions = len(entries)
    max_weight = max((e["weight"] for e in entries), default=0.0)
    total_weight = sum(e["weight"] for e in entries)

    # --- Directional exposure from real positions --------------------------
    long_est = total_weight * 0.5
    short_est = total_weight * 0.5

    if ds is not None and entries:
        has_position_data = False
        real_long = 0.0
        real_short = 0.0

        for entry in entries:
            positions = ds.get_latest_position_snapshot(entry["address"])
            if not positions:
                continue

            pos_long = sum(
                p.get("position_value_usd", 0) or 0
                for p in positions
                if p.get("side") == "Long"
            )
            pos_short = sum(
                p.get("position_value_usd", 0) or 0
                for p in positions
                if p.get("side") == "Short"
            )
            pos_total = pos_long + pos_short

            if pos_total > 0:
                has_position_data = True
                # Distribute this trader's weight proportionally to their
                # long/short position split.
                real_long += entry["weight"] * (pos_long / pos_total)
                real_short += entry["weight"] * (pos_short / pos_total)

        if has_position_data:
            long_est = real_long
            short_est = real_short

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

    risk_caps = _build_risk_caps(entries, ds=ds)

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
# GET /api/v1/allocations/history
# ---------------------------------------------------------------------------


@router.get("/allocations/history", response_model=AllocationHistoryResponse)
async def get_allocation_history(
    days: int = 30,
    ds: DataStore = Depends(get_datastore),
) -> AllocationHistoryResponse:
    """Return historical allocation snapshots grouped by timestamp."""
    raw = ds.get_allocation_history(days=days)
    snapshots = [
        AllocationSnapshot(
            computed_at=entry["computed_at"],
            allocations=[
                AllocationHistoryEntry(**a) for a in entry["allocations"]
            ],
        )
        for entry in raw
    ]
    return AllocationHistoryResponse(snapshots=snapshots, days=days)


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


def _cap_portfolio_total(entries: list[dict], total_usd: float = 50_000.0) -> None:
    """Normalize *entries* so target_usd sums to *total_usd* and weights sum to 1.0.

    Mutates *entries* in place.
    """
    current_total = sum(e["target_usd"] for e in entries)
    if current_total <= 0:
        return
    for e in entries:
        proportion = e["target_usd"] / current_total
        e["target_weight"] = round(proportion, 4)
        e["target_usd"] = round(proportion * total_usd, 2)


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

        # Convert {(token, side): usd} into list[dict] for schema.
        total_abs = sum(raw_portfolio.values()) or 1.0
        result = []
        for (token, side), target_usd in raw_portfolio.items():
            result.append({
                "token": token,
                "side": side,
                "target_weight": round(target_usd / total_abs, 4),
                "target_usd": round(target_usd, 2),
            })

        # Keep only top 10 by target_usd, capped at $50k total.
        result.sort(key=lambda e: e["target_usd"], reverse=True)
        result = result[:10]
        _cap_portfolio_total(result, total_usd=50_000.0)

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
            # Skip tokens with fewer than 3 voters — not a real consensus.
            if result["participating_traders"] < 3:
                continue
            total = result["long_weight"] + result["short_weight"]
            if total > 0:
                direction = "Long" if result["long_weight"] >= result["short_weight"] else "Short"
                confidence = round(max(result["long_weight"], result["short_weight"]) / total, 2)
            else:
                continue
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
