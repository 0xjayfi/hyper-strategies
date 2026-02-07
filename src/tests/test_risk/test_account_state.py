import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.risk.account_state import AccountStateManager, build_account_state
from src.risk.nansen_client import NansenClient, NansenPerpPosition
from src.risk.types import AccountState


# ---------------------------------------------------------------------------
# Sample positions
# ---------------------------------------------------------------------------

def _sample_positions() -> list[NansenPerpPosition]:
    return [
        NansenPerpPosition(
            token="BTC", side="Long", leverage_value=3.0,
            liquidation_price_usd=58000.0, margin_used_usd=20000.0,
            position_value_usd=60000.0, mark_price_usd=65000.0,
            entry_price_usd=62000.0,
        ),
        NansenPerpPosition(
            token="ETH", side="Short", leverage_value=5.0,
            liquidation_price_usd=4200.0, margin_used_usd=3000.0,
            position_value_usd=15000.0, mark_price_usd=3500.0,
            entry_price_usd=3600.0,
        ),
        NansenPerpPosition(
            token="BTC", side="Long", leverage_value=2.0,
            liquidation_price_usd=57000.0, margin_used_usd=10000.0,
            position_value_usd=20000.0, mark_price_usd=65000.0,
            entry_price_usd=63000.0,
        ),
    ]


# ---------------------------------------------------------------------------
# build_account_state
# ---------------------------------------------------------------------------

class TestBuildAccountState:
    def test_basic_aggregation(self):
        """Correctly aggregates positions into AccountState."""
        positions = _sample_positions()
        state = build_account_state(positions, account_value_usd=200_000.0)

        assert state.account_value_usd == 200_000.0
        # total_open = 60000 + 15000 + 20000 = 95000
        assert state.total_open_positions_usd == pytest.approx(95_000.0)
        # total_long = 60000 + 20000 = 80000
        assert state.total_long_exposure_usd == pytest.approx(80_000.0)
        # total_short = 15000
        assert state.total_short_exposure_usd == pytest.approx(15_000.0)

    def test_token_exposure(self):
        """Per-token exposure aggregated across positions."""
        positions = _sample_positions()
        state = build_account_state(positions, account_value_usd=200_000.0)

        # BTC: 60000 + 20000 = 80000
        assert state.token_exposure_usd["BTC"] == pytest.approx(80_000.0)
        # ETH: 15000
        assert state.token_exposure_usd["ETH"] == pytest.approx(15_000.0)

    def test_empty_positions(self):
        """No positions -> zero exposures."""
        state = build_account_state([], account_value_usd=100_000.0)
        assert state.total_open_positions_usd == 0.0
        assert state.total_long_exposure_usd == 0.0
        assert state.total_short_exposure_usd == 0.0
        assert state.token_exposure_usd == {}

    def test_single_position(self):
        positions = [
            NansenPerpPosition(
                token="SOL", side="Short", leverage_value=10.0,
                liquidation_price_usd=200.0, margin_used_usd=500.0,
                position_value_usd=5000.0, mark_price_usd=175.0,
                entry_price_usd=180.0,
            ),
        ]
        state = build_account_state(positions, account_value_usd=50_000.0)
        assert state.total_open_positions_usd == pytest.approx(5_000.0)
        assert state.total_long_exposure_usd == 0.0
        assert state.total_short_exposure_usd == pytest.approx(5_000.0)
        assert state.token_exposure_usd == {"SOL": pytest.approx(5_000.0)}


# ---------------------------------------------------------------------------
# AccountStateManager
# ---------------------------------------------------------------------------

class TestAccountStateManager:
    def test_initial_state(self):
        """Initial state has correct account value, zero exposures."""
        nansen = AsyncMock(spec=NansenClient)
        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
        )
        state = mgr.get_current_state()
        assert state.account_value_usd == 200_000.0
        assert state.total_open_positions_usd == 0.0

    @pytest.mark.asyncio
    async def test_refresh_updates_state(self):
        """Refresh fetches positions and rebuilds state."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=_sample_positions())

        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
        )

        state = await mgr.refresh()
        assert state.total_open_positions_usd == pytest.approx(95_000.0)
        assert state.total_long_exposure_usd == pytest.approx(80_000.0)
        assert state.total_short_exposure_usd == pytest.approx(15_000.0)

        # get_current_state returns the same refreshed state
        assert mgr.get_current_state() is state

    @pytest.mark.asyncio
    async def test_refresh_with_account_value_callback(self):
        """refresh_account_value callback updates account_value_usd."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=[])

        refresh_value = AsyncMock(return_value=250_000.0)

        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
            refresh_account_value=refresh_value,
        )

        state = await mgr.refresh()
        assert state.account_value_usd == 250_000.0
        refresh_value.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_fresh_skips_if_recent(self):
        """ensure_fresh does not refresh if state is recent enough."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=_sample_positions())

        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
            refresh_interval_s=60.0,
        )

        # First call refreshes
        await mgr.ensure_fresh()
        assert nansen.fetch_address_perp_positions.call_count == 1

        # Second call within 60s should NOT refresh
        await mgr.ensure_fresh()
        assert nansen.fetch_address_perp_positions.call_count == 1

    @pytest.mark.asyncio
    async def test_ensure_fresh_refreshes_when_stale(self):
        """ensure_fresh refreshes if state is older than max_age_s."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=[])

        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
        )

        # Force stale by setting last refresh to 0
        mgr._last_refresh = 0.0

        await mgr.ensure_fresh(max_age_s=0.0)
        assert nansen.fetch_address_perp_positions.call_count == 1

    @pytest.mark.asyncio
    async def test_seconds_since_refresh(self):
        """seconds_since_refresh reflects time since last refresh."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=[])

        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=200_000.0,
        )

        # Before any refresh, should be infinity
        assert mgr.seconds_since_refresh == float("inf")

        await mgr.refresh()
        # Should be very close to 0 right after refresh
        assert mgr.seconds_since_refresh < 1.0

    @pytest.mark.asyncio
    async def test_state_property_matches_get_current_state(self):
        """The state property and get_current_state return the same object."""
        nansen = AsyncMock(spec=NansenClient)
        mgr = AccountStateManager(
            address="0xABC",
            nansen_client=nansen,
            account_value_usd=100_000.0,
        )
        assert mgr.state is mgr.get_current_state()
