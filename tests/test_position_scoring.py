"""Tests for position-based scoring engine."""
import pytest
from src.position_scoring import (
    normalize_account_growth,
    normalize_drawdown,
    normalize_leverage,
    normalize_liquidation_distance,
    normalize_diversity,
    normalize_consistency,
    compute_position_score,
)


# --- Normalization functions ---

def test_normalize_growth_high():
    assert normalize_account_growth(0.15) == 1.0  # 15% > 10% cap


def test_normalize_growth_mid():
    assert abs(normalize_account_growth(0.05) - 0.5) < 0.001


def test_normalize_growth_negative():
    assert normalize_account_growth(-0.05) == 0.0


def test_normalize_drawdown_zero():
    assert normalize_drawdown(0.0) == 1.0


def test_normalize_drawdown_25pct():
    assert abs(normalize_drawdown(0.25) - 0.5) < 0.001


def test_normalize_drawdown_50pct():
    assert normalize_drawdown(0.50) == 0.0


def test_normalize_leverage_low():
    # base = 1 - 2/20 = 0.9, volatility_penalty = 0.5/25 = 0.02, result = 0.88
    assert abs(normalize_leverage(2.0, 0.5) - 0.88) < 0.01


def test_normalize_leverage_high():
    assert normalize_leverage(25.0, 5.0) == 0.0


def test_normalize_liq_distance_far():
    assert normalize_liquidation_distance(0.30) == 1.0


def test_normalize_liq_distance_close():
    assert normalize_liquidation_distance(0.05) == 0.0


def test_normalize_diversity_diversified():
    # HHI 0.25 (4 equal positions) = score 1.0
    assert normalize_diversity(0.25) == 1.0


def test_normalize_diversity_concentrated():
    # HHI 1.0 (single position) = score 0.2
    assert abs(normalize_diversity(1.0) - 0.2) < 0.01


def test_normalize_consistency_high():
    assert normalize_consistency(1.5) == 1.0


def test_normalize_consistency_zero():
    assert normalize_consistency(0.0) == 0.0


# --- Composite score ---

def test_compute_position_score_returns_all_fields():
    metrics = {
        "account_growth": 0.08,
        "max_drawdown": 0.10,
        "avg_leverage": 3.0,
        "leverage_std": 1.0,
        "avg_liquidation_distance": 0.20,
        "avg_hhi": 0.4,
        "consistency": 0.8,
        "deposit_withdrawal_count": 0,
        "snapshot_count": 48,
    }
    result = compute_position_score(metrics, label="Smart Money Trader")
    expected_keys = {
        "account_growth_score", "drawdown_score", "leverage_score",
        "liquidation_distance_score", "diversity_score", "consistency_score",
        "smart_money_bonus", "recency_decay",
        "raw_composite_score", "final_score",
    }
    assert expected_keys.issubset(set(result.keys()))
    assert 0 <= result["final_score"] <= 2.0  # With bonuses could exceed 1.0


def test_score_with_smart_money_bonus():
    metrics = {
        "account_growth": 0.10, "max_drawdown": 0.0, "avg_leverage": 1.0,
        "leverage_std": 0.0, "avg_liquidation_distance": 0.30,
        "avg_hhi": 0.25, "consistency": 1.0,
        "deposit_withdrawal_count": 0, "snapshot_count": 48,
    }
    score_sm = compute_position_score(metrics, label="Smart Money Fund")
    score_no = compute_position_score(metrics, label=None)
    assert score_sm["final_score"] > score_no["final_score"]
