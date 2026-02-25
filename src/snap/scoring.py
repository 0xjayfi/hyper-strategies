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

import asyncio
import logging
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from snap.config import (
    FILTER_PERCENTILE,
    MIN_ACCOUNT_VALUE,
    TOP_N_TRADERS,
    TRADE_CACHE_TTL_HOURS,
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


def passes_tier1(
    roi_30d: float | None,
    account_value: float | None,
    thresholds: dict | None = None,
) -> bool:
    """Check if a trader passes tier-1 filters.

    When *thresholds* is provided, uses dynamic percentile-based cutoffs:
    - ``roi_30d >= thresholds["roi_30d"]``
    - ``account_value >= thresholds["account_value"]``

    Returns ``False`` if either value is ``None``.
    """
    if roi_30d is None or account_value is None:
        return False
    if thresholds is None:
        return True  # no thresholds = no filter
    return (
        roi_30d >= thresholds["roi_30d"]
        and account_value >= thresholds["account_value"]
    )


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
    thresholds: dict | None = None,
) -> tuple[bool, bool]:
    """Check multi-timeframe consistency gate.

    When *thresholds* is provided, uses dynamic percentile-based cutoffs:
    - 7d: ``pnl_7d >= thresholds["pnl_7d"]`` AND ``roi_7d >= thresholds["roi_7d"]``
    - 30d: ``pnl_30d >= thresholds["pnl_30d"]`` AND ``roi_30d >= thresholds["roi_30d"]``
    - 90d: ``pnl_90d >= thresholds["pnl_90d"]`` AND ``roi_90d >= thresholds["roi_90d"]``

    Traders must pass ALL three.

    **Fallback:** If a timeframe's data is ``None``, require the other two
    and mark as "provisional" (second return value ``True``).

    Returns
    -------
    tuple[bool, bool]
        ``(passes, is_provisional)``
    """
    if thresholds is None:
        thresholds = {
            "pnl_7d": 0, "roi_7d": 0,
            "pnl_30d": 0, "roi_30d": 0,
            "pnl_90d": 0, "roi_90d": 0,
        }

    # Check 7d gate
    pass_7d = (
        pnl_7d is not None
        and roi_7d is not None
        and pnl_7d >= thresholds["pnl_7d"]
        and roi_7d >= thresholds["roi_7d"]
    )

    # Check 30d gate
    pass_30d = (
        pnl_30d is not None
        and roi_30d is not None
        and pnl_30d >= thresholds["pnl_30d"]
        and roi_30d >= thresholds["roi_30d"]
    )

    # Check 90d gate
    has_90d = roi_90d is not None and pnl_90d is not None
    pass_90d = (
        has_90d
        and pnl_90d >= thresholds["pnl_90d"]  # type: ignore[operator]
        and roi_90d >= thresholds["roi_90d"]  # type: ignore[operator]
    )

    # All three pass -> full approval
    if pass_7d and pass_30d and pass_90d:
        return True, False

    # Fallback: no 90d data, 7d+30d pass -> provisional
    if not has_90d and pass_7d and pass_30d:
        return True, True

    # Fallback: no 7d data, 30d+90d pass -> provisional
    has_7d = roi_7d is not None and pnl_7d is not None
    if not has_7d and pass_30d and pass_90d:
        return True, True

    # Fallback: only 30d passes and either 7d or 90d missing -> provisional
    if pass_30d and (not has_7d or not has_90d):
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
    trade_count: int,
    win_rate: float,
    profit_factor: float,
    quality_thresholds: dict | None = None,
    *,
    wr_bounds: tuple[float, float] | None = None,
    trend_pf: float | None = None,
    trend_wr: float | None = None,
) -> bool:
    """Check if a trader passes the quality gate based on trade metrics.

    When *quality_thresholds* is provided, uses dynamic cutoffs:
    - ``trade_count >= quality_thresholds["min_trade_count"]``
    - ``quality_thresholds["win_rate_min"] <= win_rate <= quality_thresholds["win_rate_max"]``
    - ``profit_factor >= quality_thresholds["min_profit_factor"]``

    Hard safety bounds ``WIN_RATE_MIN`` / ``WIN_RATE_MAX`` from config are
    always enforced regardless of dynamic thresholds.  Pass *wr_bounds* to
    override the config values (used by the grid search).

    The trend trader exception (low win rate + high PF) still applies.
    Pass *trend_pf* / *trend_wr* to override the config defaults.
    """
    _wr_min = wr_bounds[0] if wr_bounds is not None else WIN_RATE_MIN
    _wr_max = wr_bounds[1] if wr_bounds is not None else WIN_RATE_MAX
    _trend_pf = trend_pf if trend_pf is not None else TREND_TRADER_MIN_PF
    _trend_wr = trend_wr if trend_wr is not None else TREND_TRADER_MAX_WR

    if quality_thresholds is None:
        quality_thresholds = {
            "min_trade_count": 0,
            "min_profit_factor": 0,
            "win_rate_min": _wr_min,
            "win_rate_max": _wr_max,
        }

    if trade_count < quality_thresholds["min_trade_count"]:
        return False

    # Dynamic win rate bounds, clamped by hard safety limits
    wr_lo = max(quality_thresholds["win_rate_min"], _wr_min)
    wr_hi = min(quality_thresholds["win_rate_max"], _wr_max)
    if not (wr_lo <= win_rate <= wr_hi):
        return False

    # Standard profit factor check
    if profit_factor >= quality_thresholds["min_profit_factor"]:
        return True

    # Trend trader exception: low win rate but high profit factor
    if win_rate < _trend_wr and profit_factor >= _trend_pf:
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


def normalize_win_rate(
    win_rate: float,
    *,
    wr_min: float | None = None,
    wr_max: float | None = None,
) -> float:
    """Normalized win rate score.

    ``NORMALIZED_WIN_RATE = min(1.0, max(0, (win_rate - wr_min) / (wr_max - wr_min)))``

    Pass *wr_min* / *wr_max* to override config defaults.
    """
    lo = wr_min if wr_min is not None else WIN_RATE_MIN
    hi = wr_max if wr_max is not None else WIN_RATE_MAX
    denom = hi - lo
    if denom <= 0:
        return 0.0
    return min(1.0, max(0.0, (win_rate - lo) / denom))


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


def classify_style(
    trades_per_day: float,
    avg_hold_hours: float,
    *,
    hft_tpd: float | None = None,
    hft_ahh: float | None = None,
) -> str:
    """Classify a trader's style based on trading frequency and hold duration.

    Categories:
    - ``"HFT"``      - High-frequency trader (rejected from universe).
                       trades_per_day > *hft_tpd* AND avg_hold_hours < *hft_ahh*.
    - ``"SWING"``    - Swing trader (ideal copytrading candidate).
                       trades_per_day >= 0.3 AND avg_hold_hours < 336 (14 days).
    - ``"POSITION"`` - Position trader (acceptable but down-weighted).
                       Everything else.

    Pass *hft_tpd* / *hft_ahh* to override the default HFT thresholds (5 / 4).

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
    _hft_tpd = hft_tpd if hft_tpd is not None else 5.0
    _hft_ahh = hft_ahh if hft_ahh is not None else 4.0

    if trades_per_day > _hft_tpd and avg_hold_hours < _hft_ahh:
        return "HFT"
    elif trades_per_day >= 0.3 and avg_hold_hours < 336:
        return "SWING"
    else:
        return "POSITION"


def get_style_multiplier(style: str, *, position_mult: float | None = None) -> float:
    """Return the score multiplier for a given trading style.

    - ``"HFT"``      -> 0.0 (excluded from universe)
    - ``"SWING"``    -> 1.0 (ideal)
    - ``"POSITION"`` -> *position_mult* (default 0.8, acceptable, slight penalty)

    Pass *position_mult* to override the POSITION multiplier.

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
        "POSITION": position_mult if position_mult is not None else 0.8,
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
    *,
    weights: dict[str, float] | None = None,
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

    Pass *weights* dict with keys ``roi``, ``sharpe``, ``win_rate``,
    ``consistency``, ``smart_money``, ``risk_mgmt`` to override config defaults.

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
    weights:
        Optional dict to override scoring weights.

    Returns
    -------
    float
        Final composite score, >= 0.
    """
    w = weights or {}
    w_roi = w.get("roi", W_ROI)
    w_sharpe = w.get("sharpe", W_SHARPE)
    w_win_rate = w.get("win_rate", W_WIN_RATE)
    w_consistency = w.get("consistency", W_CONSISTENCY)
    w_smart_money = w.get("smart_money", W_SMART_MONEY)
    w_risk_mgmt = w.get("risk_mgmt", W_RISK_MGMT)

    weighted_sum = (
        w_roi * normalized_roi
        + w_sharpe * normalized_sharpe
        + w_win_rate * normalized_win_rate
        + w_consistency * consistency_score
        + w_smart_money * smart_money_bonus
        + w_risk_mgmt * risk_mgmt_score
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
    thresholds: dict | None = None,
    quality_thresholds: dict | None = None,
    *,
    overrides: dict | None = None,
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
    # Unpack overrides
    ovr = overrides or {}
    _wr_bounds = None
    if "WIN_RATE_MIN" in ovr or "WIN_RATE_MAX" in ovr:
        _wr_bounds = (
            ovr.get("WIN_RATE_MIN", WIN_RATE_MIN),
            ovr.get("WIN_RATE_MAX", WIN_RATE_MAX),
        )
    _weights = ovr.get("weights")  # dict or None
    _hft_tpd = ovr.get("hft_tpd")
    _hft_ahh = ovr.get("hft_ahh")
    _position_mult = ovr.get("position_mult")
    _trend_pf = ovr.get("TREND_TRADER_MIN_PF")
    _trend_wr = ovr.get("TREND_TRADER_MAX_WR")

    # Step 1: Tier-1 filter
    tier1_ok = passes_tier1(roi_30d, account_value, thresholds=thresholds)

    # Step 2: Consistency gate
    consistency_ok, is_provisional = passes_consistency_gate(
        roi_7d, roi_30d, roi_90d, pnl_7d, pnl_30d, pnl_90d,
        thresholds=thresholds,
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
    quality_ok = passes_quality_gate(
        trade_count, win_rate, profit_factor,
        quality_thresholds=quality_thresholds,
        wr_bounds=_wr_bounds,
        trend_pf=_trend_pf,
        trend_wr=_trend_wr,
    )

    # Step 5: Style classification
    style = classify_style(
        trades_per_day, avg_hold_hours,
        hft_tpd=_hft_tpd, hft_ahh=_hft_ahh,
    )
    style_mult = get_style_multiplier(style, position_mult=_position_mult)

    # Step 6: Normalized components
    norm_roi = normalize_roi(roi_30d if roi_30d is not None else 0.0)
    norm_sharpe = normalize_sharpe(pseudo_sharpe)
    norm_win_rate = normalize_win_rate(
        win_rate,
        wr_min=_wr_bounds[0] if _wr_bounds else None,
        wr_max=_wr_bounds[1] if _wr_bounds else None,
    )
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
        weights=_weights,
    )

    # Step 9: Eligibility determination
    is_eligible = tier1_ok and consistency_ok and quality_ok and style != "HFT"

    # Step 10: Build diagnostic fail_reason string
    _wr_min_eff = _wr_bounds[0] if _wr_bounds else WIN_RATE_MIN
    _wr_max_eff = _wr_bounds[1] if _wr_bounds else WIN_RATE_MAX
    fail_reasons: list[str] = []
    if not tier1_ok:
        fail_reasons.append("tier1")
    if not consistency_ok:
        fail_reasons.append("consistency")
    if not quality_ok:
        qt = quality_thresholds or {}
        if trade_count < qt.get("min_trade_count", 0):
            fail_reasons.append("quality:trade_count")
        else:
            wr_lo = max(qt.get("win_rate_min", _wr_min_eff), _wr_min_eff)
            wr_hi = min(qt.get("win_rate_max", _wr_max_eff), _wr_max_eff)
            if win_rate < wr_lo:
                fail_reasons.append("quality:wr_low")
            elif win_rate > wr_hi:
                fail_reasons.append("quality:wr_high")
            else:
                fail_reasons.append("quality:profit_factor")
    if style == "HFT":
        fail_reasons.append("style:hft")

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
        "passes_consistency": int(consistency_ok),
        "passes_quality": int(quality_ok),
        "is_eligible": int(is_eligible),
        "fail_reason": ",".join(fail_reasons) if fail_reasons else None,
    }


# ===========================================================================
# 10. Percentile-Based Threshold Computation
# ===========================================================================


def _percentile(vals: list[float], p: float) -> float:
    """Return the *p*-th percentile from a sorted list of values.

    Uses the "nearest rank" method: ``idx = int(len(vals) * p)``.
    Returns ``0.0`` if *vals* is empty.
    """
    if not vals:
        return 0.0
    idx = int(len(vals) * p)
    return vals[min(idx, len(vals) - 1)]


def compute_thresholds(
    merged: dict[str, dict],
    percentile: float = FILTER_PERCENTILE,
) -> dict:
    """Compute dynamic percentile-based thresholds from the merged leaderboard.

    For each metric (roi_7d, roi_30d, roi_90d, pnl_7d, pnl_30d, pnl_90d,
    account_value), collects non-``None`` values from *merged*, sorts them,
    and picks the value at the given percentile.

    Parameters
    ----------
    merged:
        Address-keyed dict of merged leaderboard records.
    percentile:
        Percentile cutoff in [0.0, 1.0]. 0.5 = median.

    Returns
    -------
    dict
        Keys match the fields used by ``passes_tier1`` and
        ``passes_consistency_gate``.
    """
    fields = ["roi_7d", "roi_30d", "roi_90d", "pnl_7d", "pnl_30d", "pnl_90d"]
    thresholds: dict[str, float] = {}

    for field in fields:
        vals = sorted(
            t[field] for t in merged.values() if t.get(field) is not None
        )
        thresholds[field] = _percentile(vals, percentile)

    acct_vals = sorted(t["account_value"] for t in merged.values())
    thresholds["account_value"] = _percentile(acct_vals, percentile)

    return thresholds


def compute_quality_thresholds(
    trade_metrics_list: list[dict],
    percentile: float = FILTER_PERCENTILE,
) -> dict:
    """Compute dynamic quality gate thresholds from fetched trade metrics.

    Called after tier-1 passers have had their trades fetched.  Computes
    percentile-based cutoffs for trade_count, win_rate, and profit_factor.

    Parameters
    ----------
    trade_metrics_list:
        List of dicts from ``compute_trade_metrics()`` — one per trader.
    percentile:
        Percentile cutoff in [0.0, 1.0].

    Returns
    -------
    dict
        Keys: ``min_trade_count``, ``min_profit_factor``,
        ``win_rate_min``, ``win_rate_max``.
    """
    tc_vals = sorted(
        m["trade_count"] for m in trade_metrics_list if m["trade_count"] > 0
    )
    pf_vals = sorted(
        m["profit_factor"]
        for m in trade_metrics_list
        if m["profit_factor"] > 0 and not math.isinf(m["profit_factor"])
    )
    wr_vals = sorted(
        m["win_rate"] for m in trade_metrics_list if m["trade_count"] > 0
    )

    # For win rate, use symmetric bounds around the percentile
    # p25 as lower bound, p75 as upper bound (symmetric around median)
    low_pct = 1.0 - percentile  # e.g. 0.25 when percentile=0.50
    high_pct = percentile + (1.0 - percentile) / 2  # e.g. 0.75

    return {
        "min_trade_count": _percentile(tc_vals, percentile),
        "min_profit_factor": _percentile(pf_vals, percentile),
        "win_rate_min": _percentile(wr_vals, low_pct),
        "win_rate_max": _percentile(wr_vals, high_pct),
    }


# ===========================================================================
# 11. Trade Data Cache Helper
# ===========================================================================


def _get_cached_trades(db_path: str, address: str, ttl_hours: int) -> list[dict] | None:
    """Return cached trades from ``trade_history`` if fresh enough.

    Returns ``None`` if no cached data or if all rows are older than
    *ttl_hours*.
    """
    conn = get_connection(db_path)
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            """SELECT token_symbol, action, side, size, price, value_usd,
                      closed_pnl, fee_usd, timestamp
               FROM trade_history
               WHERE address = ? AND fetched_at >= ?
               ORDER BY timestamp""",
            (address, cutoff),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _cache_trades(db_path: str, address: str, trades: list[dict]) -> None:
    """Store fetched trades into the ``trade_history`` table."""
    if not trades:
        return
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            for t in trades:
                conn.execute(
                    """INSERT OR IGNORE INTO trade_history
                       (address, token_symbol, action, side, size, price,
                        value_usd, closed_pnl, fee_usd, timestamp, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        address,
                        t.get("token_symbol"),
                        t.get("action"),
                        t.get("side"),
                        t.get("size"),
                        t.get("price"),
                        t.get("value_usd"),
                        t.get("closed_pnl"),
                        t.get("fee_usd"),
                        t.get("timestamp"),
                        now_utc,
                    ),
                )
    finally:
        conn.close()


# ===========================================================================
# 12. Cache-Based Scoring (no API calls)
# ===========================================================================


def _read_traders_from_db(db_path: str) -> dict[str, dict]:
    """Read all traders from the ``traders`` table and return as merged dict.

    Returns the same address-keyed dict format that
    ``_fetch_and_merge_leaderboard()`` produces, so downstream scoring
    functions work unchanged.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT address, label, account_value,
                      roi_7d, roi_30d, roi_90d,
                      pnl_7d, pnl_30d, pnl_90d
               FROM traders
               WHERE blacklisted = 0 OR blacklisted IS NULL"""
        ).fetchall()
    finally:
        conn.close()

    merged: dict[str, dict] = {}
    for row in rows:
        addr = row["address"]
        merged[addr] = {
            "address": addr,
            "label": row["label"] or "",
            "account_value": row["account_value"] or 0.0,
            "roi_7d": row["roi_7d"],
            "roi_30d": row["roi_30d"],
            "roi_90d": row["roi_90d"],
            "pnl_7d": row["pnl_7d"],
            "pnl_30d": row["pnl_30d"],
            "pnl_90d": row["pnl_90d"],
        }
    return merged


def _read_trades_from_db(db_path: str, address: str) -> list[dict]:
    """Read all cached trades for *address* from ``trade_history``.

    Unlike ``_get_cached_trades`` this ignores the TTL — it returns
    everything in the table for the address, since the collector is
    responsible for keeping data fresh.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT token_symbol, action, side, size, price, value_usd,
                      closed_pnl, fee_usd, timestamp
               FROM trade_history
               WHERE address = ?
               ORDER BY timestamp""",
            (address,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _backfill_roi_from_trades(db_path: str, merged: dict[str, dict]) -> None:
    """Estimate ROI fields from trade_history when the traders table has NULLs.

    For each trader with ``roi_30d is None``, sums ``closed_pnl`` from
    ``trade_history`` within the 7d/30d/90d windows and divides by
    ``account_value`` to produce an approximate ROI percentage.

    Modifies *merged* in-place.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    cutoffs = {
        "7d": (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "30d": (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "90d": (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    conn = get_connection(db_path)
    try:
        for addr, trader in merged.items():
            if trader.get("roi_30d") is not None:
                continue

            acct_val = trader.get("account_value") or 0.0
            if acct_val <= 0:
                continue

            for label, cutoff in cutoffs.items():
                row = conn.execute(
                    """SELECT COALESCE(SUM(closed_pnl), 0) AS total_pnl
                       FROM trade_history
                       WHERE address = ? AND timestamp >= ?""",
                    (addr, cutoff),
                ).fetchone()
                total_pnl = row["total_pnl"] if row else 0.0
                roi = (total_pnl / acct_val) * 100.0  # as percentage
                trader[f"roi_{label}"] = roi
                trader[f"pnl_{label}"] = total_pnl
    finally:
        conn.close()

    backfilled = sum(
        1 for t in merged.values() if t.get("roi_30d") is not None
    )
    logger.info(
        "Backfilled ROI from trades: %d/%d traders now have roi_30d",
        backfilled,
        len(merged),
    )


def score_from_cache(
    db_path: str,
    overrides: dict | None = None,
    *,
    strategy_db_path: str | None = None,
) -> list[dict]:
    """Score all traders using only cached data from SQLite. No API calls.

    1. Read merged traders from ``traders`` table.
    2. Compute percentile-based tier-1 thresholds from cached population.
    3. Identify tier-1 passers.
    4. Read cached trades from ``trade_history`` table.
    5. Compute trade metrics for tier-1 passers.
    6. Compute quality thresholds from tier-1 metrics.
    7. Score ALL traders -> insert into ``trader_scores``.
    8. Return list of eligible traders sorted by composite_score DESC.

    Parameters
    ----------
    db_path:
        Filesystem path to the data database (reads ``traders`` and
        ``trade_history``).  In single-DB mode this is also used for writes.
    overrides:
        Optional dict of parameter overrides (from grid search variants).
        Same keys as ``refresh_trader_universe``.
    strategy_db_path:
        Optional path to the strategy database where ``trader_scores``
        are written.  When ``None``, falls back to *db_path*.

    Returns
    -------
    list[dict]
        Eligible traders sorted by composite_score descending. Each dict
        contains all ``trader_scores`` fields plus the ``address`` key.
    """
    ovr = overrides or {}
    _percentile_val = ovr.get("FILTER_PERCENTILE", FILTER_PERCENTILE)

    # ------------------------------------------------------------------
    # Step 1: Read traders from cache
    # ------------------------------------------------------------------
    merged = _read_traders_from_db(db_path)
    logger.info("score_from_cache: %d traders read from DB", len(merged))

    if not merged:
        logger.warning("score_from_cache: no traders in DB, nothing to score")
        return []

    # ------------------------------------------------------------------
    # Step 1b: Backfill ROI from trade history when leaderboard ROI is missing
    # ------------------------------------------------------------------
    # Older data DBs may have NULL roi_* fields because the collector
    # didn't store leaderboard ROI at the time.  Estimate ROI from the
    # sum of closed_pnl in trade_history relative to account_value.
    roi_missing = sum(
        1 for t in merged.values() if t.get("roi_30d") is None
    )
    if roi_missing > len(merged) * 0.5:
        logger.info(
            "score_from_cache: %d/%d traders missing roi_30d, backfilling from trade history",
            roi_missing,
            len(merged),
        )
        _backfill_roi_from_trades(db_path, merged)

    # ------------------------------------------------------------------
    # Step 2: Compute dynamic thresholds from the population
    # ------------------------------------------------------------------
    thresholds = compute_thresholds(merged, percentile=_percentile_val)
    logger.info(
        "score_from_cache thresholds (p%.0f): roi_30d=%.4f%% acct=%.0f",
        _percentile_val * 100,
        thresholds["roi_30d"],
        thresholds["account_value"],
    )

    # ------------------------------------------------------------------
    # Step 3: Identify tier-1 passers and load their trades
    # ------------------------------------------------------------------
    tier1_data: dict[str, dict] = {}
    tier1_count = 0

    for addr, trader in merged.items():
        roi_30d = trader.get("roi_30d")
        acct_val = trader.get("account_value")

        if not passes_tier1(roi_30d, acct_val, thresholds=thresholds):
            continue

        tier1_count += 1

        # Read trades from DB (no API call)
        trades = _read_trades_from_db(db_path, addr)
        metrics = compute_trade_metrics(trades)

        tier1_data[addr] = {
            "trades": trades,
            "avg_leverage": None,  # no positions API in cache-only mode
            "metrics": metrics,
        }

    logger.info(
        "score_from_cache: %d tier-1 passers / %d total",
        tier1_count,
        len(merged),
    )

    # ------------------------------------------------------------------
    # Step 4: Compute quality thresholds from tier-1 trade metrics
    # ------------------------------------------------------------------
    all_metrics = [d["metrics"] for d in tier1_data.values()]
    quality_thresholds = compute_quality_thresholds(
        all_metrics, percentile=_percentile_val
    )
    logger.info(
        "score_from_cache quality thresholds (p%.0f): min_trades=%.0f "
        "min_pf=%.2f wr_range=[%.2f, %.2f]",
        _percentile_val * 100,
        quality_thresholds["min_trade_count"],
        quality_thresholds["min_profit_factor"],
        quality_thresholds["win_rate_min"],
        quality_thresholds["win_rate_max"],
    )

    # ------------------------------------------------------------------
    # Step 5: Score ALL traders and insert into trader_scores
    # ------------------------------------------------------------------
    scored_count = 0
    eligible_count = 0
    eligible_traders: list[dict] = []

    conn = get_connection(strategy_db_path or db_path)
    try:
        with conn:
            for addr, trader in merged.items():
                # Use fetched trade data for tier-1 passers, empty for others
                if addr in tier1_data:
                    trades = tier1_data[addr]["trades"]
                    avg_leverage = tier1_data[addr]["avg_leverage"]
                else:
                    trades = []
                    avg_leverage = None

                score_result = score_trader(
                    roi_7d=trader.get("roi_7d"),
                    roi_30d=trader.get("roi_30d"),
                    roi_90d=trader.get("roi_90d"),
                    pnl_7d=trader.get("pnl_7d"),
                    pnl_30d=trader.get("pnl_30d"),
                    pnl_90d=trader.get("pnl_90d"),
                    account_value=trader.get("account_value"),
                    label=trader.get("label", ""),
                    trades=trades,
                    avg_leverage=avg_leverage,
                    thresholds=thresholds,
                    quality_thresholds=quality_thresholds,
                    overrides=overrides,
                )

                conn.execute(
                    """INSERT INTO trader_scores (
                        address, roi_7d, roi_30d, roi_90d,
                        pnl_7d, pnl_30d, pnl_90d,
                        win_rate, profit_factor, pseudo_sharpe, trade_count,
                        avg_hold_hours, trades_per_day, style,
                        normalized_roi, normalized_sharpe, normalized_win_rate,
                        consistency_score, smart_money_bonus, risk_mgmt_score,
                        style_multiplier, recency_decay, composite_score,
                        passes_tier1, passes_consistency, passes_quality,
                        is_eligible, fail_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        score_result["passes_consistency"],
                        score_result["passes_quality"],
                        score_result["is_eligible"],
                        score_result["fail_reason"],
                    ),
                )

                scored_count += 1
                if score_result["is_eligible"]:
                    eligible_count += 1
                    eligible_traders.append({"address": addr, **score_result})
    finally:
        conn.close()

    # Sort eligible traders by composite_score descending
    eligible_traders.sort(key=lambda x: x["composite_score"], reverse=True)

    logger.info(
        "score_from_cache complete: %d scored, %d eligible",
        scored_count,
        eligible_count,
    )

    return eligible_traders


# ===========================================================================
# 13. Trader Universe Refresh Orchestrator (Agent 2)
# ===========================================================================


# Per-timeframe leaderboard config: (days, min_total_pnl).
# 30d/90d thresholds tighten initial screening from ~3000 to ~1500 traders.
_LEADERBOARD_RANGES: dict[str, tuple[int, float]] = {
    "7d": (7, 0),
    "30d": (30, 10_000),
    "90d": (90, 50_000),
}


async def _fetch_and_merge_leaderboard(client) -> dict[str, dict]:
    """Fetch leaderboard data for 3 timeframes and merge by address.

    For each of the 7d, 30d, and 90d windows this function calls
    ``client.get_leaderboard`` (with the standard filters) and merges
    the results by ``trader_address``.

    Filters are tightened per-timeframe to match the consistency gate
    thresholds, dramatically reducing the number of returned traders.

    Returns
    -------
    dict[str, dict]
        Mapping of address -> merged trader record with keys:
        ``address``, ``label``, ``account_value``, ``roi_7d``, ``roi_30d``,
        ``roi_90d``, ``pnl_7d``, ``pnl_30d``, ``pnl_90d``.
    """
    today = datetime.now(timezone.utc).date()
    merged: dict[str, dict] = {}

    for label, (days, min_pnl) in _LEADERBOARD_RANGES.items():
        date_from = (today - timedelta(days=days)).isoformat()
        date_to = today.isoformat()

        logger.info(
            "Fetching leaderboard range=%s date_from=%s date_to=%s min_pnl=%.0f",
            label,
            date_from,
            date_to,
            min_pnl,
        )

        entries = await client.get_leaderboard(
            date_from=date_from,
            date_to=date_to,
            min_account_value=MIN_ACCOUNT_VALUE,
            min_total_pnl=min_pnl,
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


def _data_is_fresh(db_path: str, max_age_hours: float = 24.0) -> bool:
    """Check whether the data DB has traders updated within *max_age_hours*.

    Returns ``True`` if the most recent ``updated_at`` in the ``traders``
    table is less than *max_age_hours* old, meaning collection can be
    skipped.
    """
    from datetime import datetime, timezone

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(updated_at) AS last_update, COUNT(*) AS cnt FROM traders"
        ).fetchone()
    finally:
        conn.close()

    if not row or not row["cnt"]:
        return False

    last_update = row["last_update"]
    if not last_update:
        return False

    try:
        dt = datetime.strptime(last_update, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        logger.info(
            "Data freshness: %d traders, last update %.1fh ago (max %.0fh)",
            row["cnt"],
            age_hours,
            max_age_hours,
        )
        return age_hours < max_age_hours
    except (ValueError, TypeError):
        return False


async def refresh_trader_universe(
    client,
    db_path: str,
    *,
    strategy_db_path: str | None = None,
    overrides: dict | None = None,
    force_collect: bool = False,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> int:
    """Full daily trader refresh orchestrator with percentile-based thresholds.

    Two-phase approach:

    1. **Data collection** — fetch leaderboard + trades from the API and
       persist to SQLite (``traders`` and ``trade_history`` tables).
       Skipped if the data DB already has fresh data (< 24h old) unless
       *force_collect* is ``True``.
    2. **Scoring** — delegate to ``score_from_cache()`` which reads only
       from SQLite.

    If ``collector.py`` is available, data collection is delegated to the
    collector module.  Otherwise, the legacy inline fetch path is used.

    Parameters
    ----------
    strategy_db_path:
        Optional path to the strategy database where ``trader_scores``
        are written.  When ``None``, falls back to *db_path*.
    overrides:
        Optional dict of parameter overrides (from grid search variants).
        Recognised keys: ``FILTER_PERCENTILE``, ``WIN_RATE_MIN``,
        ``WIN_RATE_MAX``, ``TREND_TRADER_MIN_PF``, ``TREND_TRADER_MAX_WR``,
        ``hft_tpd``, ``hft_ahh``, ``position_mult``, ``weights``.
    force_collect:
        When ``True``, always fetch fresh data from the API even if the
        data DB already has recent data.

    Returns
    -------
    int
        Count of eligible traders stored (those with ``is_eligible = 1``).
    """
    ovr = overrides or {}
    _percentile_val = ovr.get("FILTER_PERCENTILE", FILTER_PERCENTILE)

    # ------------------------------------------------------------------
    # Phase A: Data collection — skip if data is fresh enough
    # ------------------------------------------------------------------
    if not force_collect and _data_is_fresh(db_path):
        logger.info("Data is fresh, skipping API collection (use force_collect to override)")
    else:
        # Auto-detect stale trade cache: if most recent fetched_at in
        # trade_history is older than 2x TTL, force a full refetch to
        # avoid silently reusing expired data.
        force_refetch = False
        try:
            conn = get_connection(db_path)
            try:
                row = conn.execute(
                    "SELECT MAX(fetched_at) AS latest FROM trade_history"
                ).fetchone()
            finally:
                conn.close()
            if row and row["latest"]:
                latest_dt = datetime.strptime(
                    row["latest"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
                age_hours = (
                    datetime.now(timezone.utc) - latest_dt
                ).total_seconds() / 3600
                if age_hours > 2 * TRADE_CACHE_TTL_HOURS:
                    force_refetch = True
                    logger.info(
                        "Trade cache is very stale (%.1fh old, threshold=%dh) "
                        "— forcing full refetch",
                        age_hours,
                        2 * TRADE_CACHE_TTL_HOURS,
                    )
        except Exception:
            logger.debug("Could not check trade cache age", exc_info=True)

        try:
            from snap.collector import collect_trader_data  # type: ignore[import-not-found]
            logger.info("Using collector module for data collection")
            await collect_trader_data(
                client, db_path,
                on_progress=on_progress,
                force_refetch=force_refetch,
            )
        except ImportError:
            logger.info("collector module not available, using legacy fetch path")
            await _legacy_collect(client, db_path, percentile=_percentile_val)

    # ------------------------------------------------------------------
    # Phase B: Score from cache (no API calls)
    # ------------------------------------------------------------------
    eligible = score_from_cache(
        db_path, overrides=overrides, strategy_db_path=strategy_db_path
    )
    eligible_count = len(eligible)

    # Log top eligible traders
    if eligible:
        logger.info("Top %d eligible traders:", min(len(eligible), TOP_N_TRADERS))
        for i, t in enumerate(eligible[:TOP_N_TRADERS], 1):
            logger.info(
                "  #%d  %s  score=%.4f  style=%s  wr=%.2f  sharpe=%.2f",
                i,
                t["address"],
                t["composite_score"],
                t["style"],
                t["win_rate"],
                t["pseudo_sharpe"],
            )
    else:
        logger.warning("No eligible traders found after scoring!")

    # --- ML Shadow Mode ---
    # If a trained model exists, compute ML predictions alongside composite scores
    # and log them. This does NOT affect trader selection.
    try:
        from snap.config import ML_TRADER_SELECTION, ML_MODEL_DIR
        from pathlib import Path
        import glob as _glob
        model_files = sorted(_glob.glob(str(Path(ML_MODEL_DIR) / "xgb_trader_*.json")))
        if model_files:
            active_model = model_files[-1]  # latest
            from snap.ml.features import FEATURE_COLUMNS, extract_all_trader_features
            from snap.ml.predict import predict_trader_scores
            from snap.database import get_connection
            import logging
            _ml_logger = logging.getLogger(__name__)
            _ml_logger.info("ML shadow mode: scoring with model %s", active_model)
            data_conn = get_connection(db_path)
            from datetime import datetime
            all_features = extract_all_trader_features(data_conn, datetime.utcnow())
            if all_features:
                predictions = predict_trader_scores(active_model, all_features)
                predictions.sort(key=lambda x: x["ml_predicted_pnl"], reverse=True)
                _ml_logger.info(
                    "ML shadow top-5: %s",
                    [(p["address"][:10], f"{p['ml_predicted_pnl']:+.4f}") for p in predictions[:5]],
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("ML shadow mode failed: %s", e)

    return eligible_count


async def _legacy_collect(
    client,
    db_path: str,
    *,
    percentile: float = FILTER_PERCENTILE,
) -> None:
    """Legacy data collection path: fetch leaderboard + trades inline.

    Persists merged trader data (including roi/pnl) to the ``traders``
    table and trade data to ``trade_history``.  This mirrors the old
    ``refresh_trader_universe`` data-fetching logic and is used when the
    ``collector`` module is not yet available.
    """
    # Fetch and merge leaderboard across 3 timeframes
    merged = await _fetch_and_merge_leaderboard(client)
    logger.info("Legacy collect: merged %d unique traders", len(merged))

    # Upsert trader data (including roi/pnl) into the traders table
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            for trader in merged.values():
                conn.execute(
                    """INSERT OR REPLACE INTO traders
                       (address, label, account_value,
                        roi_7d, roi_30d, roi_90d,
                        pnl_7d, pnl_30d, pnl_90d,
                        updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trader["address"],
                        trader["label"],
                        trader["account_value"],
                        trader.get("roi_7d"),
                        trader.get("roi_30d"),
                        trader.get("roi_90d"),
                        trader.get("pnl_7d"),
                        trader.get("pnl_30d"),
                        trader.get("pnl_90d"),
                        now_utc,
                    ),
                )
    finally:
        conn.close()

    # Compute thresholds to identify tier-1 passers for trade fetching
    thresholds = compute_thresholds(merged, percentile=percentile)

    today = datetime.now(timezone.utc).date()
    date_from_90d = (today - timedelta(days=90)).isoformat()
    date_to = today.isoformat()

    cache_hits = 0
    tier1_count = 0

    for addr, trader in merged.items():
        roi_30d = trader.get("roi_30d")
        acct_val = trader.get("account_value")

        if not passes_tier1(roi_30d, acct_val, thresholds=thresholds):
            continue

        tier1_count += 1

        # Try cache first
        cached = _get_cached_trades(db_path, addr, TRADE_CACHE_TTL_HOURS)
        if cached is not None:
            cache_hits += 1
            continue  # trades already in DB

        try:
            trades = await client.get_perp_trades(
                address=addr,
                date_from=date_from_90d,
                date_to=date_to,
            )
            _cache_trades(db_path, addr, trades)
        except Exception:
            logger.warning(
                "Failed to fetch trades for address=%s, skipping",
                addr,
                exc_info=True,
            )

    logger.info(
        "Legacy collect: %d tier-1 passers, %d cache hits",
        tier1_count,
        cache_hits,
    )
