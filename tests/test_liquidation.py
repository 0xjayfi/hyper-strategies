"""Task 10.6 -- Liquidation detection async tests.

Tests for ``src.position_monitor.check_trader_position`` which:

  1. Fetches the source trader's current positions via Nansen.
  2. If the trader still holds the token => returns False (no action).
  3. If the trader lost the position:
     a. Looks for a recent Close trade in the last hour.
     b. If Close found => trader exited normally, returns False.
     c. If no Close found => probable liquidation:
        - Closes our position (close_position_full).
        - Blacklists the trader for LIQUIDATION_COOLDOWN_DAYS.
        - Returns True.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import OurPosition


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_position(
    *,
    id: int = 1,
    token_symbol: str = "BTC",
    side: str = "Long",
    entry_price: float = 50_000.0,
    size: float = 0.5,
    value_usd: float = 25_000.0,
    stop_price: float | None = 47_500.0,
    trailing_stop_price: float | None = 46_000.0,
    highest_price: float | None = 50_000.0,
    lowest_price: float | None = None,
    opened_at: str = "2024-06-01T12:00:00+00:00",
    source_trader: str = "0xTrader123",
    source_signal_id: str | None = "signal-abc",
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
# Tests
# ---------------------------------------------------------------------------


class TestLiquidationDetection:
    @pytest.mark.asyncio
    async def test_trader_still_has_position(self) -> None:
        """When the source trader still holds the token, return False (no action)."""
        from src.position_monitor import check_trader_position

        pos = make_position(side="Long", token_symbol="BTC")

        mock_nansen = MagicMock()
        mock_nansen.get_address_perp_positions = AsyncMock(return_value={
            "data": {
                "asset_positions": [
                    {
                        "position": {
                            "token_symbol": "BTC",
                            "size": "0.5",  # positive => Long
                        }
                    }
                ]
            }
        })

        mock_executor = MagicMock()

        result = await check_trader_position(pos, mock_nansen, mock_executor)
        assert result is False

    @pytest.mark.asyncio
    async def test_trader_position_gone_with_close_trade(self) -> None:
        """Trader no longer holds the position but has a recent Close trade.
        This means normal exit -- return False."""
        from src.position_monitor import check_trader_position

        pos = make_position(side="Long", token_symbol="BTC")

        mock_nansen = MagicMock()
        # Position is gone
        mock_nansen.get_address_perp_positions = AsyncMock(return_value={
            "data": {
                "asset_positions": []
            }
        })
        # Recent Close trade found
        mock_nansen.get_address_perp_trades = AsyncMock(return_value=[
            {
                "action": "Close",
                "token_symbol": "BTC",
                "side": "Long",
                "value_usd": 25000,
                "timestamp": "2024-06-01T14:00:00+00:00",
            }
        ])

        mock_executor = MagicMock()

        result = await check_trader_position(pos, mock_nansen, mock_executor)
        assert result is False

    @pytest.mark.asyncio
    async def test_liquidation_detected_no_close_trade(self) -> None:
        """Trader lost the position with no Close trade => probable liquidation.
        Should close our position and blacklist the trader."""
        from src.position_monitor import check_trader_position

        pos = make_position(side="Long", token_symbol="BTC")

        mock_nansen = MagicMock()
        # Position is gone
        mock_nansen.get_address_perp_positions = AsyncMock(return_value={
            "data": {
                "asset_positions": []
            }
        })
        # No Close trades found
        mock_nansen.get_address_perp_trades = AsyncMock(return_value=[])

        mock_executor = MagicMock()
        mock_executor.close_position_on_exchange = AsyncMock(
            return_value=MagicMock(success=True, fill_price=48_000.0)
        )
        mock_executor.cancel_stop_orders = AsyncMock()

        with patch("src.position_monitor.db") as mock_db:
            mock_db.close_position = AsyncMock()
            mock_db.blacklist_trader = AsyncMock()

            result = await check_trader_position(pos, mock_nansen, mock_executor)

            assert result is True

            # Verify the position was closed with reason "trader_liquidated"
            mock_db.close_position.assert_called_once_with(
                pos.id, close_reason="trader_liquidated"
            )

            # Verify the trader was blacklisted
            mock_db.blacklist_trader.assert_called_once()
            call_args = mock_db.blacklist_trader.call_args
            # Called as blacklist_trader(address, until=...)
            assert call_args[0][0] == "0xTrader123"
            assert "until" in call_args[1]

    @pytest.mark.asyncio
    async def test_no_source_trader_skips_check(self) -> None:
        """Position with no source_trader should return False immediately."""
        from src.position_monitor import check_trader_position

        pos = make_position(source_trader=None)

        mock_nansen = MagicMock()
        mock_executor = MagicMock()

        result = await check_trader_position(pos, mock_nansen, mock_executor)
        assert result is False
        # Nansen should not have been called
        mock_nansen.get_address_perp_positions.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_position_detected_by_negative_size(self) -> None:
        """For short positions, the trader's size should be negative."""
        from src.position_monitor import check_trader_position

        pos = make_position(side="Short", token_symbol="ETH")

        mock_nansen = MagicMock()
        mock_nansen.get_address_perp_positions = AsyncMock(return_value={
            "data": {
                "asset_positions": [
                    {
                        "position": {
                            "token_symbol": "ETH",
                            "size": "-2.0",  # negative => Short
                        }
                    }
                ]
            }
        })

        mock_executor = MagicMock()

        result = await check_trader_position(pos, mock_nansen, mock_executor)
        assert result is False

    @pytest.mark.asyncio
    async def test_position_fetch_error_returns_false(self) -> None:
        """If we fail to fetch trader positions, return False (don't act on incomplete data)."""
        from src.position_monitor import check_trader_position

        pos = make_position()

        mock_nansen = MagicMock()
        mock_nansen.get_address_perp_positions = AsyncMock(side_effect=Exception("API Error"))

        mock_executor = MagicMock()

        result = await check_trader_position(pos, mock_nansen, mock_executor)
        assert result is False

    @pytest.mark.asyncio
    async def test_different_token_not_counted(self) -> None:
        """Trader holds a different token -- our position token is missing => liquidation path."""
        from src.position_monitor import check_trader_position

        pos = make_position(side="Long", token_symbol="BTC")

        mock_nansen = MagicMock()
        # Trader has ETH but not BTC
        mock_nansen.get_address_perp_positions = AsyncMock(return_value={
            "data": {
                "asset_positions": [
                    {
                        "position": {
                            "token_symbol": "ETH",
                            "size": "10.0",
                        }
                    }
                ]
            }
        })
        # No Close trade for BTC
        mock_nansen.get_address_perp_trades = AsyncMock(return_value=[])

        mock_executor = MagicMock()
        mock_executor.close_position_on_exchange = AsyncMock(
            return_value=MagicMock(success=True, fill_price=49_000.0)
        )
        mock_executor.cancel_stop_orders = AsyncMock()

        with patch("src.position_monitor.db") as mock_db:
            mock_db.close_position = AsyncMock()
            mock_db.blacklist_trader = AsyncMock()

            result = await check_trader_position(pos, mock_nansen, mock_executor)
            assert result is True
