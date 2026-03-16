"""Tests for the multi-angle content dispatcher.

Covers:
- detect_and_select picks highest effective_score angle
- Cooldown blocking (angle within cooldown gets score 0)
- Freshness boost math
- Second angle only picked if score >= 0.5
- All angles below threshold -> no selections, no file written
- take_daily_snapshots calls correct functions
- Allocation snapshot population from get_latest_allocations
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import (
    CONTENT_FRESHNESS_BOOST_PER_DAY,
    CONTENT_MAX_FRESHNESS_BOOST,
    CONTENT_SECOND_POST_MIN_SCORE,
)
from src.content.base import ContentAngle, ScreenshotConfig
from src.content.dispatcher import (
    _DATA_DIR,
    detect_and_select,
    take_consensus_snapshot,
    take_daily_snapshots,
    take_index_portfolio_snapshot,
)
from src.datastore import DataStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = datetime.now(timezone.utc).date()
YESTERDAY = TODAY - timedelta(days=1)


def _insert_post(ds: DataStore, angle_type: str, post_date) -> None:
    """Insert a minimal content_posts row matching the real schema."""
    ds._conn.execute(
        """INSERT INTO content_posts
           (post_date, angle_type, raw_score, effective_score, created_at)
           VALUES (?, ?, 0.5, 0.5, ?)""",
        (post_date.isoformat() if hasattr(post_date, "isoformat") else str(post_date),
         angle_type,
         datetime.now(timezone.utc).isoformat()),
    )
    ds._conn.commit()


class StubAngle(ContentAngle):
    """Minimal concrete angle for testing the dispatcher logic."""

    def __init__(
        self,
        angle_type: str,
        raw_score: float = 0.0,
        cooldown_days: int = 2,
        auto_publish: bool = False,
        tone: str = "analytical",
    ) -> None:
        self.angle_type = angle_type
        self.cooldown_days = cooldown_days
        self.auto_publish = auto_publish
        self.tone = tone
        self._raw_score = raw_score

    def detect(self, datastore, nansen_client=None) -> float:
        return self._raw_score

    def build_payload(self, datastore, nansen_client=None) -> dict:
        return {"angle_type": self.angle_type, "data": "test"}

    def screenshot_config(self) -> ScreenshotConfig:
        return ScreenshotConfig()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ds():
    """Yield an in-memory DataStore, then close it."""
    store = DataStore(db_path=":memory:")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def clean_data_dir():
    """Remove any payload/selection files written during tests."""
    yield
    for name in os.listdir(_DATA_DIR) if os.path.isdir(_DATA_DIR) else []:
        if name.startswith("content_payload_") or name == "content_selections.json":
            try:
                os.remove(os.path.join(_DATA_DIR, name))
            except OSError:
                pass


# ===================================================================
# detect_and_select — basic selection
# ===================================================================


class TestDetectAndSelectBasic:
    """detect_and_select picks the highest effective_score angle."""

    def test_picks_highest_score(self, ds):
        angles = [
            StubAngle("low", raw_score=0.3),
            StubAngle("high", raw_score=0.8),
            StubAngle("mid", raw_score=0.5),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) >= 1
        assert result[0]["angle_type"] == "high"

    def test_all_zero_scores_no_selection(self, ds):
        angles = [
            StubAngle("a", raw_score=0.0),
            StubAngle("b", raw_score=0.0),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert result == []
        selections_path = os.path.join(_DATA_DIR, "content_selections.json")
        assert not os.path.exists(selections_path)

    def test_writes_payload_and_selections(self, ds):
        angles = [StubAngle("test_angle", raw_score=0.7)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 1
        assert result[0]["angle_type"] == "test_angle"

        # Verify payload file written
        payload_path = os.path.join(_DATA_DIR, "content_payload_test_angle.json")
        assert os.path.exists(payload_path)
        with open(payload_path) as f:
            payload = json.load(f)
        assert payload["angle_type"] == "test_angle"

        # Verify selections file written
        selections_path = os.path.join(_DATA_DIR, "content_selections.json")
        assert os.path.exists(selections_path)
        with open(selections_path) as f:
            selections = json.load(f)
        assert len(selections) == 1
        assert selections[0]["angle_type"] == "test_angle"
        assert "raw_score" in selections[0]
        assert "effective_score" in selections[0]
        assert "auto_publish" in selections[0]
        assert "payload_path" in selections[0]


# ===================================================================
# detect_and_select — cooldown blocking
# ===================================================================


class TestCooldownBlocking:
    """Angle within cooldown gets effective_score = 0."""

    def test_cooldown_blocks_angle(self, ds):
        """An angle posted yesterday with cooldown_days=2 should be blocked."""
        # Insert a content_post record for yesterday
        _insert_post(ds, "blocked_angle", YESTERDAY)

        angles = [
            StubAngle("blocked_angle", raw_score=0.9, cooldown_days=2),
            StubAngle("free_angle", raw_score=0.3),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        # blocked_angle should be blocked (1 day since post, cooldown=2)
        # free_angle should be selected
        assert len(result) >= 1
        assert result[0]["angle_type"] == "free_angle"

    def test_cooldown_expired_allows_angle(self, ds):
        """An angle posted 3 days ago with cooldown_days=2 should be allowed."""
        _insert_post(ds, "recovered_angle", TODAY - timedelta(days=3))

        angles = [StubAngle("recovered_angle", raw_score=0.6, cooldown_days=2)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 1
        assert result[0]["angle_type"] == "recovered_angle"

    def test_cooldown_exact_boundary(self, ds):
        """Posted exactly cooldown_days ago — should be allowed (days_since == cooldown)."""
        _insert_post(ds, "boundary_angle", TODAY - timedelta(days=2))

        angles = [StubAngle("boundary_angle", raw_score=0.6, cooldown_days=2)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 1
        assert result[0]["angle_type"] == "boundary_angle"


# ===================================================================
# detect_and_select — freshness boost math
# ===================================================================


class TestFreshnessBoost:
    """Verify the freshness boost formula."""

    def test_never_posted_gets_max_boost(self, ds):
        """An angle that has never been posted gets CONTENT_MAX_FRESHNESS_BOOST."""
        angles = [StubAngle("fresh", raw_score=0.5)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        expected = 0.5 * CONTENT_MAX_FRESHNESS_BOOST
        assert result[0]["effective_score"] == pytest.approx(expected, abs=0.001)

    def test_just_off_cooldown_no_extra_boost(self, ds):
        """Posted exactly cooldown_days ago -> boost = 1.0 (no extra days)."""
        _insert_post(ds, "exact", TODAY - timedelta(days=2))

        angles = [StubAngle("exact", raw_score=0.5, cooldown_days=2)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        # days_since_last=2, cooldown=2 -> boost = min(1.3, 1.0 + 0*0.05) = 1.0
        assert result[0]["effective_score"] == pytest.approx(0.5, abs=0.001)

    def test_extra_days_add_boost(self, ds):
        """Posted 5 days ago with cooldown=2 -> 3 extra days of boost."""
        _insert_post(ds, "stale", TODAY - timedelta(days=5))

        angles = [StubAngle("stale", raw_score=0.5, cooldown_days=2)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        # days_since_last=5, cooldown=2 -> boost = min(1.3, 1.0 + 3*0.05) = 1.15
        expected = 0.5 * 1.15
        assert result[0]["effective_score"] == pytest.approx(expected, abs=0.001)

    def test_boost_capped_at_max(self, ds):
        """Many extra days should cap the boost at CONTENT_MAX_FRESHNESS_BOOST."""
        _insert_post(ds, "old", TODAY - timedelta(days=30))

        angles = [StubAngle("old", raw_score=0.5, cooldown_days=2)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        # days_since_last=30, cooldown=2 -> boost = min(1.3, 1.0 + 28*0.05) = min(1.3, 2.4) = 1.3
        expected = 0.5 * CONTENT_MAX_FRESHNESS_BOOST
        assert result[0]["effective_score"] == pytest.approx(expected, abs=0.001)

    def test_freshness_boost_breaks_tie(self, ds):
        """With equal raw scores, freshness boost should favor the staler angle."""
        # Angle A: posted 3 days ago (cooldown=2, boost=1.05)
        _insert_post(ds, "recent", TODAY - timedelta(days=3))
        # Angle B: never posted (boost=1.3)

        angles = [
            StubAngle("recent", raw_score=0.6, cooldown_days=2),
            StubAngle("never_posted", raw_score=0.6),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert result[0]["angle_type"] == "never_posted"


# ===================================================================
# detect_and_select — second post threshold
# ===================================================================


class TestSecondPostThreshold:
    """Second angle only picked if effective_score >= 0.5."""

    def test_second_angle_picked_above_threshold(self, ds):
        """Two strong angles should both be selected."""
        angles = [
            StubAngle("first", raw_score=0.8),
            StubAngle("second", raw_score=0.6),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 2
        assert result[0]["angle_type"] == "first"
        assert result[1]["angle_type"] == "second"

    def test_second_angle_rejected_below_threshold(self, ds):
        """Second angle with effective_score < 0.5 should not be selected."""
        # raw=0.3 * boost=1.3 = 0.39 < 0.5
        angles = [
            StubAngle("first", raw_score=0.8),
            StubAngle("weak", raw_score=0.3),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 1
        assert result[0]["angle_type"] == "first"

    def test_only_one_angle_available(self, ds):
        """A single angle should still be selected if score > 0."""
        angles = [StubAngle("solo", raw_score=0.4)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 1
        assert result[0]["angle_type"] == "solo"

    def test_second_angle_at_exact_threshold(self, ds):
        """Second angle with effective_score == 0.5 should be selected."""
        # raw = 0.5 / 1.3 ~ 0.385 -> effective = 0.385 * 1.3 = 0.5
        # Easier: use a raw_score that gives exactly 0.5 after max boost
        # raw * 1.3 = 0.5 -> raw ~ 0.3846
        # Actually, let's just set a post date so the boost works out.
        # Never posted: effective = raw * 1.3
        # We want effective >= 0.5 -> raw >= 0.5/1.3 ~ 0.385
        angles = [
            StubAngle("first", raw_score=0.9),
            StubAngle("borderline", raw_score=0.385),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        # effective = 0.385 * 1.3 = 0.5005 >= 0.5
        assert len(result) == 2
        assert result[1]["angle_type"] == "borderline"


# ===================================================================
# detect_and_select — no selections
# ===================================================================


class TestNoSelections:
    """All angles below threshold -> no selections, no file written."""

    def test_all_blocked_by_cooldown(self, ds):
        """All angles within cooldown -> empty result, no file."""
        # Insert recent posts for all angles
        _insert_post(ds, "a", TODAY)
        _insert_post(ds, "b", TODAY)

        angles = [
            StubAngle("a", raw_score=0.9, cooldown_days=2),
            StubAngle("b", raw_score=0.8, cooldown_days=2),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert result == []

    def test_all_detect_returns_zero(self, ds):
        """All angles return 0 from detect -> empty result."""
        angles = [
            StubAngle("a", raw_score=0.0),
            StubAngle("b", raw_score=0.0),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert result == []

    def test_detect_exception_handled(self, ds):
        """If detect() raises, the angle is skipped (score=0)."""
        bad_angle = StubAngle("bad", raw_score=0.9)
        bad_angle.detect = MagicMock(side_effect=RuntimeError("boom"))

        angles = [bad_angle]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert result == []

    def test_build_payload_exception_handled(self, ds):
        """If build_payload() raises, the angle is dropped from selections."""
        bad_angle = StubAngle("bad", raw_score=0.9)
        bad_angle.build_payload = MagicMock(
            side_effect=RuntimeError("payload boom")
        )

        angles = [bad_angle]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        # build_payload failed, so no selection is written
        assert result == []


# ===================================================================
# detect_and_select — selection output format
# ===================================================================


class TestSelectionOutput:
    """Verify the structure of the selections output."""

    def test_selection_keys(self, ds):
        angles = [StubAngle("test", raw_score=0.7, auto_publish=True)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 1
        sel = result[0]
        assert sel["angle_type"] == "test"
        assert isinstance(sel["raw_score"], float)
        assert isinstance(sel["effective_score"], float)
        assert sel["auto_publish"] is True
        assert "payload_path" in sel
        assert sel["payload_path"].endswith("content_payload_test.json")


# ===================================================================
# take_daily_snapshots
# ===================================================================


class TestTakeDailySnapshots:
    """take_daily_snapshots calls the correct functions."""

    @patch("src.content.dispatcher.save_daily_score_snapshot")
    @patch("src.content.dispatcher.take_consensus_snapshot")
    @patch("src.content.dispatcher.take_index_portfolio_snapshot")
    def test_calls_all_snapshot_functions(
        self, mock_index, mock_consensus, mock_score, ds
    ):
        take_daily_snapshots(ds, nansen_client="fake_client")

        mock_score.assert_called_once()
        # First arg is datastore, second is snapshot_date
        assert mock_score.call_args[0][0] is ds

        mock_consensus.assert_called_once_with(ds, "fake_client")
        mock_index.assert_called_once_with(ds)

    @patch("src.content.dispatcher.save_daily_score_snapshot")
    def test_allocation_snapshot_populated(self, mock_score, ds):
        """Allocation snapshot should copy current allocations."""
        # Seed some allocations
        ds.upsert_trader("0xAAA")
        ds.upsert_trader("0xBBB")
        ds.insert_allocations({"0xAAA": 0.6, "0xBBB": 0.4})

        take_daily_snapshots(ds)

        # Check allocation_snapshots table was populated
        today = datetime.now(timezone.utc).date().isoformat()
        rows = ds._conn.execute(
            "SELECT trader_id, weight FROM allocation_snapshots WHERE snapshot_date = ?",
            (today,),
        ).fetchall()

        weights = {r["trader_id"]: r["weight"] for r in rows}
        assert weights["0xAAA"] == pytest.approx(0.6)
        assert weights["0xBBB"] == pytest.approx(0.4)

    @patch("src.content.dispatcher.save_daily_score_snapshot")
    def test_empty_allocations_skipped(self, mock_score, ds):
        """No allocations -> no snapshot rows, no error."""
        take_daily_snapshots(ds)

        today = datetime.now(timezone.utc).date().isoformat()
        rows = ds._conn.execute(
            "SELECT COUNT(*) as cnt FROM allocation_snapshots WHERE snapshot_date = ?",
            (today,),
        ).fetchone()
        assert rows["cnt"] == 0

    @patch("src.content.dispatcher.save_daily_score_snapshot")
    def test_nansen_client_passed_to_consensus(self, mock_score, ds):
        """Consensus snapshot receives nansen_client argument."""
        with patch(
            "src.content.dispatcher.take_consensus_snapshot"
        ) as mock_consensus:
            take_daily_snapshots(ds, nansen_client="my_client")

        mock_consensus.assert_called_once_with(ds, "my_client")

    @patch("src.content.dispatcher.save_daily_score_snapshot")
    def test_no_nansen_client_consensus_still_called(self, mock_score, ds):
        """Consensus snapshot is called even without nansen_client (it will log warning)."""
        with patch(
            "src.content.dispatcher.take_consensus_snapshot"
        ) as mock_consensus:
            take_daily_snapshots(ds, nansen_client=None)

        mock_consensus.assert_called_once_with(ds, None)


# ===================================================================
# Edge cases
# ===================================================================


class TestStaleSelectionsCleanup:
    """Bug 1: stale content_selections.json must be deleted when no angles qualify."""

    def test_stale_file_deleted_when_no_angles_qualify(self, ds, tmp_path, monkeypatch):
        """If no angles score > 0, any existing selections file is removed."""
        monkeypatch.setattr("src.content.dispatcher._DATA_DIR", str(tmp_path))
        stale_path = tmp_path / "content_selections.json"
        stale_path.write_text('[{"angle_type": "old_stale_data"}]')

        monkeypatch.setattr("src.content.dispatcher.ALL_ANGLES", [StubAngle("zero_scorer", raw_score=0.0)])

        result = detect_and_select(ds)

        assert result == []
        assert not stale_path.exists(), "Stale selections file should be deleted"

    def test_stale_file_deleted_when_all_in_cooldown(self, ds, tmp_path, monkeypatch):
        """If all angles are blocked by cooldown, stale file is removed."""
        monkeypatch.setattr("src.content.dispatcher._DATA_DIR", str(tmp_path))
        stale_path = tmp_path / "content_selections.json"
        stale_path.write_text('[{"angle_type": "old_stale_data"}]')

        monkeypatch.setattr("src.content.dispatcher.ALL_ANGLES", [StubAngle("cooled", raw_score=0.8, cooldown_days=3)])
        _insert_post(ds, "cooled", TODAY)  # Posted today -> cooldown active

        result = detect_and_select(ds)

        assert result == []
        assert not stale_path.exists()

    def test_file_not_deleted_when_angles_selected(self, ds, tmp_path, monkeypatch):
        """Normal case: file is written (not deleted) when angles qualify."""
        monkeypatch.setattr("src.content.dispatcher._DATA_DIR", str(tmp_path))

        monkeypatch.setattr("src.content.dispatcher.ALL_ANGLES", [StubAngle("good_angle", raw_score=0.8)])

        result = detect_and_select(ds)

        assert len(result) == 1
        assert (tmp_path / "content_selections.json").exists()


class TestConsensusSnapshotImplementation:
    """Bug 3: take_consensus_snapshot must populate consensus_snapshots table."""

    def test_consensus_snapshot_populates_table(self, ds):
        """With allocations and position snapshots, consensus rows are written."""
        today = datetime.now(timezone.utc).date()

        ds.upsert_trader("0xAAA")
        ds.upsert_trader("0xBBB")
        ds.insert_allocations({"0xAAA": 0.6, "0xBBB": 0.4})

        ds.insert_position_snapshot("0xAAA", [
            {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10000,
             "entry_price": 50000, "leverage_value": 1.0},
            {"token_symbol": "ETH", "side": "Long", "position_value_usd": 5000,
             "entry_price": 3000, "leverage_value": 1.0},
        ])
        ds.insert_position_snapshot("0xBBB", [
            {"token_symbol": "BTC", "side": "Short", "position_value_usd": 8000,
             "entry_price": 50000, "leverage_value": 1.0},
        ])

        take_consensus_snapshot(ds)

        rows = ds.get_consensus_snapshots_for_date(today)
        tokens = {r["token"] for r in rows}
        assert "BTC" in tokens
        assert "ETH" in tokens
        btc_row = next(r for r in rows if r["token"] == "BTC")
        assert btc_row["sm_long_usd"] > 0
        assert btc_row["sm_short_usd"] > 0

    def test_consensus_snapshot_empty_positions(self, ds):
        """No positions -> no consensus rows, no error."""
        today = datetime.now(timezone.utc).date()
        take_consensus_snapshot(ds)
        rows = ds.get_consensus_snapshots_for_date(today)
        assert rows == []


class TestIndexPortfolioSnapshotImplementation:
    """Bug 4: take_index_portfolio_snapshot must populate index_portfolio_snapshots."""

    def test_portfolio_snapshot_populates_table(self, ds):
        today = datetime.now(timezone.utc).date()

        ds.upsert_trader("0xAAA")
        ds.upsert_trader("0xBBB")
        ds.insert_allocations({"0xAAA": 0.6, "0xBBB": 0.4})
        ds.insert_position_snapshot("0xAAA", [
            {"token_symbol": "BTC", "side": "Long", "position_value_usd": 10000,
             "entry_price": 50000, "leverage_value": 1.0},
        ])
        ds.insert_position_snapshot("0xBBB", [
            {"token_symbol": "ETH", "side": "Short", "position_value_usd": 5000,
             "entry_price": 3000, "leverage_value": 1.0},
        ])

        take_index_portfolio_snapshot(ds)

        rows = ds.get_index_portfolio_snapshots_for_date(today)
        assert len(rows) >= 2
        tokens = {r["token"] for r in rows}
        assert "BTC" in tokens
        assert "ETH" in tokens

    def test_portfolio_snapshot_empty_positions(self, ds):
        today = datetime.now(timezone.utc).date()
        take_index_portfolio_snapshot(ds)
        rows = ds.get_index_portfolio_snapshots_for_date(today)
        assert rows == []


class TestCLINansenClient:
    """Bug 2: CLI path must instantiate and pass NansenClient."""

    @patch("src.content.dispatcher.detect_and_select")
    @patch("src.content.dispatcher.take_daily_snapshots")
    @patch("src.nansen_client.NansenClient")
    def test_nansen_client_passed_to_snapshot(
        self, MockNansen, mock_snapshots, mock_detect, monkeypatch
    ):
        monkeypatch.setenv("NANSEN_API_KEY", "test-key")
        from src.content.dispatcher import _run_cli
        _run_cli(snapshot=True, detect=False)

        MockNansen.assert_called_once()
        mock_snapshots.assert_called_once()
        assert mock_snapshots.call_args[1]["nansen_client"] is not None

    @patch("src.content.dispatcher.detect_and_select")
    @patch("src.content.dispatcher.take_daily_snapshots")
    @patch("src.nansen_client.NansenClient")
    def test_nansen_client_passed_to_detect(
        self, MockNansen, mock_snapshots, mock_detect, monkeypatch
    ):
        monkeypatch.setenv("NANSEN_API_KEY", "test-key")
        from src.content.dispatcher import _run_cli
        _run_cli(snapshot=False, detect=True)

        mock_detect.assert_called_once()
        assert mock_detect.call_args[1]["nansen_client"] is not None


class TestEdgeCases:
    """Miscellaneous edge cases."""

    def test_empty_angles_list(self, ds):
        """An empty ALL_ANGLES list should return no selections."""
        with patch("src.content.dispatcher.ALL_ANGLES", []):
            result = detect_and_select(ds)

        assert result == []

    def test_negative_raw_score_treated_as_zero(self, ds):
        """A negative raw_score (should not happen, but defensive) is skipped."""
        angles = [StubAngle("neg", raw_score=-0.5)]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert result == []

    def test_multiple_payloads_written(self, ds):
        """When two angles are selected, both payload files should exist."""
        angles = [
            StubAngle("alpha", raw_score=0.9),
            StubAngle("beta", raw_score=0.7),
        ]
        with patch("src.content.dispatcher.ALL_ANGLES", angles):
            result = detect_and_select(ds)

        assert len(result) == 2

        for entry in result:
            assert os.path.exists(entry["payload_path"])
