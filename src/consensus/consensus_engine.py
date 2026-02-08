"""Core consensus computation with freshness weighting and cluster dedup."""

from __future__ import annotations

import math
from datetime import datetime

from consensus.config import StrategyConfig
from consensus.models import (
    ConsensusSide,
    InferredPosition,
    TokenConsensus,
    TrackedTrader,
)


def compute_token_consensus(
    token: str,
    positions: list[InferredPosition],
    traders: dict[str, TrackedTrader],
    config: StrategyConfig,
    now: datetime,
) -> TokenConsensus:
    """Compute consensus for a single token across all tracked traders.

    Applies freshness decay, size threshold filtering, position weight
    filtering, blacklist exclusion, and cluster-aware counting (one vote
    per ``cluster_id``).
    """
    size_threshold = config.SIZE_THRESHOLDS.get(
        token, config.SIZE_THRESHOLDS["_default"]
    )

    long_traders: set[str] = set()
    short_traders: set[str] = set()
    long_volume = 0.0
    short_volume = 0.0
    weighted_long_vol = 0.0
    weighted_short_vol = 0.0
    long_clusters: set[int] = set()
    short_clusters: set[int] = set()

    for pos in positions:
        # Filter: size threshold
        if pos.current_value_usd < size_threshold:
            continue

        # Filter: position weight must be meaningful
        if pos.position_weight < config.MIN_POSITION_WEIGHT:
            continue

        trader = traders.get(pos.trader_address)
        if trader is None:
            continue

        # Skip blacklisted traders
        if trader.blacklisted_until and now < trader.blacklisted_until:
            continue

        # Freshness decay: e^(-hours / half_life)
        hours_since_action = (now - pos.last_action_at).total_seconds() / 3600
        freshness = math.exp(-hours_since_action / config.FRESHNESS_HALF_LIFE_HOURS)

        # Weighted volume = position_value * freshness * trader_score
        weighted_value = pos.current_value_usd * freshness * trader.score

        if pos.side == "Long":
            long_traders.add(pos.trader_address)
            long_volume += pos.current_value_usd
            weighted_long_vol += weighted_value
            long_clusters.add(trader.cluster_id)
        elif pos.side == "Short":
            short_traders.add(pos.trader_address)
            short_volume += pos.current_value_usd
            weighted_short_vol += weighted_value
            short_clusters.add(trader.cluster_id)

    # Consensus determination (use cluster count, not raw trader count)
    if (
        len(long_clusters) >= config.MIN_CONSENSUS_TRADERS
        and weighted_long_vol > config.VOLUME_DOMINANCE_RATIO * weighted_short_vol
    ):
        consensus = ConsensusSide.STRONG_LONG
    elif (
        len(short_clusters) >= config.MIN_CONSENSUS_TRADERS
        and weighted_short_vol > config.VOLUME_DOMINANCE_RATIO * weighted_long_vol
    ):
        consensus = ConsensusSide.STRONG_SHORT
    else:
        consensus = ConsensusSide.MIXED

    return TokenConsensus(
        token_symbol=token,
        timestamp=now,
        long_traders=long_traders,
        short_traders=short_traders,
        long_volume_usd=long_volume,
        short_volume_usd=short_volume,
        weighted_long_volume=weighted_long_vol,
        weighted_short_volume=weighted_short_vol,
        consensus=consensus,
        long_cluster_count=len(long_clusters),
        short_cluster_count=len(short_clusters),
    )


def compute_all_tokens_consensus(
    positions_by_token: dict[str, list[InferredPosition]],
    traders: dict[str, TrackedTrader],
    config: StrategyConfig,
    now: datetime | None = None,
) -> dict[str, TokenConsensus]:
    """Compute consensus for every token that has at least one position.

    Returns a mapping of ``token_symbol -> TokenConsensus``.
    """
    if now is None:
        now = datetime.utcnow()

    results: dict[str, TokenConsensus] = {}
    for token, positions in positions_by_token.items():
        results[token] = compute_token_consensus(
            token, positions, traders, config, now
        )
    return results
