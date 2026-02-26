import pytest
from src.scoring import (
    normalized_roi, normalized_sharpe, normalized_win_rate,
    consistency_score, smart_money_bonus, risk_management_score,
    classify_trader_style, recency_decay, compute_trader_score,
)
from tests.conftest import make_metrics

def test_normalized_roi_capped():
    assert normalized_roi(150) == 1.0
    # Code divides by 10.0: normalized_roi(5) = 5/10 = 0.5
    assert normalized_roi(5) == pytest.approx(0.5)
    assert normalized_roi(-10) == 0.0

def test_normalized_sharpe():
    assert normalized_sharpe(3.0) == 1.0
    assert normalized_sharpe(1.5) == pytest.approx(0.5)
    assert normalized_sharpe(-1.0) == 0.0

def test_normalized_win_rate_bounds():
    # Bounds are [0.25, 0.90], rescale range [0.25, 0.75]
    # Below floor: 0.20 < 0.25 -> 0.0
    assert normalized_win_rate(0.20) == 0.0
    # Above ceiling: 0.95 > 0.90 -> 0.0
    assert normalized_win_rate(0.95) == 0.0
    # Mid-range: (0.50 - 0.25) / (0.75 - 0.25) = 0.25 / 0.50 = 0.5
    assert normalized_win_rate(0.50) == pytest.approx(0.5)

def test_consistency_all_positive():
    score = consistency_score(roi_7d=10, roi_30d=20, roi_90d=50)
    assert score >= 0.7

def test_consistency_two_positive():
    score = consistency_score(roi_7d=-5, roi_30d=20, roi_90d=50)
    assert score == 0.5

def test_consistency_all_negative():
    score = consistency_score(roi_7d=-5, roi_30d=-10, roi_90d=-20)
    assert score == 0.2

def test_smart_money_fund():
    assert smart_money_bonus("Paradigm Fund [0x1234]") == 1.0

def test_smart_money_labeled():
    assert smart_money_bonus("Smart Money Whale") == 0.8

def test_smart_money_generic_label():
    assert smart_money_bonus("Some Whale") == 0.5

def test_smart_money_none():
    assert smart_money_bonus(None) == 0.0

def test_risk_management_good():
    score = risk_management_score(avg_leverage=3.0, max_leverage=5.0, uses_isolated=True, max_drawdown_proxy=0.05)
    assert score > 0.7

def test_risk_management_bad():
    score = risk_management_score(avg_leverage=25.0, max_leverage=50.0, uses_isolated=False, max_drawdown_proxy=0.30)
    assert score < 0.3

def test_classify_hft():
    # Code requires trades_per_day > 100 AND avg_hold_hours < 1 for HFT
    assert classify_trader_style(trades_per_day=150, avg_hold_hours=0.5) == "HFT"

def test_classify_swing():
    assert classify_trader_style(trades_per_day=2, avg_hold_hours=48) == "SWING"

def test_classify_position():
    assert classify_trader_style(trades_per_day=0.1, avg_hold_hours=500) == "POSITION"

def test_recency_decay_zero_hours():
    assert recency_decay(0) == pytest.approx(1.0)

def test_recency_decay_one_half_life():
    assert recency_decay(168) == pytest.approx(0.5, rel=0.01)

def test_compute_trader_score_returns_dict():
    m7 = make_metrics(window_days=7, roi_proxy=12.0)
    m30 = make_metrics(window_days=30)
    m90 = make_metrics(window_days=90, roi_proxy=35.0)
    score = compute_trader_score(m7, m30, m90, "Fund XYZ", [], 24.0)
    assert isinstance(score, dict)
    assert "final_score" in score
    assert "roi_tier_multiplier" in score
    assert score["final_score"] > 0
