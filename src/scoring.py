"""Composite Scoring Engine (Phase 4)

Computes a multi-factor composite score for each tracked trader.  The score
combines six normalised components — ROI, Sharpe, win rate, consistency,
smart-money bonus, and risk management — then applies a style multiplier
and recency decay.  The result feeds into the allocation engine (Phase 6).
"""

from __future__ import annotations

import math
import logging
from typing import Optional

import numpy as np

from src.models import TradeMetrics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

WEIGHTS = {
    "roi": 0.25,
    "sharpe": 0.20,
    "win_rate": 0.15,
    "consistency": 0.20,
    "smart_money": 0.10,
    "risk_mgmt": 0.10,
}

# ---------------------------------------------------------------------------
# Style multipliers
# ---------------------------------------------------------------------------

STYLE_MULTIPLIERS = {
    "SWING": 1.0,      # Ideal for copytrading
    "POSITION": 0.85,  # Good but low frequency
    "HFT": 0.4,        # Too hard to copy
}

# ---------------------------------------------------------------------------
# 4.1  Normalized ROI
# ---------------------------------------------------------------------------


def normalized_roi(roi: float) -> float:
    """Scale ROI to [0, 1].  Cap at 100%."""
    return min(1.0, max(0.0, roi / 100.0))


# ---------------------------------------------------------------------------
# 4.2  Normalized Sharpe
# ---------------------------------------------------------------------------


def normalized_sharpe(pseudo_sharpe: float) -> float:
    """Scale pseudo-Sharpe to [0, 1].  Sharpe of 3.0+ maps to 1.0."""
    return min(1.0, max(0.0, pseudo_sharpe / 3.0))


# ---------------------------------------------------------------------------
# 4.3  Normalized Win Rate
# ---------------------------------------------------------------------------


def normalized_win_rate(win_rate: float) -> float:
    """Scale win rate to [0, 1].  Apply floor at 0.35 and ceiling at 0.85."""
    if win_rate < 0.35 or win_rate > 0.85:
        return 0.0
    return (win_rate - 0.35) / (0.85 - 0.35)


# ---------------------------------------------------------------------------
# 4.4  Consistency Score
# ---------------------------------------------------------------------------


def consistency_score(roi_7d: float, roi_30d: float, roi_90d: float) -> float:
    """Multi-timeframe consistency.

    ``roi_*`` values are percentage returns for each window.
    """
    if roi_7d > 0 and roi_30d > 0 and roi_90d > 0:
        base = 0.7
        # Normalize to weekly rate for variance comparison
        variance = float(np.var([roi_7d, roi_30d / 4, roi_90d / 12]))
        consistency_bonus = max(0.0, 0.3 - (variance / 100.0))
        return base + consistency_bonus
    elif sum([roi_7d > 0, roi_30d > 0, roi_90d > 0]) >= 2:
        return 0.5
    else:
        return 0.2


# ---------------------------------------------------------------------------
# 4.5  Smart Money Bonus
# ---------------------------------------------------------------------------


def smart_money_bonus(label: Optional[str]) -> float:
    """Return a bonus score based on Nansen address label."""
    if not label:
        return 0.0
    label_lower = label.lower()
    if "fund" in label_lower:
        return 1.0
    elif "smart" in label_lower:
        return 0.8
    elif label:
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# 4.6  Risk Management Score
# ---------------------------------------------------------------------------


def risk_management_score(
    avg_leverage: float,
    max_leverage: float,
    uses_isolated: bool,
    max_drawdown_proxy: float,
) -> float:
    """Score trader's risk discipline.

    Lower leverage + isolated margin + smaller drawdowns = higher score.
    """
    leverage_score = max(0.0, 1.0 - (avg_leverage / 20.0))
    margin_score = 1.0 if uses_isolated else 0.5
    drawdown_score = max(0.0, 1.0 - (max_drawdown_proxy / 0.20))

    return leverage_score * 0.4 + margin_score * 0.2 + drawdown_score * 0.4


# ---------------------------------------------------------------------------
# 4.7  Style classification
# ---------------------------------------------------------------------------


def classify_trader_style(trades_per_day: float, avg_hold_hours: float) -> str:
    """Classify a trader as HFT, SWING, or POSITION."""
    if trades_per_day > 5 and avg_hold_hours < 4:
        return "HFT"
    elif trades_per_day >= 0.3 and avg_hold_hours < 336:
        return "SWING"
    else:
        return "POSITION"


# ---------------------------------------------------------------------------
# 4.8  Recency decay
# ---------------------------------------------------------------------------


def recency_decay(hours_since_last_trade: float, half_life_hours: float = 168.0) -> float:
    """Exponential decay with configurable half-life.

    ``half_life_hours=168`` means a 7-day half-life.  A trader who hasn't
    traded in 14 days gets ~0.25x weight.
    """
    return math.exp(-0.693 * hours_since_last_trade / half_life_hours)


# ---------------------------------------------------------------------------
# Position-level helpers (operate on datastore snapshot dicts)
# ---------------------------------------------------------------------------


def avg_leverage_from_positions(positions: list[dict]) -> float:
    """Average leverage across position snapshot dicts."""
    if not positions:
        return 0.0
    leverages = [p.get("leverage_value", 0.0) or 0.0 for p in positions]
    return sum(leverages) / len(leverages)


def max_leverage_from_positions(positions: list[dict]) -> float:
    """Maximum leverage across position snapshot dicts."""
    if not positions:
        return 0.0
    return max((p.get("leverage_value", 0.0) or 0.0 for p in positions), default=0.0)


def any_isolated_margin(positions: list[dict]) -> bool:
    """Return ``True`` if any position uses isolated margin."""
    return any(
        (p.get("leverage_type") or "").lower() == "isolated"
        for p in positions
    )


def estimate_avg_hold_hours(metrics: TradeMetrics) -> float:
    """Rough estimate of average hold duration.

    Uses ``window_days / total_trades`` as a proxy.  This intentionally
    over-estimates so that low-frequency traders are classified as
    POSITION rather than SWING.
    """
    if metrics.total_trades <= 0:
        return 9999.0
    return (metrics.window_days * 24.0) / metrics.total_trades


# ---------------------------------------------------------------------------
# 4.9  Composite score assembly
# ---------------------------------------------------------------------------


def compute_trader_score(
    metrics_7d: TradeMetrics,
    metrics_30d: TradeMetrics,
    metrics_90d: TradeMetrics,
    label: Optional[str],
    positions: list[dict],
    hours_since_last_trade: float,
) -> dict:
    """Full composite score computation.

    Parameters
    ----------
    metrics_7d / metrics_30d / metrics_90d:
        :class:`TradeMetrics` for the three rolling windows.
    label:
        Nansen address label (may be ``None``).
    positions:
        Latest position snapshot dicts from the datastore.
    hours_since_last_trade:
        Hours elapsed since the trader's most recent trade.

    Returns
    -------
    dict
        Keys match the ``_SCORE_FIELDS`` expected by
        :meth:`DataStore.insert_score`.
    """
    m = metrics_30d

    n_roi = normalized_roi(m.roi_proxy)
    n_sharpe = normalized_sharpe(m.pseudo_sharpe)
    n_win_rate = normalized_win_rate(m.win_rate)
    c_score = consistency_score(
        metrics_7d.roi_proxy, metrics_30d.roi_proxy, metrics_90d.roi_proxy
    )
    sm_bonus = smart_money_bonus(label)
    rm_score = risk_management_score(
        avg_leverage=avg_leverage_from_positions(positions),
        max_leverage=max_leverage_from_positions(positions),
        uses_isolated=any_isolated_margin(positions),
        max_drawdown_proxy=m.max_drawdown_proxy,
    )

    raw_composite = (
        WEIGHTS["roi"] * n_roi
        + WEIGHTS["sharpe"] * n_sharpe
        + WEIGHTS["win_rate"] * n_win_rate
        + WEIGHTS["consistency"] * c_score
        + WEIGHTS["smart_money"] * sm_bonus
        + WEIGHTS["risk_mgmt"] * rm_score
    )

    style = classify_trader_style(
        trades_per_day=m.total_trades / max(m.window_days, 1),
        avg_hold_hours=estimate_avg_hold_hours(metrics_30d),
    )
    style_mult = STYLE_MULTIPLIERS[style]

    decay = recency_decay(hours_since_last_trade)

    final_score = raw_composite * style_mult * decay

    # 7d ROI tier multiplier (applied at allocation stage, stored here)
    roi_7d = metrics_7d.roi_proxy
    if roi_7d > 10:
        roi_tier = 1.0
    elif roi_7d >= 0:
        roi_tier = 0.75
    else:
        roi_tier = 0.5

    return {
        "normalized_roi": n_roi,
        "normalized_sharpe": n_sharpe,
        "normalized_win_rate": n_win_rate,
        "consistency_score": c_score,
        "smart_money_bonus": sm_bonus,
        "risk_management_score": rm_score,
        "style_multiplier": style_mult,
        "recency_decay": decay,
        "raw_composite_score": raw_composite,
        "final_score": final_score,
        "roi_tier_multiplier": roi_tier,
        "passes_anti_luck": 1,  # Set by filter gate in Phase 5
    }
