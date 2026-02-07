"""Tests for copy-cluster detection."""

from __future__ import annotations

from datetime import datetime, timedelta

from consensus.clusters import UnionFind, _compute_pairwise_correlation, detect_copy_clusters
from consensus.models import TradeRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime(2025, 6, 1, 12, 0, 0)


def _trade(
    addr: str,
    token: str = "BTC",
    side: str = "Long",
    ts: datetime | None = None,
    action: str = "Open",
) -> TradeRecord:
    return TradeRecord(
        trader_address=addr,
        token_symbol=token,
        side=side,
        action=action,
        size=1.0,
        price_usd=50000.0,
        value_usd=50000.0,
        timestamp=ts or NOW,
        fee_usd=1.0,
        closed_pnl=0.0,
        transaction_hash=f"0x{hash((addr, token, side, ts)):032x}",
    )


# ===========================================================================
# UnionFind
# ===========================================================================


class TestUnionFind:

    def test_initial_each_own_cluster(self) -> None:
        uf = UnionFind(["A", "B", "C"])
        clusters = uf.clusters()
        assert len(set(clusters.values())) == 3

    def test_union_merges_clusters(self) -> None:
        uf = UnionFind(["A", "B", "C"])
        uf.union("A", "B")
        clusters = uf.clusters()
        assert clusters["A"] == clusters["B"]
        assert clusters["A"] != clusters["C"]

    def test_transitive_union(self) -> None:
        uf = UnionFind(["A", "B", "C"])
        uf.union("A", "B")
        uf.union("B", "C")
        clusters = uf.clusters()
        assert clusters["A"] == clusters["B"] == clusters["C"]

    def test_union_idempotent(self) -> None:
        uf = UnionFind(["A", "B"])
        uf.union("A", "B")
        uf.union("A", "B")
        clusters = uf.clusters()
        assert clusters["A"] == clusters["B"]
        assert len(set(clusters.values())) == 1


# ===========================================================================
# _compute_pairwise_correlation
# ===========================================================================


class TestPairwiseCorrelation:

    def test_identical_trades_full_correlation(self) -> None:
        """Same token, same side, same time => 100% correlation."""
        trades_a = [_trade("A", "BTC", "Long", NOW)]
        trades_b = [_trade("B", "BTC", "Long", NOW)]
        assert _compute_pairwise_correlation(trades_a, trades_b, copy_window_minutes=10) == 1.0

    def test_within_window_correlates(self) -> None:
        """5 min apart, 10 min window => correlated."""
        trades_a = [_trade("A", "BTC", "Long", NOW)]
        trades_b = [_trade("B", "BTC", "Long", NOW + timedelta(minutes=5))]
        assert _compute_pairwise_correlation(trades_a, trades_b, copy_window_minutes=10) == 1.0

    def test_outside_window_no_correlation(self) -> None:
        """15 min apart, 10 min window => not correlated."""
        trades_a = [_trade("A", "BTC", "Long", NOW)]
        trades_b = [_trade("B", "BTC", "Long", NOW + timedelta(minutes=15))]
        assert _compute_pairwise_correlation(trades_a, trades_b, copy_window_minutes=10) == 0.0

    def test_different_token_no_correlation(self) -> None:
        """Same time but different token => not correlated."""
        trades_a = [_trade("A", "BTC", "Long", NOW)]
        trades_b = [_trade("B", "ETH", "Long", NOW)]
        assert _compute_pairwise_correlation(trades_a, trades_b, copy_window_minutes=10) == 0.0

    def test_different_side_no_correlation(self) -> None:
        """Same token but different side => not correlated."""
        trades_a = [_trade("A", "BTC", "Long", NOW)]
        trades_b = [_trade("B", "BTC", "Short", NOW)]
        assert _compute_pairwise_correlation(trades_a, trades_b, copy_window_minutes=10) == 0.0

    def test_empty_trades_zero_correlation(self) -> None:
        assert _compute_pairwise_correlation([], [_trade("B")], copy_window_minutes=10) == 0.0
        assert _compute_pairwise_correlation([_trade("A")], [], copy_window_minutes=10) == 0.0

    def test_partial_overlap(self) -> None:
        """2 out of 4 trades overlap => 50% correlation."""
        trades_a = [
            _trade("A", "BTC", "Long", NOW),
            _trade("A", "ETH", "Long", NOW + timedelta(hours=1)),
            _trade("A", "SOL", "Long", NOW + timedelta(hours=2)),
            _trade("A", "HYPE", "Long", NOW + timedelta(hours=3)),
        ]
        trades_b = [
            _trade("B", "BTC", "Long", NOW + timedelta(minutes=5)),  # overlaps
            _trade("B", "ETH", "Long", NOW + timedelta(hours=1, minutes=5)),  # overlaps
        ]
        corr = _compute_pairwise_correlation(trades_a, trades_b, copy_window_minutes=10)
        # denominator = min(4, 2) = 2, overlaps = 2
        assert corr == 1.0

        corr_reverse = _compute_pairwise_correlation(trades_b, trades_a, copy_window_minutes=10)
        # denominator = min(2, 4) = 2, overlaps = 2
        assert corr_reverse == 1.0


# ===========================================================================
# detect_copy_clusters
# ===========================================================================


class TestDetectCopyClusters:

    def test_no_correlation_separate_clusters(self) -> None:
        """Independent traders each get their own cluster."""
        addrs = ["0xA", "0xB", "0xC"]
        trade_log = {
            "0xA": [_trade("0xA", "BTC", "Long", NOW)],
            "0xB": [_trade("0xB", "ETH", "Short", NOW + timedelta(hours=5))],
            "0xC": [_trade("0xC", "SOL", "Long", NOW + timedelta(hours=10))],
        }
        clusters = detect_copy_clusters(addrs, trade_log, copy_window_minutes=10, copy_threshold=0.4)
        assert len(set(clusters.values())) == 3

    def test_correlated_traders_merge(self) -> None:
        """Two traders copying each other get same cluster."""
        addrs = ["0xA", "0xB", "0xC"]
        base_trades = [
            ("BTC", "Long", NOW),
            ("ETH", "Short", NOW + timedelta(hours=1)),
            ("SOL", "Long", NOW + timedelta(hours=2)),
        ]
        # A and B trade the same things within 5 min
        trade_log = {
            "0xA": [_trade("0xA", tok, side, ts) for tok, side, ts in base_trades],
            "0xB": [_trade("0xB", tok, side, ts + timedelta(minutes=3)) for tok, side, ts in base_trades],
            "0xC": [_trade("0xC", "HYPE", "Long", NOW + timedelta(days=1))],  # independent
        }
        clusters = detect_copy_clusters(addrs, trade_log, copy_window_minutes=10, copy_threshold=0.4)
        assert clusters["0xA"] == clusters["0xB"]
        assert clusters["0xA"] != clusters["0xC"]

    def test_transitive_cluster_merge(self) -> None:
        """A copies B, B copies C => all in same cluster."""
        addrs = ["0xA", "0xB", "0xC"]
        base_ab = [
            ("BTC", "Long", NOW),
            ("ETH", "Short", NOW + timedelta(hours=1)),
        ]
        base_bc = [
            ("SOL", "Long", NOW + timedelta(hours=3)),
            ("HYPE", "Short", NOW + timedelta(hours=4)),
        ]
        trade_log = {
            "0xA": [_trade("0xA", tok, side, ts) for tok, side, ts in base_ab],
            "0xB": (
                [_trade("0xB", tok, side, ts + timedelta(minutes=2)) for tok, side, ts in base_ab]
                + [_trade("0xB", tok, side, ts) for tok, side, ts in base_bc]
            ),
            "0xC": [_trade("0xC", tok, side, ts + timedelta(minutes=2)) for tok, side, ts in base_bc],
        }
        clusters = detect_copy_clusters(addrs, trade_log, copy_window_minutes=10, copy_threshold=0.4)
        assert clusters["0xA"] == clusters["0xB"] == clusters["0xC"]

    def test_below_threshold_stays_separate(self) -> None:
        """Only 1 out of 5 trades overlap => 20% < 40% threshold."""
        addrs = ["0xA", "0xB"]
        trade_log = {
            "0xA": [
                _trade("0xA", "BTC", "Long", NOW),
                _trade("0xA", "ETH", "Long", NOW + timedelta(hours=1)),
                _trade("0xA", "SOL", "Long", NOW + timedelta(hours=2)),
                _trade("0xA", "HYPE", "Long", NOW + timedelta(hours=3)),
                _trade("0xA", "DOGE", "Long", NOW + timedelta(hours=4)),
            ],
            "0xB": [
                _trade("0xB", "BTC", "Long", NOW + timedelta(minutes=5)),  # one overlap
                _trade("0xB", "LINK", "Short", NOW + timedelta(hours=6)),
                _trade("0xB", "AVAX", "Short", NOW + timedelta(hours=7)),
                _trade("0xB", "MATIC", "Long", NOW + timedelta(hours=8)),
                _trade("0xB", "ARB", "Long", NOW + timedelta(hours=9)),
            ],
        }
        clusters = detect_copy_clusters(addrs, trade_log, copy_window_minutes=10, copy_threshold=0.4)
        assert clusters["0xA"] != clusters["0xB"]

    def test_empty_trade_log(self) -> None:
        """Traders with no trades get separate clusters."""
        addrs = ["0xA", "0xB"]
        clusters = detect_copy_clusters(addrs, {}, copy_window_minutes=10, copy_threshold=0.4)
        assert len(set(clusters.values())) == 2
