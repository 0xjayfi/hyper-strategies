"""Position-Based Scoring Engine.

6-component composite score derived entirely from position snapshot metrics.
Replaces the trade-based scoring for the scheduler's allocation pipeline.
"""

from __future__ import annotations

import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# --- Weights ---

POSITION_SCORE_WEIGHTS = {
    "account_growth": 0.30,
    "drawdown": 0.20,
    "leverage": 0.15,
    "liquidation_distance": 0.15,
    "diversity": 0.10,
    "consistency": 0.10,
}


# --- Normalization functions ---

def normalize_account_growth(growth: float) -> float:
    """Normalize account growth to [0, 1]. 10%+ monthly = 1.0."""
    return min(1.0, max(0.0, growth / 0.10))


def normalize_drawdown(drawdown: float) -> float:
    """Normalize max drawdown to [0, 1]. 0% = 1.0, 50%+ = 0.0."""
    return max(0.0, 1.0 - drawdown / 0.50)


def normalize_leverage(avg_leverage: float, leverage_std: float) -> float:
    """Normalize leverage to [0, 1]. Low and consistent = high score."""
    base = max(0.0, 1.0 - avg_leverage / 20.0)
    # Penalize high variance
    volatility_penalty = min(0.2, leverage_std / 25.0)
    return max(0.0, base - volatility_penalty)


def normalize_liquidation_distance(distance: float) -> float:
    """Normalize liquidation distance to [0, 1]. 30%+ = 1.0, <5% = 0.0."""
    if distance >= 0.30:
        return 1.0
    if distance <= 0.05:
        return 0.0
    return (distance - 0.05) / 0.25


def normalize_diversity(hhi: float) -> float:
    """Normalize HHI to [0, 1]. HHI < 0.25 = 1.0, HHI = 1.0 = 0.2."""
    if hhi <= 0.25:
        return 1.0
    # Linear interpolation: 0.25 -> 1.0, 1.0 -> 0.2
    return max(0.2, 1.0 - (hhi - 0.25) / 0.75 * 0.8)


def normalize_consistency(ratio: float) -> float:
    """Normalize consistency (Sharpe-like ratio) to [0, 1]. >= 1.0 = 1.0."""
    return min(1.0, max(0.0, ratio))


# --- Smart money bonus (reused from trade-based scoring) ---

def _smart_money_bonus(label: Optional[str]) -> float:
    """Return a multiplier based on Nansen address label."""
    if not label:
        return 1.0
    label_lower = label.lower()
    if "fund" in label_lower:
        return 1.10
    elif "smart" in label_lower:
        return 1.08
    elif label:
        return 1.05
    return 1.0


# --- Recency decay ---

def _recency_decay(hours_since_last_snapshot: float, half_life: float = 168.0) -> float:
    """Exponential decay based on hours since last active snapshot."""
    return math.exp(-0.693 * hours_since_last_snapshot / half_life)


# --- Composite score ---

def compute_position_score(
    metrics: dict,
    label: Optional[str] = None,
    hours_since_last_snapshot: float = 0.0,
) -> dict:
    """Compute 6-component position-based composite score.

    Parameters
    ----------
    metrics:
        Output of position_metrics.compute_position_metrics().
    label:
        Nansen address label (for smart money bonus).
    hours_since_last_snapshot:
        Hours since the trader's latest snapshot with open positions.

    Returns
    -------
    dict with individual component scores + final_score.
    """
    w = POSITION_SCORE_WEIGHTS

    ag = normalize_account_growth(metrics.get("account_growth", 0.0))
    dd = normalize_drawdown(metrics.get("max_drawdown", 0.0))
    lev = normalize_leverage(
        metrics.get("avg_leverage", 0.0),
        metrics.get("leverage_std", 0.0),
    )
    liq = normalize_liquidation_distance(
        metrics.get("avg_liquidation_distance", 1.0),
    )
    div = normalize_diversity(metrics.get("avg_hhi", 1.0))
    con = normalize_consistency(metrics.get("consistency", 0.0))

    raw = (
        w["account_growth"] * ag
        + w["drawdown"] * dd
        + w["leverage"] * lev
        + w["liquidation_distance"] * liq
        + w["diversity"] * div
        + w["consistency"] * con
    )

    sm = _smart_money_bonus(label)
    decay = _recency_decay(hours_since_last_snapshot)

    final = raw * sm * decay

    return {
        "account_growth_score": ag,
        "drawdown_score": dd,
        "leverage_score": lev,
        "liquidation_distance_score": liq,
        "diversity_score": div,
        "consistency_score": con,
        "smart_money_bonus": sm,
        "recency_decay": decay,
        "raw_composite_score": raw,
        "final_score": final,
    }
