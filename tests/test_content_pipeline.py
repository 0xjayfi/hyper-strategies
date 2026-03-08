"""Tests for the content pipeline: score snapshots + mover detection."""

import pytest
from datetime import date
from src.datastore import DataStore


@pytest.fixture
def ds():
    with DataStore(":memory:") as store:
        yield store


class TestScoreSnapshots:

    def test_insert_and_get_snapshot(self, ds):
        ds.upsert_trader("0xAAA", label="Test Trader")
        ds.insert_score_snapshot(
            snapshot_date=date(2026, 3, 7),
            trader_id="0xAAA",
            rank=1,
            composite_score=0.80,
            growth_score=0.72,
            drawdown_score=0.99,
            leverage_score=0.85,
            liq_distance_score=1.00,
            diversity_score=0.88,
            consistency_score=0.60,
            smart_money=True,
        )
        rows = ds.get_score_snapshots_for_date(date(2026, 3, 7))
        assert len(rows) == 1
        assert rows[0]["trader_id"] == "0xAAA"
        assert rows[0]["composite_score"] == 0.80
        assert rows[0]["rank"] == 1
        assert rows[0]["smart_money"] == 1

    def test_get_snapshot_returns_empty_for_missing_date(self, ds):
        rows = ds.get_score_snapshots_for_date(date(2026, 1, 1))
        assert rows == []

    def test_multiple_traders_same_date(self, ds):
        ds.upsert_trader("0xAAA", label="Trader A")
        ds.upsert_trader("0xBBB", label="Trader B")
        for addr, rank, score in [("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65)]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7),
                trader_id=addr,
                rank=rank,
                composite_score=score,
                growth_score=0.5,
                drawdown_score=0.5,
                leverage_score=0.5,
                liq_distance_score=0.5,
                diversity_score=0.5,
                consistency_score=0.5,
                smart_money=False,
            )
        rows = ds.get_score_snapshots_for_date(date(2026, 3, 7))
        assert len(rows) == 2
