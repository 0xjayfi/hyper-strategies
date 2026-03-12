"""Tests for the SmartMoneyConsensus content angle.

Covers detect() scoring, threshold gates, direction flip detection,
confidence swing detection, build_payload() structure, screenshot_config,
and edge cases with missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.content.angles.smart_money_consensus import SmartMoneyConsensus
from src.content.base import ScreenshotConfig
from src.datastore import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def _seed_consensus(
    ds: DataStore,
    date,
    token: str,
    direction: str,
    confidence_pct: float,
    *,
    sm_long_usd: float | None = None,
    sm_short_usd: float | None = None,
) -> None:
    """Insert a consensus snapshot row."""
    ds.insert_consensus_snapshot(
        snapshot_date=date,
        token=token,
        direction=direction,
        confidence_pct=confidence_pct,
        sm_long_usd=sm_long_usd,
        sm_short_usd=sm_short_usd,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ds():
    """Yield an in-memory DataStore, then close it."""
    store = DataStore(db_path=":memory:")
    yield store
    store.close()


@pytest.fixture
def angle():
    return SmartMoneyConsensus()


# ===================================================================
# detect() -- above threshold (direction flip)
# ===================================================================


class TestDetectAboveThresholdFlip:
    """detect() should return a positive score when a direction flip occurs."""

    def test_direction_flip_basic(self, ds, angle):
        """A simple LONG->SHORT flip should pass threshold."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 65.0, sm_long_usd=1500000.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 42.0, sm_short_usd=2100000.0)

        score = angle.detect(ds)
        assert score > 0.0

    def test_direction_flip_triggers_even_with_zero_swing(self, ds, angle):
        """A flip with 0 confidence swing should still pass threshold."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 50.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 50.0)

        score = angle.detect(ds)
        assert score > 0.0
        # score = min(1.0, 0.7 + 0/40) = 0.7
        assert score == pytest.approx(0.7, abs=0.01)

    def test_flip_on_one_token_triggers_for_multi_token(self, ds, angle):
        """A flip on just one of several tokens should pass threshold."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 62.0)

        _seed_consensus(ds, YESTERDAY, "ETH", "SHORT", 55.0)
        _seed_consensus(ds, TODAY, "ETH", "LONG", 52.0)  # flip!

        score = angle.detect(ds)
        assert score > 0.0


# ===================================================================
# detect() -- above threshold (confidence swing >= 20pp)
# ===================================================================


class TestDetectAboveThresholdSwing:
    """detect() should trigger for large confidence swings without a flip."""

    def test_confidence_swing_20pp(self, ds, angle):
        """A 20pp swing without flip should pass threshold."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 40.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 60.0)

        score = angle.detect(ds)
        assert score > 0.0
        # score = min(1.0, 20/40) = 0.5
        assert score == pytest.approx(0.5, abs=0.01)

    def test_confidence_swing_30pp(self, ds, angle):
        """A 30pp swing should score higher."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 40.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 70.0)

        score = angle.detect(ds)
        # score = min(1.0, 30/40) = 0.75
        assert score == pytest.approx(0.75, abs=0.01)

    def test_confidence_swing_exactly_20pp_boundary(self, ds, angle):
        """Exactly 20pp swing is right at the boundary -- should pass."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 50.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 70.0)

        score = angle.detect(ds)
        assert score > 0.0


# ===================================================================
# detect() -- below threshold
# ===================================================================


class TestDetectBelowThreshold:
    """detect() should return 0 when below threshold."""

    def test_no_flip_small_swing(self, ds, angle):
        """No flip and only 10pp swing should return 0."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 70.0)

        # 10pp < 20pp, no flip -> 0
        # Wait: 10pp swing. threshold is >= 20. So this should be 0.
        # score = 10/40 = 0.25 but threshold not met -> 0
        score = angle.detect(ds)
        assert score == 0.0

    def test_no_flip_19pp_swing(self, ds, angle):
        """19pp swing without flip should be below threshold."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 50.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 69.0)

        score = angle.detect(ds)
        assert score == 0.0

    def test_identical_snapshots(self, ds, angle):
        """Identical data both days should return 0."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 60.0)

        score = angle.detect(ds)
        assert score == 0.0


# ===================================================================
# detect() -- missing data
# ===================================================================


class TestDetectMissingData:
    """detect() should return 0 when snapshot data is unavailable."""

    def test_no_today_data(self, ds, angle):
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 60.0)
        assert angle.detect(ds) == 0.0

    def test_no_yesterday_data(self, ds, angle):
        _seed_consensus(ds, TODAY, "BTC", "LONG", 60.0)
        assert angle.detect(ds) == 0.0

    def test_empty_database(self, ds, angle):
        assert angle.detect(ds) == 0.0

    def test_token_only_in_today(self, ds, angle):
        """A token only present today (new token) with no flip should return 0."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "ETH", "SHORT", 55.0)  # no yesterday for ETH

        score = angle.detect(ds)
        # BTC has no flip and 0 swing -> below threshold
        assert score == 0.0


# ===================================================================
# Scoring formula
# ===================================================================


class TestScoringFormula:
    """Verify the scoring formulas with specific numbers."""

    def test_flip_with_zero_swing(self, ds, angle):
        """Flip + 0 swing -> min(1.0, 0.7 + 0/40) = 0.7"""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 50.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 50.0)

        score = angle.detect(ds)
        assert score == pytest.approx(0.7, abs=0.01)

    def test_flip_with_12pp_swing(self, ds, angle):
        """Flip + 12pp swing -> min(1.0, 0.7 + 12/40) = 0.7 + 0.3 = 1.0"""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 56.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 44.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_flip_with_6pp_swing(self, ds, angle):
        """Flip + 6pp swing -> min(1.0, 0.7 + 6/40) = 0.85"""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 53.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 47.0)

        score = angle.detect(ds)
        assert score == pytest.approx(0.85, abs=0.01)

    def test_no_flip_40pp_swing_clamped(self, ds, angle):
        """No flip + 40pp swing -> min(1.0, 40/40) = 1.0"""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 30.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 70.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_no_flip_50pp_swing_clamped(self, ds, angle):
        """No flip + 50pp swing -> min(1.0, 50/40) = 1.0 (clamped)"""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 20.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 70.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_best_token_selected(self, ds, angle):
        """With multiple tokens, the highest-scoring one should be picked."""
        # BTC: no flip, 25pp swing -> score = 25/40 = 0.625
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 50.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 75.0)

        # ETH: flip + 5pp swing -> score = min(1.0, 0.7 + 5/40) = 0.825
        _seed_consensus(ds, YESTERDAY, "ETH", "SHORT", 55.0)
        _seed_consensus(ds, TODAY, "ETH", "LONG", 50.0)

        score = angle.detect(ds)
        # ETH score (0.825) > BTC score (0.625) -> best_token = ETH
        assert score == pytest.approx(0.825, abs=0.01)
        assert angle._consensus_data["best_token"]["token"] == "ETH"


# ===================================================================
# Direction flip detection
# ===================================================================


class TestDirectionFlipDetection:
    """Verify that direction flips are correctly detected."""

    def test_long_to_short(self, ds, angle):
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 55.0)

        angle.detect(ds)
        best = angle._consensus_data["best_token"]
        assert best["direction_flipped"] is True
        assert best["old_direction"] == "LONG"
        assert best["new_direction"] == "SHORT"

    def test_short_to_long(self, ds, angle):
        _seed_consensus(ds, YESTERDAY, "BTC", "SHORT", 60.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 55.0)

        angle.detect(ds)
        best = angle._consensus_data["best_token"]
        assert best["direction_flipped"] is True
        assert best["old_direction"] == "SHORT"
        assert best["new_direction"] == "LONG"

    def test_same_direction_no_flip(self, ds, angle):
        """No flip when direction stays the same with large swing."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 40.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 70.0)

        angle.detect(ds)
        best = angle._consensus_data["best_token"]
        assert best["direction_flipped"] is False
        assert best["old_direction"] == "LONG"
        assert best["new_direction"] == "LONG"


# ===================================================================
# build_payload()
# ===================================================================


class TestBuildPayload:
    """build_payload() should produce a valid, complete payload dict."""

    def test_payload_structure(self, ds, angle):
        """Payload should contain all expected top-level keys."""
        _seed_consensus(
            ds, YESTERDAY, "BTC", "LONG", 65.0,
            sm_long_usd=1500000.0, sm_short_usd=500000.0,
        )
        _seed_consensus(
            ds, TODAY, "BTC", "SHORT", 42.0,
            sm_long_usd=800000.0, sm_short_usd=2100000.0,
        )

        score = angle.detect(ds)
        assert score > 0.0

        payload = angle.build_payload(ds)

        assert payload["post_worthy"] is True
        assert payload["snapshot_date"] == TODAY.isoformat()
        assert payload["token"] == "BTC"
        assert payload["direction_flipped"] is True
        assert payload["old_direction"] == "LONG"
        assert payload["new_direction"] == "SHORT"
        assert payload["old_confidence_pct"] == 65.0
        assert payload["new_confidence_pct"] == 42.0
        assert payload["confidence_swing"] == 23.0
        assert payload["sm_long_usd"] == 800000.0
        assert payload["sm_short_usd"] == 2100000.0
        assert isinstance(payload["all_token_changes"], list)
        assert len(payload["all_token_changes"]) >= 1

    def test_payload_values_no_flip(self, ds, angle):
        """Payload values should be correct for a large swing without flip."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 40.0)
        _seed_consensus(ds, TODAY, "BTC", "LONG", 65.0)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        assert payload["direction_flipped"] is False
        assert payload["old_direction"] == "LONG"
        assert payload["new_direction"] == "LONG"
        assert payload["confidence_swing"] == 25.0

    def test_payload_all_token_changes(self, ds, angle):
        """all_token_changes should include all tokens that changed."""
        _seed_consensus(ds, YESTERDAY, "BTC", "LONG", 50.0)
        _seed_consensus(ds, TODAY, "BTC", "SHORT", 50.0)

        _seed_consensus(ds, YESTERDAY, "ETH", "LONG", 60.0)
        _seed_consensus(ds, TODAY, "ETH", "LONG", 60.0)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        # ETH has 0 swing and no flip -> score = 0, but it should still
        # be in all_token_changes if it was compared
        tokens = [c["token"] for c in payload["all_token_changes"]]
        assert "BTC" in tokens

    def test_build_payload_asserts_without_detect(self, angle):
        """build_payload should raise AssertionError if detect wasn't called."""
        with pytest.raises(AssertionError, match="detect"):
            angle.build_payload(None)


# ===================================================================
# screenshot_config()
# ===================================================================


class TestScreenshotConfig:
    """screenshot_config() should return the expected page captures."""

    def test_screenshot_pages(self, angle):
        config = angle.screenshot_config()
        assert isinstance(config, ScreenshotConfig)
        assert len(config.pages) == 1

        page = config.pages[0]
        assert page.route == "/market"
        assert page.filename == "market_consensus.png"
        assert "market-overview" in page.wait_selector
        assert "market-overview" in page.capture_selector


# ===================================================================
# Class attributes
# ===================================================================


class TestClassAttributes:
    """Verify class-level attributes."""

    def test_angle_type(self, angle):
        assert angle.angle_type == "smart_money_consensus"

    def test_auto_publish(self, angle):
        assert angle.auto_publish is False

    def test_cooldown_days(self, angle):
        assert angle.cooldown_days == 3

    def test_tone(self, angle):
        assert angle.tone == "analytical"

    def test_prompt_path(self, angle):
        assert angle.prompt_path == "src/content/prompts/smart_money_consensus.md"
