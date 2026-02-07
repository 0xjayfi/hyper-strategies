"""Tests for trader scoring, style classification, and watchlist construction."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from consensus.models import TradeRecord, TraderStyle
from consensus.scoring import (
    calculate_avg_hold_time,
    classify_trader_style,
    compute_trader_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADDR = "0xAAA"
NOW = datetime(2025, 6, 1, 12, 0, 0)


def _trade(
    action: str = "Open",
    side: str = "Long",
    token: str = "BTC",
    ts: datetime | None = None,
    value: float = 1000.0,
    size: float = 0.01,
    pnl: float = 0.0,
    fee: float = 1.0,
) -> TradeRecord:
    return TradeRecord(
        trader_address=ADDR,
        token_symbol=token,
        side=side,
        action=action,
        size=size,
        price_usd=value / max(size, 0.001),
        value_usd=value,
        timestamp=ts or NOW,
        fee_usd=fee,
        closed_pnl=pnl,
        transaction_hash=f"0x{hash((action, ts, token, side)):032x}",
    )


# ===========================================================================
# classify_trader_style
# ===========================================================================


class TestClassifyTraderStyle:

    def test_hft_high_frequency_short_hold(self) -> None:
        """6 trades/day, 2h avg hold => HFT."""
        base = NOW - timedelta(days=10)
        trades = []
        for i in range(60):  # 60 trades in 10 days = 6/day
            open_time = base + timedelta(hours=i * 4)
            close_time = open_time + timedelta(hours=2)  # 2h hold
            trades.append(_trade("Open", ts=open_time))
            trades.append(_trade("Close", ts=close_time))

        assert classify_trader_style(trades, days_active=10) == TraderStyle.HFT

    def test_swing_moderate_frequency(self) -> None:
        """1 trade/day, 48h avg hold => SWING."""
        base = NOW - timedelta(days=30)
        trades = []
        for i in range(30):  # 30 trades in 30 days = 1/day
            open_time = base + timedelta(days=i)
            close_time = open_time + timedelta(hours=48)
            trades.append(_trade("Open", ts=open_time))
            trades.append(_trade("Close", ts=close_time))

        assert classify_trader_style(trades, days_active=30) == TraderStyle.SWING

    def test_position_low_frequency(self) -> None:
        """Very few trades => POSITION."""
        base = NOW - timedelta(days=90)
        trades = [
            _trade("Open", ts=base),
            _trade("Close", ts=base + timedelta(days=60)),
        ]
        # 2 trades in 90 days = ~0.02/day => below 0.3 threshold
        assert classify_trader_style(trades, days_active=90) == TraderStyle.POSITION

    def test_empty_trades_returns_position(self) -> None:
        """No trades → 0 trades/day, 0 hold time → POSITION."""
        assert classify_trader_style([], days_active=30) == TraderStyle.POSITION


# ===========================================================================
# compute_trader_score
# ===========================================================================


class TestComputeTraderScore:

    def test_no_trades_returns_zero(self) -> None:
        trader = {"roi_7d": 10, "roi_30d": 20, "roi_90d": 50}
        assert compute_trader_score(trader, [], now=NOW) == 0.0

    def test_all_positive_roi_high_score(self) -> None:
        """Trader with good metrics across all dimensions should score well."""
        base = NOW - timedelta(days=30)
        trades = []
        for i in range(30):
            open_time = base + timedelta(days=i)
            close_time = open_time + timedelta(hours=24)
            trades.append(_trade("Open", ts=open_time, value=5000, size=1.0))
            trades.append(_trade("Close", ts=close_time, value=5000, size=1.0, pnl=100))

        trader = {
            "roi_7d": 15,
            "roi_30d": 30,
            "roi_90d": 80,
            "label": "Smart Money Whale",
        }
        score = compute_trader_score(trader, trades, now=NOW)
        assert score > 0.3  # meaningful positive score
        assert score <= 1.0

    def test_hft_style_zeroes_score(self) -> None:
        """HFT trader gets style_mult=0 => score=0.

        classify_trader_style uses days_active=90 inside compute_trader_score,
        so we need >5 trades/day over 90 days = 450+ trades, each <4h hold.
        """
        base = NOW - timedelta(days=90)
        trades = []
        for i in range(500):  # 500 trades in 90 days ≈ 5.6/day
            open_time = base + timedelta(hours=i * 4)
            close_time = open_time + timedelta(hours=1)  # 1h hold
            trades.append(_trade("Open", ts=open_time, value=1000, size=1.0))
            trades.append(_trade("Close", ts=close_time, value=1000, size=1.0, pnl=10))

        trader = {"roi_7d": 10, "roi_30d": 20, "roi_90d": 50}
        score = compute_trader_score(trader, trades, now=NOW)
        assert score == 0.0

    def test_consistency_all_positive(self) -> None:
        """All 3 ROI periods positive => consistency = 0.85."""
        base = NOW - timedelta(days=30)
        trades = []
        for i in range(10):
            open_time = base + timedelta(days=i * 3)
            close_time = open_time + timedelta(hours=48)
            trades.append(_trade("Open", ts=open_time, value=5000, size=1.0))
            trades.append(_trade("Close", ts=close_time, value=5000, size=1.0, pnl=50))

        trader_all_pos = {"roi_7d": 5, "roi_30d": 15, "roi_90d": 40}
        trader_mixed = {"roi_7d": -5, "roi_30d": 15, "roi_90d": 40}

        score_all = compute_trader_score(trader_all_pos, trades, now=NOW)
        score_mixed = compute_trader_score(trader_mixed, trades, now=NOW)
        assert score_all > score_mixed

    def test_smart_money_bonus(self) -> None:
        """Fund label > Smart label > generic label > no label."""
        base = NOW - timedelta(days=30)
        trades = []
        for i in range(10):
            open_time = base + timedelta(days=i * 3)
            close_time = open_time + timedelta(hours=48)
            trades.append(_trade("Open", ts=open_time, value=5000, size=1.0))
            trades.append(_trade("Close", ts=close_time, value=5000, size=1.0, pnl=50))

        base_trader = {"roi_7d": 10, "roi_30d": 20, "roi_90d": 50}

        score_fund = compute_trader_score({**base_trader, "label": "Crypto Fund X"}, trades, now=NOW)
        score_smart = compute_trader_score({**base_trader, "label": "Smart Money Whale"}, trades, now=NOW)
        score_label = compute_trader_score({**base_trader, "label": "Binance 14"}, trades, now=NOW)
        score_none = compute_trader_score({**base_trader, "label": ""}, trades, now=NOW)

        assert score_fund > score_smart > score_label > score_none

    def test_recency_decay(self) -> None:
        """Recent trades should score higher than old trades."""
        recent_trades = [
            _trade("Open", ts=NOW - timedelta(days=1), value=5000, size=1.0),
            _trade("Close", ts=NOW, value=5000, size=1.0, pnl=100),
        ]
        old_trades = [
            _trade("Open", ts=NOW - timedelta(days=61), value=5000, size=1.0),
            _trade("Close", ts=NOW - timedelta(days=60), value=5000, size=1.0, pnl=100),
        ]
        trader = {"roi_7d": 10, "roi_30d": 20, "roi_90d": 50}

        score_recent = compute_trader_score(trader, recent_trades, now=NOW)
        score_old = compute_trader_score(trader, old_trades, now=NOW)
        assert score_recent > score_old

    def test_normalized_values_clamped_0_1(self) -> None:
        """ROI > 100% should still clamp normalized_roi to 1.0."""
        base = NOW - timedelta(days=30)
        trades = []
        for i in range(10):
            open_time = base + timedelta(days=i * 3)
            close_time = open_time + timedelta(hours=48)
            trades.append(_trade("Open", ts=open_time, value=5000, size=1.0))
            trades.append(_trade("Close", ts=close_time, value=5000, size=1.0, pnl=200))

        trader = {"roi_7d": 50, "roi_30d": 100, "roi_90d": 300}  # 300% ROI
        score = compute_trader_score(trader, trades, now=NOW)
        assert 0.0 <= score <= 1.0


# ===========================================================================
# calculate_avg_hold_time
# ===========================================================================


class TestCalculateAvgHoldTime:

    def test_single_round_trip(self) -> None:
        trades = [
            _trade("Open", ts=NOW),
            _trade("Close", ts=NOW + timedelta(hours=24)),
        ]
        assert calculate_avg_hold_time(trades) == pytest.approx(24.0)

    def test_multiple_round_trips(self) -> None:
        trades = [
            _trade("Open", ts=NOW, token="BTC"),
            _trade("Close", ts=NOW + timedelta(hours=12), token="BTC"),
            _trade("Open", ts=NOW, token="ETH"),
            _trade("Close", ts=NOW + timedelta(hours=36), token="ETH"),
        ]
        assert calculate_avg_hold_time(trades) == pytest.approx(24.0)  # avg of 12 and 36

    def test_no_completed_round_trips(self) -> None:
        trades = [_trade("Open", ts=NOW)]
        assert calculate_avg_hold_time(trades) == 0.0
