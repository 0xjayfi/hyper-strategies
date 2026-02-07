"""Copy-cluster detection using trade timestamp correlation and Union-Find."""

from __future__ import annotations

from datetime import timedelta
from itertools import combinations

from consensus.config import StrategyConfig
from consensus.models import TradeRecord


# ---------------------------------------------------------------------------
# Union-Find (Disjoint Set)
# ---------------------------------------------------------------------------


class UnionFind:
    """Weighted quick-union with path compression."""

    def __init__(self, elements: list[str]) -> None:
        self._parent: dict[str, str] = {e: e for e in elements}
        self._rank: dict[str, int] = {e: 0 for e in elements}

    def find(self, x: str) -> str:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def clusters(self) -> dict[str, int]:
        """Return mapping of element -> cluster_id (int)."""
        root_to_id: dict[str, int] = {}
        result: dict[str, int] = {}
        next_id = 0
        for elem in self._parent:
            root = self.find(elem)
            if root not in root_to_id:
                root_to_id[root] = next_id
                next_id += 1
            result[elem] = root_to_id[root]
        return result


# ---------------------------------------------------------------------------
# Pairwise trade correlation
# ---------------------------------------------------------------------------


def _compute_pairwise_correlation(
    trades_a: list[TradeRecord],
    trades_b: list[TradeRecord],
    copy_window_minutes: int,
) -> float:
    """Fraction of the smaller trader's trades that overlap with the other.

    An overlap = same token, same side, within copy_window_minutes.
    Returns correlation in [0, 1].
    """
    if not trades_a or not trades_b:
        return 0.0

    window = timedelta(minutes=copy_window_minutes)
    overlap_count = 0

    # Index trades_b by (token, side) for faster lookup
    b_by_key: dict[tuple[str, str], list[TradeRecord]] = {}
    for tb in trades_b:
        key = (tb.token_symbol, tb.side)
        b_by_key.setdefault(key, []).append(tb)

    for ta in trades_a:
        key = (ta.token_symbol, ta.side)
        candidates = b_by_key.get(key, [])
        for tb in candidates:
            if abs((ta.timestamp - tb.timestamp).total_seconds()) <= window.total_seconds():
                overlap_count += 1
                break  # count each trade_a at most once

    denominator = min(len(trades_a), len(trades_b))
    return overlap_count / denominator if denominator > 0 else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_copy_clusters(
    trader_addresses: list[str],
    trade_log: dict[str, list[TradeRecord]],
    config: StrategyConfig | None = None,
    copy_window_minutes: int | None = None,
    copy_threshold: float | None = None,
) -> dict[str, int]:
    """Detect copy-clusters among a set of traders.

    For each pair (A, B), compute trade timestamp correlation. If
    correlation > threshold for either direction (A->B or B->A),
    merge into the same cluster using Union-Find.

    Args:
        trader_addresses: List of trader addresses to cluster.
        trade_log: Mapping of address -> list of TradeRecord.
        config: StrategyConfig for copy_window_minutes and copy_threshold.
        copy_window_minutes: Override config value.
        copy_threshold: Override config value.

    Returns:
        Dict mapping each address to an integer cluster_id.
    """
    cw = copy_window_minutes if copy_window_minutes is not None else (config.COPY_WINDOW_MINUTES if config else 10)
    ct = copy_threshold if copy_threshold is not None else (config.COPY_THRESHOLD if config else 0.40)

    uf = UnionFind(trader_addresses)

    for addr_a, addr_b in combinations(trader_addresses, 2):
        trades_a = trade_log.get(addr_a, [])
        trades_b = trade_log.get(addr_b, [])

        # Compute correlation in both directions
        corr_ab = _compute_pairwise_correlation(trades_a, trades_b, cw)
        corr_ba = _compute_pairwise_correlation(trades_b, trades_a, cw)

        if corr_ab >= ct or corr_ba >= ct:
            uf.union(addr_a, addr_b)

    return uf.clusters()
