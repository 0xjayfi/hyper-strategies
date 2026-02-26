"""Tests for the position-based metrics engine."""
import pytest
from src.position_metrics import (
    compute_account_growth,
    detect_deposit_withdrawals,
    compute_max_drawdown,
    compute_effective_leverage,
    compute_liquidation_distance,
    compute_position_diversity,
    compute_consistency,
    compute_position_metrics,
)


# --- Account Growth ---

def test_account_growth_basic():
    series = [
        {"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
         "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 2},
        {"captured_at": "2026-02-15T00:00:00", "account_value": 110000,
         "total_unrealized_pnl": 5000, "total_position_value": 55000, "position_count": 2},
    ]
    growth = compute_account_growth(series)
    assert abs(growth - 0.10) < 0.001  # 10% growth


def test_account_growth_empty():
    assert compute_account_growth([]) == 0.0


def test_account_growth_single_point():
    series = [{"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
               "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 1}]
    assert compute_account_growth(series) == 0.0


# --- Deposit/Withdrawal Detection ---

def test_detect_deposit_basic():
    """Large account jump without matching PnL change = deposit."""
    series = [
        {"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
         "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 2},
        {"captured_at": "2026-02-01T01:00:00", "account_value": 150000,
         "total_unrealized_pnl": 1000, "total_position_value": 50000, "position_count": 2},
    ]
    flags = detect_deposit_withdrawals(series)
    assert flags[1] is True  # index 1 is flagged


def test_no_false_positive_on_pnl():
    """Account growth from PnL should NOT be flagged."""
    series = [
        {"captured_at": "2026-02-01T00:00:00", "account_value": 100000,
         "total_unrealized_pnl": 0, "total_position_value": 50000, "position_count": 2},
        {"captured_at": "2026-02-01T01:00:00", "account_value": 105000,
         "total_unrealized_pnl": 5000, "total_position_value": 55000, "position_count": 2},
    ]
    flags = detect_deposit_withdrawals(series)
    assert flags[1] is False


# --- Max Drawdown ---

def test_max_drawdown_basic():
    series = [
        {"captured_at": "t1", "account_value": 100000},
        {"captured_at": "t2", "account_value": 120000},
        {"captured_at": "t3", "account_value": 90000},
        {"captured_at": "t4", "account_value": 110000},
    ]
    dd = compute_max_drawdown(series, flags=[False, False, False, False])
    assert abs(dd - 0.25) < 0.001  # (120k - 90k) / 120k = 25%


def test_max_drawdown_no_drawdown():
    series = [
        {"captured_at": "t1", "account_value": 100000},
        {"captured_at": "t2", "account_value": 110000},
        {"captured_at": "t3", "account_value": 120000},
    ]
    dd = compute_max_drawdown(series, flags=[False, False, False])
    assert dd == 0.0


# --- Effective Leverage ---

def test_effective_leverage():
    series = [
        {"captured_at": "t1", "account_value": 100000,
         "total_position_value": 300000, "position_count": 3},
        {"captured_at": "t2", "account_value": 100000,
         "total_position_value": 500000, "position_count": 3},
    ]
    avg, std = compute_effective_leverage(series)
    assert abs(avg - 4.0) < 0.001  # (3x + 5x) / 2
    assert std > 0


# --- Liquidation Distance ---

def test_liquidation_distance():
    snapshots = [
        {"entry_price": 50000, "liquidation_price": 40000,
         "position_value_usd": 10000, "captured_at": "t1"},
        {"entry_price": 3000, "liquidation_price": 2700,
         "position_value_usd": 5000, "captured_at": "t1"},
    ]
    dist = compute_liquidation_distance(snapshots)
    # BTC: |50000-40000|/50000 = 0.20, weight=10k
    # ETH: |3000-2700|/3000 = 0.10, weight=5k
    # Weighted: (0.20*10000 + 0.10*5000) / 15000 = 0.1667
    assert abs(dist - 0.1667) < 0.01


def test_liquidation_distance_no_liq_price():
    """Positions without liquidation_price should be skipped."""
    snapshots = [
        {"entry_price": 50000, "liquidation_price": None,
         "position_value_usd": 10000, "captured_at": "t1"},
    ]
    dist = compute_liquidation_distance(snapshots)
    assert dist == 1.0  # No measurable risk = max score


# --- Position Diversity (HHI) ---

def test_diversity_single_position():
    snapshots = [
        {"token_symbol": "BTC", "position_value_usd": 10000, "captured_at": "t1"},
    ]
    hhi = compute_position_diversity(snapshots)
    assert hhi == 1.0  # Single position = HHI 1.0


def test_diversity_two_equal():
    snapshots = [
        {"token_symbol": "BTC", "position_value_usd": 5000, "captured_at": "t1"},
        {"token_symbol": "ETH", "position_value_usd": 5000, "captured_at": "t1"},
    ]
    hhi = compute_position_diversity(snapshots)
    assert abs(hhi - 0.5) < 0.001  # Two equal = HHI 0.5


# --- Consistency ---

def test_consistency_steady_growth():
    series = [
        {"captured_at": f"t{i}", "account_value": 100000 + i * 1000}
        for i in range(10)
    ]
    c = compute_consistency(series, flags=[False] * 10)
    assert c > 0.5  # Steady growth = high consistency


def test_consistency_volatile():
    series = [
        {"captured_at": "t0", "account_value": 100000},
        {"captured_at": "t1", "account_value": 120000},
        {"captured_at": "t2", "account_value": 80000},
        {"captured_at": "t3", "account_value": 130000},
        {"captured_at": "t4", "account_value": 70000},
    ]
    c = compute_consistency(series, flags=[False] * 5)
    assert c < 0.3  # Volatile = low consistency


# --- Full Pipeline ---

def test_compute_position_metrics_returns_all_fields():
    """Smoke test: verify the full pipeline returns all expected keys."""
    account_series = [
        {"captured_at": f"2026-02-{i+1:02d}T00:00:00", "account_value": 100000 + i * 500,
         "total_unrealized_pnl": i * 100, "total_position_value": 50000 + i * 200,
         "position_count": 3}
        for i in range(24)
    ]
    position_snapshots = [
        {"token_symbol": "BTC", "side": "Long", "position_value_usd": 30000,
         "entry_price": 50000, "liquidation_price": 40000, "leverage_value": 5.0,
         "captured_at": f"2026-02-{i+1:02d}T00:00:00"}
        for i in range(24)
    ] + [
        {"token_symbol": "ETH", "side": "Short", "position_value_usd": 20000,
         "entry_price": 3000, "liquidation_price": 3500, "leverage_value": 3.0,
         "captured_at": f"2026-02-{i+1:02d}T00:00:00"}
        for i in range(24)
    ]
    metrics = compute_position_metrics(account_series, position_snapshots)
    expected_keys = {
        "account_growth", "max_drawdown", "avg_leverage", "leverage_std",
        "avg_liquidation_distance", "avg_hhi", "consistency",
        "deposit_withdrawal_count", "snapshot_count",
    }
    assert set(metrics.keys()) == expected_keys
    assert metrics["snapshot_count"] == 24
