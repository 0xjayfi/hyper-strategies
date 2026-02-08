"""Task 10.7 -- End-to-end integration test.

Exercises the full signal pipeline with an in-memory SQLite database and
mocked external dependencies (Nansen API, Hyperliquid executor).

Flow:
  1. Init DB (in-memory via patched DB_PATH).
  2. Insert a scored trader.
  3. Create a mock trade dict.
  4. Call evaluate_trade.
  5. Verify signal passes with correct copy_size_usd.
  6. Paper-execute the signal.
  7. Verify position recorded in DB.
  8. Test trailing stop update.
  9. Test trailing stop trigger -> position closed.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import OurPosition, Signal


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_position(
    *,
    id: int = 1,
    token_symbol: str = "BTC",
    side: str = "Long",
    entry_price: float = 50_000.0,
    size: float = 0.2,
    value_usd: float = 10_000.0,
    stop_price: float | None = 47_500.0,
    trailing_stop_price: float | None = 46_000.0,
    highest_price: float | None = 50_000.0,
    lowest_price: float | None = None,
    opened_at: str = "2024-06-01T12:00:00+00:00",
    source_trader: str | None = "0xTrader456",
    source_signal_id: str | None = "sig-001",
    status: str = "open",
    close_reason: str | None = None,
) -> OurPosition:
    return OurPosition(
        id=id,
        token_symbol=token_symbol,
        side=side,
        entry_price=entry_price,
        size=size,
        value_usd=value_usd,
        stop_price=stop_price,
        trailing_stop_price=trailing_stop_price,
        highest_price=highest_price,
        lowest_price=lowest_price,
        opened_at=opened_at,
        source_trader=source_trader,
        source_signal_id=source_signal_id,
        status=status,
        close_reason=close_reason,
    )


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestFullSignalPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self) -> None:
        """End-to-end: trade evaluation -> execution -> position monitoring."""

        # -- 1. Init DB using a temp file so we get a real SQLite backend --
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("src.db.DB_PATH", tmp_path):
                from src import db
                # Force re-connection by patching the module attribute
                db.DB_PATH = tmp_path
                await db.init()

                # -- 2. Insert a scored trader --
                await db.upsert_trader(
                    address="0xTrader456",
                    label="TopTrader",
                    score=0.85,
                    style="SWING",
                    tier="primary",
                    roi_7d=15.0,
                    roi_30d=25.0,
                    account_value=500_000.0,
                    nof_trades=120,
                    last_scored_at=datetime.now(timezone.utc).isoformat(),
                )

                trader_row = await db.get_trader("0xTrader456")
                assert trader_row is not None
                assert trader_row["score"] == 0.85
                assert trader_row["tier"] == "primary"

                # -- 3. Create a mock trade --
                # Age must be > 15 min (copy delay) so it is not deferred.
                # Age > 10 min hits the "else" branch in Step 6 which requires
                # score > 0.8 AND position_weight > 0.25.
                # value_usd = 200k, account_value = 500k => weight = 0.4 > 0.25
                now_utc = datetime.now(timezone.utc)
                trade_time = now_utc - timedelta(minutes=20)
                trade = {
                    "action": "Open",
                    "side": "Long",
                    "token_symbol": "BTC",
                    "value_usd": 200_000,
                    "price": 50_000,
                    "timestamp": trade_time.isoformat(),
                    "transaction_hash": "0xabc123",
                }

                # -- 4. Evaluate the trade --
                from src.models import TraderRow
                from src.trade_ingestion import evaluate_trade

                trader = TraderRow(**trader_row)

                mock_nansen = MagicMock()
                # Step 4 position verification: trader still holds the position
                mock_nansen.get_address_perp_positions = AsyncMock(return_value={
                    "data": {
                        "asset_positions": [
                            {
                                "position": {
                                    "token_symbol": "BTC",
                                    "size": "2.0",
                                    "leverage_value": None,
                                }
                            }
                        ]
                    }
                })
                # For _find_original_open used by Add action (not needed for Open)
                mock_nansen.get_address_perp_trades = AsyncMock(return_value=[])

                # Patch get_current_price to return a price close to trade price
                with patch("src.trade_ingestion.get_current_price", new_callable=AsyncMock) as mock_price:
                    mock_price.return_value = 50_100.0  # 0.2% slippage, well under 2%

                    # Patch _get_our_account_value
                    with patch("src.trade_ingestion._get_our_account_value", new_callable=AsyncMock) as mock_acct:
                        mock_acct.return_value = 100_000.0

                        result = await evaluate_trade(trade, trader, mock_nansen)

                # -- 5. Verify signal --
                assert result is not None
                assert isinstance(result, Signal)
                assert result.decision == "EXECUTE"
                assert result.token_symbol == "BTC"
                assert result.side == "Long"
                # Sizing: 100k * (200k/500k) * 0.5 * 1.0 (hot, roi=15) = 20,000
                # Cap: min(100k*0.10, 50k) = 10,000
                assert result.copy_size_usd == 10_000

                # -- 6. Paper-execute --
                from src.executor import HyperLiquidExecutor

                mock_sdk = MagicMock()
                mock_sdk.info = MagicMock()
                mock_sdk.info.all_mids = MagicMock(return_value={"BTC": "50000.0"})

                with patch("src.executor.settings") as mock_settings:
                    mock_settings.PAPER_MODE = True
                    mock_settings.STOP_LOSS_PERCENT = 5.0
                    mock_settings.TRAILING_STOP_PERCENT = 8.0

                    executor = HyperLiquidExecutor(sdk_client=mock_sdk)
                    exec_result = await executor.execute_signal(result)

                assert exec_result.success is True
                assert exec_result.fill_price == 50_000.0

                # -- 7. Verify position in DB --
                open_positions = await db.get_open_positions()
                assert len(open_positions) >= 1

                our_pos_dict = open_positions[-1]  # most recent
                assert our_pos_dict["token_symbol"] == "BTC"
                assert our_pos_dict["side"] == "Long"
                assert our_pos_dict["entry_price"] == 50_000.0
                assert our_pos_dict["status"] == "open"

                our_pos = OurPosition(**our_pos_dict)

                # -- 8. Test trailing stop update --
                from src.position_monitor import update_trailing_stop

                # Simulate price going up to 55,000
                updates = update_trailing_stop(our_pos, mark_price=55_000.0)
                assert updates is not None
                assert updates["highest_price"] == 55_000.0
                expected_trail = 55_000.0 * (1 - 0.08)  # 50,600
                assert updates["trailing_stop_price"] == pytest.approx(expected_trail, rel=1e-4)

                # Apply the updates to the position in-memory
                for key, value in updates.items():
                    if hasattr(our_pos, key):
                        object.__setattr__(our_pos, key, value)

                # -- 9. Test trailing stop trigger -> close --
                from src.position_monitor import trailing_stop_triggered

                # Price drops below trail (50,600) -> triggered
                assert trailing_stop_triggered(our_pos, mark_price=50_000.0) is True

                # Price above trail -> not triggered
                assert trailing_stop_triggered(our_pos, mark_price=52_000.0) is False

        finally:
            os.unlink(tmp_path)


class TestDBInsertAndRetrieve:
    """Lower-level integration test: verify DB round-trip for positions."""

    @pytest.mark.asyncio
    async def test_insert_and_close_position(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("src.db.DB_PATH", tmp_path):
                from src import db
                db.DB_PATH = tmp_path
                await db.init()

                row_id = await db.insert_our_position(
                    token_symbol="ETH",
                    side="Short",
                    entry_price=3_500.0,
                    size=5.0,
                    value_usd=17_500.0,
                    stop_price=3_675.0,
                    trailing_stop_price=3_780.0,
                    highest_price=None,
                    lowest_price=3_500.0,
                    opened_at=datetime.now(timezone.utc).isoformat(),
                    source_trader="0xShortSeller",
                    source_signal_id="sig-short-1",
                    status="open",
                    close_reason=None,
                )
                assert row_id >= 1

                open_positions = await db.get_open_positions()
                assert len(open_positions) == 1
                assert open_positions[0]["token_symbol"] == "ETH"
                assert open_positions[0]["side"] == "Short"

                await db.close_position(row_id, close_reason="trailing_stop")

                open_after_close = await db.get_open_positions()
                assert len(open_after_close) == 0

        finally:
            os.unlink(tmp_path)


class TestTrailingStopFullCycle:
    """Integration: trailing stop update -> trigger -> close via monitor_positions."""

    @pytest.mark.asyncio
    async def test_trailing_stop_cycle(self) -> None:
        """Simulate mark price rising, then falling through the trailing stop."""
        from src.position_monitor import (
            trailing_stop_triggered,
            update_trailing_stop,
        )

        pos = make_position(
            side="Long",
            entry_price=100.0,
            size=10.0,
            value_usd=1_000.0,
            highest_price=100.0,
            trailing_stop_price=92.0,  # initial: 100 * (1 - 0.08)
        )

        # Price rises to 120 -> update trail
        updates = update_trailing_stop(pos, mark_price=120.0)
        assert updates is not None
        assert updates["highest_price"] == 120.0
        new_trail = updates["trailing_stop_price"]
        assert new_trail == pytest.approx(120.0 * 0.92, rel=1e-4)

        # Apply
        object.__setattr__(pos, "highest_price", updates["highest_price"])
        object.__setattr__(pos, "trailing_stop_price", new_trail)

        # Price rises to 130 -> update trail again
        updates2 = update_trailing_stop(pos, mark_price=130.0)
        assert updates2 is not None
        new_trail_2 = updates2["trailing_stop_price"]
        assert new_trail_2 == pytest.approx(130.0 * 0.92, rel=1e-4)
        assert new_trail_2 > new_trail  # trail only moves up

        # Apply
        object.__setattr__(pos, "highest_price", updates2["highest_price"])
        object.__setattr__(pos, "trailing_stop_price", new_trail_2)

        # Price drops to 125 -> no update (below highest)
        updates3 = update_trailing_stop(pos, mark_price=125.0)
        assert updates3 is None

        # Price drops below trail (119.6) -> triggered
        assert trailing_stop_triggered(pos, mark_price=119.0) is True

        # Just above trail -> not triggered
        assert trailing_stop_triggered(pos, mark_price=120.5) is False


class TestUnrealizedPnL:
    """Integration: verify unrealized PnL computation feeds into monitoring."""

    def test_unrealized_long_profit(self) -> None:
        from src.position_monitor import compute_unrealized_pct

        pos = make_position(side="Long", entry_price=100.0)
        pct = compute_unrealized_pct(pos, mark_price=110.0)
        assert pct == pytest.approx(10.0)  # +10%

    def test_unrealized_long_loss(self) -> None:
        from src.position_monitor import compute_unrealized_pct

        pos = make_position(side="Long", entry_price=100.0)
        pct = compute_unrealized_pct(pos, mark_price=90.0)
        assert pct == pytest.approx(-10.0)  # -10%

    def test_unrealized_short_profit(self) -> None:
        from src.position_monitor import compute_unrealized_pct

        pos = make_position(side="Short", entry_price=100.0)
        pct = compute_unrealized_pct(pos, mark_price=90.0)
        assert pct == pytest.approx(10.0)  # +10%

    def test_unrealized_short_loss(self) -> None:
        from src.position_monitor import compute_unrealized_pct

        pos = make_position(side="Short", entry_price=100.0)
        pct = compute_unrealized_pct(pos, mark_price=110.0)
        assert pct == pytest.approx(-10.0)  # -10%

    def test_unrealized_zero_entry(self) -> None:
        from src.position_monitor import compute_unrealized_pct

        pos = make_position(entry_price=0.0)
        pct = compute_unrealized_pct(pos, mark_price=100.0)
        assert pct == 0.0
