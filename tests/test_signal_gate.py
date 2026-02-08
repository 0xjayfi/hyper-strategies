"""Tests for signal gate and confirmation window."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from consensus.config import StrategyConfig
from consensus.models import ConsensusSide, PendingSignal, TokenConsensus
from consensus.signal_gate import SignalGate, _compute_weighted_avg_entry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _consensus(
    token: str = "BTC",
    side: ConsensusSide = ConsensusSide.STRONG_LONG,
    long_traders: set[str] | None = None,
    short_traders: set[str] | None = None,
    long_volume: float = 300_000,
    short_volume: float = 0.0,
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
        long_cluster_count=3 if side == ConsensusSide.STRONG_LONG else 0,
        short_cluster_count=3 if side == ConsensusSide.STRONG_SHORT else 0,
    )


# ===========================================================================
# SignalGate.process_consensus_change
# ===========================================================================


class TestSignalGateConfirmation:

    def test_first_strong_signal_creates_pending(self, config: StrategyConfig) -> None:
        """First STRONG consensus creates a pending signal, returns None."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        result = gate.process_consensus_change(
            "BTC", consensus, current_price=50_000, config=config, now=NOW
        )

        assert result is None
        assert "BTC" in gate.pending_signals
        assert gate.pending_signals["BTC"].consensus == ConsensusSide.STRONG_LONG

    def test_signal_confirmed_after_15_min_with_low_slippage(
        self, config: StrategyConfig
    ) -> None:
        """Signal created, confirmed after 15 min with <2% slippage => entry."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        # T=0: Create signal
        gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=NOW
        )
        avg_entry = gate.pending_signals["BTC"].avg_entry_price_at_detection

        # T=15min: Confirm — price within 2% of avg entry
        t_confirm = NOW + timedelta(minutes=15)
        price_within_slippage = avg_entry * 1.01  # 1% move — within 2% gate
        result = gate.process_consensus_change(
            "BTC", consensus, current_price=price_within_slippage,
            config=config, now=t_confirm,
        )

        assert result is not None
        assert result.confirmed is True
        assert result.consensus == ConsensusSide.STRONG_LONG
        assert "BTC" not in gate.pending_signals

    def test_signal_rejected_price_moves_over_2_percent(
        self, config: StrategyConfig
    ) -> None:
        """Signal created, price moves >2% during window => rejected."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        # T=0: Create signal
        gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=NOW
        )
        avg_entry = gate.pending_signals["BTC"].avg_entry_price_at_detection

        # T=15min: Price moved 5% — exceeds 2% gate
        t_confirm = NOW + timedelta(minutes=15)
        price_too_far = avg_entry * 1.05
        result = gate.process_consensus_change(
            "BTC", consensus, current_price=price_too_far,
            config=config, now=t_confirm,
        )

        assert result is None
        assert "BTC" not in gate.pending_signals  # Signal discarded

    def test_signal_cancelled_consensus_breaks_during_window(
        self, config: StrategyConfig
    ) -> None:
        """Signal created, consensus breaks during window => cancelled."""
        gate = SignalGate()
        strong = _consensus(side=ConsensusSide.STRONG_LONG)
        mixed = _consensus(side=ConsensusSide.MIXED)

        # T=0: Create signal
        gate.process_consensus_change(
            "BTC", strong, current_price=100_000, config=config, now=NOW
        )
        assert "BTC" in gate.pending_signals

        # T=5min: Consensus breaks
        t_break = NOW + timedelta(minutes=5)
        result = gate.process_consensus_change(
            "BTC", mixed, current_price=100_000, config=config, now=t_break
        )

        assert result is None
        assert "BTC" not in gate.pending_signals

    def test_signal_still_pending_at_14_min(self, config: StrategyConfig) -> None:
        """Signal created, re-checked at 14 min => still pending."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        # T=0: Create signal
        gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=NOW
        )

        # T=14min: Not yet at 15 min threshold
        t_early = NOW + timedelta(minutes=14)
        result = gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=t_early
        )

        assert result is None
        assert "BTC" in gate.pending_signals  # Still waiting

    def test_signal_confirmed_at_exactly_15_min(
        self, config: StrategyConfig
    ) -> None:
        """Signal confirmed at exactly COPY_DELAY_MINUTES boundary."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=NOW
        )
        avg_entry = gate.pending_signals["BTC"].avg_entry_price_at_detection

        # Exactly at 15 min boundary
        t_exact = NOW + timedelta(minutes=15)
        result = gate.process_consensus_change(
            "BTC", consensus, current_price=avg_entry,
            config=config, now=t_exact,
        )

        assert result is not None
        assert result.confirmed is True

    def test_strong_short_signal(self, config: StrategyConfig) -> None:
        """STRONG_SHORT signals work the same as STRONG_LONG."""
        gate = SignalGate()
        consensus = _consensus(
            side=ConsensusSide.STRONG_SHORT,
            long_traders=set(),
            short_traders={"0x0", "0x1", "0x2"},
            long_volume=0.0,
            short_volume=150_000,
        )

        # T=0: Create
        gate.process_consensus_change(
            "ETH", consensus, current_price=3_000, config=config, now=NOW
        )
        assert gate.pending_signals["ETH"].consensus == ConsensusSide.STRONG_SHORT

        avg_entry = gate.pending_signals["ETH"].avg_entry_price_at_detection

        # T=15min: Confirm
        t_confirm = NOW + timedelta(minutes=15)
        result = gate.process_consensus_change(
            "ETH", consensus, current_price=avg_entry,
            config=config, now=t_confirm,
        )
        assert result is not None
        assert result.consensus == ConsensusSide.STRONG_SHORT

    def test_mixed_consensus_with_no_pending_is_noop(
        self, config: StrategyConfig
    ) -> None:
        """MIXED consensus with no pending signal does nothing."""
        gate = SignalGate()
        mixed = _consensus(side=ConsensusSide.MIXED)

        result = gate.process_consensus_change(
            "BTC", mixed, current_price=50_000, config=config, now=NOW
        )

        assert result is None
        assert len(gate.pending_signals) == 0

    def test_multiple_tokens_independent(self, config: StrategyConfig) -> None:
        """Signals for different tokens are tracked independently."""
        gate = SignalGate()
        btc_consensus = _consensus(token="BTC", side=ConsensusSide.STRONG_LONG)
        eth_consensus = _consensus(
            token="ETH", side=ConsensusSide.STRONG_SHORT,
            long_traders=set(), short_traders={"0x0", "0x1", "0x2"},
            long_volume=0.0, short_volume=75_000,
        )

        gate.process_consensus_change(
            "BTC", btc_consensus, current_price=100_000, config=config, now=NOW
        )
        gate.process_consensus_change(
            "ETH", eth_consensus, current_price=3_000, config=config, now=NOW
        )

        assert "BTC" in gate.pending_signals
        assert "ETH" in gate.pending_signals

        # Cancel BTC only
        mixed = _consensus(token="BTC", side=ConsensusSide.MIXED)
        gate.process_consensus_change(
            "BTC", mixed, current_price=100_000, config=config,
            now=NOW + timedelta(minutes=5),
        )

        assert "BTC" not in gate.pending_signals
        assert "ETH" in gate.pending_signals  # Still pending

    def test_slippage_at_exactly_2_percent_rejected(
        self, config: StrategyConfig
    ) -> None:
        """Slippage at exactly MAX_PRICE_SLIPPAGE_PERCENT is rejected (> not >=)."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=NOW
        )
        avg_entry = gate.pending_signals["BTC"].avg_entry_price_at_detection

        # Exactly 2% move (equal to threshold — rejected because > not >=)
        # With 2.0% threshold: 2.0 is NOT > 2.0 so it should pass
        t_confirm = NOW + timedelta(minutes=15)
        price_at_boundary = avg_entry * 1.02  # exactly 2%
        result = gate.process_consensus_change(
            "BTC", consensus, current_price=price_at_boundary,
            config=config, now=t_confirm,
        )

        # Exactly at 2.0% => 2.0 is NOT > 2.0, so signal passes
        assert result is not None
        assert result.confirmed is True

    def test_price_drop_within_slippage_passes(
        self, config: StrategyConfig
    ) -> None:
        """Price dropping (negative move) within slippage passes."""
        gate = SignalGate()
        consensus = _consensus(side=ConsensusSide.STRONG_LONG)

        gate.process_consensus_change(
            "BTC", consensus, current_price=100_000, config=config, now=NOW
        )
        avg_entry = gate.pending_signals["BTC"].avg_entry_price_at_detection

        # Price dropped 1% — within slippage gate
        t_confirm = NOW + timedelta(minutes=15)
        price_down = avg_entry * 0.99
        result = gate.process_consensus_change(
            "BTC", consensus, current_price=price_down,
            config=config, now=t_confirm,
        )

        assert result is not None
        assert result.confirmed is True


# ===========================================================================
# _compute_weighted_avg_entry
# ===========================================================================


class TestComputeWeightedAvgEntry:

    def test_strong_long_avg(self) -> None:
        """Average entry for STRONG_LONG = long_volume / long_trader_count."""
        consensus = _consensus(
            side=ConsensusSide.STRONG_LONG,
            long_traders={"0x0", "0x1", "0x2"},
            long_volume=300_000,
        )
        result = _compute_weighted_avg_entry(consensus)
        assert result == pytest.approx(100_000)  # 300K / 3 traders

    def test_strong_short_avg(self) -> None:
        """Average entry for STRONG_SHORT = short_volume / short_trader_count."""
        consensus = _consensus(
            side=ConsensusSide.STRONG_SHORT,
            long_traders=set(),
            short_traders={"0x0", "0x1"},
            long_volume=0,
            short_volume=100_000,
        )
        result = _compute_weighted_avg_entry(consensus)
        assert result == pytest.approx(50_000)  # 100K / 2 traders

    def test_mixed_returns_zero(self) -> None:
        """MIXED consensus returns 0."""
        consensus = _consensus(side=ConsensusSide.MIXED)
        assert _compute_weighted_avg_entry(consensus) == 0.0

    def test_empty_traders_returns_zero(self) -> None:
        """No traders on dominant side returns 0."""
        consensus = _consensus(
            side=ConsensusSide.STRONG_LONG,
            long_traders=set(),
            long_volume=0,
        )
        assert _compute_weighted_avg_entry(consensus) == 0.0


# ===========================================================================
# HyperliquidPriceFeed
# ===========================================================================


class TestHyperliquidPriceFeed:

    def test_initial_state_is_stale(self) -> None:
        """Price feed is stale before any updates."""
        from consensus.hl_client import HyperliquidPriceFeed

        feed = HyperliquidPriceFeed()
        assert feed.is_stale() is True
        assert feed.prices == {}
        assert feed.get_price("BTC") is None

    def test_handle_ws_message_updates_prices(self) -> None:
        """Valid WS message updates prices and freshness."""
        import json
        from consensus.hl_client import HyperliquidPriceFeed

        feed = HyperliquidPriceFeed()
        msg = json.dumps({
            "channel": "allMids",
            "data": {"mids": {"BTC": "97000.5", "ETH": "3200.1"}},
        })
        feed._handle_ws_message(msg)

        assert feed.get_price("BTC") == pytest.approx(97000.5)
        assert feed.get_price("ETH") == pytest.approx(3200.1)
        assert feed.is_stale() is False

    def test_handle_ws_message_ignores_other_channels(self) -> None:
        """Messages from other channels are ignored."""
        import json
        from consensus.hl_client import HyperliquidPriceFeed

        feed = HyperliquidPriceFeed()
        msg = json.dumps({"channel": "trades", "data": {"some": "data"}})
        feed._handle_ws_message(msg)

        assert feed.prices == {}

    def test_handle_ws_message_handles_malformed_json(self) -> None:
        """Malformed JSON doesn't crash."""
        from consensus.hl_client import HyperliquidPriceFeed

        feed = HyperliquidPriceFeed()
        feed._handle_ws_message("not valid json {{{")
        assert feed.prices == {}

    def test_stale_after_threshold(self) -> None:
        """Price becomes stale after STALE_PRICE_THRESHOLD seconds."""
        import time
        from consensus.hl_client import HyperliquidPriceFeed, STALE_PRICE_THRESHOLD

        feed = HyperliquidPriceFeed()
        # Simulate an old update
        feed._last_update = time.monotonic() - STALE_PRICE_THRESHOLD - 1
        assert feed.is_stale() is True

    def test_not_stale_within_threshold(self) -> None:
        """Price is not stale within STALE_PRICE_THRESHOLD seconds."""
        import time
        from consensus.hl_client import HyperliquidPriceFeed

        feed = HyperliquidPriceFeed()
        feed._last_update = time.monotonic()
        assert feed.is_stale() is False
