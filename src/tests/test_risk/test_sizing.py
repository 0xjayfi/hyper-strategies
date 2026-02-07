import pytest

from src.risk.types import Side, MarginType, OrderType, SizingRequest, AccountState
from src.risk.sizing import adjust_position_for_leverage, calculate_position_size
from src.risk.constants import MAX_ALLOWED_LEVERAGE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_account(value: float = 200_000.0) -> AccountState:
    return AccountState(
        account_value_usd=value,
        total_open_positions_usd=0.0,
        total_long_exposure_usd=0.0,
        total_short_exposure_usd=0.0,
        token_exposure_usd={},
    )


# ---------------------------------------------------------------------------
# 9.1 Leverage Cap Enforcement
# ---------------------------------------------------------------------------

def test_leverage_cap_at_5x():
    """Trader at 20x should be capped to 5x for our execution."""
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=20.0,
    )
    result = calculate_position_size(req, _clean_account())
    assert result.effective_leverage == 5.0


def test_leverage_below_cap_unchanged():
    """Trader at 3x stays at 3x."""
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=3.0,
    )
    result = calculate_position_size(req, _clean_account())
    assert result.effective_leverage == 3.0


def test_leverage_exactly_at_cap():
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=5.0,
    )
    result = calculate_position_size(req, _clean_account())
    assert result.effective_leverage == 5.0


def test_leverage_none_defaults_to_max():
    """When leverage unknown, default to MAX_ALLOWED_LEVERAGE."""
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=None,
        trader_position_value_usd=None,
        trader_margin_used_usd=None,
    )
    result = calculate_position_size(req, _clean_account())
    assert result.effective_leverage == 5.0


# ---------------------------------------------------------------------------
# 9.2 Leverage Penalty Mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("leverage,expected_multiplier", [
    (1, 1.00), (2, 0.90), (3, 0.80), (5, 0.60),
    (10, 0.40), (20, 0.20), (50, 0.10), (7, 0.10),
])
def test_leverage_penalty(leverage, expected_multiplier):
    result = adjust_position_for_leverage(10_000.0, leverage)
    assert result == pytest.approx(10_000.0 * expected_multiplier)


def test_penalty_uses_original_leverage_not_capped():
    """20x trader gets 0.20 multiplier, even though we execute at 5x."""
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=20.0,
    )
    result = calculate_position_size(req, _clean_account())
    # 10000 * 0.20 = 2000 (before caps)
    assert result.sizing_breakdown["after_leverage_penalty"] == pytest.approx(2_000.0)


# ---------------------------------------------------------------------------
# 9.3 Position and Exposure Caps
# ---------------------------------------------------------------------------

def test_single_position_cap_10_pct():
    """Account $100k -> max single position $10k."""
    account = AccountState(account_value_usd=100_000)
    req = SizingRequest(
        base_position_usd=50_000, token="BTC", side=Side.LONG,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 10_000


def test_single_position_hard_cap_50k():
    """Account $1M -> 10% = $100k, but hard cap is $50k."""
    account = AccountState(account_value_usd=1_000_000)
    req = SizingRequest(
        base_position_usd=200_000, token="BTC", side=Side.LONG,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 50_000


def test_total_exposure_cap():
    """Reject when total open positions at 50% of account."""
    account = AccountState(
        account_value_usd=100_000,
        total_open_positions_usd=50_000,
    )
    req = SizingRequest(
        base_position_usd=5_000, token="BTC", side=Side.LONG,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, account)
    assert result.rejected is True


def test_per_token_exposure_cap():
    """15% per token cap."""
    account = AccountState(
        account_value_usd=100_000,
        token_exposure_usd={"BTC": 14_000},
    )
    req = SizingRequest(
        base_position_usd=5_000, token="BTC", side=Side.LONG,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 1_000


def test_directional_long_exposure_cap():
    """60% directional cap for longs."""
    account = AccountState(
        account_value_usd=100_000,
        total_long_exposure_usd=59_000,
    )
    req = SizingRequest(
        base_position_usd=5_000, token="BTC", side=Side.LONG,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 1_000


def test_directional_short_exposure_cap():
    """60% directional cap for shorts."""
    account = AccountState(
        account_value_usd=100_000,
        total_short_exposure_usd=60_000,
    )
    req = SizingRequest(
        base_position_usd=5_000, token="BTC", side=Side.SHORT,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, account)
    assert result.rejected is True


# ---------------------------------------------------------------------------
# 9.7 Margin Type
# ---------------------------------------------------------------------------

def test_margin_always_isolated():
    """Every SizingResult must have margin_type = ISOLATED."""
    req = SizingRequest(
        base_position_usd=1_000, token="BTC", side=Side.LONG,
        trader_leverage=1.0,
    )
    result = calculate_position_size(req, _clean_account())
    assert result.margin_type == MarginType.ISOLATED


# ---------------------------------------------------------------------------
# 9.8 Full Pipeline Integration
# ---------------------------------------------------------------------------

def test_full_pipeline_20x_trader():
    """
    20x trader, $10k base, $200k account.
    Step 1: leverage = 20 (provided)
    Step 2: effective = min(20, 5) = 5x
    Step 3: penalty = 10000 * 0.20 = $2,000
    Step 4: cap = min(2000, 200000*0.10, 50000) = $2,000
    Step 5-7: well within caps (assuming clean account)
    Result: $2,000 at 5x isolated
    """
    account = _clean_account(200_000)
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=20.0,
    )
    result = calculate_position_size(req, account)
    assert result.final_position_usd == pytest.approx(2_000.0)
    assert result.effective_leverage == 5.0
    assert result.margin_type == MarginType.ISOLATED
    assert result.rejected is False


def test_full_pipeline_inferred_leverage():
    """Leverage inferred from position_value / margin."""
    account = _clean_account(200_000)
    req = SizingRequest(
        base_position_usd=10_000, token="ETH", side=Side.SHORT,
        trader_leverage=None,
        trader_position_value_usd=50_000.0,
        trader_margin_used_usd=10_000.0,  # 5x inferred
    )
    result = calculate_position_size(req, account)
    # 5x -> penalty 0.60 -> 10000 * 0.60 = 6000
    assert result.final_position_usd == pytest.approx(6_000.0)
    assert result.effective_leverage == 5.0


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def test_raises_on_zero_base_position():
    req = SizingRequest(base_position_usd=0, token="BTC", side=Side.LONG)
    with pytest.raises(ValueError, match="base_position_usd"):
        calculate_position_size(req, _clean_account())


def test_raises_on_empty_token():
    req = SizingRequest(base_position_usd=1000, token="", side=Side.LONG)
    with pytest.raises(ValueError, match="token"):
        calculate_position_size(req, _clean_account())


def test_raises_on_zero_account_value():
    account = AccountState(account_value_usd=0)
    req = SizingRequest(base_position_usd=1000, token="BTC", side=Side.LONG)
    with pytest.raises(ValueError, match="account_value_usd"):
        calculate_position_size(req, account)


# ---------------------------------------------------------------------------
# Dust Trade Rejection
# ---------------------------------------------------------------------------

def test_dust_trade_rejected():
    """Position penalized to below $10 should be rejected."""
    account = _clean_account(200_000)
    # 50x leverage -> penalty 0.10 -> 50 * 0.10 = $5 (dust)
    req = SizingRequest(
        base_position_usd=50, token="BTC", side=Side.LONG,
        trader_leverage=50.0,
    )
    result = calculate_position_size(req, account)
    assert result.rejected is True


# ---------------------------------------------------------------------------
# Sizing Breakdown Audit Trail
# ---------------------------------------------------------------------------

def test_sizing_breakdown_present():
    """Every SizingResult includes a sizing_breakdown dict."""
    req = SizingRequest(
        base_position_usd=10_000, token="BTC", side=Side.LONG,
        trader_leverage=3.0,
    )
    result = calculate_position_size(req, _clean_account())
    assert isinstance(result.sizing_breakdown, dict)
    assert "resolved_leverage" in result.sizing_breakdown
    assert "effective_leverage" in result.sizing_breakdown
    assert "after_leverage_penalty" in result.sizing_breakdown
    assert "final_position_usd" in result.sizing_breakdown
