"""Tests for the TokenSpotlight content angle.

Covers detect() scoring, threshold gates, new position vs growth detection,
time bucketing, build_payload() structure, screenshot_config, and edge cases
with missing data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.content.angles.token_spotlight import TokenSpotlight
from src.content.base import ScreenshotConfig
from src.datastore import DataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
RECENT_TS = (NOW - timedelta(hours=6)).isoformat()   # within last 24h
PRIOR_TS = (NOW - timedelta(hours=30)).isoformat()    # 24-48h ago
OLD_TS = (NOW - timedelta(hours=60)).isoformat()      # > 48h ago


def _seed_smart_money(ds: DataStore, address: str) -> None:
    """Insert a score snapshot with smart_money=True for today."""
    ds.upsert_trader(address, label=f"Label-{address[:6]}")
    ds.insert_score_snapshot(
        snapshot_date=TODAY,
        trader_id=address,
        rank=1,
        composite_score=0.90,
        growth_score=0.80,
        drawdown_score=0.85,
        leverage_score=0.70,
        liq_distance_score=0.75,
        diversity_score=0.65,
        consistency_score=0.80,
        smart_money=True,
    )


def _insert_position_row(
    ds: DataStore,
    address: str,
    captured_at: str,
    token_symbol: str,
    position_value_usd: float,
    *,
    side: str = "Long",
    entry_price: float = 3500.0,
    leverage_value: float = 5.0,
    unrealized_pnl: float = 25000.0,
) -> None:
    """Insert a position snapshot row with a specific captured_at via raw SQL."""
    ds._conn.execute(
        """
        INSERT INTO position_snapshots
            (address, captured_at, token_symbol, side, position_value_usd,
             entry_price, leverage_value, leverage_type, liquidation_price,
             unrealized_pnl, account_value)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            address,
            captured_at,
            token_symbol,
            side,
            position_value_usd,
            entry_price,
            leverage_value,
            "cross",
            None,
            unrealized_pnl,
            1000000.0,
        ),
    )
    ds._conn.commit()


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
    return TokenSpotlight()


# ===================================================================
# detect() -- above threshold (new large position)
# ===================================================================


class TestDetectAboveThresholdNewPosition:
    """detect() should return a positive score for new large positions."""

    def test_new_position_above_500k(self, ds, angle):
        """A new $500k+ position should pass threshold."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 600_000.0)

        score = angle.detect(ds)
        assert score > 0.0
        # score = min(1.0, 600000/2000000) = 0.3
        assert score == pytest.approx(0.3, abs=0.01)

    def test_new_position_2m_capped(self, ds, angle):
        """A new $2M position should score 1.0."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "BTC", 2_000_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_new_position_above_2m_clamped(self, ds, angle):
        """A new $5M position should clamp to 1.0."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "SOL", 5_000_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)


# ===================================================================
# detect() -- above threshold (growth)
# ===================================================================


class TestDetectAboveThresholdGrowth:
    """detect() should return a positive score for significant position growth."""

    def test_growth_above_500k(self, ds, angle):
        """A position that grew by $500k should pass threshold."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "ETH", 300_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 900_000.0)

        score = angle.detect(ds)
        assert score > 0.0
        # growth = 600k, position_value = 900k
        # score = min(1.0, 900000/2000000) = 0.45
        assert score == pytest.approx(0.45, abs=0.01)

    def test_growth_to_2m(self, ds, angle):
        """A position that grew to $2M should score 1.0."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "BTC", 1_000_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "BTC", 2_000_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)


# ===================================================================
# detect() -- below threshold
# ===================================================================


class TestDetectBelowThreshold:
    """detect() should return 0 when below threshold."""

    def test_new_position_below_500k(self, ds, angle):
        """A new $400k position should not pass threshold."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 400_000.0)

        score = angle.detect(ds)
        assert score == 0.0

    def test_growth_below_500k(self, ds, angle):
        """A position that grew by only $200k should not pass."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "ETH", 300_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 400_000.0)

        score = angle.detect(ds)
        assert score == 0.0

    def test_position_decrease(self, ds, angle):
        """A position that decreased should not trigger."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "ETH", 1_000_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 500_000.0)

        score = angle.detect(ds)
        assert score == 0.0

    def test_no_recent_snapshots(self, ds, angle):
        """Only prior snapshots, nothing recent, should return 0."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "ETH", 1_000_000.0)

        score = angle.detect(ds)
        assert score == 0.0


# ===================================================================
# detect() -- missing data
# ===================================================================


class TestDetectMissingData:
    """detect() should return 0 when snapshot data is unavailable."""

    def test_no_smart_money_wallets(self, ds, angle):
        """No smart money wallets should return 0."""
        assert angle.detect(ds) == 0.0

    def test_no_position_snapshots(self, ds, angle):
        """Smart money exists but no position snapshots should return 0."""
        _seed_smart_money(ds, "0xSM1")
        assert angle.detect(ds) == 0.0

    def test_empty_database(self, ds, angle):
        """Empty database should return 0."""
        assert angle.detect(ds) == 0.0

    def test_smart_money_no_label(self, ds, angle):
        """Smart money without a trader label should still work."""
        # Insert trader without label
        ds.upsert_trader("0xSM1")
        ds.insert_score_snapshot(
            snapshot_date=TODAY,
            trader_id="0xSM1",
            rank=1, composite_score=0.90,
            growth_score=0.80, drawdown_score=0.85,
            leverage_score=0.70, liq_distance_score=0.75,
            diversity_score=0.65, consistency_score=0.80,
            smart_money=True,
        )
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 600_000.0)

        score = angle.detect(ds)
        assert score > 0.0


# ===================================================================
# Scoring formula
# ===================================================================


class TestScoringFormula:
    """Verify the scoring formula: min(1.0, position_value / 2_000_000)."""

    def test_500k_score(self, ds, angle):
        """$500k -> 0.25"""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 500_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(0.25, abs=0.01)

    def test_1m_score(self, ds, angle):
        """$1M -> 0.5"""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 1_000_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_1_5m_score(self, ds, angle):
        """$1.5M -> 0.75"""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 1_500_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(0.75, abs=0.01)

    def test_2m_score(self, ds, angle):
        """$2M -> 1.0"""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 2_000_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_3m_clamped_score(self, ds, angle):
        """$3M -> clamped to 1.0"""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 3_000_000.0)

        score = angle.detect(ds)
        assert score == pytest.approx(1.0, abs=0.01)


# ===================================================================
# New position vs growth detection
# ===================================================================


class TestNewVsGrowthDetection:
    """Verify detection correctly classifies new positions vs growth."""

    def test_new_position_detected(self, ds, angle):
        """A token only in recent bucket should be classified as new."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 800_000.0)

        angle.detect(ds)
        data = angle._spotlight_data
        assert data is not None
        assert data["is_new_position"] is True
        assert data["growth_amount_usd"] is None
        assert data["token"] == "ETH"

    def test_growth_detected(self, ds, angle):
        """A token present in both buckets with $500k+ growth should be classified as growth."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "ETH", 200_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 900_000.0)

        angle.detect(ds)
        data = angle._spotlight_data
        assert data is not None
        assert data["is_new_position"] is False
        assert data["growth_amount_usd"] == pytest.approx(700_000.0, abs=1.0)

    def test_largest_position_wins(self, ds, angle):
        """When multiple qualifying positions exist, the largest should be picked."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 600_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "BTC", 1_500_000.0)

        angle.detect(ds)
        data = angle._spotlight_data
        assert data["token"] == "BTC"
        assert data["position_value_usd"] == 1_500_000.0

    def test_multiple_smart_money_wallets(self, ds, angle):
        """The best position across all smart money wallets should be selected."""
        _seed_smart_money(ds, "0xSM1")
        _seed_smart_money(ds, "0xSM2")

        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 600_000.0)
        _insert_position_row(ds, "0xSM2", RECENT_TS, "BTC", 1_200_000.0)

        angle.detect(ds)
        data = angle._spotlight_data
        assert data["address"] == "0xSM2"
        assert data["token"] == "BTC"

    def test_old_snapshots_ignored(self, ds, angle):
        """Snapshots older than 48h should not be in the prior bucket."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", OLD_TS, "ETH", 200_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 600_000.0)

        angle.detect(ds)
        data = angle._spotlight_data
        # The old snapshot should not be in the prior bucket, so ETH
        # is a "new" position (only in recent bucket).
        assert data["is_new_position"] is True


# ===================================================================
# Time bucketing
# ===================================================================


class TestTimeBucketing:
    """Verify correct time bucket classification."""

    def test_exactly_24h_boundary(self, ds, angle):
        """A snapshot exactly at the 24h boundary should be in the prior bucket."""
        _seed_smart_money(ds, "0xSM1")
        boundary_ts = (NOW - timedelta(hours=24)).isoformat()
        _insert_position_row(ds, "0xSM1", boundary_ts, "ETH", 200_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "ETH", 900_000.0)

        score = angle.detect(ds)
        # Growth = 700k, should be detected as growth
        assert score > 0.0
        assert angle._spotlight_data["is_new_position"] is False

    def test_most_recent_per_bucket(self, ds, angle):
        """Multiple snapshots in the same bucket — the most recent should be used."""
        _seed_smart_money(ds, "0xSM1")
        earlier_recent = (NOW - timedelta(hours=12)).isoformat()
        later_recent = (NOW - timedelta(hours=2)).isoformat()

        _insert_position_row(ds, "0xSM1", earlier_recent, "ETH", 300_000.0)
        _insert_position_row(ds, "0xSM1", later_recent, "ETH", 800_000.0)

        angle.detect(ds)
        data = angle._spotlight_data
        assert data["position_value_usd"] == 800_000.0


# ===================================================================
# build_payload()
# ===================================================================


class TestBuildPayload:
    """build_payload() should produce a valid, complete payload dict."""

    def test_payload_structure_new_position(self, ds, angle):
        """Payload for a new position should have correct structure."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(
            ds, "0xSM1", RECENT_TS, "ETH", 1_500_000.0,
            side="Long", entry_price=3500.0, leverage_value=5.0,
            unrealized_pnl=25000.0,
        )

        score = angle.detect(ds)
        assert score > 0.0

        payload = angle.build_payload(ds)

        assert payload["post_worthy"] is True
        assert payload["snapshot_date"] == TODAY.isoformat()
        assert payload["trader"]["address"] == "0xSM1"
        assert payload["trader"]["label"] is not None
        assert payload["trader"]["smart_money"] is True
        assert payload["token"] == "ETH"
        assert payload["position_value_usd"] == 1_500_000.0
        assert payload["is_new_position"] is True
        assert payload["growth_amount_usd"] is None

        details = payload["position_details"]
        assert details["side"] == "Long"
        assert details["entry_price"] == 3500.0
        assert details["leverage_value"] == 5.0
        assert details["unrealized_pnl"] == 25000.0

    def test_payload_structure_growth(self, ds, angle):
        """Payload for a grown position should include growth_amount_usd."""
        _seed_smart_money(ds, "0xSM1")
        _insert_position_row(ds, "0xSM1", PRIOR_TS, "BTC", 500_000.0)
        _insert_position_row(ds, "0xSM1", RECENT_TS, "BTC", 1_200_000.0)

        angle.detect(ds)
        payload = angle.build_payload(ds)

        assert payload["is_new_position"] is False
        assert payload["growth_amount_usd"] == pytest.approx(700_000.0, abs=1.0)
        assert payload["position_value_usd"] == 1_200_000.0

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
        assert page.route == "/positions"
        assert page.filename == "token_spotlight.png"
        assert "position-explorer" in page.wait_selector
        assert "position-explorer" in page.capture_selector


# ===================================================================
# Class attributes
# ===================================================================


class TestClassAttributes:
    """Verify class-level attributes."""

    def test_angle_type(self, angle):
        assert angle.angle_type == "token_spotlight"

    def test_auto_publish(self, angle):
        assert angle.auto_publish is False

    def test_cooldown_days(self, angle):
        assert angle.cooldown_days == 3

    def test_tone(self, angle):
        assert angle.tone == "analytical"

    def test_prompt_path(self, angle):
        assert angle.prompt_path == "src/content/prompts/token_spotlight.md"
