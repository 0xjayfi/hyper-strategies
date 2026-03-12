"""Tests for the WalletSpotlight content angle.

Covers detect() scoring, threshold gates, build_payload() structure,
the top-5 entry/exit floor, and edge cases with missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.content.angles.wallet_spotlight import WalletSpotlight
from src.content.base import ScreenshotConfig
from src.datastore import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def _seed_snapshot(
    ds: DataStore,
    date,
    trader_id: str,
    rank: int,
    composite: float,
    *,
    growth: float = 0.5,
    drawdown: float = 0.5,
    leverage: float = 0.5,
    liq_distance: float = 0.5,
    diversity: float = 0.5,
    consistency: float = 0.5,
    smart_money: bool = False,
) -> None:
    """Insert a score snapshot with sensible defaults."""
    ds.insert_score_snapshot(
        snapshot_date=date,
        trader_id=trader_id,
        rank=rank,
        composite_score=composite,
        growth_score=growth,
        drawdown_score=drawdown,
        leverage_score=leverage,
        liq_distance_score=liq_distance,
        diversity_score=diversity,
        consistency_score=consistency,
        smart_money=smart_money,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def ds():
    """Yield an in-memory DataStore, then close it."""
    store = DataStore(db_path=":memory:")
    yield store
    store.close()


@pytest.fixture
def angle():
    return WalletSpotlight()


# ===================================================================
# detect() — above threshold
# ===================================================================


class TestDetectAboveThreshold:
    """detect() should return a positive score for significant movers."""

    def test_large_score_delta(self, ds, angle):
        """A score increase of 0.15 should trigger detection."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=3, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=3, composite=0.65)

        # Filler wallets to avoid empty snapshot days
        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        assert score > 0.0
        assert angle._mover is not None
        assert angle._mover["address"] == "0xAAA"

    def test_large_rank_change(self, ds, angle):
        """A rank change of 3 positions should trigger detection."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=8, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=5, composite=0.52)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        assert score > 0.0

    def test_top5_entry_triggers_floor(self, ds, angle):
        """Entering top 5 should guarantee at least 0.5 score."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=6, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=4, composite=0.55)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        assert score >= 0.5

    def test_top5_exit_triggers_floor(self, ds, angle):
        """Exiting top 5 should guarantee at least 0.5 score."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=5, composite=0.60)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=7, composite=0.52)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        assert score >= 0.5

    def test_new_entrant_in_top5(self, ds, angle):
        """A brand-new wallet in top 5 (not present yesterday) triggers floor."""
        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        # 0xNEW only appears today
        _seed_snapshot(ds, TODAY, "0xNEW", rank=3, composite=0.70)

        score = angle.detect(ds)
        assert score >= 0.5
        assert angle._mover["new_entrant"] is True


# ===================================================================
# detect() — below threshold
# ===================================================================


class TestDetectBelowThreshold:
    """detect() should return 0 for insignificant changes."""

    def test_small_changes_return_zero(self, ds, angle):
        """Rank change of 1 and score delta of 0.05 should be below threshold."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=3, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=2, composite=0.55)

        # This wallet doesn't move at all
        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        assert score == 0.0

    def test_no_change_returns_zero(self, ds, angle):
        """Identical snapshots should return 0."""
        for addr, rank, comp in [("0xA", 1, 0.9), ("0xB", 2, 0.8)]:
            _seed_snapshot(ds, YESTERDAY, addr, rank, comp)
            _seed_snapshot(ds, TODAY, addr, rank, comp)

        score = angle.detect(ds)
        assert score == 0.0


# ===================================================================
# detect() — missing data
# ===================================================================


class TestDetectMissingData:
    """detect() should return 0 when snapshot data is unavailable."""

    def test_no_today_data(self, ds, angle):
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=1, composite=0.90)
        assert angle.detect(ds) == 0.0

    def test_no_yesterday_data(self, ds, angle):
        _seed_snapshot(ds, TODAY, "0xAAA", rank=1, composite=0.90)
        assert angle.detect(ds) == 0.0

    def test_empty_database(self, ds, angle):
        assert angle.detect(ds) == 0.0


# ===================================================================
# Scoring formula
# ===================================================================


class TestScoringFormula:
    """Verify the scoring formula with specific numbers."""

    def test_formula_score_delta_only(self, ds, angle):
        """score_delta=0.30, rank_change=0 -> raw = (0.30/0.30)*0.5 + 0 = 0.5"""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=3, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=3, composite=0.80)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        # raw = (0.30 / 0.30) * 0.5 + (0 / 10) * 0.5 = 0.5
        assert score == pytest.approx(0.5, abs=0.01)

    def test_formula_rank_change_only(self, ds, angle):
        """score_delta=0.10, rank_change=5 -> raw = (0.10/0.30)*0.5 + (5/10)*0.5"""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=10, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=5, composite=0.60)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        # rank 10->5 enters top 5, so top5_floor = 0.5
        # raw = (0.10/0.30)*0.5 + (5/10)*0.5 = 0.1667 + 0.25 = 0.4167
        # max(0.5, min(1.0, 0.4167)) = 0.5 (floor dominates)
        assert score >= 0.5

    def test_formula_combined_large(self, ds, angle):
        """score_delta=0.60, rank_change=8 -> raw clamped to 1.0"""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=12, composite=0.20)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=4, composite=0.80)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        # raw = (0.60/0.30)*0.5 + (8/10)*0.5 = 1.0 + 0.4 = 1.4 -> clamped to 1.0
        assert score == pytest.approx(1.0, abs=0.01)

    def test_top5_floor_guarantees_minimum(self, ds, angle):
        """When entering top 5 with small raw score, floor should apply."""
        # rank 6->5 with tiny score delta = small raw score
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=6, composite=0.50)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=5, composite=0.50)

        # Need rank change >= 2 or top5 entry to pass threshold
        # rank change = 1, score delta = 0 -> but top5 entry triggers threshold
        # Wait — rank_delta=1, score_delta=0, so the mover detection requires
        # entered_top_n to pass the filter in _detect_score_movers.
        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        # raw = (0/0.30)*0.5 + (1/10)*0.5 = 0.05
        # max(0.5, min(1.0, 0.05)) = 0.5
        assert score == pytest.approx(0.5, abs=0.01)


# ===================================================================
# build_payload()
# ===================================================================


class TestBuildPayload:
    """build_payload() should produce a valid, complete payload dict."""

    def test_payload_structure(self, ds, angle):
        """Payload should contain all expected top-level keys."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=5, composite=0.50, growth=0.6, drawdown=0.4)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=2, composite=0.70, growth=0.8, drawdown=0.5)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        score = angle.detect(ds)
        assert score > 0

        payload = angle.build_payload(ds)

        assert payload["post_worthy"] is True
        assert payload["snapshot_date"] == TODAY.isoformat()

        # wallet
        assert "address" in payload["wallet"]
        assert "label" in payload["wallet"]
        assert "smart_money" in payload["wallet"]

        # change
        change = payload["change"]
        assert "old_rank" in change
        assert "new_rank" in change
        assert "rank_delta" in change
        assert "old_score" in change
        assert "new_score" in change
        assert "score_delta" in change
        assert "new_entrant" in change

        # dimensions
        assert isinstance(payload["current_dimensions"], dict)
        assert isinstance(payload["previous_dimensions"], dict)
        assert "growth" in payload["current_dimensions"]
        assert "growth" in payload["previous_dimensions"]

        # top_movers
        assert isinstance(payload["top_movers"], list)

        # current_positions (empty without nansen_client)
        assert payload["current_positions"] == []

        # context
        assert "top_5_wallets" in payload["context"]
        assert isinstance(payload["context"]["top_5_wallets"], list)

    def test_payload_mover_values(self, ds, angle):
        """Payload change values should match the seeded data."""
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=8, composite=0.40)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=3, composite=0.65)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        assert payload["wallet"]["address"] == "0xAAA"
        assert payload["change"]["old_rank"] == 8
        assert payload["change"]["new_rank"] == 3
        assert payload["change"]["rank_delta"] == 5
        assert payload["change"]["old_score"] == pytest.approx(0.40)
        assert payload["change"]["new_score"] == pytest.approx(0.65)
        assert payload["change"]["score_delta"] == pytest.approx(0.25)
        assert payload["change"]["new_entrant"] is False

    def test_payload_with_new_entrant(self, ds, angle):
        """A new entrant should have None for old values."""
        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xNEW", rank=2, composite=0.80)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        assert payload["wallet"]["address"] == "0xNEW"
        assert payload["change"]["old_rank"] is None
        assert payload["change"]["old_score"] is None
        assert payload["change"]["new_entrant"] is True

    def test_top_movers_populated(self, ds, angle):
        """top_movers should list dimension changes."""
        _seed_snapshot(
            ds, YESTERDAY, "0xAAA", rank=5, composite=0.50,
            growth=0.3, drawdown=0.5, leverage=0.5,
        )
        _seed_snapshot(
            ds, TODAY, "0xAAA", rank=2, composite=0.70,
            growth=0.7, drawdown=0.3, leverage=0.5,
        )

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        dims = {m["dimension"] for m in payload["top_movers"]}
        assert "growth" in dims
        assert "drawdown" in dims


# ===================================================================
# screenshot_config()
# ===================================================================


class TestScreenshotConfig:
    """screenshot_config() should return the expected page captures."""

    def test_screenshot_pages(self, ds, angle):
        _seed_snapshot(ds, YESTERDAY, "0xAAA", rank=8, composite=0.40)
        _seed_snapshot(ds, TODAY, "0xAAA", rank=3, composite=0.65)

        _seed_snapshot(ds, YESTERDAY, "0xBBB", rank=1, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xBBB", rank=1, composite=0.90)

        angle.detect(ds)
        config = angle.screenshot_config()

        assert isinstance(config, ScreenshotConfig)
        assert len(config.pages) == 3

        # Page 1: leaderboard
        assert config.pages[0].route == "/leaderboard"
        assert config.pages[0].filename == "leaderboard_top5.png"
        assert config.pages[0].pre_capture_js is not None

        # Page 2: trader scoring
        assert "/traders/0xAAA" in config.pages[1].route
        assert config.pages[1].filename == "trader_scoring.png"

        # Page 3: trader positions
        assert "/traders/0xAAA" in config.pages[2].route
        assert config.pages[2].filename == "trader_positions.png"
