"""Tests for the IndexPortfolio content angle.

Covers detect() scoring, threshold gates, side flip detection, new entry
detection, build_payload() structure, screenshot_config, and edge cases
with missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.content.angles.index_portfolio import IndexPortfolio
from src.content.base import ScreenshotConfig
from src.datastore import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def _seed_portfolio(
    ds: DataStore,
    date,
    token: str,
    side: str,
    target_weight: float,
    target_usd: float = 100_000.0,
) -> None:
    """Insert an index portfolio snapshot row."""
    ds.insert_index_portfolio_snapshot(
        snapshot_date=date,
        token=token,
        side=side,
        target_weight=target_weight,
        target_usd=target_usd,
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
    return IndexPortfolio()


# ===================================================================
# detect() -- above threshold (side flips)
# ===================================================================


class TestDetectAboveThresholdSideFlip:
    """detect() should return a positive score for side flips."""

    def test_two_side_flips(self, ds, angle):
        """Two tokens flipping side should pass threshold."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)  # flip
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25)  # flip
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.20)

        score = angle.detect(ds)
        assert score > 0.0
        # tokens_flipped = 2, score = min(1.0, 2/3) = 0.667
        assert score == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_three_side_flips_capped(self, ds, angle):
        """Three or more flips should score 1.0."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)  # flip
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25)  # flip
        _seed_portfolio(ds, TODAY, "SOL", "LONG", 0.20)   # flip

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)


# ===================================================================
# detect() -- above threshold (new entries)
# ===================================================================


class TestDetectAboveThresholdNewEntry:
    """detect() should return a positive score for new entries meeting threshold."""

    def test_two_new_entries(self, ds, angle):
        """Two new token entries should pass threshold (tokens_flipped >= 2)."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.40)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.20)  # new entry
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.15) # new entry

        score = angle.detect(ds)
        assert score > 0.0

    def test_new_entry_in_top5(self, ds, angle):
        """A single new entry in the top 5 should pass threshold."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.20)  # new entry, top 3

        score = angle.detect(ds)
        assert score > 0.0

    def test_one_flip_one_new_entry(self, ds, angle):
        """One flip + one new entry = 2 tokens_flipped, should pass threshold."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)   # flip
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.15)   # new entry

        score = angle.detect(ds)
        assert score > 0.0
        # tokens_flipped = 2, score = min(1.0, 2/3) = 0.667
        assert score == pytest.approx(2.0 / 3.0, abs=0.01)


# ===================================================================
# detect() -- below threshold
# ===================================================================


class TestDetectBelowThreshold:
    """detect() should return 0 when below threshold."""

    def test_one_side_flip_no_new_entry(self, ds, angle):
        """A single flip with no new entries should not pass (tokens_flipped = 1 < 2)."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)   # flip
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.25)

        score = angle.detect(ds)
        assert score == 0.0

    def test_no_changes(self, ds, angle):
        """Identical portfolios should return 0."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.20)

        score = angle.detect(ds)
        assert score == 0.0

    def test_weight_change_only(self, ds, angle):
        """Weight changes without side flips or new entries should return 0."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.40)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.15)

        score = angle.detect(ds)
        assert score == 0.0

    def test_one_new_entry_not_in_top5(self, ds, angle):
        """A single new entry NOT in the top 5 should not pass threshold."""
        # 5 existing tokens with higher weights
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.15)
        _seed_portfolio(ds, YESTERDAY, "AVAX", "LONG", 0.12)
        _seed_portfolio(ds, YESTERDAY, "LINK", "SHORT", 0.10)

        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.15)
        _seed_portfolio(ds, TODAY, "AVAX", "LONG", 0.12)
        _seed_portfolio(ds, TODAY, "LINK", "SHORT", 0.10)
        _seed_portfolio(ds, TODAY, "DOGE", "LONG", 0.05)  # new, small weight

        score = angle.detect(ds)
        # tokens_flipped = 1 (new entry only), not >= 2
        # DOGE not in top 5 (weight 0.05 is smallest)
        assert score == 0.0


# ===================================================================
# detect() -- missing data
# ===================================================================


class TestDetectMissingData:
    """detect() should return 0 when snapshot data is unavailable."""

    def test_no_today_data(self, ds, angle):
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        assert angle.detect(ds) == 0.0

    def test_no_yesterday_data(self, ds, angle):
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        assert angle.detect(ds) == 0.0

    def test_empty_database(self, ds, angle):
        assert angle.detect(ds) == 0.0

    def test_both_days_empty(self, ds, angle):
        assert angle.detect(ds) == 0.0


# ===================================================================
# Scoring formula
# ===================================================================


class TestScoringFormula:
    """Verify the scoring formula: min(1.0, tokens_flipped / 3)."""

    def test_1_token_flipped_with_top5_entry(self, ds, angle):
        """1 new entry in top 5 -> score = min(1.0, 1/3) = 0.333"""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.25)  # new entry in top 5

        score = angle.detect(ds)
        # tokens_flipped = 1, passes because new entry in top 5
        assert score == pytest.approx(1.0 / 3.0, abs=0.01)

    def test_2_tokens_flipped(self, ds, angle):
        """2 flipped -> score = min(1.0, 2/3) = 0.667"""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.20)

        score = angle.detect(ds)
        assert score == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_3_tokens_flipped(self, ds, angle):
        """3 flipped -> score = 1.0"""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25)
        _seed_portfolio(ds, TODAY, "SOL", "LONG", 0.20)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_4_tokens_flipped_clamped(self, ds, angle):
        """4 flipped -> clamped to 1.0"""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.15)
        _seed_portfolio(ds, YESTERDAY, "AVAX", "LONG", 0.10)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.25)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "SOL", "LONG", 0.15)
        _seed_portfolio(ds, TODAY, "AVAX", "SHORT", 0.10)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)


# ===================================================================
# Side flip + new entry detection
# ===================================================================


class TestSideFlipAndNewEntryDetection:
    """Verify correct classification of side flips and new entries."""

    def test_side_flip_long_to_short(self, ds, angle):
        """LONG -> SHORT should be detected as a side flip."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)   # flip
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25)   # flip

        angle.detect(ds)
        data = angle._portfolio_data
        assert data["tokens_flipped"] == 2
        assert len(data["flipped_tokens"]) == 2

        btc_flip = next(f for f in data["flipped_tokens"] if f["token"] == "BTC")
        assert btc_flip["old_side"] == "LONG"
        assert btc_flip["new_side"] == "SHORT"
        assert btc_flip["old_weight"] == 0.30
        assert btc_flip["new_weight"] == 0.30

    def test_side_flip_short_to_long(self, ds, angle):
        """SHORT -> LONG should be detected as a side flip."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "SHORT", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "SHORT", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.25)

        angle.detect(ds)
        data = angle._portfolio_data
        flips = data["flipped_tokens"]
        assert all(f["old_side"] == "SHORT" and f["new_side"] == "LONG" for f in flips)

    def test_new_entry_detected(self, ds, angle):
        """A token in today but not yesterday should be classified as new entry."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.20)  # new entry, in top 5

        angle.detect(ds)
        data = angle._portfolio_data
        assert len(data["new_entries"]) == 1
        assert data["new_entries"][0]["token"] == "SOL"
        assert data["new_entries"][0]["side"] == "SHORT"
        assert data["new_entries"][0]["weight"] == 0.20

    def test_mix_of_flips_and_entries(self, ds, angle):
        """A mix of side flips and new entries should be counted together."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)   # flip
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.15)   # new entry

        angle.detect(ds)
        data = angle._portfolio_data
        assert data["tokens_flipped"] == 2
        assert len(data["flipped_tokens"]) == 1
        assert len(data["new_entries"]) == 1

    def test_token_disappears_not_counted(self, ds, angle):
        """A token in yesterday but not today (removed) should NOT count as a flip."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30)   # flip
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25)   # flip
        # SOL disappears

        angle.detect(ds)
        data = angle._portfolio_data
        assert data["tokens_flipped"] == 2
        assert len(data["flipped_tokens"]) == 2
        assert len(data["new_entries"]) == 0


# ===================================================================
# Top-5 new entry logic
# ===================================================================


class TestTop5NewEntry:
    """Verify the top-5 threshold for single new entries."""

    def test_new_entry_in_top5_triggers(self, ds, angle):
        """A single new entry with a high weight (top 5) should trigger."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, TODAY, "SOL", "LONG", 0.15)  # new, 3rd place

        score = angle.detect(ds)
        assert score > 0.0

    def test_new_entry_at_6th_place_no_trigger(self, ds, angle):
        """A single new entry at 6th place should NOT trigger alone."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.25)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, YESTERDAY, "SOL", "SHORT", 0.15)
        _seed_portfolio(ds, YESTERDAY, "AVAX", "LONG", 0.12)
        _seed_portfolio(ds, YESTERDAY, "LINK", "SHORT", 0.10)

        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "ETH", "LONG", 0.20)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.15)
        _seed_portfolio(ds, TODAY, "AVAX", "LONG", 0.12)
        _seed_portfolio(ds, TODAY, "LINK", "SHORT", 0.10)
        _seed_portfolio(ds, TODAY, "DOGE", "LONG", 0.03)  # new, 6th place

        score = angle.detect(ds)
        assert score == 0.0


# ===================================================================
# build_payload()
# ===================================================================


class TestBuildPayload:
    """build_payload() should produce a valid, complete payload dict."""

    def test_payload_structure(self, ds, angle):
        """Payload should contain all expected top-level keys."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30, 150_000.0)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25, 125_000.0)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30, 150_000.0)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25, 125_000.0)

        score = angle.detect(ds)
        assert score > 0.0

        payload = angle.build_payload(ds)

        assert payload["post_worthy"] is True
        assert payload["snapshot_date"] == TODAY.isoformat()
        assert payload["tokens_flipped"] == 2
        assert isinstance(payload["flipped_tokens"], list)
        assert isinstance(payload["new_entries"], list)
        assert isinstance(payload["portfolio_today"], list)
        assert len(payload["flipped_tokens"]) == 2
        assert len(payload["new_entries"]) == 0

    def test_payload_flipped_token_structure(self, ds, angle):
        """Flipped token entries should have the right keys."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.35)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.20)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        btc = next(f for f in payload["flipped_tokens"] if f["token"] == "BTC")
        assert btc["old_side"] == "LONG"
        assert btc["new_side"] == "SHORT"
        assert btc["old_weight"] == 0.30
        assert btc["new_weight"] == 0.35

    def test_payload_new_entry_structure(self, ds, angle):
        """New entry entries should have the right keys."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "BTC", "LONG", 0.30)
        _seed_portfolio(ds, TODAY, "SOL", "SHORT", 0.20)  # top 5 entry

        angle.detect(ds)
        payload = angle.build_payload(ds)

        assert len(payload["new_entries"]) == 1
        sol = payload["new_entries"][0]
        assert sol["token"] == "SOL"
        assert sol["side"] == "SHORT"
        assert sol["weight"] == 0.20

    def test_payload_portfolio_today(self, ds, angle):
        """portfolio_today should reflect all tokens in today's snapshot."""
        _seed_portfolio(ds, YESTERDAY, "BTC", "LONG", 0.30, 150_000.0)
        _seed_portfolio(ds, YESTERDAY, "ETH", "LONG", 0.25, 125_000.0)
        _seed_portfolio(ds, TODAY, "BTC", "SHORT", 0.30, 150_000.0)
        _seed_portfolio(ds, TODAY, "ETH", "SHORT", 0.25, 125_000.0)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        tokens_in_portfolio = {p["token"] for p in payload["portfolio_today"]}
        assert "BTC" in tokens_in_portfolio
        assert "ETH" in tokens_in_portfolio

        btc = next(p for p in payload["portfolio_today"] if p["token"] == "BTC")
        assert btc["side"] == "SHORT"
        assert btc["target_weight"] == 0.30
        assert btc["target_usd"] == 150_000.0

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
        assert page.route == "/allocations"
        assert page.filename == "index_portfolio.png"
        assert "allocation-dashboard" in page.wait_selector
        assert "allocation-strategies" in page.capture_selector
        assert page.pre_capture_js is not None
        assert "scrollIntoView" in page.pre_capture_js


# ===================================================================
# Class attributes
# ===================================================================


class TestClassAttributes:
    """Verify class-level attributes."""

    def test_angle_type(self, angle):
        assert angle.angle_type == "index_portfolio"

    def test_auto_publish(self, angle):
        assert angle.auto_publish is True

    def test_cooldown_days(self, angle):
        assert angle.cooldown_days == 4

    def test_tone(self, angle):
        assert angle.tone == "neutral"

    def test_prompt_path(self, angle):
        assert angle.prompt_path == "src/content/prompts/index_portfolio.md"
