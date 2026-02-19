"""Traders router — trader deep-dive detail, trades, and PnL curve."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.cache import CacheLayer
from backend.config import CACHE_TTL_TRADER, MOCK_STRATEGY_DATA
from backend.dependencies import get_cache, get_datastore, get_nansen_client
from backend.mock_data import (
    generate_mock_allocation_weight,
    generate_mock_pnl_curve,
    generate_mock_score,
)
from backend.schemas import (
    AntiLuckStatus,
    PnlCurveResponse,
    PnlPoint,
    ScoreBreakdown,
    TimeframeMetrics,
    TradeItem,
    TraderDetailResponse,
    TraderPosition,
    TradesResponse,
)
from src.datastore import DataStore
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["traders"])


def _safe_float(value: str | float | None, default: float = 0.0) -> float:
    """Safely convert a string or None to float."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _position_side(size_str: str) -> str:
    """Determine position side from size string (negative = Short)."""
    try:
        return "Short" if float(size_str) < 0 else "Long"
    except (ValueError, TypeError):
        return "Long"


@router.get("/traders/{address}", response_model=TraderDetailResponse)
async def get_trader_detail(
    address: str,
    nansen_client: NansenClient = Depends(get_nansen_client),
    datastore: DataStore = Depends(get_datastore),
    cache: CacheLayer = Depends(get_cache),
) -> TraderDetailResponse:
    """Return detailed information for a single trader."""
    cache_key = f"trader:{address}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Fetch current positions from Nansen
    try:
        snapshot = await nansen_client.fetch_address_positions(address)
    except NansenRateLimitError:
        raise HTTPException(
            status_code=429, detail="Nansen rate limit exceeded. Try again later."
        )
    except NansenAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Trader not found")
        logger.error("Nansen API error fetching positions for %s: %s", address, exc)
        raise HTTPException(
            status_code=502, detail=f"Upstream API error: {exc.detail}"
        )

    # Parse positions from snapshot
    positions: list[TraderPosition] = []
    for ap in snapshot.asset_positions:
        pos = ap.position
        positions.append(
            TraderPosition(
                token_symbol=pos.token_symbol,
                side=_position_side(pos.size),
                position_value_usd=_safe_float(pos.position_value_usd),
                entry_price=_safe_float(pos.entry_price_usd),
                leverage_value=pos.leverage_value,
                liquidation_price=_safe_float(pos.liquidation_price_usd) or None,
                unrealized_pnl_usd=_safe_float(pos.unrealized_pnl_usd) or None,
            )
        )

    account_value = _safe_float(snapshot.margin_summary_account_value_usd) or None

    # Look up trader in DataStore
    trader_row = datastore.get_trader(address)
    label = trader_row["label"] if trader_row else None
    trading_style = trader_row.get("style") if trader_row else None

    # Last active
    last_active = datastore.get_last_trade_time(address)

    # Score breakdown
    score_breakdown: ScoreBreakdown | None = None
    if MOCK_STRATEGY_DATA:
        mock_score = generate_mock_score(address)
        score_breakdown = ScoreBreakdown(**mock_score)
    else:
        score_data = datastore.get_latest_score(address)
        if score_data:
            score_breakdown = ScoreBreakdown(
                roi=score_data.get("normalized_roi", 0.0),
                sharpe=score_data.get("normalized_sharpe", 0.0),
                win_rate=score_data.get("normalized_win_rate", 0.0),
                consistency=score_data.get("consistency_score", 0.0),
                smart_money=score_data.get("smart_money_bonus", 0.0),
                risk_mgmt=score_data.get("risk_management_score", 0.0),
                style_multiplier=score_data.get("style_multiplier", 1.0),
                recency_decay=score_data.get("recency_decay", 1.0),
                final_score=score_data.get("final_score", 0.0),
            )

    # Allocation weight
    allocation_weight: float | None = None
    if MOCK_STRATEGY_DATA:
        allocation_weight = generate_mock_allocation_weight(address)
    else:
        allocations = datastore.get_latest_allocations()
        allocation_weight = allocations.get(address)

    # Anti-luck status
    anti_luck: AntiLuckStatus | None = None
    score_data_raw = datastore.get_latest_score(address) if not MOCK_STRATEGY_DATA else None
    if score_data_raw:
        passes = bool(score_data_raw.get("passes_anti_luck", 0))
        anti_luck = AntiLuckStatus(
            passed=passes,
            failures=[] if passes else ["Did not pass anti-luck filter"],
        )

    # Blacklist
    is_blacklisted = datastore.is_blacklisted(address)

    # Metrics from DataStore (30d window)
    metrics: dict[str, TimeframeMetrics] | None = None
    m30 = datastore.get_latest_metrics(address, window_days=30)
    if m30:
        metrics = {
            "30d": TimeframeMetrics(
                pnl=m30.total_pnl,
                roi=m30.roi_proxy,
                win_rate=m30.win_rate,
                trades=m30.total_trades,
            ),
        }

    response = TraderDetailResponse(
        address=address,
        label=label,
        trading_style=trading_style,
        last_active=last_active,
        positions=positions,
        account_value_usd=account_value,
        metrics=metrics,
        score_breakdown=score_breakdown,
        allocation_weight=allocation_weight,
        anti_luck_status=anti_luck,
        is_blacklisted=is_blacklisted,
    )

    cache.set(cache_key, response, ttl=CACHE_TTL_TRADER)
    return response


@router.get("/traders/{address}/trades", response_model=TradesResponse)
async def get_trader_trades(
    address: str,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=1000),
    nansen_client: NansenClient = Depends(get_nansen_client),
    cache: CacheLayer = Depends(get_cache),
) -> TradesResponse:
    """Return recent trades for a trader."""
    cache_key = f"trades:{address}:{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        raw_trades = await nansen_client.fetch_address_trades(
            address=address,
            date_from=date_from,
            date_to=date_to,
        )
    except NansenRateLimitError:
        raise HTTPException(
            status_code=429, detail="Nansen rate limit exceeded. Try again later."
        )
    except NansenAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Trader not found")
        logger.error("Nansen API error fetching trades for %s: %s", address, exc)
        raise HTTPException(
            status_code=502, detail=f"Upstream API error: {exc.detail}"
        )

    trade_items = [
        TradeItem(
            timestamp=t.timestamp,
            token_symbol=t.token_symbol,
            action=t.action,
            side=t.side,
            size=t.size,
            value_usd=t.value_usd,
            price=t.price,
            closed_pnl=t.closed_pnl,
            fee_usd=t.fee_usd,
        )
        for t in raw_trades[:limit]
    ]

    response = TradesResponse(trades=trade_items, total=len(raw_trades))
    cache.set(cache_key, response, ttl=CACHE_TTL_TRADER)
    return response


@router.get("/traders/{address}/pnl-curve", response_model=PnlCurveResponse)
async def get_trader_pnl_curve(
    address: str,
    days: int = Query(default=90, ge=1, le=365),
    nansen_client: NansenClient = Depends(get_nansen_client),
    cache: CacheLayer = Depends(get_cache),
) -> PnlCurveResponse:
    """Return cumulative PnL curve for a trader."""
    cache_key = f"pnl_curve:{address}:{days}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if MOCK_STRATEGY_DATA:
        mock_points = generate_mock_pnl_curve(address, days=days)
        points = [PnlPoint(**p) for p in mock_points]
        response = PnlCurveResponse(points=points)
        cache.set(cache_key, response, ttl=CACHE_TTL_TRADER)
        return response

    # Fetch trades for the time window
    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        raw_trades = await nansen_client.fetch_address_trades(
            address=address,
            date_from=date_from,
            date_to=date_to,
        )
    except NansenRateLimitError:
        raise HTTPException(
            status_code=429, detail="Nansen rate limit exceeded. Try again later."
        )
    except NansenAPIError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Trader not found")
        logger.error("Nansen API error fetching trades for PnL curve %s: %s", address, exc)
        raise HTTPException(
            status_code=502, detail=f"Upstream API error: {exc.detail}"
        )

    # Filter to Close trades and sort by timestamp ascending
    close_trades = [t for t in raw_trades if t.action == "Close"]
    close_trades.sort(key=lambda t: t.timestamp)

    # Compute cumulative PnL
    points: list[PnlPoint] = []
    cumulative = 0.0
    for trade in close_trades:
        cumulative += trade.closed_pnl
        points.append(
            PnlPoint(
                timestamp=trade.timestamp,
                cumulative_pnl=round(cumulative, 2),
            )
        )

    response = PnlCurveResponse(points=points)
    cache.set(cache_key, response, ttl=CACHE_TTL_TRADER)
    return response
