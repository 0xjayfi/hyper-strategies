"""Tests for the AllocationShift content angle.

Covers detect() scoring, threshold gates, entry/exit detection,
weight change detection, build_payload() structure, screenshot_config,
and edge cases with missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.content.angles.allocation_shift import AllocationShift
from src.content.base import ScreenshotConfig
from src.datastore import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def _seed_allocation(
    ds: DataStore,
    date,
    trader_id: str,
    weight: float,
) -> None:
    """Insert an allocation snapshot row."""
    ds.insert_allocation_snapshot(
        snapshot_date=date,
        trader_id=trader_id,
        weight=weight,
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
    return AllocationShift()


# ===================================================================
# detect() -- above threshold (entry/exit)
# ===================================================================


class TestDetectAboveThresholdEntryExit:
    """detect() should return a positive score when entries or exits occur."""

    def test_new_entry(self, ds, angle):
        """A trader entering the portfolio should pass threshold."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xBBB", 0.15)  # entry

        score = angle.detect(ds)
        assert score > 0.0
        assert score == pytest.approx(0.6, abs=0.01)

    def test_exit(self, ds, angle):
        """A trader exiting the portfolio should pass threshold."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.15)
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)
        # 0xBBB exits

        score = angle.detect(ds)
        assert score > 0.0
        assert score == pytest.approx(0.6, abs=0.01)

    def test_entry_and_exit_together(self, ds, angle):
        """An entry and an exit at the same time should trigger detection."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.30)
        _seed_allocation(ds, TODAY, "0xBBB", 0.25)  # entry; 0xAAA exits

        score = angle.detect(ds)
        assert score > 0.0


# ===================================================================
# detect() -- above threshold (weight change)
# ===================================================================


class TestDetectAboveThresholdWeightChange:
    """detect() should trigger for large weight changes."""

    def test_weight_change_10pp(self, ds, angle):
        """A 10pp weight change should pass threshold."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.30)

        score = angle.detect(ds)
        assert score > 0.0
        # score = min(1.0, 0.10 / 0.25) = 0.4
        assert score == pytest.approx(0.4, abs=0.01)

    def test_weight_change_25pp_max(self, ds, angle):
        """A 25pp weight change should give score = 1.0."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.10)
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_weight_change_50pp_clamped(self, ds, angle):
        """A 50pp weight change should clamp to 1.0."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.10)
        _seed_allocation(ds, TODAY, "0xAAA", 0.60)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_weight_decrease(self, ds, angle):
        """A weight decrease of >= 10pp should also trigger."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.40)
        _seed_allocation(ds, TODAY, "0xAAA", 0.25)

        score = angle.detect(ds)
        assert score > 0.0
        # delta = 0.15, score = min(1.0, 0.15 / 0.25) = 0.6
        assert score == pytest.approx(0.6, abs=0.01)


# ===================================================================
# detect() -- below threshold
# ===================================================================


class TestDetectBelowThreshold:
    """detect() should return 0 when below threshold."""

    def test_small_weight_change(self, ds, angle):
        """A 5pp weight change with no entry/exit should return 0."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.25)

        score = angle.detect(ds)
        assert score == 0.0

    def test_tiny_weight_change(self, ds, angle):
        """A 1pp weight change should return 0."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.21)

        score = angle.detect(ds)
        assert score == 0.0

    def test_identical_snapshots(self, ds, angle):
        """Identical data both days should return 0."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.30)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.30)
        _seed_allocation(ds, TODAY, "0xBBB", 0.20)

        score = angle.detect(ds)
        assert score == 0.0

    def test_9pp_weight_change(self, ds, angle):
        """A 9pp weight change without entry/exit should return 0."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.29)

        score = angle.detect(ds)
        assert score == 0.0


# ===================================================================
# detect() -- missing data
# ===================================================================


class TestDetectMissingData:
    """detect() should return 0 when snapshot data is unavailable."""

    def test_no_today_data(self, ds, angle):
        """Only yesterday data -- detects exits but should still work."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)

        # This has exits (0xAAA exits), so should detect
        score = angle.detect(ds)
        assert score > 0.0
        assert score == pytest.approx(0.6, abs=0.01)

    def test_no_yesterday_data(self, ds, angle):
        """Only today data -- detects entries."""
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)

        score = angle.detect(ds)
        assert score > 0.0
        assert score == pytest.approx(0.6, abs=0.01)

    def test_empty_database(self, ds, angle):
        assert angle.detect(ds) == 0.0

    def test_both_days_empty(self, ds, angle):
        """No data for either day should return 0."""
        assert angle.detect(ds) == 0.0


# ===================================================================
# Scoring formula
# ===================================================================


class TestScoringFormula:
    """Verify the scoring formulas with specific numbers."""

    def test_entry_flat_score(self, ds, angle):
        """An entry gets flat 0.6."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xBBB", 0.10)

        score = angle.detect(ds)
        assert score == pytest.approx(0.6, abs=0.01)

    def test_exit_flat_score(self, ds, angle):
        """An exit gets flat 0.6."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.10)
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)

        score = angle.detect(ds)
        assert score == pytest.approx(0.6, abs=0.01)

    def test_weight_10pp_score(self, ds, angle):
        """10pp weight change -> min(1.0, 0.10/0.25) = 0.4"""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.30)

        score = angle.detect(ds)
        assert score == pytest.approx(0.4, abs=0.01)

    def test_weight_20pp_score(self, ds, angle):
        """20pp weight change -> min(1.0, 0.20/0.25) = 0.8"""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.40)

        score = angle.detect(ds)
        assert score == pytest.approx(0.8, abs=0.01)

    def test_weight_25pp_score(self, ds, angle):
        """25pp weight change -> min(1.0, 0.25/0.25) = 1.0"""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.10)
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_entry_plus_large_weight_change(self, ds, angle):
        """Entry (0.6) + 20pp weight change (0.8) -> max = 0.8"""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.10)
        _seed_allocation(ds, TODAY, "0xAAA", 0.30)  # 20pp change
        _seed_allocation(ds, TODAY, "0xBBB", 0.15)  # entry

        score = angle.detect(ds)
        assert score == pytest.approx(0.8, abs=0.01)

    def test_max_of_multiple_weight_changes(self, ds, angle):
        """The largest weight delta should determine the score."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.10)
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)  # 15pp
        _seed_allocation(ds, TODAY, "0xBBB", 0.22)  # 12pp

        score = angle.detect(ds)
        # max delta = 0.15, score = min(1.0, 0.15/0.25) = 0.6
        assert score == pytest.approx(0.6, abs=0.01)


# ===================================================================
# Entry/exit detection
# ===================================================================


class TestEntryExitDetection:
    """Verify entry and exit detection logic."""

    def test_single_entry_detected(self, ds, angle):
        """A single new trader should be detected as an entry."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.30)
        _seed_allocation(ds, TODAY, "0xAAA", 0.30)
        _seed_allocation(ds, TODAY, "0xNEW", 0.15)

        angle.detect(ds)
        changes = angle._shift_data["changes"]
        entries = [c for c in changes if c["change_type"] == "entry"]
        assert len(entries) == 1
        assert entries[0]["trader_id"] == "0xNEW"
        assert entries[0]["new_weight"] == 0.15
        assert entries[0]["old_weight"] is None

    def test_single_exit_detected(self, ds, angle):
        """A trader disappearing should be detected as an exit."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.30)
        _seed_allocation(ds, YESTERDAY, "0xGONE", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.30)

        angle.detect(ds)
        changes = angle._shift_data["changes"]
        exits = [c for c in changes if c["change_type"] == "exit"]
        assert len(exits) == 1
        assert exits[0]["trader_id"] == "0xGONE"
        assert exits[0]["old_weight"] == 0.20
        assert exits[0]["new_weight"] is None

    def test_weight_change_detected(self, ds, angle):
        """A weight change should be detected with correct delta."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)

        angle.detect(ds)
        changes = angle._shift_data["changes"]
        weight_changes = [c for c in changes if c["change_type"] == "weight_change"]
        assert len(weight_changes) == 1
        assert weight_changes[0]["trader_id"] == "0xAAA"
        assert weight_changes[0]["old_weight"] == 0.20
        assert weight_changes[0]["new_weight"] == 0.35
        assert weight_changes[0]["weight_delta"] == pytest.approx(0.15, abs=0.001)

    def test_multiple_changes(self, ds, angle):
        """Multiple changes of different types should all be detected."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.15)  # will exit
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)  # weight change
        _seed_allocation(ds, TODAY, "0xCCC", 0.10)  # entry

        angle.detect(ds)
        changes = angle._shift_data["changes"]

        types = {c["change_type"] for c in changes}
        assert types == {"entry", "exit", "weight_change"}


# ===================================================================
# build_payload()
# ===================================================================


class TestBuildPayload:
    """build_payload() should produce a valid, complete payload dict."""

    def test_payload_structure(self, ds, angle):
        """Payload should contain all expected top-level keys."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.15)
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)  # weight change
        _seed_allocation(ds, TODAY, "0xCCC", 0.10)  # entry
        # 0xBBB exits

        score = angle.detect(ds)
        assert score > 0.0

        payload = angle.build_payload(ds)

        assert payload["post_worthy"] is True
        assert payload["snapshot_date"] == TODAY.isoformat()
        assert isinstance(payload["changes"], list)
        assert payload["total_entries"] == 1
        assert payload["total_exits"] == 1
        assert payload["total_weight_changes"] == 1
        assert isinstance(payload["max_weight_delta"], float)
        assert payload["max_weight_delta"] == pytest.approx(0.15, abs=0.01)

    def test_payload_change_entry(self, ds, angle):
        """Entry change in payload should have correct structure."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xNEW", 0.15)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        entries = [c for c in payload["changes"] if c["change_type"] == "entry"]
        assert len(entries) == 1
        entry = entries[0]
        assert entry["trader_id"] == "0xNEW"
        assert entry["old_weight"] is None
        assert entry["new_weight"] == 0.15
        assert entry["weight_delta"] is None

    def test_payload_change_exit(self, ds, angle):
        """Exit change in payload should have correct structure."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, YESTERDAY, "0xBBB", 0.15)
        _seed_allocation(ds, TODAY, "0xAAA", 0.20)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        exits = [c for c in payload["changes"] if c["change_type"] == "exit"]
        assert len(exits) == 1
        ex = exits[0]
        assert ex["trader_id"] == "0xBBB"
        assert ex["old_weight"] == 0.15
        assert ex["new_weight"] is None
        assert ex["weight_delta"] is None

    def test_payload_change_weight_change(self, ds, angle):
        """Weight change in payload should have correct structure."""
        _seed_allocation(ds, YESTERDAY, "0xAAA", 0.20)
        _seed_allocation(ds, TODAY, "0xAAA", 0.35)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        wcs = [c for c in payload["changes"] if c["change_type"] == "weight_change"]
        assert len(wcs) == 1
        wc = wcs[0]
        assert wc["trader_id"] == "0xAAA"
        assert wc["old_weight"] == 0.20
        assert wc["new_weight"] == 0.35
        assert wc["weight_delta"] == pytest.approx(0.15, abs=0.001)

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
        assert page.filename == "allocation_shift.png"
        assert "allocation-dashboard" in page.wait_selector
        assert "allocation-dashboard" in page.capture_selector


# ===================================================================
# Class attributes
# ===================================================================


class TestClassAttributes:
    """Verify class-level attributes."""

    def test_angle_type(self, angle):
        assert angle.angle_type == "allocation_shift"

    def test_auto_publish(self, angle):
        assert angle.auto_publish is True

    def test_cooldown_days(self, angle):
        assert angle.cooldown_days == 3

    def test_tone(self, angle):
        assert angle.tone == "neutral"

    def test_prompt_path(self, angle):
        assert angle.prompt_path == "src/content/prompts/allocation_shift.md"
