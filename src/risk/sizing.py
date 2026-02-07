from typing import Optional

from src.risk.constants import (
    MAX_ALLOWED_LEVERAGE,
    LEVERAGE_PENALTY_MAP,
    LEVERAGE_PENALTY_DEFAULT,
    USE_MARGIN_TYPE,
    MAX_SINGLE_POSITION_HARD_CAP,
    MAX_SINGLE_POSITION_PCT,
    MAX_TOTAL_OPEN_POSITIONS_PCT,
    MAX_EXPOSURE_PER_TOKEN_PCT,
    MAX_LONG_EXPOSURE_PCT,
    MAX_SHORT_EXPOSURE_PCT,
    MIN_POSITION_USD,
)
from src.risk.types import (
    Side,
    OrderType,
    SizingRequest,
    AccountState,
    SizingResult,
)
from src.risk.leverage import infer_leverage
from src.risk.slippage import get_slippage_assumption


def adjust_position_for_leverage(base_position_usd: float, leverage: float) -> float:
    """
    Apply leverage penalty to base position size.
    Uses the ORIGINAL trader leverage (not capped), because the penalty reflects
    the risk profile of the trader being copied.

    Exact Agent 1 rule:
    leverage_penalty = {1: 1.00, 2: 0.90, 3: 0.80, 5: 0.60, 10: 0.40, 20: 0.20}
    multiplier = leverage_penalty.get(leverage, 0.10)
    """
    leverage_int = int(round(leverage))
    multiplier = LEVERAGE_PENALTY_MAP.get(leverage_int, LEVERAGE_PENALTY_DEFAULT)
    return base_position_usd * multiplier


def calculate_position_size(request: SizingRequest, account: AccountState) -> SizingResult:
    """
    Main entry point. Runs the full sizing pipeline (Steps 1-9) and returns a SizingResult.

    Raises ValueError for invalid inputs.
    Returns SizingResult(rejected=True) for soft failures (caps exceeded, exposure breached).
    """
    # --- Input validation ---
    if request.base_position_usd <= 0:
        raise ValueError("base_position_usd must be > 0")
    if not request.token:
        raise ValueError("token must not be empty")
    if account.account_value_usd <= 0:
        raise ValueError("account_value_usd must be > 0")

    breakdown: dict = {}

    # Step 1: Resolve leverage
    if request.trader_leverage is not None:
        resolved_leverage = request.trader_leverage
    elif (
        request.trader_position_value_usd is not None
        and request.trader_margin_used_usd is not None
    ):
        resolved_leverage = infer_leverage(
            request.trader_position_value_usd, request.trader_margin_used_usd
        )
    else:
        resolved_leverage = MAX_ALLOWED_LEVERAGE
    breakdown["resolved_leverage"] = resolved_leverage

    # Step 2: Cap leverage
    effective_leverage = min(resolved_leverage, MAX_ALLOWED_LEVERAGE)
    breakdown["effective_leverage"] = effective_leverage

    # Step 3: Apply leverage penalty (uses ORIGINAL trader leverage, not capped)
    penalized_usd = adjust_position_for_leverage(
        request.base_position_usd, resolved_leverage
    )
    breakdown["after_leverage_penalty"] = penalized_usd

    # Step 4: Apply single-position cap
    account_pct_cap = account.account_value_usd * MAX_SINGLE_POSITION_PCT
    capped_usd = min(penalized_usd, account_pct_cap, MAX_SINGLE_POSITION_HARD_CAP)
    breakdown["after_single_position_cap"] = capped_usd

    # Step 5: Check total open positions cap
    remaining_capacity = (
        account.account_value_usd * MAX_TOTAL_OPEN_POSITIONS_PCT
    ) - account.total_open_positions_usd
    breakdown["total_position_remaining_capacity"] = remaining_capacity
    if remaining_capacity <= 0:
        return _rejected_result(
            effective_leverage,
            "Total open positions cap exceeded",
            breakdown,
            request.token,
        )
    capped_usd = min(capped_usd, remaining_capacity)
    breakdown["after_total_position_cap"] = capped_usd

    # Step 6: Check per-token exposure cap
    current_token_exposure = account.token_exposure_usd.get(request.token, 0.0)
    token_capacity = (
        account.account_value_usd * MAX_EXPOSURE_PER_TOKEN_PCT
    ) - current_token_exposure
    breakdown["token_remaining_capacity"] = token_capacity
    if token_capacity <= 0:
        return _rejected_result(
            effective_leverage,
            f"Per-token exposure cap exceeded for {request.token}",
            breakdown,
            request.token,
        )
    capped_usd = min(capped_usd, token_capacity)
    breakdown["after_token_cap"] = capped_usd

    # Step 7: Check directional exposure cap
    if request.side == Side.LONG:
        dir_capacity = (
            account.account_value_usd * MAX_LONG_EXPOSURE_PCT
        ) - account.total_long_exposure_usd
    else:
        dir_capacity = (
            account.account_value_usd * MAX_SHORT_EXPOSURE_PCT
        ) - account.total_short_exposure_usd
    breakdown["directional_remaining_capacity"] = dir_capacity
    if dir_capacity <= 0:
        return _rejected_result(
            effective_leverage,
            f"Directional exposure cap exceeded for {request.side.value}",
            breakdown,
            request.token,
        )
    capped_usd = min(capped_usd, dir_capacity)
    breakdown["after_directional_cap"] = capped_usd

    # Step 8: Final validation — dust trade check
    if capped_usd < MIN_POSITION_USD:
        return _rejected_result(
            effective_leverage,
            f"Position size {capped_usd:.2f} below minimum {MIN_POSITION_USD}",
            breakdown,
            request.token,
        )

    # Step 9: Build result
    breakdown["final_position_usd"] = capped_usd
    slippage = get_slippage_assumption(request.token)

    return SizingResult(
        final_position_usd=capped_usd,
        effective_leverage=effective_leverage,
        margin_type=USE_MARGIN_TYPE,
        order_type=OrderType.LIMIT,
        max_slippage_pct=slippage,
        rejected=False,
        rejection_reason=None,
        sizing_breakdown=breakdown,
    )


def _rejected_result(
    effective_leverage: float,
    reason: str,
    breakdown: dict,
    token: str,
) -> SizingResult:
    """Helper to build a rejected SizingResult."""
    breakdown["rejection_reason"] = reason
    return SizingResult(
        final_position_usd=0.0,
        effective_leverage=effective_leverage,
        margin_type=USE_MARGIN_TYPE,
        order_type=OrderType.LIMIT,
        max_slippage_pct=get_slippage_assumption(token),
        rejected=True,
        rejection_reason=reason,
        sizing_breakdown=breakdown,
    )
