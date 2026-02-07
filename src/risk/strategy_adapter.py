import logging
from dataclasses import dataclass
from typing import Optional

from src.risk.account_state import AccountStateManager
from src.risk.sizing import calculate_position_size
from src.risk.types import AccountState, Side, SizingRequest, SizingResult

logger = logging.getLogger(__name__)


@dataclass
class ExecutionOrder:
    """Output order ready for the execution layer."""
    token: str
    side: str
    size_usd: float
    leverage: float
    margin_type: str
    order_type: str
    max_slippage_pct: float


def sizing_result_to_order(result: SizingResult, token: str, side: Side) -> Optional[ExecutionOrder]:
    """Convert a non-rejected SizingResult to an ExecutionOrder."""
    if result.rejected:
        return None
    return ExecutionOrder(
        token=token,
        side=side.value,
        size_usd=result.final_position_usd,
        leverage=result.effective_leverage,
        margin_type=result.margin_type.value,
        order_type=result.order_type.value,
        max_slippage_pct=result.max_slippage_pct,
    )


def log_sizing_audit(strategy_name: str, request: SizingRequest, result: SizingResult) -> None:
    """Log a structured audit trail for a sizing decision."""
    if result.rejected:
        logger.warning(
            "[%s] REJECTED %s %s $%.2f — reason: %s",
            strategy_name, request.token, request.side.value,
            request.base_position_usd, result.rejection_reason,
        )
    else:
        logger.info(
            "[%s] SIZED %s %s $%.2f -> $%.2f @ %.1fx %s (slippage=%.2f%%)",
            strategy_name, request.token, request.side.value,
            request.base_position_usd, result.final_position_usd,
            result.effective_leverage, result.margin_type.value,
            result.max_slippage_pct,
        )

    logger.debug("[%s] Breakdown: %s", strategy_name, result.sizing_breakdown)


class RiskAdapter:
    """
    Integration adapter for upstream strategies to call the risk module.

    Wraps calculate_position_size with AccountStateManager for fresh state,
    structured logging, and order conversion.

    Usage:
        adapter = RiskAdapter(account_state_manager)
        order = adapter.size_position("consensus", request)
        if order is not None:
            execute(order)
    """

    def __init__(self, state_manager: AccountStateManager) -> None:
        self._state_manager = state_manager

    def size_position(
        self,
        strategy_name: str,
        request: SizingRequest,
        account: Optional[AccountState] = None,
    ) -> Optional[ExecutionOrder]:
        """
        Run the sizing pipeline and return an ExecutionOrder (or None if rejected).

        Args:
            strategy_name: Name of the calling strategy (for audit trail).
            request: The SizingRequest from the strategy.
            account: Optional AccountState override. If None, uses the
                     AccountStateManager's current cached state.
        """
        if account is None:
            account = self._state_manager.get_current_state()

        result = calculate_position_size(request, account)
        log_sizing_audit(strategy_name, request, result)

        return sizing_result_to_order(result, request.token, request.side)

    async def size_position_fresh(
        self,
        strategy_name: str,
        request: SizingRequest,
    ) -> Optional[ExecutionOrder]:
        """
        Like size_position but ensures the account state is fresh first.

        Useful when a strategy needs the most up-to-date account state
        before making a sizing decision (e.g. at signal time).
        """
        account = await self._state_manager.ensure_fresh()
        return self.size_position(strategy_name, request, account)


# ---------------------------------------------------------------------------
# Example integration helpers for each strategy
# ---------------------------------------------------------------------------

def build_rebalance_request(
    token: str,
    side: Side,
    target_usd: float,
) -> SizingRequest:
    """
    Strategy #2 — Position Snapshot Rebalancing.
    Aggregated from multiple traders, no specific leverage.
    """
    return SizingRequest(
        base_position_usd=target_usd,
        token=token,
        side=side,
        trader_leverage=None,
        trader_position_value_usd=None,
        trader_margin_used_usd=None,
    )


def build_consensus_request(
    token: str,
    side: Side,
    suggested_size_usd: float,
    avg_leverage: float,
) -> SizingRequest:
    """
    Strategy #3 — Consensus Trading.
    Average leverage from agreeing traders.
    """
    return SizingRequest(
        base_position_usd=suggested_size_usd,
        token=token,
        side=side,
        trader_leverage=avg_leverage,
        trader_position_value_usd=None,
        trader_margin_used_usd=None,
    )


def build_entry_only_request(
    token: str,
    side: Side,
    signal_value_usd: float,
    copy_ratio: float,
    trader_leverage: Optional[float],
    position_value_usd: Optional[float],
    margin_used_usd: Optional[float],
) -> SizingRequest:
    """
    Strategy #5 — Entry-Only Signals.
    Copies "Open" actions with specific trader leverage data.
    """
    return SizingRequest(
        base_position_usd=signal_value_usd * copy_ratio,
        token=token,
        side=side,
        trader_leverage=trader_leverage,
        trader_position_value_usd=position_value_usd,
        trader_margin_used_usd=margin_used_usd,
    )


def build_pnl_weighted_request(
    token: str,
    side: Side,
    default_allocation_usd: float,
    pnl_weight: float,
    trader_leverage: Optional[float],
    position_value_usd: Optional[float],
    margin_used_usd: Optional[float],
) -> SizingRequest:
    """
    Strategy #9 — PnL-Weighted Allocation.
    Base position is PnL-weighted by the strategy.
    """
    return SizingRequest(
        base_position_usd=default_allocation_usd * pnl_weight,
        token=token,
        side=side,
        trader_leverage=trader_leverage,
        trader_position_value_usd=position_value_usd,
        trader_margin_used_usd=margin_used_usd,
    )
