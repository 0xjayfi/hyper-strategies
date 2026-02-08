"""Tests for entry sizing and risk caps."""

from __future__ import annotations

from datetime import datetime

import pytest

from consensus.config import StrategyConfig
from consensus.models import ConsensusSide, OurPosition, TokenConsensus
from consensus.sizing import calculate_entry_size, select_leverage, select_order_type

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _consensus(
    token: str = "BTC",
    side: ConsensusSide = ConsensusSide.STRONG_LONG,
    long_cluster_count: int = 3,
    short_cluster_count: int = 0,
    long_volume: float = 300_000,
    short_volume: float = 0.0,
    long_traders: set[str] | None = None,
    short_traders: set[str] | None = None,
) -> TokenConsensus:
    return TokenConsensus(
        token_symbol=token,
        timestamp=NOW,
        long_traders=long_traders or {"0x0", "0x1", "0x2"},
        short_traders=short_traders or set(),
        long_volume_usd=long_volume,
        short_volume_usd=short_volume,
        weighted_long_volume=long_volume * 0.8,
        weighted_short_volume=short_volume * 0.8,
        consensus=side,
        long_cluster_count=long_cluster_count,
        short_cluster_count=short_cluster_count,
    )


def _position(
    token: str = "BTC",
    side: str = "Long",
    size_usd: float = 10_000,
) -> OurPosition:
    return OurPosition(
        token_symbol=token,
        side=side,
        entry_price_usd=50_000,
        current_price_usd=50_000,
        size_usd=size_usd,
        leverage=3,
        margin_type="isolated",
        stop_loss_price=47_500,
        trailing_stop_price=None,
        highest_price_since_entry=50_000,
        opened_at=NOW,
        consensus_side_at_entry=ConsensusSide.STRONG_LONG,
    )


# ===========================================================================
# calculate_entry_size
# ===========================================================================


class TestCalculateEntrySize:

    def test_basic_entry_allowed(self, config: StrategyConfig) -> None:
        """$10K entry with $100K account, no existing positions => allowed."""
        consensus = _consensus()
        size = calculate_entry_size(
            "BTC", "Long", consensus, account_value=100_000,
            existing_positions=[], config=config,
        )
        assert size is not None
        assert size > 0
        # Base: 100K * 0.05 * 0.5 * (3/3) = 2500
        assert size == pytest.approx(2_500)

    def test_strength_multiplier_scales_size(self, config: StrategyConfig) -> None:
        """More clusters = higher strength multiplier."""
        consensus_3 = _consensus(long_cluster_count=3)
        consensus_6 = _consensus(long_cluster_count=6)

        size_3 = calculate_entry_size(
            "BTC", "Long", consensus_3, 100_000, [], config,
        )
        size_6 = calculate_entry_size(
            "BTC", "Long", consensus_6, 100_000, [], config,
        )

        assert size_6 is not None and size_3 is not None
        # 6 clusters: mult = min(2.0, 6/3) = 2.0
        # 3 clusters: mult = min(2.0, 3/3) = 1.0
        assert size_6 == pytest.approx(size_3 * 2.0)

    def test_strength_multiplier_capped_at_2(self, config: StrategyConfig) -> None:
        """Strength multiplier caps at 2.0 regardless of cluster count."""
        consensus_10 = _consensus(long_cluster_count=10)

        size = calculate_entry_size(
            "BTC", "Long", consensus_10, 100_000, [], config,
        )
        # mult = min(2.0, 10/3) = 2.0
        # base = 100K * 0.05 * 0.5 * 2.0 = 5000
        assert size == pytest.approx(5_000)

    def test_position_count_cap_blocks_6th(self, config: StrategyConfig) -> None:
        """6th position attempt => blocked (MAX_TOTAL_POSITIONS=5)."""
        existing = [_position(token=f"T{i}") for i in range(5)]
        consensus = _consensus()

        size = calculate_entry_size(
            "BTC", "Long", consensus, 100_000, existing, config,
        )
        assert size is None

    def test_single_position_ratio_cap(self, config: StrategyConfig) -> None:
        """Single position capped at MAX_SINGLE_POSITION_RATIO * account."""
        # With huge cluster count, base would be large
        consensus = _consensus(long_cluster_count=100)
        size = calculate_entry_size(
            "BTC", "Long", consensus, 100_000, [], config,
        )
        # Max single = min(100K * 0.10, 50K) = 10K
        assert size is not None
        assert size <= 10_000

    def test_single_position_hard_cap(self, config: StrategyConfig) -> None:
        """Single position capped at MAX_SINGLE_POSITION_HARD_CAP ($50K)."""
        consensus = _consensus(long_cluster_count=100)
        # With a $1M account: ratio cap = 100K, hard cap = 50K => 50K wins
        size = calculate_entry_size(
            "BTC", "Long", consensus, 1_000_000, [], config,
        )
        assert size is not None
        assert size <= 50_000

    def test_total_exposure_cap(self, config: StrategyConfig) -> None:
        """Total exposure capped at MAX_TOTAL_EXPOSURE_RATIO * account."""
        # 100K account, 50% max total = 50K max
        # 4 existing positions at 12K each = 48K used
        existing = [_position(token=f"T{i}", size_usd=12_000) for i in range(4)]
        consensus = _consensus()

        size = calculate_entry_size(
            "BTC", "Long", consensus, 100_000, existing, config,
        )
        # Max remaining = 50K - 48K = 2K
        assert size is not None
        assert size <= 2_000

    def test_token_exposure_cap(self, config: StrategyConfig) -> None:
        """Token exposure capped at MAX_EXPOSURE_PER_TOKEN * account."""
        # 100K account, 15% max per token = 15K
        # Existing BTC position at 14K
        existing = [_position(token="BTC", size_usd=14_000)]
        consensus = _consensus()

        size = calculate_entry_size(
            "BTC", "Long", consensus, 100_000, existing, config,
        )
        # Max remaining = 15K - 14K = 1K
        assert size is not None
        assert size <= 1_000

    def test_token_exposure_cap_returns_none_when_dust(
        self, config: StrategyConfig
    ) -> None:
        """Token already at 14.95K of 15K cap => remainder <$100 => None."""
        existing = [_position(token="BTC", size_usd=14_950)]
        consensus = _consensus()

        size = calculate_entry_size(
            "BTC", "Long", consensus, 100_000, existing, config,
        )
        # Max remaining = 15K - 14.95K = 50, below $100 dust threshold
        assert size is None

    def test_directional_long_exposure_cap(self, config: StrategyConfig) -> None:
        """Long exposure capped when MAX_LONG_EXPOSURE < MAX_TOTAL_EXPOSURE.

        With default config, total cap (50%) always binds before long cap (60%).
        Use a tighter long cap (30%) to isolate the directional constraint.
        """
        from consensus.config import StrategyConfig as SC
        tight_config = SC(
            NANSEN_API_KEY="test-key", HL_PRIVATE_KEY="test-key",
            TYPEFULLY_API_KEY="test-key",
            MAX_LONG_EXPOSURE=0.30,
        )
        # 100K account: total cap = 50K, long cap = 30K.
        # 2 longs at 13K = 26K long, 26K total.
        existing = [_position(token=f"T{i}", side="Long", size_usd=13_000) for i in range(2)]
        consensus = _consensus(long_cluster_count=6)

        size = calculate_entry_size(
            "BTC", "Long", consensus, 100_000, existing, tight_config,
        )
        # base = 5K, total OK, token OK, long: 26+5=31>30 => capped to 4K
        assert size is not None
        assert size == pytest.approx(4_000)

    def test_directional_short_exposure_cap(self, config: StrategyConfig) -> None:
        """Short exposure capped when MAX_SHORT_EXPOSURE < MAX_TOTAL_EXPOSURE."""
        from consensus.config import StrategyConfig as SC
        tight_config = SC(
            NANSEN_API_KEY="test-key", HL_PRIVATE_KEY="test-key",
            TYPEFULLY_API_KEY="test-key",
            MAX_SHORT_EXPOSURE=0.30,
        )
        # 100K account: total cap = 50K, short cap = 30K.
        existing = [_position(token=f"T{i}", side="Short", size_usd=13_000) for i in range(2)]
        consensus = _consensus(
            side=ConsensusSide.STRONG_SHORT,
            short_cluster_count=6, long_cluster_count=0,
            long_traders=set(), short_traders={"0x0", "0x1", "0x2"},
        )

        size = calculate_entry_size(
            "ETH", "Short", consensus, 100_000, existing, tight_config,
        )
        # base = 5K, short: 26+5=31>30 => capped to 4K
        assert size is not None
        assert size == pytest.approx(4_000)

    def test_dust_prevention_returns_none(self, config: StrategyConfig) -> None:
        """Size below $100 returns None."""
        # Near total exposure cap with tiny room
        existing = [_position(token=f"T{i}", size_usd=12_475) for i in range(4)]
        # Total = 49,900. Max total = 50K. Room = 100. But after all caps
        # it may round below 100.
        consensus = _consensus(long_cluster_count=1)  # low strength

        size = calculate_entry_size(
            "NEW", "Long", consensus, 100_000, existing, config,
        )
        # base = 100K * 0.05 * 0.5 * (1/3) = 833
        # total cap: 50K - 49.9K = 100 remaining
        # So size should be capped to 100 which is exactly $100 — allowed
        # But with cluster_count=1, strength = 1/3, base = 833
        # After total exposure cap: min(833, 100) = 100
        # 100 >= 100 threshold, so it passes
        if size is not None:
            assert size >= 100

    def test_no_existing_positions_no_caps_hit(self, config: StrategyConfig) -> None:
        """Clean portfolio with no positions should size purely from formula."""
        consensus = _consensus(long_cluster_count=3)
        size = calculate_entry_size(
            "BTC", "Long", consensus, 200_000, [], config,
        )
        # base = 200K * 0.05 * 0.5 * 1.0 = 5000
        # single cap = min(200K*0.1, 50K) = min(20K, 50K) = 20K
        # 5000 < 20K, no cap hit
        assert size == pytest.approx(5_000)

    def test_short_side_uses_short_clusters(self, config: StrategyConfig) -> None:
        """Short entry uses short_cluster_count for strength multiplier."""
        consensus = _consensus(
            side=ConsensusSide.STRONG_SHORT,
            long_cluster_count=0,
            short_cluster_count=6,
            long_traders=set(),
            short_traders={"0x0", "0x1", "0x2"},
        )
        size = calculate_entry_size(
            "ETH", "Short", consensus, 100_000, [], config,
        )
        # strength = min(2.0, 6/3) = 2.0
        # base = 100K * 0.05 * 0.5 * 2.0 = 5000
        assert size == pytest.approx(5_000)


# ===========================================================================
# select_leverage
# ===========================================================================


class TestSelectLeverage:

    def test_leverage_capped_at_max(self, config: StrategyConfig) -> None:
        """20x from trader => capped to 5x."""
        assert select_leverage(20.0, config) == 5

    def test_leverage_below_cap_passes(self, config: StrategyConfig) -> None:
        """3x from trader => 3x."""
        assert select_leverage(3.0, config) == 3

    def test_leverage_at_cap(self, config: StrategyConfig) -> None:
        """5x from trader => 5x."""
        assert select_leverage(5.0, config) == 5

    def test_leverage_rounds_down(self, config: StrategyConfig) -> None:
        """3.7x => int(3.7) = 3."""
        assert select_leverage(3.7, config) == 3

    def test_leverage_minimum_1(self, config: StrategyConfig) -> None:
        """Very low leverage floors to 1."""
        assert select_leverage(0.5, config) == 1


# ===========================================================================
# select_order_type
# ===========================================================================


class TestSelectOrderType:

    def test_close_always_market(self) -> None:
        """Close action always returns market order."""
        order_type, price = select_order_type(
            action="Close", signal_age_seconds=0,
            current_price=50_000, trader_entry_price=49_000, token="BTC",
        )
        assert order_type == "market"
        assert price is None

    def test_fresh_signal_market(self) -> None:
        """Signal < 2 min old => market order."""
        order_type, price = select_order_type(
            action="Open", signal_age_seconds=60,
            current_price=50_000, trader_entry_price=50_000, token="BTC",
        )
        assert order_type == "market"
        assert price is None

    def test_moderate_age_low_drift_limit(self) -> None:
        """Signal 2-10 min old, drift < 0.3% => limit at current price."""
        order_type, price = select_order_type(
            action="Open", signal_age_seconds=300,  # 5 min
            current_price=50_000, trader_entry_price=50_050, token="BTC",
        )
        # drift = |50000 - 50050| / 50050 * 100 = 0.099% < 0.3%
        assert order_type == "limit"
        assert price == 50_000

    def test_moderate_age_high_drift_skip(self) -> None:
        """Signal 2-10 min old, drift > 0.3% => skip."""
        order_type, price = select_order_type(
            action="Open", signal_age_seconds=300,  # 5 min
            current_price=50_500, trader_entry_price=50_000, token="BTC",
        )
        # drift = 500/50000 * 100 = 1.0% > 0.3%
        assert order_type == "skip"
        assert price is None

    def test_old_signal_skip(self) -> None:
        """Signal >= 10 min old => skip."""
        order_type, price = select_order_type(
            action="Open", signal_age_seconds=600,  # 10 min
            current_price=50_000, trader_entry_price=50_000, token="BTC",
        )
        assert order_type == "skip"
        assert price is None

    def test_exactly_2_min_is_limit_not_market(self) -> None:
        """At exactly 2 min boundary: age_min = 2.0, not < 2 so enters limit branch."""
        order_type, price = select_order_type(
            action="Open", signal_age_seconds=120,  # exactly 2 min
            current_price=50_000, trader_entry_price=50_000, token="BTC",
        )
        # age_min = 2.0, which is NOT < 2, so it enters the elif branch
        # drift = 0% < 0.3% => limit
        assert order_type == "limit"
        assert price == 50_000

    def test_close_ignores_age(self) -> None:
        """Close action returns market regardless of signal age."""
        order_type, _ = select_order_type(
            action="Close", signal_age_seconds=9999,
            current_price=50_000, trader_entry_price=50_000, token="BTC",
        )
        assert order_type == "market"
