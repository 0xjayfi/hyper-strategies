import pytest
from tests.conftest import make_metrics
from src.filters import apply_anti_luck_filter, is_trader_eligible, blacklist_trader, is_fully_eligible
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
    m7 = make_metrics(window_days=7, total_pnl=-100, roi_proxy=-2)
    ok, reason = apply_anti_luck_filter(m7, good_m30, good_m90)
    assert ok is False
    assert "7d gate" in reason

def test_fails_30d_gate():
    m30 = make_metrics(window_days=30, total_pnl=5000, roi_proxy=10)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "30d gate" in reason

def test_fails_90d_gate():
    m90 = make_metrics(window_days=90, total_pnl=20000, roi_proxy=10)
    ok, reason = apply_anti_luck_filter(good_m7, good_m30, m90)
    assert ok is False
    assert "90d gate" in reason

def test_high_win_rate_rejected():
    m30 = make_metrics(window_days=30, win_rate=0.90, profit_factor=1.1, total_trades=50, total_pnl=15000, roi_proxy=20)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "too high" in reason

def test_trend_trader_exception():
    m30 = make_metrics(window_days=30, win_rate=0.32, profit_factor=3.0, total_trades=50, total_pnl=15000, roi_proxy=20)
    ok, _ = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is True

def test_low_win_rate_low_pf_rejected():
    m30 = make_metrics(window_days=30, win_rate=0.30, profit_factor=1.0, total_trades=50, total_pnl=15000, roi_proxy=20)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "not trend trader" in reason

def test_insufficient_trades_rejected():
    m30 = make_metrics(window_days=30, total_trades=10, total_pnl=15000, roi_proxy=20, win_rate=0.55, profit_factor=2.0)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "Insufficient" in reason

def test_low_profit_factor_rejected():
    m30 = make_metrics(window_days=30, profit_factor=1.2, total_trades=50, total_pnl=15000, roi_proxy=20, win_rate=0.55)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "Profit factor" in reason
