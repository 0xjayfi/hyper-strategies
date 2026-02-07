"""Scoring calculators for the Snap copytrading system.

Implements the full trader scoring pipeline:

1. Tier-1 filter (minimum ROI and account value)
2. Multi-timeframe consistency gate (7d/30d/90d checks)
3. Trade metrics computation (win rate, profit factor, pseudo-Sharpe, etc.)
4. Quality gate (trade count, win rate range, profit factor threshold)
5. Normalized component scores (ROI, Sharpe, win rate, consistency, etc.)
6. Recency decay and smart money bonus

All threshold constants are imported from ``snap.config``.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from snap.config import (
    MIN_ACCOUNT_VALUE,
    MIN_PROFIT_FACTOR,
    MIN_ROI_30D,
    MIN_TRADE_COUNT,
    TOP_N_TRADERS,
    TREND_TRADER_MAX_WR,
    TREND_TRADER_MIN_PF,
    W_CONSISTENCY,
    W_RISK_MGMT,
    W_ROI,
    W_SHARPE,
    W_SMART_MONEY,
    W_WIN_RATE,
    WIN_RATE_MAX,
    WIN_RATE_MIN,
)
from snap.database import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(ts: str | datetime) -> datetime:
    """Parse a timestamp string into a timezone-aware datetime.

    Handles ISO 8601 strings (with or without timezone info) and passes
    through ``datetime`` objects unchanged.  Naive datetimes are assumed UTC.
    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    ts_str = str(ts)
    # Remove trailing 'Z' and replace with +00:00 for fromisoformat
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"

    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ===========================================================================
# 1. Tier-1 Filter
# ===========================================================================


def passes_tier1(roi_30d: float | None, account_value: float | None) -> bool:
    """Check if a trader passes tier-1 filters.

    Requirements:
    - ``roi_30d >= MIN_ROI_30D`` (15.0)
    - ``account_value >= MIN_ACCOUNT_VALUE`` (50000)

    Returns ``False`` if either value is ``None``.
    """
    if roi_30d is None or account_value is None:
        return False
    return roi_30d >= MIN_ROI_30D and account_value >= MIN_ACCOUNT_VALUE


# ===========================================================================
# 2. Multi-timeframe Consistency Gate
# ===========================================================================


def passes_consistency_gate(
    roi_7d: float | None,
    roi_30d: float | None,
    roi_90d: float | None,
    pnl_7d: float | None,
    pnl_30d: float | None,
    pnl_90d: float | None,
) -> tuple[bool, bool]:
    """Check multi-timeframe consistency gate.

    Gates:
    - 7d: ``pnl_7d > 0`` AND ``roi_7d > 5``
    - 30d: ``pnl_30d > 10000`` AND ``roi_30d > 15``
    - 90d: ``pnl_90d > 50000`` AND ``roi_90d > 30``

    Traders must pass ALL three.

    **Fallback:** If 90d data is ``None`` (new trader), require 7d+30d pass
    and mark as "provisional" (second return value ``True``).

    Returns
    -------
    tuple[bool, bool]
        ``(passes, is_provisional)``
    """
    # Check 7d gate
    pass_7d = (
        pnl_7d is not None
        and roi_7d is not None
        and pnl_7d > 0
        and roi_7d > 5
    )

    # Check 30d gate
    pass_30d = (
        pnl_30d is not None
        and roi_30d is not None
        and pnl_30d > 10_000
        and roi_30d > 15
    )

    # Check 90d gate
    has_90d = roi_90d is not None and pnl_90d is not None
    pass_90d = has_90d and pnl_90d > 50_000 and roi_90d > 30  # type: ignore[operator]

    # All three pass -> full approval
    if pass_7d and pass_30d and pass_90d:
        return True, False

    # Fallback: no 90d data, 7d+30d pass -> provisional
    if not has_90d and pass_7d and pass_30d:
        return True, True

    return False, False


# ===========================================================================
# 3. Trade Metrics Calculators
# ===========================================================================


def compute_trade_metrics(trades: list[dict]) -> dict:
    """Compute trade-derived metrics from a list of trade records.

    Each trade dict has: ``action``, ``closed_pnl``, ``fee_usd``, ``price``,
    ``side``, ``size``, ``timestamp`` (str), ``token_symbol``, ``value_usd``.

    Returns
    -------
    dict
        Keys: ``trade_count``, ``win_rate``, ``profit_factor``,
        ``pseudo_sharpe``, ``avg_hold_hours``, ``trades_per_day``,
        ``most_recent_trade``.
    """
    trade_count = len(trades)

    if trade_count == 0:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "pseudo_sharpe": 0.0,
            "avg_hold_hours": 0.0,
            "trades_per_day": 0.0,
            "most_recent_trade": None,
        }

    # ----- Close / Reduce trades for win rate, profit factor, sharpe -----
    close_reduce_trades = [
        t for t in trades if t.get("action") in ("Close", "Reduce")
    ]

    if not close_reduce_trades:
        win_rate = 0.0
        profit_factor = 0.0
        pseudo_sharpe = 0.0
    else:
        # Win rate
        wins = sum(1 for t in close_reduce_trades if t.get("closed_pnl", 0) > 0)
        win_rate = wins / len(close_reduce_trades)

        # Profit factor
        positive_pnl = sum(
            t.get("closed_pnl", 0)
            for t in close_reduce_trades
            if t.get("closed_pnl", 0) > 0
        )
        negative_pnl = sum(
            t.get("closed_pnl", 0)
            for t in close_reduce_trades
            if t.get("closed_pnl", 0) < 0
        )

        if negative_pnl == 0:
            # No losing trades
            profit_factor = float("inf") if positive_pnl > 0 else 0.0
        else:
            profit_factor = positive_pnl / abs(negative_pnl)

        # Pseudo-Sharpe: mean(returns) / std(returns)
        # where returns = closed_pnl / value_usd
        returns = []
        for t in close_reduce_trades:
            value_usd = t.get("value_usd", 0)
            if value_usd != 0:
                returns.append(t.get("closed_pnl", 0) / value_usd)

        if len(returns) < 2:
            # Cannot compute std with fewer than 2 data points
            pseudo_sharpe = 0.0
        else:
            mean_ret = statistics.mean(returns)
            # Use population stdev for consistency
            std_ret = statistics.pstdev(returns)
            if std_ret == 0:
                pseudo_sharpe = 0.0
            else:
                pseudo_sharpe = mean_ret / std_ret

    # ----- Average hold hours -----
    avg_hold_hours = compute_avg_hold_hours(trades)

    # ----- Trades per day -----
    timestamps = []
    for t in trades:
        try:
            timestamps.append(_parse_timestamp(t["timestamp"]))
        except (KeyError, ValueError, TypeError):
            continue

    if len(timestamps) >= 2:
        timestamps.sort()
        days_span = (timestamps[-1] - timestamps[0]).total_seconds() / 86400
        days_span = max(days_span, 1.0)  # minimum 1 day
        trades_per_day = trade_count / days_span
    else:
        # Single trade or no parseable timestamps -> 1 day minimum
        trades_per_day = float(trade_count)

    # ----- Most recent trade -----
    most_recent_trade: str | None = None
    if timestamps:
        most_recent_dt = max(timestamps)
        most_recent_trade = most_recent_dt.isoformat()

    return {
        "trade_count": trade_count,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "pseudo_sharpe": pseudo_sharpe,
        "avg_hold_hours": avg_hold_hours,
        "trades_per_day": trades_per_day,
        "most_recent_trade": most_recent_trade,
    }


# ===========================================================================
# 4. Hold-Time Pairing Algorithm
# ===========================================================================


def compute_avg_hold_hours(trades: list[dict]) -> float:
    """Pair Open -> Close trades by token to compute average hold time in hours.

    Algorithm:
    - Sort trades by timestamp ASC.
    - For each token, maintain a queue (FIFO) of Open timestamps.
    - When a Close/Reduce trade is encountered, pop the earliest Open for
      that token and compute the duration in hours.
    - Return the average across all pairs.

    If no pairs are found, returns ``0.0``.
    """
    # Parse and sort trades by timestamp
    parsed: list[tuple[datetime, dict]] = []
    for t in trades:
        try:
            dt = _parse_timestamp(t["timestamp"])
            parsed.append((dt, t))
        except (KeyError, ValueError, TypeError):
            continue

    if not parsed:
        return 0.0

    parsed.sort(key=lambda x: x[0])

    # Per-token FIFO queue of Open timestamps
    open_stacks: dict[str, list[datetime]] = defaultdict(list)
    durations_hours: list[float] = []

    for dt, trade in parsed:
        action = trade.get("action", "")
        token = trade.get("token_symbol", "")

        if action == "Open":
            open_stacks[token].append(dt)
        elif action in ("Close", "Reduce"):
            if open_stacks[token]:
                open_dt = open_stacks[token].pop(0)  # FIFO: earliest Open
                duration_hours = (dt - open_dt).total_seconds() / 3600
                durations_hours.append(duration_hours)

    if not durations_hours:
        return 0.0

    return statistics.mean(durations_hours)


# ===========================================================================
# 5. Quality Gate
# ===========================================================================


def passes_quality_gate(
    trade_count: int, win_rate: float, profit_factor: float
) -> bool:
    """Check if a trader passes the quality gate based on trade metrics.

    Requirements:
    - ``trade_count >= MIN_TRADE_COUNT`` (50)
    - ``WIN_RATE_MIN (0.35) <= win_rate <= WIN_RATE_MAX (0.85)``
    - ``profit_factor >= MIN_PROFIT_FACTOR (1.5)`` **OR**
      trend trader exception: ``win_rate < TREND_TRADER_MAX_WR (0.40)``
      AND ``profit_factor >= TREND_TRADER_MIN_PF (2.5)``
    """
    if trade_count < MIN_TRADE_COUNT:
        return False

    if not (WIN_RATE_MIN <= win_rate <= WIN_RATE_MAX):
        return False

    # Standard profit factor check
    if profit_factor >= MIN_PROFIT_FACTOR:
        return True

    # Trend trader exception: low win rate but high profit factor
    if win_rate < TREND_TRADER_MAX_WR and profit_factor >= TREND_TRADER_MIN_PF:
        return True

    return False


# ===========================================================================
# 6. Normalized Component Calculators
# ===========================================================================


def normalize_roi(roi_30d: float) -> float:
    """Normalized ROI score.

    ``NORMALIZED_ROI = min(1.0, max(0, roi_30d / 100))``
    """
    return min(1.0, max(0.0, roi_30d / 100.0))


def normalize_sharpe(pseudo_sharpe: float) -> float:
    """Normalized Sharpe score.

    ``NORMALIZED_SHARPE = min(1.0, max(0, pseudo_sharpe / 3.0))``
    """
    return min(1.0, max(0.0, pseudo_sharpe / 3.0))


def normalize_win_rate(win_rate: float) -> float:
    """Normalized win rate score.

    ``NORMALIZED_WIN_RATE = min(1.0, max(0, (win_rate - 0.35) / (0.85 - 0.35)))``
    """
    return min(1.0, max(0.0, (win_rate - 0.35) / (0.85 - 0.35)))


def compute_consistency_score(
    roi_7d: float, roi_30d: float, roi_90d: float | None
) -> float:
    """Compute consistency score from multi-timeframe ROIs.

    If all three ROIs > 0:
        ``base = 0.7``
        ``weekly_equiv = [roi_7d, roi_30d / 4, roi_90d / 12]``
        ``variance = population_variance(weekly_equiv)``
        ``consistency_bonus = max(0, 0.3 - (variance / 100))``
        ``return base + consistency_bonus``

    Elif at least 2 of 3 > 0:
        ``return 0.5``

    Else:
        ``return 0.2``

    If ``roi_90d`` is ``None``, treat as 0 for the positive-count check.
    """
    roi_90d_val = roi_90d if roi_90d is not None else 0.0

    positive_count = sum(1 for r in [roi_7d, roi_30d, roi_90d_val] if r > 0)

    if positive_count == 3 and roi_90d is not None:
        # All three are > 0 and 90d data is available
        weekly_equiv = [roi_7d, roi_30d / 4.0, roi_90d / 12.0]
        # Population variance: sum((x - mean)^2) / N
        mean_val = sum(weekly_equiv) / len(weekly_equiv)
        variance = sum((x - mean_val) ** 2 for x in weekly_equiv) / len(weekly_equiv)
        consistency_bonus = max(0.0, 0.3 - (variance / 100.0))
        return 0.7 + consistency_bonus
    elif positive_count >= 2:
        return 0.5
    else:
        return 0.2


def compute_smart_money_bonus(label: str) -> float:
    """Smart money bonus based on trader label.

    - ``"Fund"`` in label -> 1.0
    - ``"Smart"`` in label -> 0.8
    - Non-empty label -> 0.5
    - Empty label -> 0.0
    """
    if not label:
        return 0.0
    if "Fund" in label:
        return 1.0
    if "Smart" in label:
        return 0.8
    return 0.5


def compute_risk_mgmt_score(avg_leverage: float | None) -> float:
    """Risk management score based on average leverage.

    - ``avg_leverage <= 3`` -> 1.0
    - ``avg_leverage <= 5`` -> 0.8
    - ``avg_leverage <= 10`` -> 0.5
    - ``avg_leverage <= 20`` -> 0.3
    - else -> 0.1

    **Fallback:** If ``avg_leverage`` is ``None`` (no positions), return 0.5.
    """
    if avg_leverage is None:
        return 0.5

    if avg_leverage <= 3:
        return 1.0
    if avg_leverage <= 5:
        return 0.8
    if avg_leverage <= 10:
        return 0.5
    if avg_leverage <= 20:
        return 0.3
    return 0.1


def compute_recency_decay(most_recent_trade_ts: str | None) -> float:
    """Recency decay based on days since last trade.

    ``days_since_last = (now - most_recent_trade_timestamp).days``
    ``recency_decay = exp(-days_since_last / 30)``

    If no timestamp provided, returns ``0.0`` (no recent activity).
    """
    if most_recent_trade_ts is None:
        return 0.0

    try:
        last_trade_dt = _parse_timestamp(most_recent_trade_ts)
    except (ValueError, TypeError):
        logger.warning(
            "Could not parse most_recent_trade_ts=%r, returning 0.0",
            most_recent_trade_ts,
        )
        return 0.0

    now = datetime.now(timezone.utc)
    days_since_last = (now - last_trade_dt).days
    return math.exp(-days_since_last / 30.0)


# ===========================================================================
# 7. Style Classification (Agent 2)
# ===========================================================================


def classify_style(trades_per_day: float, avg_hold_hours: float) -> str:
    """Classify a trader's style based on trading frequency and hold duration.

    Categories:
    - ``"HFT"``      - High-frequency trader (rejected from universe).
                       trades_per_day > 5 AND avg_hold_hours < 4.
    - ``"SWING"``    - Swing trader (ideal copytrading candidate).
                       trades_per_day >= 0.3 AND avg_hold_hours < 336 (14 days).
    - ``"POSITION"`` - Position trader (acceptable but down-weighted).
                       Everything else.

    Parameters
    ----------
    trades_per_day:
        Average number of trades per day over the analysis window.
    avg_hold_hours:
        Average hold time in hours across all paired Open->Close trades.

    Returns
    -------
    str
        One of ``"HFT"``, ``"SWING"``, or ``"POSITION"``.
    """
    if trades_per_day > 5 and avg_hold_hours < 4:
        return "HFT"
    elif trades_per_day >= 0.3 and avg_hold_hours < 336:
        return "SWING"
    else:
        return "POSITION"


def get_style_multiplier(style: str) -> float:
    """Return the score multiplier for a given trading style.

    - ``"HFT"``      -> 0.0 (excluded from universe)
    - ``"SWING"``    -> 1.0 (ideal)
    - ``"POSITION"`` -> 0.8 (acceptable, slight penalty)

    Parameters
    ----------
    style:
        One of ``"HFT"``, ``"SWING"``, or ``"POSITION"``.

    Returns
    -------
    float
        Score multiplier in [0.0, 1.0].
    """
    _STYLE_MULTIPLIERS = {
        "HFT": 0.0,
        "SWING": 1.0,
        "POSITION": 0.8,
    }
    return _STYLE_MULTIPLIERS.get(style, 0.0)


# ===========================================================================
# 8. Composite Score (Agent 2)
# ===========================================================================


def compute_composite_score(
    normalized_roi: float,
    normalized_sharpe: float,
    normalized_win_rate: float,
    consistency_score: float,
    smart_money_bonus: float,
    risk_mgmt_score: float,
    style_multiplier: float,
    recency_decay: float,
) -> float:
    """Compute the final composite trader score.

    Formula::

        TRADER_SCORE = (
            W_ROI * normalized_roi +
            W_SHARPE * normalized_sharpe +
            W_WIN_RATE * normalized_win_rate +
            W_CONSISTENCY * consistency_score +
            W_SMART_MONEY * smart_money_bonus +
            W_RISK_MGMT * risk_mgmt_score
        ) * style_multiplier * recency_decay

    Weights (from ``snap.config``):
    - ``W_ROI``         = 0.25
    - ``W_SHARPE``      = 0.20
    - ``W_WIN_RATE``    = 0.15
    - ``W_CONSISTENCY`` = 0.20
    - ``W_SMART_MONEY`` = 0.10
    - ``W_RISK_MGMT``   = 0.10

    Parameters
    ----------
    normalized_roi:
        ROI score in [0, 1].
    normalized_sharpe:
        Sharpe score in [0, 1].
    normalized_win_rate:
        Win rate score in [0, 1].
    consistency_score:
        Consistency score in [0, 1].
    smart_money_bonus:
        Smart money bonus in [0, 1].
    risk_mgmt_score:
        Risk management score in [0, 1].
    style_multiplier:
        Style multiplier (0.0 for HFT, 0.8 for POSITION, 1.0 for SWING).
    recency_decay:
        Recency decay factor in [0, 1], based on days since last trade.

    Returns
    -------
    float
        Final composite score, >= 0.
    """
    weighted_sum = (
        W_ROI * normalized_roi
        + W_SHARPE * normalized_sharpe
        + W_WIN_RATE * normalized_win_rate
        + W_CONSISTENCY * consistency_score
        + W_SMART_MONEY * smart_money_bonus
        + W_RISK_MGMT * risk_mgmt_score
    )
    return weighted_sum * style_multiplier * recency_decay


# ===========================================================================
# 9. Score One Trader (Agent 2)
# ===========================================================================


def score_trader(
    roi_7d: float | None,
    roi_30d: float | None,
    roi_90d: float | None,
    pnl_7d: float | None,
    pnl_30d: float | None,
    pnl_90d: float | None,
    account_value: float | None,
    label: str,
    trades: list[dict],
    avg_leverage: float | None,
) -> dict:
    """Score a single trader end-to-end, returning all fields for the trader_scores table.

    Orchestrates the full scoring pipeline:

    1. **Tier-1 filter** -- minimum ROI and account value.
    2. **Consistency gate** -- multi-timeframe ROI/PnL checks (may be provisional).
    3. **Trade metrics** -- win rate, profit factor, pseudo-Sharpe, hold time, etc.
    4. **Quality gate** -- trade count, win rate range, profit factor threshold.
    5. **Style classification** -- HFT / SWING / POSITION with multiplier.
    6. **Normalized components** -- six scoring dimensions scaled to [0, 1].
    7. **Recency decay** -- exponential decay based on days since last trade.
       Provisional traders receive a 0.7x additional penalty on recency.
    8. **Composite score** -- weighted sum * style multiplier * recency decay.
    9. **Eligibility** -- ``passes_tier1 AND passes_consistency AND
       passes_quality AND style != "HFT"``.

    Parameters
    ----------
    roi_7d, roi_30d, roi_90d:
        Return on investment for 7d / 30d / 90d windows (percent).
        May be ``None`` if unavailable.
    pnl_7d, pnl_30d, pnl_90d:
        Absolute PnL in USD for 7d / 30d / 90d windows.
        May be ``None`` if unavailable.
    account_value:
        Trader's account value in USD.  May be ``None``.
    label:
        Nansen label string (e.g. ``"Smart Money"``, ``"Fund"``).
    trades:
        List of trade dicts from the Nansen trades API.
    avg_leverage:
        Average leverage across the trader's current positions.
        May be ``None`` if no positions.

    Returns
    -------
    dict
        All fields needed for the ``trader_scores`` table insertion:
        ``roi_7d``, ``roi_30d``, ``roi_90d``, ``pnl_7d``, ``pnl_30d``,
        ``pnl_90d``, ``win_rate``, ``profit_factor``, ``pseudo_sharpe``,
        ``trade_count``, ``avg_hold_hours``, ``trades_per_day``, ``style``,
        ``normalized_roi``, ``normalized_sharpe``, ``normalized_win_rate``,
        ``consistency_score``, ``smart_money_bonus``, ``risk_mgmt_score``,
        ``style_multiplier``, ``recency_decay``, ``composite_score``,
        ``passes_tier1``, ``passes_quality``, ``is_eligible``.
    """
    # Step 1: Tier-1 filter
    tier1_ok = passes_tier1(roi_30d, account_value)

    # Step 2: Consistency gate
    consistency_ok, is_provisional = passes_consistency_gate(
        roi_7d, roi_30d, roi_90d, pnl_7d, pnl_30d, pnl_90d
    )

    # Step 3: Trade metrics
    metrics = compute_trade_metrics(trades)
    trade_count = metrics["trade_count"]
    win_rate = metrics["win_rate"]
    profit_factor = metrics["profit_factor"]
    pseudo_sharpe = metrics["pseudo_sharpe"]
    avg_hold_hours = metrics["avg_hold_hours"]
    trades_per_day = metrics["trades_per_day"]
    most_recent_trade = metrics["most_recent_trade"]

    # Step 4: Quality gate
    quality_ok = passes_quality_gate(trade_count, win_rate, profit_factor)

    # Step 5: Style classification
    style = classify_style(trades_per_day, avg_hold_hours)
    style_mult = get_style_multiplier(style)

    # Step 6: Normalized components
    norm_roi = normalize_roi(roi_30d if roi_30d is not None else 0.0)
    norm_sharpe = normalize_sharpe(pseudo_sharpe)
    norm_win_rate = normalize_win_rate(win_rate)
    cons_score = compute_consistency_score(
        roi_7d if roi_7d is not None else 0.0,
        roi_30d if roi_30d is not None else 0.0,
        roi_90d,
    )
    sm_bonus = compute_smart_money_bonus(label)
    risk_score = compute_risk_mgmt_score(avg_leverage)

    # Step 7: Recency decay (with 0.7x penalty for provisional traders)
    rec_decay = compute_recency_decay(most_recent_trade)
    if is_provisional:
        rec_decay *= 0.7

    # Step 8: Composite score
    composite = compute_composite_score(
        normalized_roi=norm_roi,
        normalized_sharpe=norm_sharpe,
        normalized_win_rate=norm_win_rate,
        consistency_score=cons_score,
        smart_money_bonus=sm_bonus,
        risk_mgmt_score=risk_score,
        style_multiplier=style_mult,
        recency_decay=rec_decay,
    )

    # Step 9: Eligibility determination
    is_eligible = tier1_ok and consistency_ok and quality_ok and style != "HFT"

    return {
        "roi_7d": roi_7d,
        "roi_30d": roi_30d,
        "roi_90d": roi_90d,
        "pnl_7d": pnl_7d,
        "pnl_30d": pnl_30d,
        "pnl_90d": pnl_90d,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "pseudo_sharpe": pseudo_sharpe,
        "trade_count": trade_count,
        "avg_hold_hours": avg_hold_hours,
        "trades_per_day": trades_per_day,
        "style": style,
        "normalized_roi": norm_roi,
        "normalized_sharpe": norm_sharpe,
        "normalized_win_rate": norm_win_rate,
        "consistency_score": cons_score,
        "smart_money_bonus": sm_bonus,
        "risk_mgmt_score": risk_score,
        "style_multiplier": style_mult,
        "recency_decay": rec_decay,
        "composite_score": composite,
        "passes_tier1": int(tier1_ok),
        "passes_quality": int(quality_ok),
        "is_eligible": int(is_eligible),
    }


# ===========================================================================
# 10. Trader Universe Refresh Orchestrator (Agent 2)
# ===========================================================================


_LEADERBOARD_RANGES = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
}


async def _fetch_and_merge_leaderboard(client) -> dict[str, dict]:
    """Fetch leaderboard data for 3 timeframes and merge by address.

    For each of the 7d, 30d, and 90d windows this function calls
    ``client.get_leaderboard`` (with the standard filters) and merges
    the results by ``trader_address``.

    Returns
    -------
    dict[str, dict]
        Mapping of address -> merged trader record with keys:
        ``address``, ``label``, ``account_value``, ``roi_7d``, ``roi_30d``,
        ``roi_90d``, ``pnl_7d``, ``pnl_30d``, ``pnl_90d``.
    """
    today = datetime.now(timezone.utc).date()
    merged: dict[str, dict] = {}

    for label, days in _LEADERBOARD_RANGES.items():
        date_from = (today - timedelta(days=days)).isoformat()
        date_to = today.isoformat()

        logger.info(
            "Fetching leaderboard range=%s date_from=%s date_to=%s",
            label,
            date_from,
            date_to,
        )

        entries = await client.get_leaderboard(
            date_from=date_from,
            date_to=date_to,
            min_account_value=50_000,
            min_total_pnl=0,
        )

        logger.info("Leaderboard range=%s returned %d entries", label, len(entries))

        for entry in entries:
            addr = entry.get("trader_address", "")
            if not addr:
                continue

            if addr not in merged:
                merged[addr] = {
                    "address": addr,
                    "label": "",
                    "account_value": 0.0,
                    "roi_7d": None,
                    "roi_30d": None,
                    "roi_90d": None,
                    "pnl_7d": None,
                    "pnl_30d": None,
                    "pnl_90d": None,
                }

            trader = merged[addr]
            trader[f"roi_{label}"] = entry.get("roi", 0.0)
            trader[f"pnl_{label}"] = entry.get("total_pnl", 0.0)

            entry_account_value = entry.get("account_value", 0.0)
            if entry_account_value > trader["account_value"]:
                trader["account_value"] = entry_account_value

            entry_label = entry.get("trader_address_label", "")
            if entry_label and not trader["label"]:
                trader["label"] = entry_label

    return merged


async def _fetch_avg_leverage(client, address: str) -> float | None:
    """Fetch current positions for a trader and compute average leverage.

    Returns ``None`` if the trader has no open positions or if the fetch
    fails.

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    address:
        Trader wallet address.

    Returns
    -------
    float | None
        Average leverage across all current positions, or ``None``.
    """
    try:
        data = await client.get_perp_positions(address)
    except Exception:
        logger.warning(
            "Failed to fetch positions for avg_leverage, address=%s",
            address,
            exc_info=True,
        )
        return None

    asset_positions = data.get("asset_positions", [])
    if not asset_positions:
        return None

    leverages: list[float] = []
    for ap in asset_positions:
        pos = ap.get("position", {})
        lev_val = pos.get("leverage_value")
        if lev_val is not None:
            try:
                leverages.append(float(lev_val))
            except (ValueError, TypeError):
                continue

    if not leverages:
        return None

    return sum(leverages) / len(leverages)


async def refresh_trader_universe(client, db_path: str) -> int:
    """Full daily trader refresh orchestrator.

    Performs the complete pipeline for refreshing the scored trader universe:

    1. **Fetch & merge leaderboard** -- Query the Nansen API for 3 timeframes
       (7d, 30d, 90d) and merge by address to get per-timeframe ROI/PnL.
    2. **Upsert traders** -- Store/update addresses, labels, and account values
       in the ``traders`` table.
    3. **Score each trader** -- For each trader that passes tier-1:
       a. Fetch their 90-day trade history via ``client.get_perp_trades``.
       b. Fetch their current positions for average leverage.
       c. Run ``score_trader()`` to compute all metrics and composite score.
       d. Insert score record into the ``trader_scores`` table.
    4. **Log summary** -- Report total eligible traders and top N by score.

    Parameters
    ----------
    client:
        An initialised ``NansenClient`` instance.
    db_path:
        Filesystem path to the SQLite database.

    Returns
    -------
    int
        Count of eligible traders stored (those with ``is_eligible = 1``).
    """
    # ------------------------------------------------------------------
    # Step 1: Fetch and merge leaderboard across 3 timeframes
    # ------------------------------------------------------------------
    merged = await _fetch_and_merge_leaderboard(client)
    logger.info("Merged leaderboard: %d unique traders", len(merged))

    # ------------------------------------------------------------------
    # Step 2: Upsert trader base data into the traders table
    # ------------------------------------------------------------------
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            for trader in merged.values():
                conn.execute(
                    """INSERT OR REPLACE INTO traders
                       (address, label, account_value, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (
                        trader["address"],
                        trader["label"],
                        trader["account_value"],
                        now_utc,
                    ),
                )
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # Step 3: Score each trader
    # ------------------------------------------------------------------
    today = datetime.now(timezone.utc).date()
    date_from_90d = (today - timedelta(days=90)).isoformat()
    date_to = today.isoformat()

    scored_count = 0
    eligible_count = 0

    for addr, trader in merged.items():
        roi_30d = trader.get("roi_30d")
        acct_val = trader.get("account_value")

        # Quick tier-1 pre-check to avoid unnecessary API calls
        if not passes_tier1(roi_30d, acct_val):
            logger.debug(
                "Trader %s failed tier-1 pre-check (roi_30d=%s, account_value=%s), "
                "scoring with defaults",
                addr,
                roi_30d,
                acct_val,
            )
            # Still score them so we have a complete record, but with empty trades
            trades: list[dict] = []
            avg_leverage: float | None = None
        else:
            # Fetch trade history (90 days)
            try:
                trades = await client.get_perp_trades(
                    address=addr,
                    date_from=date_from_90d,
                    date_to=date_to,
                )
            except Exception:
                logger.warning(
                    "Failed to fetch trades for address=%s, using empty list",
                    addr,
                    exc_info=True,
                )
                trades = []

            # Fetch average leverage from current positions
            avg_leverage = await _fetch_avg_leverage(client, addr)

        # Run the scoring pipeline
        score_result = score_trader(
            roi_7d=trader.get("roi_7d"),
            roi_30d=trader.get("roi_30d"),
            roi_90d=trader.get("roi_90d"),
            pnl_7d=trader.get("pnl_7d"),
            pnl_30d=trader.get("pnl_30d"),
            pnl_90d=trader.get("pnl_90d"),
            account_value=acct_val,
            label=trader.get("label", ""),
            trades=trades,
            avg_leverage=avg_leverage,
        )

        # Insert score into trader_scores table
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    """INSERT INTO trader_scores (
                        address, roi_7d, roi_30d, roi_90d,
                        pnl_7d, pnl_30d, pnl_90d,
                        win_rate, profit_factor, pseudo_sharpe, trade_count,
                        avg_hold_hours, trades_per_day, style,
                        normalized_roi, normalized_sharpe, normalized_win_rate,
                        consistency_score, smart_money_bonus, risk_mgmt_score,
                        style_multiplier, recency_decay, composite_score,
                        passes_tier1, passes_quality, is_eligible
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        addr,
                        score_result["roi_7d"],
                        score_result["roi_30d"],
                        score_result["roi_90d"],
                        score_result["pnl_7d"],
                        score_result["pnl_30d"],
                        score_result["pnl_90d"],
                        score_result["win_rate"],
                        score_result["profit_factor"],
                        score_result["pseudo_sharpe"],
                        score_result["trade_count"],
                        score_result["avg_hold_hours"],
                        score_result["trades_per_day"],
                        score_result["style"],
                        score_result["normalized_roi"],
                        score_result["normalized_sharpe"],
                        score_result["normalized_win_rate"],
                        score_result["consistency_score"],
                        score_result["smart_money_bonus"],
                        score_result["risk_mgmt_score"],
                        score_result["style_multiplier"],
                        score_result["recency_decay"],
                        score_result["composite_score"],
                        score_result["passes_tier1"],
                        score_result["passes_quality"],
                        score_result["is_eligible"],
                    ),
                )
        finally:
            conn.close()

        scored_count += 1
        if score_result["is_eligible"]:
            eligible_count += 1

        logger.debug(
            "Scored trader %s: composite=%.4f eligible=%s style=%s",
            addr,
            score_result["composite_score"],
            bool(score_result["is_eligible"]),
            score_result["style"],
        )

    # ------------------------------------------------------------------
    # Step 4: Log summary
    # ------------------------------------------------------------------
    logger.info(
        "Scoring complete: %d traders scored, %d eligible (TOP_N=%d)",
        scored_count,
        eligible_count,
        TOP_N_TRADERS,
    )

    # Log the top N eligible traders by composite score
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT address, composite_score, style, win_rate, pseudo_sharpe
               FROM trader_scores
               WHERE is_eligible = 1
               ORDER BY composite_score DESC
               LIMIT ?""",
            (TOP_N_TRADERS,),
        ).fetchall()

        if rows:
            logger.info("Top %d eligible traders:", min(len(rows), TOP_N_TRADERS))
            for i, row in enumerate(rows, 1):
                logger.info(
                    "  #%d  %s  score=%.4f  style=%s  wr=%.2f  sharpe=%.2f",
                    i,
                    row["address"],
                    row["composite_score"],
                    row["style"],
                    row["win_rate"],
                    row["pseudo_sharpe"],
                )
        else:
            logger.warning("No eligible traders found after scoring!")
    finally:
        conn.close()

    return eligible_count
