import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.risk.account_state import AccountStateManager
from src.risk.nansen_client import NansenClient
from src.risk.strategy_adapter import (
    ExecutionOrder,
    RiskAdapter,
    build_consensus_request,
    build_entry_only_request,
    build_pnl_weighted_request,
    build_rebalance_request,
    log_sizing_audit,
    sizing_result_to_order,
)
from src.risk.sizing import calculate_position_size
from src.risk.types import AccountState, MarginType, Side, SizingRequest, SizingResult


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


def _make_adapter(account_value: float = 200_000.0) -> RiskAdapter:
    nansen = AsyncMock(spec=NansenClient)
    mgr = AccountStateManager(
        address="0xABC",
        nansen_client=nansen,
        account_value_usd=account_value,
    )
    return RiskAdapter(state_manager=mgr)


# ---------------------------------------------------------------------------
# Strategy Request Builders
# ---------------------------------------------------------------------------

class TestRequestBuilders:
    def test_rebalance_request(self):
        req = build_rebalance_request("BTC", Side.LONG, 8_000.0)
        assert req.base_position_usd == 8_000.0
        assert req.token == "BTC"
        assert req.side == Side.LONG
        assert req.trader_leverage is None

    def test_consensus_request(self):
        req = build_consensus_request("ETH", Side.SHORT, 5_000.0, avg_leverage=3.5)
        assert req.base_position_usd == 5_000.0
        assert req.trader_leverage == 3.5

    def test_entry_only_request(self):
        req = build_entry_only_request(
            "SOL", Side.LONG, signal_value_usd=10_000.0, copy_ratio=0.5,
            trader_leverage=5.0, position_value_usd=50_000.0, margin_used_usd=10_000.0,
        )
        assert req.base_position_usd == pytest.approx(5_000.0)
        assert req.trader_leverage == 5.0
        assert req.trader_position_value_usd == 50_000.0
        assert req.trader_margin_used_usd == 10_000.0

    def test_pnl_weighted_request(self):
        req = build_pnl_weighted_request(
            "BTC", Side.SHORT, default_allocation_usd=10_000.0, pnl_weight=0.8,
            trader_leverage=2.0, position_value_usd=20_000.0, margin_used_usd=10_000.0,
        )
        assert req.base_position_usd == pytest.approx(8_000.0)
        assert req.trader_leverage == 2.0


# ---------------------------------------------------------------------------
# Sizing Result to Order Conversion
# ---------------------------------------------------------------------------

class TestOrderConversion:
    def test_accepted_result_produces_order(self):
        result = SizingResult(
            final_position_usd=5_000.0, effective_leverage=3.0,
            margin_type=MarginType.ISOLATED, order_type=MarginType.ISOLATED,
            max_slippage_pct=0.05, rejected=False,
        )
        # Need proper OrderType
        from src.risk.types import OrderType
        result.order_type = OrderType.LIMIT
        order = sizing_result_to_order(result, "BTC", Side.LONG)
        assert order is not None
        assert isinstance(order, ExecutionOrder)
        assert order.token == "BTC"
        assert order.side == "Long"
        assert order.size_usd == 5_000.0
        assert order.leverage == 3.0
        assert order.margin_type == "isolated"

    def test_rejected_result_returns_none(self):
        result = SizingResult(
            final_position_usd=0.0, effective_leverage=5.0,
            margin_type=MarginType.ISOLATED, order_type=MarginType.ISOLATED,
            max_slippage_pct=0.05, rejected=True, rejection_reason="Caps exceeded",
        )
        order = sizing_result_to_order(result, "BTC", Side.LONG)
        assert order is None


# ---------------------------------------------------------------------------
# RiskAdapter
# ---------------------------------------------------------------------------

class TestRiskAdapter:
    def test_size_position_with_cached_state(self):
        """Adapter uses AccountStateManager's cached state."""
        adapter = _make_adapter(200_000.0)
        req = build_rebalance_request("BTC", Side.LONG, 8_000.0)
        order = adapter.size_position("rebalance", req)

        # 8000 * 0.60 (5x penalty) = 4800 (leverage=None -> default 5x)
        assert order is not None
        assert order.token == "BTC"
        assert order.side == "Long"
        assert order.leverage == 5.0
        assert order.margin_type == "isolated"

    def test_size_position_with_explicit_account(self):
        """Adapter uses explicit AccountState when provided."""
        adapter = _make_adapter(200_000.0)
        account = _clean_account(50_000.0)
        req = build_consensus_request("ETH", Side.SHORT, 5_000.0, avg_leverage=2.0)
        order = adapter.size_position("consensus", req, account=account)

        assert order is not None
        # 5000 * 0.90 (2x penalty) = 4500
        assert order.size_usd == pytest.approx(4_500.0)

    def test_size_position_rejected_returns_none(self):
        """When sizing rejects (caps exceeded), adapter returns None."""
        adapter = _make_adapter(200_000.0)
        # Max out total positions to force rejection
        full_account = AccountState(
            account_value_usd=100_000.0,
            total_open_positions_usd=50_000.0,
        )
        req = build_rebalance_request("BTC", Side.LONG, 5_000.0)
        order = adapter.size_position("rebalance", req, account=full_account)
        assert order is None

    @pytest.mark.asyncio
    async def test_size_position_fresh(self):
        """size_position_fresh calls ensure_fresh before sizing."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=[])
        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
        )
        adapter = RiskAdapter(state_manager=mgr)
        req = build_rebalance_request("BTC", Side.LONG, 5_000.0)
        order = await adapter.size_position_fresh("rebalance", req)

        assert order is not None
        # ensure_fresh should have been called (refreshed state)
        nansen.fetch_address_perp_positions.assert_called_once()


# ---------------------------------------------------------------------------
# E2E: Full Signal -> Sizing -> Mock Execution Pipeline
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_strategy2_rebalance_e2e(self):
        """Strategy #2: $8k BTC rebalance on $200k account."""
        account = _clean_account(200_000.0)
        req = build_rebalance_request("BTC", Side.LONG, 8_000.0)
        result = calculate_position_size(req, account)

        assert not result.rejected
        # leverage=None -> 5x default -> penalty=0.60 -> 8000*0.60 = 4800
        assert result.final_position_usd == pytest.approx(4_800.0)
        assert result.effective_leverage == 5.0
        assert result.margin_type == MarginType.ISOLATED

        order = sizing_result_to_order(result, "BTC", Side.LONG)
        assert order is not None
        assert order.size_usd == pytest.approx(4_800.0)
        assert order.margin_type == "isolated"

    def test_strategy3_consensus_e2e(self):
        """Strategy #3: $5k ETH consensus with avg 3x leverage on $200k account."""
        account = _clean_account(200_000.0)
        req = build_consensus_request("ETH", Side.SHORT, 5_000.0, avg_leverage=3.0)
        result = calculate_position_size(req, account)

        assert not result.rejected
        # 3x -> penalty=0.80 -> 5000*0.80 = 4000
        assert result.final_position_usd == pytest.approx(4_000.0)
        assert result.effective_leverage == 3.0

    def test_strategy5_entry_only_e2e(self):
        """Strategy #5: Entry-only $10k SOL with 0.5 copy ratio, 5x leverage."""
        account = _clean_account(200_000.0)
        req = build_entry_only_request(
            "SOL", Side.LONG, signal_value_usd=10_000.0, copy_ratio=0.5,
            trader_leverage=5.0, position_value_usd=50_000.0, margin_used_usd=10_000.0,
        )
        result = calculate_position_size(req, account)

        assert not result.rejected
        # base = 10000 * 0.5 = 5000, 5x -> penalty=0.60 -> 5000*0.60 = 3000
        assert result.final_position_usd == pytest.approx(3_000.0)
        assert result.effective_leverage == 5.0

    def test_strategy9_pnl_weighted_e2e(self):
        """Strategy #9: PnL-weighted $10k * 0.8 = $8k, 2x leverage."""
        account = _clean_account(200_000.0)
        req = build_pnl_weighted_request(
            "BTC", Side.SHORT, default_allocation_usd=10_000.0, pnl_weight=0.8,
            trader_leverage=2.0, position_value_usd=20_000.0, margin_used_usd=10_000.0,
        )
        result = calculate_position_size(req, account)

        assert not result.rejected
        # base = 10000 * 0.8 = 8000, 2x -> penalty=0.90 -> 8000*0.90 = 7200
        assert result.final_position_usd == pytest.approx(7_200.0)
        assert result.effective_leverage == 2.0

    def test_e2e_progressive_account_fill(self):
        """
        Simulate progressive fills: multiple signals filling the account.
        The last signal should be capped or rejected due to exposure limits.
        """
        account = AccountState(
            account_value_usd=100_000.0,
            total_open_positions_usd=45_000.0,  # 45% filled
            total_long_exposure_usd=30_000.0,
            total_short_exposure_usd=15_000.0,
            token_exposure_usd={"BTC": 12_000.0, "ETH": 8_000.0},
        )
        # Try to add another $10k BTC long
        req = build_rebalance_request("BTC", Side.LONG, 10_000.0)
        result = calculate_position_size(req, account)

        if not result.rejected:
            # Should be capped: remaining total capacity = 50k - 45k = 5k
            # remaining BTC capacity = 15k - 12k = 3k
            # So final should be <= 3000 (BTC token cap is tighter)
            assert result.final_position_usd <= 3_000.0
        # Either way, the module enforced the caps

    def test_e2e_audit_trail_logged(self, caplog):
        """Verify audit trail is logged."""
        account = _clean_account(200_000.0)
        req = build_consensus_request("ETH", Side.LONG, 5_000.0, avg_leverage=3.0)
        result = calculate_position_size(req, account)

        with caplog.at_level(logging.INFO):
            log_sizing_audit("consensus", req, result)

        assert "consensus" in caplog.text
        assert "SIZED" in caplog.text
        assert "ETH" in caplog.text

    def test_e2e_rejected_audit_trail_logged(self, caplog):
        """Verify rejected audit trail is logged."""
        full_account = AccountState(
            account_value_usd=100_000.0,
            total_open_positions_usd=50_000.0,
        )
        req = build_rebalance_request("BTC", Side.LONG, 5_000.0)
        result = calculate_position_size(req, full_account)
        assert result.rejected

        with caplog.at_level(logging.WARNING):
            log_sizing_audit("rebalance", req, result)

        assert "REJECTED" in caplog.text
        assert "rebalance" in caplog.text
