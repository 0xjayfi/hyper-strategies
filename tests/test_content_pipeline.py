"""Tests for the content pipeline: score snapshots + mover detection."""

import pytest
from datetime import date
from pathlib import Path
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


from datetime import datetime, timezone
from src.scheduler import save_daily_score_snapshot


class TestDailyScoreSnapshot:

    def test_save_snapshot_from_scores(self, ds):
        ds.upsert_trader("0xAAA", label="Smart Trader")
        ds.upsert_trader("0xBBB", label="Regular")

        ds.insert_score("0xAAA", {
            "normalized_roi": 0.72,
            "normalized_sharpe": 0.99,
            "normalized_win_rate": 0.85,
            "consistency_score": 0.60,
            "smart_money_bonus": 1.08,
            "risk_management_score": 1.00,
            "style_multiplier": 0.88,
            "recency_decay": 1.0,
            "raw_composite_score": 0.80,
            "final_score": 0.80,
            "roi_tier_multiplier": 1.0,
            "passes_anti_luck": 1,
        })
        ds.insert_score("0xBBB", {
            "normalized_roi": 0.50,
            "normalized_sharpe": 0.60,
            "normalized_win_rate": 0.70,
            "consistency_score": 0.40,
            "smart_money_bonus": 1.0,
            "risk_management_score": 0.80,
            "style_multiplier": 0.50,
            "recency_decay": 0.90,
            "raw_composite_score": 0.55,
            "final_score": 0.55,
            "roi_tier_multiplier": 1.0,
            "passes_anti_luck": 1,
        })

        today = date(2026, 3, 8)
        save_daily_score_snapshot(ds, today)

        rows = ds.get_score_snapshots_for_date(today)
        assert len(rows) == 2
        assert rows[0]["trader_id"] == "0xAAA"
        assert rows[0]["rank"] == 1
        assert rows[0]["composite_score"] == 0.80
        assert rows[1]["trader_id"] == "0xBBB"
        assert rows[1]["rank"] == 2

    def test_save_snapshot_empty_scores(self, ds):
        """No scores means no snapshot rows."""
        save_daily_score_snapshot(ds, date(2026, 3, 8))
        rows = ds.get_score_snapshots_for_date(date(2026, 3, 8))
        assert rows == []


from src.content_pipeline import detect_score_movers, generate_content_payload
from src.chart_generator import generate_charts


class TestDetectScoreMovers:

    def _seed_two_days(self, ds):
        """Seed snapshots for day1 and day2 with a rank change."""
        ds.upsert_trader("0xAAA", label="Smart Trader")
        ds.upsert_trader("0xBBB", label="Token Millionaire")
        ds.upsert_trader("0xCCC", label="Whale")

        for addr, rank, score in [
            ("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65), ("0xCCC", 3, 0.50),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7),
                trader_id=addr, rank=rank, composite_score=score,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        for addr, rank, score, growth in [
            ("0xBBB", 1, 0.85, 0.90),
            ("0xCCC", 2, 0.70, 0.60),
            ("0xAAA", 3, 0.55, 0.30),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 8),
                trader_id=addr, rank=rank, composite_score=score,
                growth_score=growth, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

    def test_detects_rank_mover(self, ds):
        self._seed_two_days(ds)
        movers = detect_score_movers(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert len(movers) >= 1
        addresses = [m["address"] for m in movers]
        assert "0xAAA" in addresses

    def test_detects_score_delta_mover(self, ds):
        self._seed_two_days(ds)
        movers = detect_score_movers(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
            min_score_delta=0.10,
        )
        addresses = [m["address"] for m in movers]
        assert "0xBBB" in addresses
        assert "0xAAA" in addresses

    def test_no_movers_when_stable(self, ds):
        ds.upsert_trader("0xAAA", label="Stable")
        for d in [date(2026, 3, 7), date(2026, 3, 8)]:
            ds.insert_score_snapshot(
                snapshot_date=d, trader_id="0xAAA", rank=1,
                composite_score=0.80,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )
        movers = detect_score_movers(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert movers == []


class TestGenerateContentPayload:

    def test_generates_payload_for_top_mover(self, ds):
        ds.upsert_trader("0xBBB", label="Token Millionaire")
        ds.upsert_trader("0xAAA", label="Smart Trader")
        for addr, rank, score in [("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65)]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )
        for addr, rank, score in [("0xBBB", 1, 0.85), ("0xAAA", 2, 0.55)]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 8), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=0.9, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        payload = generate_content_payload(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert payload["post_worthy"] is True
        assert payload["wallet"]["address"] in ("0xBBB", "0xAAA")
        assert "change" in payload
        assert "top_movers" in payload
        assert "context" in payload

    def test_not_post_worthy_when_no_movers(self, ds):
        ds.upsert_trader("0xAAA", label="Stable")
        for d in [date(2026, 3, 7), date(2026, 3, 8)]:
            ds.insert_score_snapshot(
                snapshot_date=d, trader_id="0xAAA", rank=1,
                composite_score=0.80,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )
        payload = generate_content_payload(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert payload["post_worthy"] is False


class TestFullPipelineIntegration:

    def test_end_to_end_payload_generation(self, ds, tmp_path):
        """Full pipeline: seed data -> detect movers -> generate payload -> generate charts."""
        # Seed traders
        ds.upsert_trader("0xAAA", label="Smart Trader")
        ds.upsert_trader("0xBBB", label="Token Millionaire")
        ds.upsert_trader("0xCCC", label="Whale")

        # Day 1 snapshots
        for addr, rank, score in [
            ("0xAAA", 1, 0.80), ("0xBBB", 2, 0.65), ("0xCCC", 3, 0.50),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 7), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=0.5, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        # Day 2 snapshots with a big mover
        for addr, rank, score, growth in [
            ("0xBBB", 1, 0.85, 0.90),
            ("0xCCC", 2, 0.70, 0.60),
            ("0xAAA", 3, 0.55, 0.30),
        ]:
            ds.insert_score_snapshot(
                snapshot_date=date(2026, 3, 8), trader_id=addr,
                rank=rank, composite_score=score,
                growth_score=growth, drawdown_score=0.5, leverage_score=0.5,
                liq_distance_score=0.5, diversity_score=0.5,
                consistency_score=0.5, smart_money=False,
            )

        # Generate payload
        payload = generate_content_payload(
            ds, today=date(2026, 3, 8), yesterday=date(2026, 3, 7),
        )
        assert payload["post_worthy"] is True
        assert payload["wallet"]["address"] in ("0xBBB", "0xAAA")
        assert payload["change"]["score_delta"] is not None

        # Generate charts from the payload
        chart_dir = str(tmp_path / "charts")
        chart_paths = generate_charts(payload, output_dir=chart_dir, count=2)
        assert len(chart_paths) >= 1
        for p in chart_paths:
            path = Path(p)
            assert path.exists()
            assert path.suffix == ".png"
            assert path.stat().st_size > 1000  # Not an empty/trivial image
