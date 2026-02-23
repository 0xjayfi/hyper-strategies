"""Allocation Engine (Phase 6)

Converts composite trader scores into normalised allocation weights via a
pipeline of softmax → ROI-tier adjustment → risk caps → turnover limits.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from src.config import (
    MAX_SINGLE_WEIGHT,
    MAX_TOTAL_POSITIONS,
    MAX_WEIGHT_CHANGE_PER_DAY,
    SOFTMAX_TEMPERATURE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk configuration
# ---------------------------------------------------------------------------


@dataclass
class RiskConfig:
    """Hard risk constraints for the allocation engine."""

    max_total_open_usd: float       # account_value * 0.50
    max_total_positions: int = MAX_TOTAL_POSITIONS
    max_exposure_per_token: float = 0.15  # 15% of account per token
    max_long_exposure: float = 0.60
    max_short_exposure: float = 0.60


# ---------------------------------------------------------------------------
# 6.1  Score-to-weight conversion: softmax
# ---------------------------------------------------------------------------


def scores_to_weights_softmax(
    scores: dict[str, float],
    temperature: float = SOFTMAX_TEMPERATURE,
) -> dict[str, float]:
    """Convert ``{trader_address: final_score}`` into allocation weights via softmax.

    Parameters
    ----------
    scores:
        Mapping of trader address to final composite score.
    temperature:
        Controls concentration.  ``T=2.0`` (default) gives a smooth
        distribution; ``T=0.5`` is aggressive winner-takes-all.
    """
    if not scores:
        return {}

    addresses = list(scores.keys())
    vals = np.array([scores[a] for a in addresses])

    scaled = vals / temperature
    scaled -= scaled.max()  # numerical stability
    exp_vals = np.exp(scaled)
    weights = exp_vals / exp_vals.sum()

    return {addr: float(w) for addr, w in zip(addresses, weights)}


# ---------------------------------------------------------------------------
# 6.2  Apply ROI tier multiplier
# ---------------------------------------------------------------------------


def apply_roi_tier(
    weights: dict[str, float],
    tier_multipliers: dict[str, float],
) -> dict[str, float]:
    """Multiply each weight by the trader's 7d ROI tier, then renormalise.

    Tier values are typically 1.0 / 0.75 / 0.5.
    """
    adjusted = {
        addr: w * tier_multipliers.get(addr, 0.5)
        for addr, w in weights.items()
    }

    # Remove traders with zero effective weight
    adjusted = {a: w for a, w in adjusted.items() if w > 0}

    total = sum(adjusted.values())
    if total == 0:
        return {}
    return {a: w / total for a, w in adjusted.items()}


# ---------------------------------------------------------------------------
# 6.3  Apply risk caps
# ---------------------------------------------------------------------------


def apply_risk_caps(
    weights: dict[str, float],
    trader_positions: dict[str, list],
    config: RiskConfig,
) -> dict[str, float]:
    """Enforce hard position and weight caps, then renormalise.

    1. Keep top *N* traders by weight.
    2. Cap any single trader at ``MAX_SINGLE_WEIGHT`` (40%).
    3. Renormalise so weights sum to 1.
    """
    # 1. Keep top N by weight
    sorted_traders = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_traders) > config.max_total_positions:
        sorted_traders = sorted_traders[: config.max_total_positions]

    capped = dict(sorted_traders)

    # 2. Cap individual weights
    for addr in capped:
        capped[addr] = min(capped[addr], MAX_SINGLE_WEIGHT)

    # 3. Renormalise
    total = sum(capped.values())
    if total > 0:
        capped = {a: w / total for a, w in capped.items()}

    return capped


# ---------------------------------------------------------------------------
# 6.4  Performance-chasing guardrails
# ---------------------------------------------------------------------------


def apply_turnover_limits(
    new_weights: dict[str, float],
    old_weights: dict[str, float],
) -> dict[str, float]:
    """Limit daily allocation changes to prevent performance-chasing whipsaws.

    Each trader's weight may change by at most ``MAX_WEIGHT_CHANGE_PER_DAY``
    (15 pp) per rebalance.
    """
    result: dict[str, float] = {}
    # Only consider addresses in new_weights (post risk-cap).  Addresses
    # removed by apply_risk_caps must NOT be re-introduced here.
    all_addrs = set(new_weights.keys())

    for addr in all_addrs:
        new_w = new_weights.get(addr, 0.0)
        old_w = old_weights.get(addr, 0.0)

        delta = new_w - old_w
        if abs(delta) > MAX_WEIGHT_CHANGE_PER_DAY:
            clamped_delta = (
                MAX_WEIGHT_CHANGE_PER_DAY if delta > 0 else -MAX_WEIGHT_CHANGE_PER_DAY
            )
            result[addr] = old_w + clamped_delta
        else:
            result[addr] = new_w

    # Remove zero / negligible weights, renormalise
    result = {a: w for a, w in result.items() if w > 0.001}
    total = sum(result.values())
    if total > 0:
        result = {a: w / total for a, w in result.items()}

    return result


# ---------------------------------------------------------------------------
# 6.5  Full allocation pipeline
# ---------------------------------------------------------------------------


def compute_allocations(
    eligible_traders: list[str],
    scores: dict[str, dict],
    old_allocations: dict[str, float],
    trader_positions: dict[str, list],
    risk_config: RiskConfig,
    softmax_temperature: float = SOFTMAX_TEMPERATURE,
) -> dict[str, float]:
    """End-to-end allocation computation.

    Parameters
    ----------
    eligible_traders:
        Addresses that passed all filters.
    scores:
        ``{address: score_dict}`` where each *score_dict* contains
        ``"final_score"`` and ``"roi_tier_multiplier"`` keys.
    old_allocations:
        Previous ``{address: weight}`` for turnover limiting.
    trader_positions:
        ``{address: [position_dicts]}`` for risk-cap checks.
    risk_config:
        Hard risk constraints.
    softmax_temperature:
        Softmax temperature (default from config).

    Returns
    -------
    dict[str, float]
        ``{address: final_weight}`` summing to 1.0 (or empty).
    """
    # 1. Build score dict for eligible traders only
    score_map = {
        addr: scores[addr]["final_score"]
        for addr in eligible_traders
        if addr in scores and scores[addr]["final_score"] > 0
    }

    if not score_map:
        return {}

    # 2. Softmax → raw weights
    weights = scores_to_weights_softmax(score_map, temperature=softmax_temperature)

    # 3. Apply 7d ROI tier multiplier
    tier_map = {addr: scores[addr]["roi_tier_multiplier"] for addr in weights}
    weights = apply_roi_tier(weights, tier_map)

    # 4. Apply risk caps
    weights = apply_risk_caps(weights, trader_positions, risk_config)

    # 5. Apply turnover limits
    weights = apply_turnover_limits(weights, old_allocations)

    logger.info(
        "Allocations computed: %d traders, top weight=%.2f",
        len(weights),
        max(weights.values()) if weights else 0.0,
    )

    return weights
