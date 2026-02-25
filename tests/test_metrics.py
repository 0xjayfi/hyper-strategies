import pytest
import numpy as np
from tests.conftest import make_trade, make_metrics
from src.metrics import compute_trade_metrics

def test_win_rate_basic():
    trades = [make_trade(closed_pnl=100), make_trade(closed_pnl=-50), make_trade(closed_pnl=200)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.win_rate == pytest.approx(2/3)

def test_profit_factor():
    trades = [make_trade(closed_pnl=300), make_trade(closed_pnl=-100)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.profit_factor == pytest.approx(3.0)

def test_pseudo_sharpe():
    trades = [make_trade(closed_pnl=100, value_usd=1000),
              make_trade(closed_pnl=-50, value_usd=1000),
              make_trade(closed_pnl=80, value_usd=1000)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    expected_mean = (0.1 - 0.05 + 0.08) / 3
    expected_std = np.std([0.1, -0.05, 0.08], ddof=1)
    assert m.pseudo_sharpe == pytest.approx(expected_mean / expected_std, rel=1e-4)

def test_empty_trades():
    m = compute_trade_metrics([], account_value=10000, window_days=7)
    assert m.total_trades == 0
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0

def test_roi_proxy():
    trades = [make_trade(closed_pnl=500), make_trade(closed_pnl=-200)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=30)
    assert m.roi_proxy == pytest.approx(3.0)  # 300/10000*100

def test_only_open_trades_ignored():
    """Open/Add trades should be filtered out."""
    trades = [make_trade(action="Open", closed_pnl=0), make_trade(action="Add", closed_pnl=0)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.total_trades == 0

def test_max_drawdown_proxy():
    trades = [make_trade(closed_pnl=500), make_trade(closed_pnl=-800)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.max_drawdown_proxy == pytest.approx(0.08)  # 800/10000

def test_zero_account_value():
    trades = [make_trade(closed_pnl=100)]
    m = compute_trade_metrics(trades, account_value=0, window_days=7)
    assert m.roi_proxy == 0.0
    assert m.max_drawdown_proxy == 0.0

def test_trade_metrics_has_extended_fields():
    m = make_metrics(max_leverage=25.0, leverage_std=5.0, largest_trade_pnl_ratio=0.35, pnl_trend_slope=0.02)
    assert m.max_leverage == 25.0
    assert m.leverage_std == 5.0
    assert m.largest_trade_pnl_ratio == 0.35
    assert m.pnl_trend_slope == 0.02

def test_trade_metrics_empty_has_extended_fields():
    from src.models import TradeMetrics
    m = TradeMetrics.empty(30)
    assert m.max_leverage == 0.0
    assert m.leverage_std == 0.0
    assert m.largest_trade_pnl_ratio == 0.0
    assert m.pnl_trend_slope == 0.0


# --- Task 2: Extended metrics computation tests ---

def test_leverage_computed():
    """max_leverage should be max(value_usd / account_value) across close trades."""
    trades = [
        make_trade(closed_pnl=100, value_usd=5000),
        make_trade(closed_pnl=-50, value_usd=8000),
        make_trade(closed_pnl=200, value_usd=3000),
    ]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    # max leverage = 8000/10000 = 0.8
    assert m.max_leverage == pytest.approx(0.8)
    # leverage_std = std([0.5, 0.8, 0.3], ddof=1)
    expected_std = float(np.std([0.5, 0.8, 0.3], ddof=1))
    assert m.leverage_std == pytest.approx(expected_std, rel=1e-4)

def test_leverage_zero_account_value():
    """When account_value is 0, leverage fields should be 0."""
    trades = [make_trade(closed_pnl=100, value_usd=5000)]
    m = compute_trade_metrics(trades, account_value=0, window_days=7)
    assert m.max_leverage == 0.0
    assert m.leverage_std == 0.0

def test_largest_trade_pnl_ratio():
    """largest_trade_pnl_ratio = max(|pnl|) / sum(|pnl|)."""
    trades = [
        make_trade(closed_pnl=100),
        make_trade(closed_pnl=-400),
        make_trade(closed_pnl=200),
    ]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    # abs pnls: 100, 400, 200 -> total = 700, max = 400 -> ratio = 400/700
    assert m.largest_trade_pnl_ratio == pytest.approx(400 / 700, rel=1e-4)

def test_pnl_trend_slope():
    """pnl_trend_slope = (second_half_pnl - first_half_pnl) / total_abs_pnl."""
    trades = [
        make_trade(closed_pnl=100, timestamp="2026-01-01T00:00:00"),
        make_trade(closed_pnl=200, timestamp="2026-01-02T00:00:00"),
        make_trade(closed_pnl=300, timestamp="2026-01-03T00:00:00"),
        make_trade(closed_pnl=400, timestamp="2026-01-04T00:00:00"),
    ]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    # sorted by timestamp: [100, 200, 300, 400]
    # mid = 4 // 2 = 2
    # first_half = 100 + 200 = 300
    # second_half = 300 + 400 = 700
    # total_abs_pnl = 100 + 200 + 300 + 400 = 1000
    # slope = (700 - 300) / 1000 = 0.4
    assert m.pnl_trend_slope == pytest.approx(0.4, rel=1e-4)

def test_extended_metrics_empty_trades():
    """All extended metrics should be 0.0 for empty trades."""
    m = compute_trade_metrics([], account_value=10000, window_days=7)
    assert m.max_leverage == 0.0
    assert m.leverage_std == 0.0
    assert m.largest_trade_pnl_ratio == 0.0
    assert m.pnl_trend_slope == 0.0

def test_single_trade_leverage_std():
    """With a single trade, leverage_std should be 0 (can't compute std with ddof=1)."""
    trades = [make_trade(closed_pnl=100, value_usd=5000)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.leverage_std == 0.0

def test_pnl_trend_single_trade():
    """With one trade, mid=0 so slope should be 0."""
    trades = [make_trade(closed_pnl=100, timestamp="2026-01-01T00:00:00")]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.pnl_trend_slope == 0.0
