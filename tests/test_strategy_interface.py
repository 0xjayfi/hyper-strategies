import pytest
from src.strategy_interface import (
    get_trader_allocation,
    get_all_allocations,
    build_index_portfolio,
    weighted_consensus,
    size_copied_trade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(token, side="Long", value=1000.0):
    """Shortcut to build a position dict used by strategy_interface."""
    return {"token_symbol": token, "side": side, "position_value_usd": value}


# ---------------------------------------------------------------------------
# Core interface via DataStore (get_trader_allocation / get_all_allocations)
# ---------------------------------------------------------------------------

class TestCoreInterface:
    def test_get_trader_allocation_present(self, ds):
        ds.upsert_trader("0xA")
        ds.upsert_trader("0xB")
        ds.insert_allocations({"0xA": 0.6, "0xB": 0.4})
        assert get_trader_allocation("0xA", ds) == pytest.approx(0.6)

    def test_get_trader_allocation_missing(self, ds):
        ds.upsert_trader("0xA")
        ds.insert_allocations({"0xA": 1.0})
        assert get_trader_allocation("0xUNKNOWN", ds) == 0.0

    def test_get_trader_allocation_empty_store(self, ds):
        assert get_trader_allocation("0xA", ds) == 0.0

    def test_get_all_allocations(self, ds):
        ds.upsert_trader("0xA")
        ds.upsert_trader("0xB")
        ds.insert_allocations({"0xA": 0.7, "0xB": 0.3})
        allocs = get_all_allocations(ds)
        assert allocs == {"0xA": pytest.approx(0.7), "0xB": pytest.approx(0.3)}

    def test_get_all_allocations_empty(self, ds):
        assert get_all_allocations(ds) == {}


# ---------------------------------------------------------------------------
# Strategy #2 — Index Portfolio Rebalancing
# ---------------------------------------------------------------------------

class TestBuildIndexPortfolio:
    def test_basic_long(self):
        allocations = {"A": 1.0}
        positions = {"A": [_pos("BTC", "Long", 1000)]}
        result = build_index_portfolio(allocations, positions, 10000)
        # Only one token, exposure = 1000*1.0 = 1000, scale = 5000/1000 = 5
        assert result["BTC"] == pytest.approx(5000.0)

    def test_basic_short(self):
        allocations = {"A": 1.0}
        positions = {"A": [_pos("ETH", "Short", 2000)]}
        result = build_index_portfolio(allocations, positions, 10000)
        assert result["ETH"] < 0  # short
        assert result["ETH"] == pytest.approx(-5000.0)

    def test_mixed_positions(self):
        allocations = {"A": 0.6, "B": 0.4}
        positions = {
            "A": [_pos("BTC", "Long", 1000)],
            "B": [_pos("BTC", "Short", 500)],
        }
        result = build_index_portfolio(allocations, positions, 10000)
        # Raw: BTC = 1000*0.6 - 500*0.4 = 600 - 200 = 400 (long)
        # Total exposure = 400, scale = 5000/400 = 12.5
        assert result["BTC"] == pytest.approx(5000.0)

    def test_multiple_tokens(self):
        allocations = {"A": 0.5, "B": 0.5}
        positions = {
            "A": [_pos("BTC", "Long", 2000)],
            "B": [_pos("ETH", "Long", 1000)],
        }
        result = build_index_portfolio(allocations, positions, 10000)
        assert "BTC" in result
        assert "ETH" in result
        total_exposure = sum(abs(v) for v in result.values())
        assert total_exposure == pytest.approx(5000.0)

    def test_scales_to_50_pct_of_account(self):
        allocations = {"A": 1.0}
        positions = {"A": [_pos("BTC", "Long", 50000)]}
        result = build_index_portfolio(allocations, positions, 20000)
        assert abs(result["BTC"]) == pytest.approx(10000.0)  # 50% of 20k

    def test_empty_allocations(self):
        result = build_index_portfolio({}, {}, 10000)
        assert result == {}

    def test_trader_with_no_positions(self):
        allocations = {"A": 0.5, "B": 0.5}
        positions = {"A": [_pos("BTC", "Long", 1000)]}  # B has no positions
        result = build_index_portfolio(allocations, positions, 10000)
        assert "BTC" in result
        assert result["BTC"] > 0


# ---------------------------------------------------------------------------
# Strategy #3 — Consensus Voting
# ---------------------------------------------------------------------------

class TestWeightedConsensus:
    def test_strong_long(self):
        allocations = {"A": 0.4, "B": 0.3, "C": 0.3}
        positions = {
            "A": [_pos("BTC", "Long", 5000)],
            "B": [_pos("BTC", "Long", 3000)],
            "C": [_pos("BTC", "Long", 2000)],
        }
        result = weighted_consensus("BTC", allocations, positions)
        assert result["signal"] == "STRONG_LONG"
        assert result["participating_traders"] == 3
        assert result["long_weight"] > 0
        assert result["short_weight"] == 0

    def test_strong_short(self):
        allocations = {"A": 0.4, "B": 0.3, "C": 0.3}
        positions = {
            "A": [_pos("ETH", "Short", 5000)],
            "B": [_pos("ETH", "Short", 3000)],
            "C": [_pos("ETH", "Short", 2000)],
        }
        result = weighted_consensus("ETH", allocations, positions)
        assert result["signal"] == "STRONG_SHORT"
        assert result["participating_traders"] == 3

    def test_mixed_signal(self):
        allocations = {"A": 0.5, "B": 0.5}
        positions = {
            "A": [_pos("BTC", "Long", 1000)],
            "B": [_pos("BTC", "Short", 1000)],
        }
        result = weighted_consensus("BTC", allocations, positions)
        assert result["signal"] == "MIXED"

    def test_mixed_when_few_participants(self):
        # Even with all longs, <3 participants -> MIXED
        allocations = {"A": 0.5, "B": 0.5}
        positions = {
            "A": [_pos("BTC", "Long", 5000)],
            "B": [_pos("BTC", "Long", 5000)],
        }
        result = weighted_consensus("BTC", allocations, positions)
        assert result["signal"] == "MIXED"
        assert result["participating_traders"] == 2

    def test_no_positions_for_token(self):
        allocations = {"A": 0.5, "B": 0.5}
        positions = {
            "A": [_pos("ETH", "Long", 1000)],
            "B": [_pos("ETH", "Long", 1000)],
        }
        result = weighted_consensus("BTC", allocations, positions)
        assert result["signal"] == "MIXED"
        assert result["participating_traders"] == 0
        assert result["long_weight"] == 0
        assert result["short_weight"] == 0

    def test_weights_are_allocation_weighted(self):
        allocations = {"A": 0.8, "B": 0.2}
        positions = {
            "A": [_pos("BTC", "Long", 1000)],
            "B": [_pos("BTC", "Long", 1000)],
        }
        result = weighted_consensus("BTC", allocations, positions)
        # A contributes 1000*0.8 = 800, B contributes 1000*0.2 = 200
        assert result["long_weight"] == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Strategy #5 — Per-Trade Sizing
# ---------------------------------------------------------------------------

class TestSizeCopiedTrade:
    def test_basic_sizing(self):
        allocs = {"0xA": 0.5}
        result = size_copied_trade("0xA", 5000, 100000, 10000, allocs)
        # trader_alloc_pct = 5000/100000 = 0.05
        # target = 10000 * 0.05 * 0.5 * 0.5 = 125
        assert result == pytest.approx(125.0)

    def test_zero_weight_returns_zero(self):
        allocs = {"0xA": 0.5}
        result = size_copied_trade("0xUNKNOWN", 5000, 100000, 10000, allocs)
        assert result == 0.0

    def test_zero_trader_account_value(self):
        allocs = {"0xA": 0.5}
        result = size_copied_trade("0xA", 5000, 0, 10000, allocs)
        assert result == 0.0

    def test_hard_cap_10_pct(self):
        allocs = {"0xA": 1.0}
        # Large trade: trader puts 90% of account into one trade
        result = size_copied_trade("0xA", 90000, 100000, 10000, allocs)
        # Without cap: 10000 * 0.9 * 1.0 * 0.5 = 4500
        # Cap: 10000 * 0.10 = 1000
        assert result == pytest.approx(1000.0)

    def test_small_trade_no_cap(self):
        allocs = {"0xA": 0.5}
        result = size_copied_trade("0xA", 1000, 100000, 10000, allocs)
        # trader_alloc_pct = 0.01
        # target = 10000 * 0.01 * 0.5 * 0.5 = 25
        assert result == pytest.approx(25.0)
        assert result < 10000 * 0.10  # well below cap

    def test_full_weight_scaling(self):
        allocs = {"0xA": 1.0}
        result = size_copied_trade("0xA", 10000, 100000, 50000, allocs)
        # trader_alloc_pct = 0.10
        # target = 50000 * 0.10 * 1.0 * 0.5 = 2500
        assert result == pytest.approx(2500.0)
