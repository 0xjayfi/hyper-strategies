"""Tests for the LeaderboardShakeup content angle.

Covers detect() scoring, threshold gates, build_payload() structure,
new top-3 entrant detection, and edge cases with missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.content.angles.leaderboard_shakeup import LeaderboardShakeup
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
    smart_money: bool = False,
) -> None:
    """Insert a score snapshot with sensible defaults."""
    ds.insert_score_snapshot(
        snapshot_date=date,
        trader_id=trader_id,
        rank=rank,
        composite_score=composite,
        growth_score=0.5,
        drawdown_score=0.5,
        leverage_score=0.5,
        liq_distance_score=0.5,
        diversity_score=0.5,
        consistency_score=0.5,
        smart_money=smart_money,
    )


def _seed_stable_top10(ds: DataStore, *, skip_ranks: set[int] | None = None) -> None:
    """Seed 10 wallets at ranks 1-10 with identical positions both days.

    Use ``skip_ranks`` to leave specific positions empty for test wallets.
    """
    skip = skip_ranks or set()
    for i in range(1, 11):
        if i in skip:
            continue
        addr = f"0xSTABLE{i:02d}"
        score = round(1.0 - i * 0.05, 2)
        _seed_snapshot(ds, YESTERDAY, addr, rank=i, composite=score)
        _seed_snapshot(ds, TODAY, addr, rank=i, composite=score)


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
    return LeaderboardShakeup()


# ===================================================================
# detect() — above threshold (>= 3 shuffled)
# ===================================================================


class TestDetectAboveThreshold:
    """detect() should return a positive score when enough wallets shuffle."""

    def test_three_wallets_shuffled(self, ds, angle):
        """Exactly 3 shuffled wallets should pass threshold."""
        # Stable wallets at ranks 4-10
        for i in range(4, 11):
            addr = f"0xS{i:02d}"
            _seed_snapshot(ds, YESTERDAY, addr, rank=i, composite=round(1.0 - i * 0.05, 2))
            _seed_snapshot(ds, TODAY, addr, rank=i, composite=round(1.0 - i * 0.05, 2))

        # 3 wallets that swap positions
        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.95)
        _seed_snapshot(ds, TODAY, "0xA", rank=3, composite=0.92)

        _seed_snapshot(ds, YESTERDAY, "0xB", rank=2, composite=0.93)
        _seed_snapshot(ds, TODAY, "0xB", rank=1, composite=0.95)

        _seed_snapshot(ds, YESTERDAY, "0xC", rank=3, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xC", rank=2, composite=0.93)

        score = angle.detect(ds)
        assert score > 0.0
        # score = min(1.0, 3/8) = 0.375
        assert score == pytest.approx(3 / 8, abs=0.01)

    def test_eight_wallets_shuffled_gives_max_score(self, ds, angle):
        """8 shuffled wallets should give score = 1.0."""
        # All 10 wallets shift; 8 change rank within top 10
        for i in range(1, 11):
            addr = f"0xW{i:02d}"
            old_rank = i
            # Reverse ranks for today
            new_rank = 11 - i
            _seed_snapshot(ds, YESTERDAY, addr, rank=old_rank, composite=round(1.0 - old_rank * 0.05, 2))
            _seed_snapshot(ds, TODAY, addr, rank=new_rank, composite=round(1.0 - new_rank * 0.05, 2))

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_new_top3_entrant_triggers_detection(self, ds, angle):
        """A single new top-3 entrant should trigger even with < 3 shuffles."""
        _seed_stable_top10(ds, skip_ranks={2})

        # Wallet moves from rank 5 to rank 2 (new top-3 entrant, +1 shuffle)
        _seed_snapshot(ds, YESTERDAY, "0xRISER", rank=5, composite=0.70)
        _seed_snapshot(ds, TODAY, "0xRISER", rank=2, composite=0.85)

        score = angle.detect(ds)
        # Only 1 wallet shuffled but there's a new top-3 entrant
        assert score > 0.0
        assert angle._shakeup_data is not None
        assert len(angle._shakeup_data["new_top3_entrants"]) >= 1

    def test_brand_new_wallet_in_top3(self, ds, angle):
        """A wallet not present yesterday appearing in top 3 counts as new entrant."""
        _seed_stable_top10(ds, skip_ranks={2})

        # 0xBRAND only appears today at rank 2
        _seed_snapshot(ds, TODAY, "0xBRAND", rank=2, composite=0.88)

        score = angle.detect(ds)
        assert score > 0.0
        entrants = angle._shakeup_data["new_top3_entrants"]
        assert any(e["address"] == "0xBRAND" for e in entrants)


# ===================================================================
# detect() — below threshold
# ===================================================================


class TestDetectBelowThreshold:
    """detect() should return 0 when below threshold."""

    def test_stable_leaderboard(self, ds, angle):
        """No rank changes should return 0."""
        _seed_stable_top10(ds)

        score = angle.detect(ds)
        assert score == 0.0

    def test_only_two_shuffled(self, ds, angle):
        """Only 2 shuffled wallets (and no top-3 entrant) should return 0."""
        _seed_stable_top10(ds, skip_ranks={8, 9})

        # 2 wallets swap positions at 8 and 9
        _seed_snapshot(ds, YESTERDAY, "0xX", rank=8, composite=0.55)
        _seed_snapshot(ds, TODAY, "0xX", rank=9, composite=0.52)

        _seed_snapshot(ds, YESTERDAY, "0xY", rank=9, composite=0.52)
        _seed_snapshot(ds, TODAY, "0xY", rank=8, composite=0.55)

        score = angle.detect(ds)
        assert score == 0.0

    def test_single_shuffle_no_top3_entry(self, ds, angle):
        """1 shuffle with no top-3 entry should return 0."""
        _seed_stable_top10(ds, skip_ranks={7})

        _seed_snapshot(ds, YESTERDAY, "0xONE", rank=7, composite=0.62)
        _seed_snapshot(ds, TODAY, "0xONE", rank=6, composite=0.64)

        # Need to also shift rank 6 stable wallet
        # Actually, stable wallet at rank 6 is still at rank 6; 0xONE moved from 7->6.
        # This means 0xONE changed, and stable#6 didn't. 1 shuffle only.
        score = angle.detect(ds)
        assert score == 0.0


# ===================================================================
# detect() — missing data
# ===================================================================


class TestDetectMissingData:
    """detect() should return 0 when snapshot data is unavailable."""

    def test_no_today_data(self, ds, angle):
        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.90)
        assert angle.detect(ds) == 0.0

    def test_no_yesterday_data(self, ds, angle):
        _seed_snapshot(ds, TODAY, "0xA", rank=1, composite=0.90)
        assert angle.detect(ds) == 0.0

    def test_empty_database(self, ds, angle):
        assert angle.detect(ds) == 0.0


# ===================================================================
# Scoring formula
# ===================================================================


class TestScoringFormula:
    """Verify the scoring formula: min(1.0, shuffled_wallets / 8)."""

    def test_formula_3_shuffled(self, ds, angle):
        """3 shuffled -> 3/8 = 0.375"""
        _seed_stable_top10(ds, skip_ranks={1, 2, 3})

        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.95)
        _seed_snapshot(ds, TODAY, "0xA", rank=3, composite=0.90)

        _seed_snapshot(ds, YESTERDAY, "0xB", rank=2, composite=0.93)
        _seed_snapshot(ds, TODAY, "0xB", rank=1, composite=0.95)

        _seed_snapshot(ds, YESTERDAY, "0xC", rank=3, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xC", rank=2, composite=0.93)

        score = angle.detect(ds)
        assert score == pytest.approx(3 / 8, abs=0.01)

    def test_formula_5_shuffled(self, ds, angle):
        """5 shuffled -> 5/8 = 0.625"""
        _seed_stable_top10(ds, skip_ranks={1, 2, 3, 4, 5})

        # Create 5 wallets that each change rank (shift by +1, wrapping)
        old_ranks = [1, 2, 3, 4, 5]
        new_ranks = [2, 3, 4, 5, 1]
        for i, (old_r, new_r) in enumerate(zip(old_ranks, new_ranks)):
            addr = f"0xM{i}"
            _seed_snapshot(ds, YESTERDAY, addr, rank=old_r, composite=round(1.0 - old_r * 0.05, 2))
            _seed_snapshot(ds, TODAY, addr, rank=new_r, composite=round(1.0 - new_r * 0.05, 2))

        score = angle.detect(ds)
        assert score == pytest.approx(5 / 8, abs=0.01)

    def test_formula_clamped_at_1(self, ds, angle):
        """10 shuffled -> min(1.0, 10/8) = 1.0"""
        for i in range(1, 11):
            addr = f"0xW{i:02d}"
            new_rank = 11 - i
            _seed_snapshot(ds, YESTERDAY, addr, rank=i, composite=round(1.0 - i * 0.05, 2))
            _seed_snapshot(ds, TODAY, addr, rank=new_rank, composite=round(1.0 - new_rank * 0.05, 2))

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)


# ===================================================================
# New top-3 entrant detection
# ===================================================================


class TestNewTop3Entrants:
    """Verify new top-3 entrant detection logic."""

    def test_entrant_from_rank_5_to_rank_2(self, ds, angle):
        """Moving from rank 5 to rank 2 should be detected as new top-3 entrant."""
        _seed_stable_top10(ds, skip_ranks={2})

        _seed_snapshot(ds, YESTERDAY, "0xRISER", rank=5, composite=0.70)
        _seed_snapshot(ds, TODAY, "0xRISER", rank=2, composite=0.88)

        angle.detect(ds)
        entrants = angle._shakeup_data["new_top3_entrants"]
        assert len(entrants) == 1
        assert entrants[0]["address"] == "0xRISER"
        assert entrants[0]["new_rank"] == 2
        assert entrants[0]["old_rank"] == 5

    def test_staying_in_top3_not_counted(self, ds, angle):
        """Moving within top 3 (rank 3 -> rank 1) is NOT a new top-3 entrant."""
        _seed_stable_top10(ds, skip_ranks={1, 2, 3})

        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.95)
        _seed_snapshot(ds, TODAY, "0xA", rank=3, composite=0.90)

        _seed_snapshot(ds, YESTERDAY, "0xB", rank=2, composite=0.93)
        _seed_snapshot(ds, TODAY, "0xB", rank=1, composite=0.95)

        _seed_snapshot(ds, YESTERDAY, "0xC", rank=3, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xC", rank=2, composite=0.93)

        angle.detect(ds)
        # All 3 were already in top 3 yesterday
        entrants = angle._shakeup_data["new_top3_entrants"]
        assert len(entrants) == 0

    def test_multiple_new_top3_entrants(self, ds, angle):
        """Multiple wallets entering top 3 should all be detected."""
        _seed_stable_top10(ds, skip_ranks={1, 2})

        _seed_snapshot(ds, YESTERDAY, "0xRISER1", rank=6, composite=0.60)
        _seed_snapshot(ds, TODAY, "0xRISER1", rank=1, composite=0.98)

        _seed_snapshot(ds, YESTERDAY, "0xRISER2", rank=7, composite=0.55)
        _seed_snapshot(ds, TODAY, "0xRISER2", rank=2, composite=0.95)

        angle.detect(ds)
        entrants = angle._shakeup_data["new_top3_entrants"]
        addrs = {e["address"] for e in entrants}
        assert addrs == {"0xRISER1", "0xRISER2"}


# ===================================================================
# build_payload()
# ===================================================================


class TestBuildPayload:
    """build_payload() should produce a valid, complete payload dict."""

    def test_payload_structure(self, ds, angle):
        """Payload should contain all expected top-level keys."""
        _seed_stable_top10(ds, skip_ranks={1, 2, 3})

        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.95)
        _seed_snapshot(ds, TODAY, "0xA", rank=3, composite=0.90)

        _seed_snapshot(ds, YESTERDAY, "0xB", rank=2, composite=0.93)
        _seed_snapshot(ds, TODAY, "0xB", rank=1, composite=0.95)

        _seed_snapshot(ds, YESTERDAY, "0xC", rank=3, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xC", rank=2, composite=0.93)

        score = angle.detect(ds)
        assert score > 0

        payload = angle.build_payload(ds)

        assert payload["post_worthy"] is True
        assert payload["snapshot_date"] == TODAY.isoformat()
        assert isinstance(payload["total_shuffled"], int)
        assert payload["total_shuffled"] == 3
        assert isinstance(payload["new_top3_entrants"], list)
        assert isinstance(payload["rank_changes"], list)
        assert len(payload["rank_changes"]) == 3
        assert isinstance(payload["top_10_today"], list)
        assert len(payload["top_10_today"]) == 10

    def test_rank_changes_structure(self, ds, angle):
        """Each rank_change entry should have the required keys."""
        _seed_stable_top10(ds, skip_ranks={1, 2, 3})

        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.95)
        _seed_snapshot(ds, TODAY, "0xA", rank=3, composite=0.90)

        _seed_snapshot(ds, YESTERDAY, "0xB", rank=2, composite=0.93)
        _seed_snapshot(ds, TODAY, "0xB", rank=1, composite=0.95)

        _seed_snapshot(ds, YESTERDAY, "0xC", rank=3, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xC", rank=2, composite=0.93)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        for rc in payload["rank_changes"]:
            assert "address" in rc
            assert "label" in rc
            assert "old_rank" in rc
            assert "new_rank" in rc
            assert "rank_delta" in rc
            assert "score" in rc

    def test_top_10_today_structure(self, ds, angle):
        """Each top_10_today entry should have address, label, rank, score."""
        _seed_stable_top10(ds, skip_ranks={1, 2, 3})

        _seed_snapshot(ds, YESTERDAY, "0xA", rank=1, composite=0.95)
        _seed_snapshot(ds, TODAY, "0xA", rank=3, composite=0.90)

        _seed_snapshot(ds, YESTERDAY, "0xB", rank=2, composite=0.93)
        _seed_snapshot(ds, TODAY, "0xB", rank=1, composite=0.95)

        _seed_snapshot(ds, YESTERDAY, "0xC", rank=3, composite=0.90)
        _seed_snapshot(ds, TODAY, "0xC", rank=2, composite=0.93)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        for entry in payload["top_10_today"]:
            assert "address" in entry
            assert "label" in entry
            assert "rank" in entry
            assert "score" in entry


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
        assert page.route == "/leaderboard"
        assert page.filename == "leaderboard_shakeup.png"
        assert "leaderboard-table" in page.wait_selector
        assert "leaderboard-table" in page.capture_selector


# ===================================================================
# Class attributes
# ===================================================================


class TestClassAttributes:
    """Verify class-level attributes."""

    def test_angle_type(self, angle):
        assert angle.angle_type == "leaderboard_shakeup"

    def test_auto_publish(self, angle):
        assert angle.auto_publish is True

    def test_cooldown_days(self, angle):
        assert angle.cooldown_days == 2

    def test_tone(self, angle):
        assert angle.tone == "neutral"

    def test_prompt_path(self, angle):
        assert angle.prompt_path == "src/content/prompts/leaderboard_shakeup.md"
