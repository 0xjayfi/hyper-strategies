"""Unit tests for the scoring engine.

Tests cover all 7 groups + 1 regression test:

1. Tier-1 filter edge cases (5 tests)
2. Win rate bounds rejection (3 tests)
3. Profit factor with trend-trader exception (4 tests)
4. Style classification boundary cases (5 tests)
5. Composite score normalization - all components in [0,1] (10 tests)
6. Zero-trade, zero-variance, single-trade edge cases (7 tests)
7. Regression: deterministic scoring (1 test)
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from snap.scoring import (
    _percentile,
    classify_style,
    compute_avg_hold_hours,
    compute_composite_score,
    compute_consistency_score,
    compute_quality_thresholds,
    compute_recency_decay,
    compute_risk_mgmt_score,
    compute_smart_money_bonus,
    compute_thresholds,
    compute_trade_metrics,
    get_style_multiplier,
    normalize_roi,
    normalize_sharpe,
    normalize_win_rate,
    passes_quality_gate,
    passes_tier1,
    score_trader,
)

# ---------------------------------------------------------------------------
# Default threshold dicts matching the old hardcoded constants for test compat
# ---------------------------------------------------------------------------

_TEST_THRESHOLDS = {
    "roi_30d": 10.0,
    "account_value": 25_000,
    "roi_7d": 5.0,
    "pnl_7d": 0,
    "roi_90d": 30.0,
    "pnl_90d": 50_000,
    "pnl_30d": 10_000,
}

_TEST_QUALITY_THRESHOLDS = {
    "min_trade_count": 20,
    "min_profit_factor": 1.2,
    "win_rate_min": 0.30,
    "win_rate_max": 0.95,
}


# ---------------------------------------------------------------------------
# Helper: Build a realistic trade dict
# ---------------------------------------------------------------------------


def _make_trade(
    action: str = "Open",
    token: str = "BTC",
    side: str = "Long",
    size: float = 0.1,
    price: float = 45000.0,
    value_usd: float = 4500.0,
    closed_pnl: float = 0.0,
    fee_usd: float = 1.0,
    timestamp: str = "2025-10-01T12:00:00",
) -> dict:
    """Build a single trade dict matching Nansen API format."""
    return {
        "action": action,
        "token_symbol": token,
        "side": side,
        "size": size,
        "price": price,
        "value_usd": value_usd,
        "closed_pnl": closed_pnl,
        "fee_usd": fee_usd,
        "timestamp": timestamp,
    }


def _make_trade_pair(
    token: str = "BTC",
    open_ts: str = "2025-10-01T12:00:00",
    close_ts: str = "2025-10-02T12:00:00",
    closed_pnl: float = 500.0,
) -> list[dict]:
    """Build an Open->Close trade pair for a given token."""
    return [
        _make_trade(
            action="Open",
            token=token,
            timestamp=open_ts,
            closed_pnl=0.0,
            value_usd=5000.0,
        ),
        _make_trade(
            action="Close",
            token=token,
            timestamp=close_ts,
            closed_pnl=closed_pnl,
            value_usd=5000.0,
        ),
    ]


def _make_bulk_trades(
    count: int,
    win_ratio: float = 0.6,
    pnl_win: float = 200.0,
    pnl_loss: float = -100.0,
    base_ts: datetime | None = None,
) -> list[dict]:
    """Generate *count* trade pairs (2*count raw trades: Open then Close).

    Each pair consists of an Open and a Close separated by ~12 hours,
    each pair spaced 1 day apart.  *win_ratio* fraction of close trades
    have positive PnL.
    """
    if base_ts is None:
        base_ts = datetime(2025, 7, 1, 8, 0, tzinfo=timezone.utc)

    wins = int(count * win_ratio)
    trades: list[dict] = []

    for i in range(count):
        open_dt = base_ts + timedelta(days=i)
        close_dt = open_dt + timedelta(hours=12)
        pnl = pnl_win if i < wins else pnl_loss

        trades.append(
            _make_trade(
                action="Open",
                token="BTC",
                timestamp=open_dt.isoformat(),
                value_usd=5000.0,
                closed_pnl=0.0,
            )
        )
        trades.append(
            _make_trade(
                action="Close",
                token="BTC",
                timestamp=close_dt.isoformat(),
                value_usd=5000.0,
                closed_pnl=pnl,
            )
        )
    return trades


# ===========================================================================
# Group 1: Tier-1 Filter Edge Cases
# ===========================================================================


class TestTier1Filter:
    """Tests for passes_tier1() boundary logic."""

    def test_tier1_passes_at_exact_thresholds(self):
        """roi_30d=10.0, account_value=25000 should pass (boundary inclusive)."""
        assert passes_tier1(10.0, 25_000, thresholds=_TEST_THRESHOLDS) is True

    def test_tier1_fails_below_roi(self):
        """roi_30d=9.99 should fail."""
        assert passes_tier1(9.99, 100_000, thresholds=_TEST_THRESHOLDS) is False

    def test_tier1_fails_below_account(self):
        """account_value=24999 should fail."""
        assert passes_tier1(20.0, 24_999, thresholds=_TEST_THRESHOLDS) is False

    def test_tier1_fails_with_none(self):
        """None values should fail."""
        assert passes_tier1(None, 25_000, thresholds=_TEST_THRESHOLDS) is False
        assert passes_tier1(10.0, None, thresholds=_TEST_THRESHOLDS) is False
        assert passes_tier1(None, None, thresholds=_TEST_THRESHOLDS) is False

    def test_tier1_passes_above_thresholds(self):
        """roi_30d=50, account_value=200000 should pass comfortably."""
        assert passes_tier1(50.0, 200_000, thresholds=_TEST_THRESHOLDS) is True


# ===========================================================================
# Group 2: Win Rate Bounds Rejection
# ===========================================================================


class TestWinRateBounds:
    """Tests for win-rate bounds within passes_quality_gate()."""

    def test_win_rate_above_max_rejected(self):
        """win_rate=0.96 should fail quality gate (exceeds WIN_RATE_MAX=0.95)."""
        assert passes_quality_gate(100, 0.96, 2.0, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is False

    def test_win_rate_below_min_rejected(self):
        """win_rate=0.29 should fail quality gate (below WIN_RATE_MIN=0.30)."""
        assert passes_quality_gate(100, 0.29, 2.0, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is False

    def test_win_rate_at_exact_bounds_pass(self):
        """win_rate=0.30 and win_rate=0.95 should both pass with sufficient PF and count."""
        assert passes_quality_gate(100, 0.30, 1.2, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is True
        assert passes_quality_gate(100, 0.95, 1.2, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is True


# ===========================================================================
# Group 3: Profit Factor with Trend-Trader Exception
# ===========================================================================


class TestProfitFactor:
    """Tests for profit factor logic in passes_quality_gate(), including trend exception."""

    def test_profit_factor_above_threshold_passes(self):
        """PF=1.3, win_rate=0.5 should pass standard check (PF >= 1.2)."""
        assert passes_quality_gate(100, 0.5, 1.3, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is True

    def test_profit_factor_below_threshold_fails(self):
        """PF=1.1, win_rate=0.5 should fail (below min_profit_factor=1.2, no trend exception)."""
        assert passes_quality_gate(100, 0.5, 1.1, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is False

    def test_trend_trader_exception(self):
        """PF=2.6 with win_rate=0.38 (< 0.40) should pass via trend exception."""
        assert passes_quality_gate(100, 0.38, 2.6, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is True

    def test_trend_trader_exception_fails_when_pf_too_low(self):
        """PF=1.0 with WR=0.38 should fail both standard and trend exception."""
        # PF=1.0 fails standard (< 1.2) AND fails trend exception (< 2.5)
        assert passes_quality_gate(100, 0.38, 1.0, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is False

        # PF=2.4, WR=0.38: standard passes since 2.4 >= 1.2, so this IS True
        assert passes_quality_gate(100, 0.38, 2.4, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is True

        # PF=1.1 fails standard (< 1.2); trend exception also fails (1.1 < 2.5)
        assert passes_quality_gate(100, 0.38, 1.1, quality_thresholds=_TEST_QUALITY_THRESHOLDS) is False


# ===========================================================================
# Group 4: Style Classification Boundary Cases
# ===========================================================================


class TestStyleClassification:
    """Tests for classify_style() and get_style_multiplier()."""

    def test_hft_classification(self):
        """trades_per_day=6, avg_hold_hours=3 -> HFT."""
        assert classify_style(trades_per_day=6.0, avg_hold_hours=3.0) == "HFT"

    def test_hft_boundary_not_triggered(self):
        """trades_per_day=5, avg_hold_hours=3 -> NOT HFT (needs >5).

        With trades_per_day=5 and avg_hold_hours=3, the HFT check (>5 AND <4)
        fails on the first condition.  Since 5 >= 0.3 and 3 < 336, it falls
        into SWING.
        """
        result = classify_style(trades_per_day=5.0, avg_hold_hours=3.0)
        assert result != "HFT"
        assert result == "SWING"

    def test_swing_classification(self):
        """trades_per_day=1, avg_hold_hours=24 -> SWING."""
        assert classify_style(trades_per_day=1.0, avg_hold_hours=24.0) == "SWING"

    def test_position_classification(self):
        """trades_per_day=0.2, avg_hold_hours=500 -> POSITION.

        trades_per_day=0.2 < 0.3 so the SWING check fails, resulting in POSITION.
        """
        assert classify_style(trades_per_day=0.2, avg_hold_hours=500.0) == "POSITION"

    def test_style_multipliers(self):
        """HFT=0.0, SWING=1.0, POSITION=0.8."""
        assert get_style_multiplier("HFT") == 0.0
        assert get_style_multiplier("SWING") == 1.0
        assert get_style_multiplier("POSITION") == 0.8


# ===========================================================================
# Group 5: Composite Score Normalization (all components in [0,1])
# ===========================================================================


class TestNormalization:
    """Tests for individual normalized component calculators."""

    def test_normalized_roi_clamped(self):
        """roi_30d=-10 -> 0, roi_30d=150 -> 1.0, roi_30d=50 -> 0.5."""
        assert normalize_roi(-10.0) == 0.0
        assert normalize_roi(150.0) == 1.0
        assert normalize_roi(50.0) == pytest.approx(0.5)

    def test_normalized_sharpe_clamped(self):
        """pseudo_sharpe=-1 -> 0, pseudo_sharpe=5 -> 1.0, pseudo_sharpe=1.5 -> 0.5."""
        assert normalize_sharpe(-1.0) == 0.0
        assert normalize_sharpe(5.0) == 1.0
        assert normalize_sharpe(1.5) == pytest.approx(0.5)

    def test_normalized_win_rate_clamped(self):
        """win_rate=0.30 -> 0, win_rate=0.95 -> 1.0, win_rate=0.625 -> 0.5."""
        assert normalize_win_rate(0.30) == 0.0
        assert normalize_win_rate(0.95) == pytest.approx(1.0)
        assert normalize_win_rate(0.625) == pytest.approx(0.5)

    def test_consistency_score_all_positive(self):
        """All ROIs positive with low variance -> score near 1.0.

        Use equal weekly-equivalent ROIs for zero variance:
        roi_7d=5.0, roi_30d=20.0 (20/4=5), roi_90d=60.0 (60/12=5)
        -> base=0.7, variance=0, bonus=0.3, total=1.0
        """
        score = compute_consistency_score(roi_7d=5.0, roi_30d=20.0, roi_90d=60.0)
        assert score == pytest.approx(1.0)

    def test_consistency_score_two_positive(self):
        """Only 2 of 3 ROIs positive -> 0.5.

        roi_7d=10, roi_30d=20, roi_90d=-5 (only 2 positive).
        """
        score = compute_consistency_score(roi_7d=10.0, roi_30d=20.0, roi_90d=-5.0)
        assert score == pytest.approx(0.5)

    def test_consistency_score_one_positive(self):
        """Only 1 of 3 ROIs positive -> 0.2.

        roi_7d=-5, roi_30d=-10, roi_90d=20 (only 1 positive out of 3).
        """
        score = compute_consistency_score(roi_7d=-5.0, roi_30d=-10.0, roi_90d=20.0)
        assert score == pytest.approx(0.2)

    def test_smart_money_bonus_values(self):
        """Fund->1.0, Smart Money->0.8, SomeLabel->0.5, empty->0.0."""
        assert compute_smart_money_bonus("Fund") == 1.0
        assert compute_smart_money_bonus("Smart Money") == 0.8
        assert compute_smart_money_bonus("SomeLabel") == 0.5
        assert compute_smart_money_bonus("") == 0.0

    def test_risk_mgmt_score_values(self):
        """Validate risk management score for various leverage values."""
        assert compute_risk_mgmt_score(2.0) == 1.0
        assert compute_risk_mgmt_score(4.0) == 0.8
        assert compute_risk_mgmt_score(7.0) == 0.5
        assert compute_risk_mgmt_score(15.0) == 0.3
        assert compute_risk_mgmt_score(25.0) == 0.1
        assert compute_risk_mgmt_score(None) == 0.5

    def test_recency_decay_recent(self):
        """Trade today -> decay near 1.0.

        days_since_last=0 -> exp(0) = 1.0.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        decay = compute_recency_decay(now_ts)
        # Should be very close to 1.0 (within the same day)
        assert decay > 0.95
        assert decay <= 1.0

    def test_recency_decay_old(self):
        """Trade 60 days ago -> decay near exp(-60/30) = exp(-2) ~ 0.135."""
        old_dt = datetime.now(timezone.utc) - timedelta(days=60)
        decay = compute_recency_decay(old_dt.isoformat())
        expected = math.exp(-60 / 30.0)
        assert decay == pytest.approx(expected, abs=0.02)


# ===========================================================================
# Group 6: Zero-Trade, Zero-Variance, Single-Trade Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Tests for degenerate inputs: empty, single, or unusual trade lists."""

    def test_compute_trade_metrics_empty(self):
        """Empty trades list -> all zeros."""
        metrics = compute_trade_metrics([])
        assert metrics["trade_count"] == 0
        assert metrics["win_rate"] == 0.0
        assert metrics["profit_factor"] == 0.0
        assert metrics["pseudo_sharpe"] == 0.0
        assert metrics["avg_hold_hours"] == 0.0
        assert metrics["trades_per_day"] == 0.0
        assert metrics["most_recent_trade"] is None

    def test_compute_trade_metrics_single_trade(self):
        """Single Open trade -> trade_count=1, win_rate=0 (no closes), etc."""
        trades = [_make_trade(action="Open", timestamp="2025-10-01T12:00:00")]
        metrics = compute_trade_metrics(trades)
        assert metrics["trade_count"] == 1
        assert metrics["win_rate"] == 0.0
        assert metrics["profit_factor"] == 0.0
        assert metrics["avg_hold_hours"] == 0.0
        assert metrics["most_recent_trade"] is not None

    def test_compute_trade_metrics_no_close_trades(self):
        """Only Open trades -> win_rate=0, PF=0."""
        trades = [
            _make_trade(action="Open", token="BTC", timestamp="2025-10-01T12:00:00"),
            _make_trade(action="Open", token="ETH", timestamp="2025-10-02T12:00:00"),
            _make_trade(action="Open", token="SOL", timestamp="2025-10-03T12:00:00"),
        ]
        metrics = compute_trade_metrics(trades)
        assert metrics["trade_count"] == 3
        assert metrics["win_rate"] == 0.0
        assert metrics["profit_factor"] == 0.0

    def test_hold_time_no_pairs(self):
        """No matching Open->Close pairs -> 0.0.

        Three Open trades with no corresponding Close = no pairs.
        """
        trades = [
            _make_trade(action="Open", token="BTC", timestamp="2025-10-01T12:00:00"),
            _make_trade(action="Open", token="ETH", timestamp="2025-10-02T12:00:00"),
        ]
        assert compute_avg_hold_hours(trades) == 0.0

    def test_hold_time_single_pair(self):
        """One Open then one Close -> correct duration.

        Open at T, Close at T+24h -> 24.0 hours.
        """
        trades = [
            _make_trade(
                action="Open",
                token="BTC",
                timestamp="2025-10-01T12:00:00",
            ),
            _make_trade(
                action="Close",
                token="BTC",
                timestamp="2025-10-02T12:00:00",
            ),
        ]
        avg_hours = compute_avg_hold_hours(trades)
        assert avg_hours == pytest.approx(24.0)

    def test_consistency_score_zero_roi_90d(self):
        """roi_90d=None -> treated as 0 for consistency count.

        With roi_7d=10 and roi_30d=20 both positive, and roi_90d=None
        (treated as 0, which is not > 0), only 2 positives -> 0.5.
        """
        score = compute_consistency_score(roi_7d=10.0, roi_30d=20.0, roi_90d=None)
        assert score == pytest.approx(0.5)

    def test_score_trader_with_no_trades(self):
        """score_trader with empty trades -> not eligible, composite=0.

        With no trades: trade_count=0 (fails quality gate), but tier1 and
        consistency can still be checked.  The composite is 0 because there
        is no recent trade (recency_decay=0.0).
        """
        result = score_trader(
            roi_7d=10.0,
            roi_30d=20.0,
            roi_90d=40.0,
            pnl_7d=5000.0,
            pnl_30d=20000.0,
            pnl_90d=80000.0,
            account_value=100_000,
            label="Smart Money",
            trades=[],
            avg_leverage=3.0,
            thresholds=_TEST_THRESHOLDS,
            quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )
        assert result["composite_score"] == 0.0
        # Not eligible: quality gate fails (trade_count=0 < 20)
        assert result["is_eligible"] == 0
        assert result["passes_quality"] == 0
        assert result["passes_consistency"] == 1
        assert "quality:trade_count" in result["fail_reason"]


# ===========================================================================
# Group 7: Regression Test - Deterministic Scoring
# ===========================================================================


class TestRegression:
    """Regression test ensuring deterministic, repeatable scoring output."""

    def test_score_deterministic(self):
        """Given FIXED input data, score output is deterministic across runs.

        Create a fixed set of trades, fixed ROI values, fixed leverage.
        Call score_trader twice with identical inputs.
        Assert all output fields are exactly equal.

        We use very recent trade timestamps (within the last few days) to
        ensure recency_decay is nonzero, and we pin datetime.now inside the
        scoring module so both calls see exactly the same "now".
        """
        # Use recent trades (last 60 days from a pinned "now") so recency > 0
        pinned_now = datetime(2025, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
        base_ts = datetime(2025, 9, 15, 8, 0, tzinfo=timezone.utc)

        trades = _make_bulk_trades(
            count=60,
            win_ratio=0.6,
            pnl_win=300.0,
            pnl_loss=-150.0,
            base_ts=base_ts,
        )

        kwargs = dict(
            roi_7d=10.0,
            roi_30d=25.0,
            roi_90d=45.0,
            pnl_7d=3000.0,
            pnl_30d=15000.0,
            pnl_90d=60000.0,
            account_value=120_000,
            label="Smart Money",
            trades=trades,
            avg_leverage=4.0,
            thresholds=_TEST_THRESHOLDS,
            quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )

        # Patch only datetime.now() in the scoring module while preserving
        # all other datetime functionality (fromisoformat, constructors, etc.)
        import snap.scoring as _scoring_mod

        _orig_datetime = _scoring_mod.datetime

        class _FrozenDatetime(_orig_datetime):
            """datetime subclass that returns a fixed 'now'."""

            @classmethod
            def now(cls, tz=None):
                return pinned_now

        with patch.object(_scoring_mod, "datetime", _FrozenDatetime):
            result1 = score_trader(**kwargs)
            result2 = score_trader(**kwargs)

        # All fields must be exactly equal
        assert result1.keys() == result2.keys()
        for key in result1:
            assert result1[key] == result2[key], (
                f"Field {key!r} differs: {result1[key]} != {result2[key]}"
            )

        # Sanity: composite_score should be > 0 for this well-formed input
        assert result1["composite_score"] > 0

        # Additional sanity: the trader should be eligible with these inputs
        # (depends on trade_count of Close trades = 60, exceeding MIN_TRADE_COUNT=50)
        assert result1["trade_count"] == 120  # 60 opens + 60 closes
        assert result1["passes_tier1"] == 1
        assert "passes_consistency" in result1
        assert "fail_reason" in result1


# ===========================================================================
# Additional composite score integration tests
# ===========================================================================


class TestCompositeScore:
    """Integration tests for compute_composite_score()."""

    def test_composite_score_all_ones_swing(self):
        """All components at 1.0, SWING style, recency=1.0 -> weighted sum = 1.0.

        The weights sum to 1.0 (0.25+0.20+0.15+0.20+0.10+0.10), so
        composite = 1.0 * 1.0 * 1.0 = 1.0.
        """
        score = compute_composite_score(
            normalized_roi=1.0,
            normalized_sharpe=1.0,
            normalized_win_rate=1.0,
            consistency_score=1.0,
            smart_money_bonus=1.0,
            risk_mgmt_score=1.0,
            style_multiplier=1.0,
            recency_decay=1.0,
        )
        assert score == pytest.approx(1.0)

    def test_composite_score_hft_multiplier_zeros_out(self):
        """HFT style_multiplier=0.0 -> composite=0 regardless of other values."""
        score = compute_composite_score(
            normalized_roi=1.0,
            normalized_sharpe=1.0,
            normalized_win_rate=1.0,
            consistency_score=1.0,
            smart_money_bonus=1.0,
            risk_mgmt_score=1.0,
            style_multiplier=0.0,  # HFT
            recency_decay=1.0,
        )
        assert score == 0.0

    def test_composite_score_zero_recency_zeros_out(self):
        """recency_decay=0.0 -> composite=0 regardless of other values."""
        score = compute_composite_score(
            normalized_roi=0.8,
            normalized_sharpe=0.7,
            normalized_win_rate=0.5,
            consistency_score=0.9,
            smart_money_bonus=0.5,
            risk_mgmt_score=0.8,
            style_multiplier=1.0,
            recency_decay=0.0,
        )
        assert score == 0.0

    def test_composite_score_position_penalty(self):
        """POSITION style (multiplier=0.8) reduces score by 20% vs SWING."""
        kwargs = dict(
            normalized_roi=0.5,
            normalized_sharpe=0.5,
            normalized_win_rate=0.5,
            consistency_score=0.5,
            smart_money_bonus=0.5,
            risk_mgmt_score=0.5,
            recency_decay=1.0,
        )
        swing_score = compute_composite_score(style_multiplier=1.0, **kwargs)
        position_score = compute_composite_score(style_multiplier=0.8, **kwargs)
        assert position_score == pytest.approx(swing_score * 0.8)


# ===========================================================================
# Percentile-based threshold tests
# ===========================================================================


class TestPercentile:
    """Tests for _percentile() helper."""

    def test_percentile_empty(self):
        assert _percentile([], 0.5) == 0.0

    def test_percentile_single(self):
        assert _percentile([42.0], 0.5) == 42.0

    def test_percentile_median(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _percentile(vals, 0.5) == 6.0

    def test_percentile_p25(self):
        vals = list(range(1, 101))  # 1..100
        assert _percentile([float(v) for v in vals], 0.25) == 26.0

    def test_percentile_p75(self):
        vals = list(range(1, 101))
        assert _percentile([float(v) for v in vals], 0.75) == 76.0


class TestComputeThresholds:
    """Tests for compute_thresholds()."""

    def test_compute_thresholds_p50(self):
        """At p50, thresholds should be roughly the median of each field."""
        merged = {}
        for i in range(100):
            addr = f"0x{i:040x}"
            merged[addr] = {
                "roi_7d": float(i),
                "roi_30d": float(i * 2),
                "roi_90d": float(i * 3),
                "pnl_7d": float(i * 100),
                "pnl_30d": float(i * 200),
                "pnl_90d": float(i * 300),
                "account_value": float(10_000 + i * 1000),
            }
        t = compute_thresholds(merged, percentile=0.5)
        assert t["roi_30d"] == 100.0  # 50 * 2
        assert t["account_value"] == 60_000.0  # 10000 + 50*1000

    def test_roughly_half_pass_tier1_at_p50(self):
        """About 50% of the population should pass tier-1 at p50."""
        merged = {}
        for i in range(200):
            addr = f"0x{i:040x}"
            merged[addr] = {
                "roi_7d": float(i),
                "roi_30d": float(i),
                "roi_90d": float(i),
                "pnl_7d": float(i * 100),
                "pnl_30d": float(i * 100),
                "pnl_90d": float(i * 100),
                "account_value": float(i * 1000),
            }
        t = compute_thresholds(merged, percentile=0.5)
        passers = sum(
            1 for trader in merged.values()
            if passes_tier1(trader["roi_30d"], trader["account_value"], thresholds=t)
        )
        # Should be roughly 50% (100/200), give or take a few for boundary
        assert 90 <= passers <= 110


class TestComputeQualityThresholds:
    """Tests for compute_quality_thresholds()."""

    def test_quality_thresholds_from_metrics(self):
        metrics = [
            {"trade_count": 10, "win_rate": 0.4, "profit_factor": 1.0},
            {"trade_count": 20, "win_rate": 0.5, "profit_factor": 1.5},
            {"trade_count": 30, "win_rate": 0.6, "profit_factor": 2.0},
            {"trade_count": 40, "win_rate": 0.7, "profit_factor": 2.5},
        ]
        qt = compute_quality_thresholds(metrics, percentile=0.5)
        # 4 items sorted, idx=int(4*0.5)=2 -> vals[2]
        assert qt["min_trade_count"] == 30
        assert qt["min_profit_factor"] == 2.0
        assert qt["win_rate_min"] > 0.0
        assert qt["win_rate_max"] <= 1.0
        assert qt["win_rate_min"] < qt["win_rate_max"]

    def test_empty_metrics(self):
        qt = compute_quality_thresholds([], percentile=0.5)
        assert qt["min_trade_count"] == 0.0
        assert qt["min_profit_factor"] == 0.0


# ===========================================================================
# Fail Reason Diagnostic Tests
# ===========================================================================


class TestFailReasonDiagnostics:
    """Tests for fail_reason and passes_consistency fields in score_trader()."""

    def test_eligible_trader_has_no_fail_reason(self):
        """An eligible trader should have fail_reason=None."""
        trades = _make_bulk_trades(count=60, win_ratio=0.6, pnl_win=300, pnl_loss=-100)
        result = score_trader(
            roi_7d=10.0, roi_30d=25.0, roi_90d=45.0,
            pnl_7d=3000.0, pnl_30d=15000.0, pnl_90d=80000.0,
            account_value=120_000, label="", trades=trades, avg_leverage=3.0,
            thresholds=_TEST_THRESHOLDS, quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )
        assert result["is_eligible"] == 1
        assert result["passes_consistency"] == 1
        assert result["fail_reason"] is None

    def test_tier1_fail_reason(self):
        """Trader failing tier1 should have 'tier1' in fail_reason."""
        result = score_trader(
            roi_7d=1.0, roi_30d=1.0, roi_90d=1.0,
            pnl_7d=100.0, pnl_30d=100.0, pnl_90d=100.0,
            account_value=1_000, label="", trades=[], avg_leverage=None,
            thresholds=_TEST_THRESHOLDS, quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )
        assert result["passes_tier1"] == 0
        assert "tier1" in result["fail_reason"]

    def test_consistency_fail_reason(self):
        """Trader failing consistency gate should have 'consistency' in fail_reason."""
        result = score_trader(
            roi_7d=-50.0, roi_30d=25.0, roi_90d=-20.0,
            pnl_7d=-5000.0, pnl_30d=15000.0, pnl_90d=-10000.0,
            account_value=120_000, label="", trades=[], avg_leverage=None,
            thresholds=_TEST_THRESHOLDS, quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )
        assert result["passes_consistency"] == 0
        assert "consistency" in result["fail_reason"]

    def test_quality_wr_high_fail_reason(self):
        """Trader with win_rate > max should get 'quality:wr_high'."""
        # Create trades with 100% win rate (all closes positive)
        trades = _make_bulk_trades(count=60, win_ratio=1.0, pnl_win=300, pnl_loss=-100)
        result = score_trader(
            roi_7d=10.0, roi_30d=25.0, roi_90d=45.0,
            pnl_7d=3000.0, pnl_30d=15000.0, pnl_90d=80000.0,
            account_value=120_000, label="", trades=trades, avg_leverage=3.0,
            thresholds=_TEST_THRESHOLDS, quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )
        assert result["passes_quality"] == 0
        assert "quality:wr_high" in result["fail_reason"]

    def test_multiple_fail_reasons(self):
        """Trader failing multiple gates should have comma-separated reasons."""
        result = score_trader(
            roi_7d=-50.0, roi_30d=1.0, roi_90d=-20.0,
            pnl_7d=-5000.0, pnl_30d=100.0, pnl_90d=-10000.0,
            account_value=1_000, label="", trades=[], avg_leverage=None,
            thresholds=_TEST_THRESHOLDS, quality_thresholds=_TEST_QUALITY_THRESHOLDS,
        )
        assert result["is_eligible"] == 0
        reasons = result["fail_reason"].split(",")
        assert len(reasons) >= 2
        assert "tier1" in reasons
