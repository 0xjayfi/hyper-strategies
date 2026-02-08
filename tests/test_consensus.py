"""Tests for consensus engine."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from consensus.config import StrategyConfig
from consensus.models import (
    ConsensusSide,
    InferredPosition,
    SignalStrength,
    TokenConsensus,
    TrackedTrader,
    TraderStyle,
)
from consensus.consensus_engine import (
    compute_all_tokens_consensus,
    compute_token_consensus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _trader(
    address: str,
    cluster_id: int = 0,
    score: float = 0.8,
    blacklisted_until: datetime | None = None,
) -> TrackedTrader:
    return TrackedTrader(
        address=address,
        label="Whale",
        score=score,
        style=TraderStyle.SWING,
        cluster_id=cluster_id,
        account_value_usd=500_000,
        roi_7d=10.0,
        roi_30d=20.0,
        roi_90d=50.0,
        trade_count=100,
        last_scored_at=NOW,
        blacklisted_until=blacklisted_until,
    )


def _position(
    trader_address: str,
    token: str = "BTC",
    side: str = "Long",
    value_usd: float = 100_000,
    position_weight: float = 0.20,
    last_action_at: datetime | None = None,
) -> InferredPosition:
    return InferredPosition(
        trader_address=trader_address,
        token_symbol=token,
        side=side,
        entry_price_usd=50_000.0,
        current_value_usd=value_usd,
        size=value_usd / 50_000,
        leverage_value=3,
        leverage_type="isolated",
        liquidation_price_usd=40_000.0,
        unrealized_pnl_usd=500.0,
        position_weight=position_weight,
        signal_strength=SignalStrength.HIGH,
        first_open_at=NOW - timedelta(hours=2),
        last_action_at=last_action_at or NOW - timedelta(hours=1),
        freshness_weight=1.0,
    )


# ===========================================================================
# compute_token_consensus
# ===========================================================================


class TestComputeTokenConsensus:

    def test_strong_long_three_clusters(self, config: StrategyConfig) -> None:
        """3 traders in 3 different clusters all long BTC with no shorts
        => STRONG_LONG."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        positions = [
            _position(f"0x{i}", token="BTC", side="Long") for i in range(3)
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.STRONG_LONG
        assert result.long_cluster_count == 3
        assert result.short_cluster_count == 0
        assert len(result.long_traders) == 3
        assert result.long_volume_usd == pytest.approx(300_000)

    def test_strong_short(self, config: StrategyConfig) -> None:
        """3 traders short with dominant volume => STRONG_SHORT."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        positions = [
            _position(f"0x{i}", token="ETH", side="Short", value_usd=50_000)
            for i in range(3)
        ]
        result = compute_token_consensus("ETH", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.STRONG_SHORT
        assert result.short_cluster_count == 3

    def test_mixed_two_vs_two(self, config: StrategyConfig) -> None:
        """2 long, 2 short with equal volume => MIXED."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(4)
        }
        positions = [
            _position("0x0", side="Long"),
            _position("0x1", side="Long"),
            _position("0x2", side="Short"),
            _position("0x3", side="Short"),
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.MIXED

    def test_same_cluster_not_strong(self, config: StrategyConfig) -> None:
        """3 traders all in cluster 0 => only 1 unique cluster => NOT strong
        even though 3 raw traders agree."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=0) for i in range(3)
        }
        positions = [
            _position(f"0x{i}", side="Long") for i in range(3)
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.MIXED
        assert result.long_cluster_count == 1
        assert len(result.long_traders) == 3  # raw count still 3

    def test_stale_positions_freshness_decay(self, config: StrategyConfig) -> None:
        """Positions opened 48h ago => freshness near zero => weighted volume
        too low for STRONG even with 3 clusters.

        freshness = e^(-48/4) = e^(-12) ~ 6.1e-6
        weighted_vol = 100_000 * 6.1e-6 * 0.8 ~ 0.49 per trader
        With 3 traders: ~1.47 total, which won't dominate anything.
        """
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        stale_time = NOW - timedelta(hours=48)
        positions = [
            _position(f"0x{i}", side="Long", last_action_at=stale_time)
            for i in range(3)
        ]
        # Add one small short so that dominance ratio check matters
        traders["0x9"] = _trader("0x9", cluster_id=9)
        positions.append(
            _position("0x9", side="Short", value_usd=60_000, last_action_at=NOW)
        )

        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        # Stale longs can't dominate fresh short
        assert result.consensus == ConsensusSide.MIXED

    def test_position_weight_below_threshold_filtered(
        self, config: StrategyConfig
    ) -> None:
        """Positions with weight < MIN_POSITION_WEIGHT (10%) are excluded."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        # All positions have 5% weight (below 10% threshold)
        positions = [
            _position(f"0x{i}", side="Long", position_weight=0.05)
            for i in range(3)
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.MIXED
        assert len(result.long_traders) == 0
        assert result.long_volume_usd == 0.0

    def test_size_threshold_filters_small_positions(
        self, config: StrategyConfig
    ) -> None:
        """BTC positions below $50K size threshold are excluded."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        # $30K each — below BTC's $50K threshold
        positions = [
            _position(f"0x{i}", token="BTC", side="Long", value_usd=30_000)
            for i in range(3)
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.MIXED
        assert len(result.long_traders) == 0

    def test_default_size_threshold_for_unknown_token(
        self, config: StrategyConfig
    ) -> None:
        """Unknown token uses _default threshold ($5K)."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        positions = [
            _position(f"0x{i}", token="DOGE", side="Long", value_usd=10_000)
            for i in range(3)
        ]
        result = compute_token_consensus("DOGE", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.STRONG_LONG

    def test_blacklisted_trader_excluded(self, config: StrategyConfig) -> None:
        """Blacklisted trader's position is ignored."""
        traders = {
            "0x0": _trader("0x0", cluster_id=0),
            "0x1": _trader("0x1", cluster_id=1),
            "0x2": _trader(
                "0x2", cluster_id=2,
                blacklisted_until=NOW + timedelta(days=7),
            ),
        }
        positions = [
            _position("0x0", side="Long"),
            _position("0x1", side="Long"),
            _position("0x2", side="Long"),  # blacklisted — should be ignored
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        # Only 2 clusters pass => below MIN_CONSENSUS_TRADERS (3)
        assert result.consensus == ConsensusSide.MIXED
        assert result.long_cluster_count == 2

    def test_volume_dominance_ratio(self, config: StrategyConfig) -> None:
        """Long volume must be > 2x short volume for STRONG_LONG.

        3 clusters long at $100K each = $300K weighted.
        1 cluster short at $100K = $100K weighted.
        With equal freshness and score:
          long weighted ~= 300K * 0.78 * 0.8 = 187.2K
          short weighted ~= 100K * 0.78 * 0.8 = 62.4K
          ratio: 187.2 / 62.4 = 3.0 > 2.0 => STRONG_LONG
        """
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(4)
        }
        positions = [
            _position("0x0", side="Long"),
            _position("0x1", side="Long"),
            _position("0x2", side="Long"),
            _position("0x3", side="Short"),
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.STRONG_LONG

    def test_volume_dominance_ratio_not_met(self, config: StrategyConfig) -> None:
        """3 long clusters but short volume is >50% of long => MIXED.

        3 long at $60K each = $180K, 1 short at $150K.
        weighted long ~= 180K * f * s, weighted short ~= 150K * f * s.
        ratio: 180/150 = 1.2 < 2.0 => MIXED.
        """
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(4)
        }
        positions = [
            _position("0x0", side="Long", value_usd=60_000),
            _position("0x1", side="Long", value_usd=60_000),
            _position("0x2", side="Long", value_usd=60_000),
            _position("0x3", side="Short", value_usd=150_000),
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert result.consensus == ConsensusSide.MIXED

    def test_freshness_weight_calculation(self, config: StrategyConfig) -> None:
        """Verify that freshness decay is applied correctly to weighted volume."""
        traders = {"0x0": _trader("0x0", cluster_id=0)}
        hours_ago = 4.0  # one half-life
        expected_freshness = math.exp(-hours_ago / config.FRESHNESS_HALF_LIFE_HOURS)

        positions = [
            _position(
                "0x0", side="Long", value_usd=100_000,
                last_action_at=NOW - timedelta(hours=hours_ago),
            )
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        expected_weighted = 100_000 * expected_freshness * 0.8  # score=0.8
        assert result.weighted_long_volume == pytest.approx(expected_weighted, rel=1e-6)

    def test_empty_positions(self, config: StrategyConfig) -> None:
        """No positions => MIXED with all zeros."""
        traders = {"0x0": _trader("0x0")}
        result = compute_token_consensus("BTC", [], traders, config, NOW)

        assert result.consensus == ConsensusSide.MIXED
        assert result.long_volume_usd == 0.0
        assert result.short_volume_usd == 0.0
        assert result.long_cluster_count == 0

    def test_unknown_trader_address_skipped(self, config: StrategyConfig) -> None:
        """Position from an address not in the traders dict is ignored."""
        traders = {"0x0": _trader("0x0", cluster_id=0)}
        positions = [
            _position("0x0", side="Long"),
            _position("0xUNKNOWN", side="Long"),  # not in traders
        ]
        result = compute_token_consensus("BTC", positions, traders, config, NOW)

        assert len(result.long_traders) == 1


# ===========================================================================
# compute_all_tokens_consensus
# ===========================================================================


class TestComputeAllTokensConsensus:

    def test_multiple_tokens(self, config: StrategyConfig) -> None:
        """Processes each token independently."""
        traders = {
            f"0x{i}": _trader(f"0x{i}", cluster_id=i) for i in range(3)
        }
        positions_by_token = {
            "BTC": [
                _position(f"0x{i}", token="BTC", side="Long") for i in range(3)
            ],
            "SOL": [
                _position(f"0x{i}", token="SOL", side="Short", value_usd=20_000)
                for i in range(3)
            ],
        }
        results = compute_all_tokens_consensus(
            positions_by_token, traders, config, now=NOW
        )

        assert "BTC" in results
        assert "SOL" in results
        assert results["BTC"].consensus == ConsensusSide.STRONG_LONG
        assert results["SOL"].consensus == ConsensusSide.STRONG_SHORT

    def test_empty_positions_by_token(self, config: StrategyConfig) -> None:
        """Empty dict returns empty results."""
        results = compute_all_tokens_consensus({}, {}, config, now=NOW)
        assert results == {}

    def test_returns_correct_token_symbols(self, config: StrategyConfig) -> None:
        """Each result has the correct token_symbol set."""
        traders = {"0x0": _trader("0x0", cluster_id=0)}
        positions_by_token = {
            "HYPE": [_position("0x0", token="HYPE", side="Long", value_usd=10_000)],
        }
        results = compute_all_tokens_consensus(
            positions_by_token, traders, config, now=NOW
        )

        assert results["HYPE"].token_symbol == "HYPE"
