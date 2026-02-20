"""Tests for the data collector module (snap.collector)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from snap.collector import (
    CollectionSummary,
    _cache_trades,
    _get_cached_trades,
    _store_traders,
    collect_trader_data,
    fetch_and_merge_leaderboard,
)
from snap.database import get_connection, init_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_leaderboard_entry(
    addr: str,
    roi: float = 10.0,
    total_pnl: float = 5000.0,
    account_value: float = 50000.0,
    label: str = "",
) -> dict:
    return {
        "trader_address": addr,
        "trader_address_label": label,
        "roi": roi,
        "total_pnl": total_pnl,
        "account_value": account_value,
    }


def _make_trade(
    token: str = "BTC",
    side: str = "Long",
    action: str = "Open",
    price: float = 50000.0,
    size: float = 0.1,
    value_usd: float = 5000.0,
    closed_pnl: float = 0.0,
    fee_usd: float = 2.5,
    timestamp: str = "2026-01-15T10:00:00",
) -> dict:
    return {
        "token_symbol": token,
        "side": side,
        "action": action,
        "price": price,
        "size": size,
        "value_usd": value_usd,
        "closed_pnl": closed_pnl,
        "fee_usd": fee_usd,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Tests: fetch_and_merge_leaderboard
# ---------------------------------------------------------------------------


class TestFetchAndMergeLeaderboard:
    async def test_merges_three_timeframes(self):
        """Leaderboard entries from 7d/30d/90d should merge by address."""
        client = AsyncMock()
        addr = "0xabc123"

        # Each call returns the same trader with different ROI
        client.get_leaderboard = AsyncMock(
            side_effect=[
                [_make_leaderboard_entry(addr, roi=5.0, total_pnl=1000)],  # 7d
                [_make_leaderboard_entry(addr, roi=15.0, total_pnl=3000)],  # 30d
                [_make_leaderboard_entry(addr, roi=25.0, total_pnl=8000)],  # 90d
            ]
        )

        merged = await fetch_and_merge_leaderboard(client)

        assert len(merged) == 1
        assert merged[addr]["roi_7d"] == 5.0
        assert merged[addr]["roi_30d"] == 15.0
        assert merged[addr]["roi_90d"] == 25.0
        assert merged[addr]["pnl_7d"] == 1000
        assert merged[addr]["pnl_30d"] == 3000
        assert merged[addr]["pnl_90d"] == 8000

    async def test_takes_max_account_value(self):
        """Account value should be max across all timeframes."""
        client = AsyncMock()
        addr = "0xabc"

        client.get_leaderboard = AsyncMock(
            side_effect=[
                [_make_leaderboard_entry(addr, account_value=30000)],
                [_make_leaderboard_entry(addr, account_value=80000)],
                [_make_leaderboard_entry(addr, account_value=50000)],
            ]
        )

        merged = await fetch_and_merge_leaderboard(client)
        assert merged[addr]["account_value"] == 80000

    async def test_multiple_traders(self):
        """Different addresses should produce separate entries."""
        client = AsyncMock()

        client.get_leaderboard = AsyncMock(
            side_effect=[
                [
                    _make_leaderboard_entry("0xaaa", roi=10),
                    _make_leaderboard_entry("0xbbb", roi=20),
                ],
                [],
                [],
            ]
        )

        merged = await fetch_and_merge_leaderboard(client)
        assert len(merged) == 2
        assert "0xaaa" in merged
        assert "0xbbb" in merged

    async def test_skips_empty_address(self):
        """Entries with empty trader_address should be skipped."""
        client = AsyncMock()
        client.get_leaderboard = AsyncMock(
            side_effect=[
                [{"trader_address": "", "roi": 5, "total_pnl": 100, "account_value": 1000}],
                [],
                [],
            ]
        )

        merged = await fetch_and_merge_leaderboard(client)
        assert len(merged) == 0


# ---------------------------------------------------------------------------
# Tests: _store_traders
# ---------------------------------------------------------------------------


class TestStoreTraders:
    def test_stores_all_fields(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        merged = {
            "0xabc": {
                "address": "0xabc",
                "label": "Smart Money",
                "account_value": 100000.0,
                "roi_7d": 5.0,
                "roi_30d": 15.0,
                "roi_90d": 25.0,
                "pnl_7d": 1000.0,
                "pnl_30d": 3000.0,
                "pnl_90d": 8000.0,
            }
        }

        _store_traders(db_path, merged)

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM traders WHERE address = '0xabc'"
            ).fetchone()
            assert row is not None
            assert row["label"] == "Smart Money"
            assert row["account_value"] == 100000.0
            assert row["roi_7d"] == 5.0
            assert row["roi_30d"] == 15.0
            assert row["roi_90d"] == 25.0
            assert row["pnl_7d"] == 1000.0
            assert row["pnl_30d"] == 3000.0
            assert row["pnl_90d"] == 8000.0
        finally:
            conn.close()

    def test_upserts_on_duplicate(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        merged_v1 = {
            "0xabc": {
                "address": "0xabc",
                "label": "Old",
                "account_value": 50000.0,
                "roi_7d": 1.0, "roi_30d": 2.0, "roi_90d": 3.0,
                "pnl_7d": 100, "pnl_30d": 200, "pnl_90d": 300,
            }
        }
        _store_traders(db_path, merged_v1)

        merged_v2 = {
            "0xabc": {
                "address": "0xabc",
                "label": "Updated",
                "account_value": 100000.0,
                "roi_7d": 10.0, "roi_30d": 20.0, "roi_90d": 30.0,
                "pnl_7d": 1000, "pnl_30d": 2000, "pnl_90d": 3000,
            }
        }
        _store_traders(db_path, merged_v2)

        conn = get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM traders WHERE address = '0xabc'"
            ).fetchone()
            assert row["label"] == "Updated"
            assert row["account_value"] == 100000.0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Tests: Trade cache
# ---------------------------------------------------------------------------


class TestTradeCache:
    def _insert_trader(self, db_path: str, addr: str) -> None:
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO traders (address) VALUES (?)", (addr,)
                )
        finally:
            conn.close()

    def test_cache_and_retrieve(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        self._insert_trader(db_path, "0xabc")

        trades = [_make_trade(token="BTC"), _make_trade(token="ETH")]
        _cache_trades(db_path, "0xabc", trades)

        cached = _get_cached_trades(db_path, "0xabc", ttl_hours=48)
        assert cached is not None
        assert len(cached) == 2

    def test_returns_none_when_expired(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        self._insert_trader(db_path, "0xabc")

        trades = [_make_trade()]
        _cache_trades(db_path, "0xabc", trades)

        # Backdate the fetched_at to make it stale
        conn = get_connection(db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE trade_history SET fetched_at = '2020-01-01T00:00:00Z'"
                    " WHERE address = '0xabc'"
                )
        finally:
            conn.close()

        cached = _get_cached_trades(db_path, "0xabc", ttl_hours=1)
        assert cached is None

    def test_returns_none_for_unknown_address(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        cached = _get_cached_trades(db_path, "0xunknown", ttl_hours=48)
        assert cached is None

    def test_empty_trades_not_cached(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _cache_trades(db_path, "0xabc", [])
        cached = _get_cached_trades(db_path, "0xabc", ttl_hours=48)
        assert cached is None


# ---------------------------------------------------------------------------
# Tests: collect_trader_data (integration)
# ---------------------------------------------------------------------------


class TestCollectTraderData:
    async def test_full_collection_pipeline(self, tmp_path):
        """End-to-end collection: leaderboard + trades + positions."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        client = AsyncMock()

        # Phase 1: Leaderboard returns 2 traders (on 30d with pnl qualifying)
        client.get_leaderboard = AsyncMock(
            side_effect=[
                [],  # 7d empty
                [
                    _make_leaderboard_entry("0xaaa", account_value=50000, total_pnl=20000),
                    _make_leaderboard_entry("0xbbb", account_value=30000, total_pnl=15000),
                ],
                [],  # 90d empty
            ]
        )

        # Phase 2: Trades for each trader
        client.get_perp_trades = AsyncMock(
            return_value=[_make_trade()]
        )

        # Phase 3: Positions (ingest_positions is called, mock its dependency)
        client.get_perp_positions = AsyncMock(
            return_value={"asset_positions": [], "margin_summary_account_value_usd": "0"}
        )

        summary = await collect_trader_data(client, db_path, min_account_value=25000)

        assert isinstance(summary, CollectionSummary)
        assert summary.traders_fetched == 2
        assert summary.trades_fetched == 2  # both traders qualify
        assert summary.trades_cached == 0
        assert summary.errors == 0
        assert summary.duration_seconds >= 0

    async def test_uses_trade_cache(self, tmp_path):
        """Trades should be served from cache when fresh."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Pre-populate trader + trade cache
        _store_traders(db_path, {
            "0xaaa": {
                "address": "0xaaa", "label": "", "account_value": 50000.0,
                "roi_7d": None, "roi_30d": None, "roi_90d": None,
                "pnl_7d": None, "pnl_30d": None, "pnl_90d": None,
            }
        })
        _cache_trades(db_path, "0xaaa", [_make_trade()])

        client = AsyncMock()
        client.get_leaderboard = AsyncMock(
            side_effect=[
                [],  # 7d
                [_make_leaderboard_entry("0xaaa", account_value=50000, total_pnl=20000)],
                [],  # 90d
            ]
        )
        client.get_perp_positions = AsyncMock(
            return_value={"asset_positions": [], "margin_summary_account_value_usd": "0"}
        )

        summary = await collect_trader_data(client, db_path, min_account_value=25000)

        assert summary.trades_cached == 1
        assert summary.trades_fetched == 0
        # get_perp_trades should NOT have been called
        client.get_perp_trades.assert_not_called()

    async def test_handles_trade_fetch_errors(self, tmp_path):
        """Failed trade fetches should be counted as errors, not crash."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        client = AsyncMock()
        client.get_leaderboard = AsyncMock(
            side_effect=[
                [],  # 7d
                [_make_leaderboard_entry("0xaaa", account_value=50000, total_pnl=20000)],
                [],  # 90d
            ]
        )
        client.get_perp_trades = AsyncMock(side_effect=Exception("API error"))
        client.get_perp_positions = AsyncMock(
            return_value={"asset_positions": [], "margin_summary_account_value_usd": "0"}
        )

        summary = await collect_trader_data(client, db_path, min_account_value=25000)

        assert summary.errors == 1
        assert summary.trades_fetched == 0

    async def test_filters_by_min_account_value(self, tmp_path):
        """Only traders above min_account_value should get trades fetched."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        client = AsyncMock()
        client.get_leaderboard = AsyncMock(
            side_effect=[
                [],  # 7d
                [
                    _make_leaderboard_entry("0xrich", account_value=100000, total_pnl=20000),
                    _make_leaderboard_entry("0xpoor", account_value=1000, total_pnl=20000),
                ],
                [],  # 90d
            ]
        )
        client.get_perp_trades = AsyncMock(return_value=[_make_trade()])
        client.get_perp_positions = AsyncMock(
            return_value={"asset_positions": [], "margin_summary_account_value_usd": "0"}
        )

        summary = await collect_trader_data(client, db_path, min_account_value=50000)

        # Only 0xrich qualifies for trade fetching (acct >= 50k AND pnl_30d >= 10k)
        assert summary.trades_fetched == 1


# ---------------------------------------------------------------------------
# Tests: score_from_cache
# ---------------------------------------------------------------------------


class TestScoreFromCache:
    def test_scores_from_cached_data(self, tmp_path):
        """score_from_cache should work with pre-populated DB data."""
        from snap.scoring import score_from_cache

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # Populate traders table
        _store_traders(db_path, {
            "0xaaa": {
                "address": "0xaaa",
                "label": "Trader A",
                "account_value": 100000.0,
                "roi_7d": 5.0, "roi_30d": 15.0, "roi_90d": 25.0,
                "pnl_7d": 1000, "pnl_30d": 5000, "pnl_90d": 10000,
            },
            "0xbbb": {
                "address": "0xbbb",
                "label": "Trader B",
                "account_value": 80000.0,
                "roi_7d": 3.0, "roi_30d": 10.0, "roi_90d": 20.0,
                "pnl_7d": 500, "pnl_30d": 3000, "pnl_90d": 7000,
            },
        })

        # Score — should not crash even without trade data
        result = score_from_cache(db_path)
        assert isinstance(result, list)

    def test_returns_empty_on_empty_db(self, tmp_path):
        """score_from_cache should return empty list on empty DB."""
        from snap.scoring import score_from_cache

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        result = score_from_cache(db_path)
        assert result == []

    def test_accepts_variant_overrides(self, tmp_path):
        """score_from_cache should accept variant overrides without error."""
        from snap.scoring import score_from_cache

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        _store_traders(db_path, {
            "0xaaa": {
                "address": "0xaaa",
                "label": "",
                "account_value": 100000.0,
                "roi_7d": 5.0, "roi_30d": 15.0, "roi_90d": 25.0,
                "pnl_7d": 1000, "pnl_30d": 5000, "pnl_90d": 10000,
            },
        })

        overrides = {"FILTER_PERCENTILE": 0.30, "WIN_RATE_MIN": 0.20}
        result = score_from_cache(db_path, overrides=overrides)
        assert isinstance(result, list)
