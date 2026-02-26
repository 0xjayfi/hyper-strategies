"""Position-Based Metrics Engine.

Derives scoring inputs from position snapshot time series.
No API calls — all computation from the position_snapshots DB table.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def detect_deposit_withdrawals(
    series: list[dict],
    threshold_usd: float = 1000.0,
    threshold_pct: float = 0.10,
) -> list[bool]:
    """Flag snapshots where account value change doesn't match PnL change.

    A snapshot is flagged if:
    - |account_value_delta| > threshold_usd AND
    - |account_value_delta| > threshold_pct * prev_account_value AND
    - |account_value_delta - unrealized_pnl_delta| > threshold_usd

    Returns a list of booleans, one per snapshot. Index 0 is always False.
    """
    flags = [False] * len(series)
    if len(series) < 2:
        return flags

    for i in range(1, len(series)):
        prev = series[i - 1]
        curr = series[i]

        prev_av = prev.get("account_value") or 0
        curr_av = curr.get("account_value") or 0
        av_delta = curr_av - prev_av

        prev_upnl = prev.get("total_unrealized_pnl") or 0
        curr_upnl = curr.get("total_unrealized_pnl") or 0
        upnl_delta = curr_upnl - prev_upnl

        # Check if the account value change is large
        if abs(av_delta) <= threshold_usd:
            continue
        if prev_av > 0 and abs(av_delta) <= threshold_pct * prev_av:
            continue

        # Check if PnL explains the change
        unexplained = abs(av_delta - upnl_delta)
        if unexplained > threshold_usd:
            flags[i] = True
            logger.debug(
                "Deposit/withdrawal flagged at %s: av_delta=%.0f, upnl_delta=%.0f",
                curr.get("captured_at", "?"),
                av_delta,
                upnl_delta,
            )

    return flags


def compute_account_growth(
    series: list[dict],
    flags: Optional[list[bool]] = None,
) -> float:
    """Compute account growth as a fraction, excluding deposit/withdrawal events.

    Returns 0.0 if insufficient data.
    """
    if len(series) < 2:
        return 0.0

    if flags is None:
        flags = detect_deposit_withdrawals(series)

    # Build adjusted series: accumulate only non-flagged deltas
    start_value = series[0].get("account_value") or 0
    if start_value <= 0:
        return 0.0

    cumulative_excluded = 0.0
    for i in range(1, len(series)):
        if flags[i]:
            prev_av = series[i - 1].get("account_value") or 0
            curr_av = series[i].get("account_value") or 0
            cumulative_excluded += (curr_av - prev_av)

    end_value = series[-1].get("account_value") or 0
    adjusted_growth = (end_value - start_value - cumulative_excluded) / start_value
    return adjusted_growth


def compute_max_drawdown(
    series: list[dict],
    flags: Optional[list[bool]] = None,
) -> float:
    """Peak-to-trough max drawdown from account value series.

    Excludes flagged deposit/withdrawal snapshots.
    Returns 0.0 if no drawdown or insufficient data.
    """
    if len(series) < 2:
        return 0.0

    if flags is None:
        flags = [False] * len(series)

    peak = 0.0
    max_dd = 0.0

    for i, s in enumerate(series):
        if flags[i]:
            continue
        av = s.get("account_value") or 0
        if av <= 0:
            continue
        if av > peak:
            peak = av
        if peak > 0:
            dd = (peak - av) / peak
            if dd > max_dd:
                max_dd = dd

    return max_dd


def compute_effective_leverage(
    series: list[dict],
) -> tuple[float, float]:
    """Average and std of effective portfolio leverage.

    Effective leverage = total_position_value / account_value per snapshot.
    Returns (avg_leverage, leverage_std).
    """
    leverages = []
    for s in series:
        av = s.get("account_value") or 0
        pv = s.get("total_position_value") or 0
        if av > 0:
            leverages.append(pv / av)

    if not leverages:
        return 0.0, 0.0

    return float(np.mean(leverages)), float(np.std(leverages))


def compute_liquidation_distance(
    snapshots: list[dict],
) -> float:
    """Weighted average distance to liquidation across all position snapshots.

    Distance per position = |entry_price - liquidation_price| / entry_price
    Weighted by position_value_usd.

    Returns 1.0 if no positions have liquidation prices (safest score).
    """
    total_weight = 0.0
    weighted_distance = 0.0

    for s in snapshots:
        entry = s.get("entry_price")
        liq = s.get("liquidation_price")
        pv = s.get("position_value_usd") or 0

        if entry is None or liq is None or entry == 0 or pv <= 0:
            continue

        entry = float(entry)
        liq = float(liq)
        distance = abs(entry - liq) / entry
        weighted_distance += distance * pv
        total_weight += pv

    if total_weight <= 0:
        return 1.0  # No measurable liquidation risk

    return weighted_distance / total_weight


def compute_position_diversity(
    snapshots: list[dict],
) -> float:
    """HHI (Herfindahl-Hirschman Index) across position values.

    Computed per snapshot timestamp, then averaged.
    HHI = sum((value_i / total)^2). 1.0 = single position, lower = more diverse.
    """
    if not snapshots:
        return 1.0

    # Group by captured_at
    by_time: dict[str, list[float]] = {}
    for s in snapshots:
        ts = s.get("captured_at", "")
        pv = s.get("position_value_usd") or 0
        if pv > 0:
            by_time.setdefault(ts, []).append(pv)

    if not by_time:
        return 1.0

    hhis = []
    for values in by_time.values():
        total = sum(values)
        if total <= 0:
            continue
        hhi = sum((v / total) ** 2 for v in values)
        hhis.append(hhi)

    return float(np.mean(hhis)) if hhis else 1.0


def compute_consistency(
    series: list[dict],
    flags: Optional[list[bool]] = None,
) -> float:
    """Sharpe-like consistency ratio from daily account value deltas.

    consistency = mean(deltas) / std(deltas) if std > 0.
    Excludes flagged deposit/withdrawal snapshots.
    Returns 0.0 if insufficient data.
    """
    if len(series) < 3:
        return 0.0

    if flags is None:
        flags = [False] * len(series)

    deltas = []
    for i in range(1, len(series)):
        if flags[i] or flags[i - 1]:
            continue
        prev_av = series[i - 1].get("account_value") or 0
        curr_av = series[i].get("account_value") or 0
        if prev_av > 0:
            deltas.append((curr_av - prev_av) / prev_av)

    if len(deltas) < 2:
        return 0.0

    mean_delta = float(np.mean(deltas))
    std_delta = float(np.std(deltas))

    if std_delta <= 0:
        return 1.0 if mean_delta > 0 else 0.0

    return mean_delta / std_delta


def compute_position_metrics(
    account_series: list[dict],
    position_snapshots: list[dict],
) -> dict:
    """Full position-based metrics pipeline.

    Parameters
    ----------
    account_series:
        Output of DataStore.get_account_value_series() — one row per
        snapshot timestamp with account_value, total_position_value,
        total_unrealized_pnl, position_count.
    position_snapshots:
        Output of DataStore.get_position_snapshot_series() — all
        individual position rows.

    Returns
    -------
    dict with keys: account_growth, max_drawdown, avg_leverage, leverage_std,
    avg_liquidation_distance, avg_hhi, consistency, deposit_withdrawal_count,
    snapshot_count.
    """
    flags = detect_deposit_withdrawals(account_series)

    growth = compute_account_growth(account_series, flags)
    drawdown = compute_max_drawdown(account_series, flags)
    avg_lev, lev_std = compute_effective_leverage(account_series)
    liq_dist = compute_liquidation_distance(position_snapshots)
    hhi = compute_position_diversity(position_snapshots)
    consistency = compute_consistency(account_series, flags)

    return {
        "account_growth": growth,
        "max_drawdown": drawdown,
        "avg_leverage": avg_lev,
        "leverage_std": lev_std,
        "avg_liquidation_distance": liq_dist,
        "avg_hhi": hhi,
        "consistency": consistency,
        "deposit_withdrawal_count": sum(flags),
        "snapshot_count": len(account_series),
    }
