"""Tests for the content-pipeline datastore tables and CRUD methods.

Uses an in-memory DataStore to verify insert + retrieval for each new
table, UNIQUE constraint upserts, get_last_post_date, get_smart_money_addresses,
and enforce_retention coverage of the new tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.datastore import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _iso_past(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ds():
    """Yield an in-memory DataStore, then close it."""
    store = DataStore(db_path=":memory:")
    yield store
    store.close()


# ===================================================================
# Content Posts
# ===================================================================


class TestContentPosts:
    """Tests for content_posts insert and retrieval."""

    def test_insert_and_query_content_post(self, ds: DataStore) -> None:
        """A content post should be persisted and queryable."""
        ds.insert_content_post(
            post_date="2026-03-10",
            angle_type="wallet_spotlight",
            raw_score=0.85,
            effective_score=0.90,
            auto_published=False,
            typefully_url="https://typefully.com/abc",
            payload_path="data/payloads/ws_2026-03-10.json",
        )

        row = ds._conn.execute(
            "SELECT * FROM content_posts WHERE angle_type = ?",
            ("wallet_spotlight",),
        ).fetchone()

        assert row is not None
        assert row["post_date"] == "2026-03-10"
        assert row["raw_score"] == pytest.approx(0.85)
        assert row["effective_score"] == pytest.approx(0.90)
        assert row["auto_published"] == 0
        assert row["typefully_url"] == "https://typefully.com/abc"
        assert row["payload_path"] == "data/payloads/ws_2026-03-10.json"
        assert row["created_at"] is not None

    def test_insert_content_post_auto_published(self, ds: DataStore) -> None:
        """auto_published=True should be stored as 1."""
        ds.insert_content_post(
            post_date="2026-03-10",
            angle_type="leaderboard_shakeup",
            raw_score=0.70,
            effective_score=0.75,
            auto_published=True,
        )

        row = ds._conn.execute(
            "SELECT auto_published FROM content_posts WHERE angle_type = ?",
            ("leaderboard_shakeup",),
        ).fetchone()
        assert row["auto_published"] == 1

    def test_get_last_post_date(self, ds: DataStore) -> None:
        """get_last_post_date should return the most recent post_date for the angle."""
        ds.insert_content_post("2026-03-08", "wallet_spotlight", 0.5, 0.6)
        ds.insert_content_post("2026-03-10", "wallet_spotlight", 0.7, 0.8)
        ds.insert_content_post("2026-03-06", "wallet_spotlight", 0.4, 0.5)

        result = ds.get_last_post_date("wallet_spotlight")
        assert result == "2026-03-10"

    def test_get_last_post_date_none(self, ds: DataStore) -> None:
        """get_last_post_date should return None when no posts exist for the angle."""
        result = ds.get_last_post_date("nonexistent_angle")
        assert result is None

    def test_get_last_post_date_different_angles(self, ds: DataStore) -> None:
        """Posts for different angles should be independent."""
        ds.insert_content_post("2026-03-10", "wallet_spotlight", 0.7, 0.8)
        ds.insert_content_post("2026-03-12", "leaderboard_shakeup", 0.9, 0.95)

        assert ds.get_last_post_date("wallet_spotlight") == "2026-03-10"
        assert ds.get_last_post_date("leaderboard_shakeup") == "2026-03-12"

    def test_multiple_posts_same_angle_not_replaced(self, ds: DataStore) -> None:
        """content_posts uses plain INSERT; multiple posts for the same angle are allowed."""
        ds.insert_content_post("2026-03-10", "wallet_spotlight", 0.5, 0.6)
        ds.insert_content_post("2026-03-10", "wallet_spotlight", 0.7, 0.8)

        rows = ds._conn.execute(
            "SELECT * FROM content_posts WHERE angle_type = ?",
            ("wallet_spotlight",),
        ).fetchall()
        assert len(rows) == 2


# ===================================================================
# Consensus Snapshots
# ===================================================================


class TestConsensusSnapshots:
    """Tests for consensus_snapshots insert and retrieval."""

    def test_insert_and_get_consensus_snapshot(self, ds: DataStore) -> None:
        """A consensus snapshot should round-trip through insert + get."""
        ds.insert_consensus_snapshot(
            snapshot_date="2026-03-10",
            token="BTC",
            direction="long",
            confidence_pct=72.5,
            sm_long_usd=1_500_000.0,
            sm_short_usd=500_000.0,
        )

        rows = ds.get_consensus_snapshots_for_date("2026-03-10")
        assert len(rows) == 1
        row = rows[0]
        assert row["token"] == "BTC"
        assert row["direction"] == "long"
        assert row["confidence_pct"] == pytest.approx(72.5)
        assert row["sm_long_usd"] == pytest.approx(1_500_000.0)
        assert row["sm_short_usd"] == pytest.approx(500_000.0)

    def test_get_consensus_snapshots_empty(self, ds: DataStore) -> None:
        """Should return empty list for a date with no snapshots."""
        rows = ds.get_consensus_snapshots_for_date("2026-01-01")
        assert rows == []

    def test_consensus_unique_constraint_replaces(self, ds: DataStore) -> None:
        """INSERT OR REPLACE should overwrite on (snapshot_date, token) conflict."""
        ds.insert_consensus_snapshot("2026-03-10", "BTC", "long", 72.5)
        ds.insert_consensus_snapshot("2026-03-10", "BTC", "short", 60.0)

        rows = ds.get_consensus_snapshots_for_date("2026-03-10")
        assert len(rows) == 1
        assert rows[0]["direction"] == "short"
        assert rows[0]["confidence_pct"] == pytest.approx(60.0)

    def test_multiple_tokens_same_date(self, ds: DataStore) -> None:
        """Different tokens on the same date should coexist."""
        ds.insert_consensus_snapshot("2026-03-10", "BTC", "long", 72.5)
        ds.insert_consensus_snapshot("2026-03-10", "ETH", "short", 55.0)

        rows = ds.get_consensus_snapshots_for_date("2026-03-10")
        assert len(rows) == 2
        tokens = {r["token"] for r in rows}
        assert tokens == {"BTC", "ETH"}


# ===================================================================
# Allocation Snapshots
# ===================================================================


class TestAllocationSnapshots:
    """Tests for allocation_snapshots insert and retrieval."""

    def test_insert_and_get_allocation_snapshot(self, ds: DataStore) -> None:
        """An allocation snapshot should round-trip through insert + get."""
        ds.insert_allocation_snapshot("2026-03-10", "0xAAA", 0.35)
        ds.insert_allocation_snapshot("2026-03-10", "0xBBB", 0.25)

        rows = ds.get_allocation_snapshots_for_date("2026-03-10")
        assert len(rows) == 2
        # Ordered by weight DESC
        assert rows[0]["trader_id"] == "0xAAA"
        assert rows[0]["weight"] == pytest.approx(0.35)
        assert rows[1]["trader_id"] == "0xBBB"
        assert rows[1]["weight"] == pytest.approx(0.25)

    def test_get_allocation_snapshots_empty(self, ds: DataStore) -> None:
        """Should return empty list for a date with no snapshots."""
        rows = ds.get_allocation_snapshots_for_date("2026-01-01")
        assert rows == []

    def test_allocation_unique_constraint_replaces(self, ds: DataStore) -> None:
        """INSERT OR REPLACE should overwrite on (snapshot_date, trader_id) conflict."""
        ds.insert_allocation_snapshot("2026-03-10", "0xAAA", 0.35)
        ds.insert_allocation_snapshot("2026-03-10", "0xAAA", 0.50)

        rows = ds.get_allocation_snapshots_for_date("2026-03-10")
        assert len(rows) == 1
        assert rows[0]["weight"] == pytest.approx(0.50)


# ===================================================================
# Index Portfolio Snapshots
# ===================================================================


class TestIndexPortfolioSnapshots:
    """Tests for index_portfolio_snapshots insert and retrieval."""

    def test_insert_and_get_index_portfolio_snapshot(self, ds: DataStore) -> None:
        """An index portfolio snapshot should round-trip through insert + get."""
        ds.insert_index_portfolio_snapshot(
            "2026-03-10", "BTC", "long", 0.40, 40000.0
        )
        ds.insert_index_portfolio_snapshot(
            "2026-03-10", "ETH", "long", 0.30, 30000.0
        )

        rows = ds.get_index_portfolio_snapshots_for_date("2026-03-10")
        assert len(rows) == 2
        # Ordered by token ASC, side ASC
        assert rows[0]["token"] == "BTC"
        assert rows[0]["target_weight"] == pytest.approx(0.40)
        assert rows[0]["target_usd"] == pytest.approx(40000.0)
        assert rows[1]["token"] == "ETH"

    def test_get_index_portfolio_snapshots_empty(self, ds: DataStore) -> None:
        """Should return empty list for a date with no snapshots."""
        rows = ds.get_index_portfolio_snapshots_for_date("2026-01-01")
        assert rows == []

    def test_index_portfolio_unique_constraint_replaces(self, ds: DataStore) -> None:
        """INSERT OR REPLACE should overwrite on (snapshot_date, token, side) conflict."""
        ds.insert_index_portfolio_snapshot("2026-03-10", "BTC", "long", 0.40, 40000.0)
        ds.insert_index_portfolio_snapshot("2026-03-10", "BTC", "long", 0.50, 50000.0)

        rows = ds.get_index_portfolio_snapshots_for_date("2026-03-10")
        assert len(rows) == 1
        assert rows[0]["target_weight"] == pytest.approx(0.50)
        assert rows[0]["target_usd"] == pytest.approx(50000.0)

    def test_same_token_different_sides(self, ds: DataStore) -> None:
        """Same token with different sides should coexist."""
        ds.insert_index_portfolio_snapshot("2026-03-10", "BTC", "long", 0.30, 30000.0)
        ds.insert_index_portfolio_snapshot("2026-03-10", "BTC", "short", 0.10, 10000.0)

        rows = ds.get_index_portfolio_snapshots_for_date("2026-03-10")
        assert len(rows) == 2
        sides = {r["side"] for r in rows}
        assert sides == {"long", "short"}


# ===================================================================
# Smart Money Addresses
# ===================================================================


class TestSmartMoneyAddresses:
    """Tests for get_smart_money_addresses."""

    def test_get_smart_money_addresses(self, ds: DataStore) -> None:
        """Should return correct set of smart money trader IDs for a date."""
        # Insert score snapshots — some smart money, some not
        ds.insert_score_snapshot(
            snapshot_date="2026-03-10", trader_id="0xSM1", rank=1,
            composite_score=0.9, growth_score=0.8, drawdown_score=0.7,
            leverage_score=0.6, liq_distance_score=0.5, diversity_score=0.4,
            consistency_score=0.3, smart_money=True,
        )
        ds.insert_score_snapshot(
            snapshot_date="2026-03-10", trader_id="0xSM2", rank=2,
            composite_score=0.85, growth_score=0.7, drawdown_score=0.6,
            leverage_score=0.5, liq_distance_score=0.4, diversity_score=0.3,
            consistency_score=0.2, smart_money=True,
        )
        ds.insert_score_snapshot(
            snapshot_date="2026-03-10", trader_id="0xREG", rank=3,
            composite_score=0.5, growth_score=0.4, drawdown_score=0.3,
            leverage_score=0.2, liq_distance_score=0.1, diversity_score=0.1,
            consistency_score=0.1, smart_money=False,
        )

        result = ds.get_smart_money_addresses("2026-03-10")
        assert result == {"0xSM1", "0xSM2"}

    def test_get_smart_money_addresses_empty(self, ds: DataStore) -> None:
        """Should return empty set when no score snapshots exist for the date."""
        result = ds.get_smart_money_addresses("2026-01-01")
        assert result == set()

    def test_get_smart_money_addresses_different_dates(self, ds: DataStore) -> None:
        """Smart money queries for different dates should be independent."""
        ds.insert_score_snapshot(
            snapshot_date="2026-03-10", trader_id="0xSM1", rank=1,
            composite_score=0.9, growth_score=0.8, drawdown_score=0.7,
            leverage_score=0.6, liq_distance_score=0.5, diversity_score=0.4,
            consistency_score=0.3, smart_money=True,
        )
        ds.insert_score_snapshot(
            snapshot_date="2026-03-11", trader_id="0xSM2", rank=1,
            composite_score=0.85, growth_score=0.7, drawdown_score=0.6,
            leverage_score=0.5, liq_distance_score=0.4, diversity_score=0.3,
            consistency_score=0.2, smart_money=True,
        )

        assert ds.get_smart_money_addresses("2026-03-10") == {"0xSM1"}
        assert ds.get_smart_money_addresses("2026-03-11") == {"0xSM2"}


# ===================================================================
# Enforce Retention — new tables
# ===================================================================


class TestEnforceRetentionContentTables:
    """Tests that enforce_retention deletes old rows from the new content tables."""

    def test_enforce_retention_content_posts(self, ds: DataStore) -> None:
        """Old content posts should be deleted; recent ones kept."""
        old_date = "2025-01-01"
        recent_date = _iso_now()[:10]  # YYYY-MM-DD

        ds.insert_content_post(old_date, "wallet_spotlight", 0.5, 0.6)
        ds.insert_content_post(recent_date, "wallet_spotlight", 0.7, 0.8)

        ds.enforce_retention(days=90)

        rows = ds._conn.execute("SELECT * FROM content_posts").fetchall()
        assert len(rows) == 1
        assert rows[0]["post_date"] == recent_date

    def test_enforce_retention_consensus_snapshots(self, ds: DataStore) -> None:
        """Old consensus snapshots should be deleted; recent ones kept."""
        old_date = "2025-01-01"
        recent_date = _iso_now()[:10]

        ds.insert_consensus_snapshot(old_date, "BTC", "long", 72.5)
        ds.insert_consensus_snapshot(recent_date, "ETH", "short", 55.0)

        ds.enforce_retention(days=90)

        rows = ds._conn.execute("SELECT * FROM consensus_snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0]["snapshot_date"] == recent_date

    def test_enforce_retention_allocation_snapshots(self, ds: DataStore) -> None:
        """Old allocation snapshots should be deleted; recent ones kept."""
        old_date = "2025-01-01"
        recent_date = _iso_now()[:10]

        ds.insert_allocation_snapshot(old_date, "0xOLD", 0.5)
        ds.insert_allocation_snapshot(recent_date, "0xNEW", 0.5)

        ds.enforce_retention(days=90)

        rows = ds._conn.execute("SELECT * FROM allocation_snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0]["snapshot_date"] == recent_date

    def test_enforce_retention_index_portfolio_snapshots(self, ds: DataStore) -> None:
        """Old index portfolio snapshots should be deleted; recent ones kept."""
        old_date = "2025-01-01"
        recent_date = _iso_now()[:10]

        ds.insert_index_portfolio_snapshot(old_date, "BTC", "long", 0.4, 40000.0)
        ds.insert_index_portfolio_snapshot(recent_date, "ETH", "long", 0.3, 30000.0)

        ds.enforce_retention(days=90)

        rows = ds._conn.execute(
            "SELECT * FROM index_portfolio_snapshots"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["snapshot_date"] == recent_date
