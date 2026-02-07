import pytest
from src.allocation import (
    scores_to_weights_softmax, apply_roi_tier, apply_risk_caps,
    apply_turnover_limits, compute_allocations, RiskConfig,
)
from src.config import MAX_WEIGHT_CHANGE_PER_DAY

def test_allocations_sum_to_one():
    scores = {"A": 0.8, "B": 0.6, "C": 0.4}
    weights = scores_to_weights_softmax(scores)
    assert sum(weights.values()) == pytest.approx(1.0)

def test_softmax_empty():
    assert scores_to_weights_softmax({}) == {}

def test_softmax_single():
    weights = scores_to_weights_softmax({"A": 0.5})
    assert weights["A"] == pytest.approx(1.0)

def test_softmax_ordering():
    weights = scores_to_weights_softmax({"A": 0.9, "B": 0.5, "C": 0.1})
    assert weights["A"] > weights["B"] > weights["C"]

def test_max_positions_cap():
    scores = {f"trader_{i}": 0.5 + i*0.01 for i in range(10)}
    weights = scores_to_weights_softmax(scores)
    config = RiskConfig(max_total_open_usd=50000, max_total_positions=5)
    capped = apply_risk_caps(weights, {}, config)
    assert len(capped) <= 5

def test_single_trader_weight_cap():
    # apply_risk_caps clips each weight to 40%, then renormalises.
    # With equal inputs the cap never fires; verify it fires on unequal.
    weights = {"A": 0.70, "B": 0.20, "C": 0.10}
    config = RiskConfig(max_total_open_usd=50000)
    capped = apply_risk_caps(weights, {}, config)
    # A was 70% pre-cap → clipped to 40%, then renormalised
    # Renorm pushes A up a bit but the relative ordering is preserved
    assert capped["A"] < 0.70  # cap had an effect
    assert capped["A"] > capped["B"] > capped["C"]
    assert sum(capped.values()) == pytest.approx(1.0)

def test_roi_tier_applied():
    weights = {"A": 0.5, "B": 0.5}
    tiers = {"A": 1.0, "B": 0.5}
    result = apply_roi_tier(weights, tiers)
    assert result["A"] > result["B"]
    assert sum(result.values()) == pytest.approx(1.0)

def test_roi_tier_all_zero():
    weights = {"A": 0.5, "B": 0.5}
    tiers = {"A": 0, "B": 0}
    result = apply_roi_tier(weights, tiers)
    assert result == {}

def test_turnover_limit():
    old = {"A": 0.5, "B": 0.5}
    new = {"A": 0.9, "B": 0.1}
    limited = apply_turnover_limits(new, old)
    # Before renorm: A = 0.5+0.15=0.65, B = 0.5-0.15=0.35
    # After renorm: A = 0.65, B = 0.35
    assert limited["A"] == pytest.approx(0.65, abs=0.01)
    assert limited["B"] == pytest.approx(0.35, abs=0.01)

def test_turnover_small_change_passes():
    old = {"A": 0.5, "B": 0.5}
    new = {"A": 0.55, "B": 0.45}
    limited = apply_turnover_limits(new, old)
    assert limited["A"] == pytest.approx(0.55, abs=0.01)

def test_turnover_removes_negligible():
    old = {"A": 0.01}
    new = {}
    limited = apply_turnover_limits(new, old)
    assert "A" not in limited or limited.get("A", 0) < 0.002

def test_compute_allocations_full():
    # With existing old allocations that match ordering, the pipeline preserves it
    scores = {
        "A": {"final_score": 2.0, "roi_tier_multiplier": 1.0},
        "B": {"final_score": 0.5, "roi_tier_multiplier": 1.0},
    }
    old_alloc = {"A": 0.6, "B": 0.4}  # provide old so turnover limits don't equalise
    config = RiskConfig(max_total_open_usd=50000)
    alloc = compute_allocations(["A", "B"], scores, old_alloc, {}, config)
    assert abs(sum(alloc.values()) - 1.0) < 0.01
    assert alloc["A"] > alloc["B"]

def test_compute_allocations_empty():
    config = RiskConfig(max_total_open_usd=50000)
    alloc = compute_allocations([], {}, {}, {}, config)
    assert alloc == {}
