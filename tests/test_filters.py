import pytest
from tests.conftest import make_metrics
from src.filters import apply_anti_luck_filter, is_trader_eligible, blacklist_trader, is_fully_eligible, is_position_eligible
from src.datastore import DataStore
from datetime import datetime, timedelta

# Good metrics that pass all gates
good_m7 = make_metrics(window_days=7, total_pnl=500, roi_proxy=8, win_rate=0.55, profit_factor=2.0, total_trades=30)
good_m30 = make_metrics(window_days=30, total_pnl=15000, roi_proxy=20, win_rate=0.55, profit_factor=2.0, total_trades=50)
good_m90 = make_metrics(window_days=90, total_pnl=60000, roi_proxy=35, win_rate=0.55, profit_factor=2.0, total_trades=100)

def test_passes_all_gates():
    ok, _ = apply_anti_luck_filter(good_m7, good_m30, good_m90)
    assert ok is True

def test_fails_7d_gate():
    # ANTI_LUCK_7D: min_pnl=-999999, min_roi=-999 (effectively disabled)
    # Need pnl <= -999999 or roi <= -999 to fail
    m7 = make_metrics(window_days=7, total_pnl=-999_999, roi_proxy=-1000)
    ok, reason = apply_anti_luck_filter(m7, good_m30, good_m90)
    assert ok is False
    assert "7d gate" in reason

def test_fails_30d_gate():
    # ANTI_LUCK_30D: min_pnl=500, min_roi=0
    m30 = make_metrics(window_days=30, total_pnl=400, roi_proxy=-1)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "30d gate" in reason

def test_fails_90d_gate():
    # ANTI_LUCK_90D: min_pnl=1000, min_roi=0
    m90 = make_metrics(window_days=90, total_pnl=800, roi_proxy=-1)
    ok, reason = apply_anti_luck_filter(good_m7, good_m30, m90)
    assert ok is False
    assert "90d gate" in reason

def test_high_win_rate_rejected():
    # WIN_RATE_BOUNDS upper = 0.90; code checks win_rate > 0.90 (strict >)
    m30 = make_metrics(window_days=30, win_rate=0.91, profit_factor=1.5, total_trades=50, total_pnl=15000, roi_proxy=20)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "too high" in reason

def test_trend_trader_exception():
    m30 = make_metrics(window_days=30, win_rate=0.32, profit_factor=3.0, total_trades=50, total_pnl=15000, roi_proxy=20)
    ok, _ = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is True

def test_low_win_rate_low_pf_rejected():
    # WIN_RATE_BOUNDS lower = 0.25; need win_rate < 0.25 to enter low-WR path
    # profit_factor < TREND_TRADER_PF (2.0) means "not trend trader"
    m30 = make_metrics(window_days=30, win_rate=0.20, profit_factor=1.5, total_trades=50, total_pnl=15000, roi_proxy=20)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "not trend trader" in reason

def test_insufficient_trades_rejected():
    # MIN_TRADES_30D = 10; code checks total_trades < 10 (strict <)
    m30 = make_metrics(window_days=30, total_trades=9, total_pnl=15000, roi_proxy=20, win_rate=0.55, profit_factor=2.0)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "Insufficient" in reason

def test_low_profit_factor_rejected():
    # MIN_PROFIT_FACTOR = 1.1; code checks profit_factor < 1.1 (strict <)
    m30 = make_metrics(window_days=30, profit_factor=1.05, total_trades=50, total_pnl=15000, roi_proxy=20, win_rate=0.55)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "Profit factor" in reason


# ---------------------------------------------------------------------------
# Position-based eligibility tests
# ---------------------------------------------------------------------------


def test_position_eligible_passes(ds):
    ds.upsert_trader("0xGOOD", label="Good Trader")
    metrics = {
        "account_growth": 0.05,
        "avg_leverage": 5.0,
        "snapshot_count": 48,
    }
    ok, reason = is_position_eligible("0xGOOD", metrics, ds)
    assert ok is True


def test_position_eligible_insufficient_snapshots(ds):
    ds.upsert_trader("0xFEW", label="Few Snapshots")
    metrics = {
        "account_growth": 0.05,
        "avg_leverage": 5.0,
        "snapshot_count": 10,  # < 48 minimum
    }
    ok, reason = is_position_eligible("0xFEW", metrics, ds)
    assert ok is False
    assert "snapshots" in reason.lower()


def test_position_eligible_negative_growth(ds):
    ds.upsert_trader("0xLOSER", label="Loser")
    metrics = {
        "account_growth": -0.05,
        "avg_leverage": 5.0,
        "snapshot_count": 48,
    }
    ok, reason = is_position_eligible("0xLOSER", metrics, ds)
    assert ok is False
    assert "growth" in reason.lower()


def test_position_eligible_high_leverage(ds):
    ds.upsert_trader("0xDEGEN", label="Degen")
    metrics = {
        "account_growth": 0.05,
        "avg_leverage": 30.0,  # > 25x
        "snapshot_count": 48,
    }
    ok, reason = is_position_eligible("0xDEGEN", metrics, ds)
    assert ok is False
    assert "leverage" in reason.lower()


def test_position_eligible_blacklisted(ds):
    ds.upsert_trader("0xBLACK", label="Blacklisted")
    ds.add_to_blacklist("0xBLACK", "test")
    metrics = {
        "account_growth": 0.10,
        "avg_leverage": 3.0,
        "snapshot_count": 100,
    }
    ok, reason = is_position_eligible("0xBLACK", metrics, ds)
    assert ok is False
    assert "blacklist" in reason.lower()
