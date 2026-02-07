"""Integration smoke tests for the Nansen API client.

These tests hit the real Nansen API and are skipped when ``NANSEN_API_KEY``
is not set in the environment.  They are intended for manual / CI-gated
validation, not routine unit testing.

Run with::

    NANSEN_API_KEY=your_key pytest tests/test_nansen_client_smoke.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

from src.models import (
    LeaderboardEntry,
    PnlLeaderboardEntry,
    PositionSnapshot,
    Trade,
)
from src.nansen_client import NansenClient

# Skip every test in this module when there is no API key.
_SKIP_REASON = "NANSEN_API_KEY not set — skipping live API tests"
_HAS_KEY = bool(os.getenv("NANSEN_API_KEY"))

# A known active address used by the Nansen docs themselves.
TEST_ADDRESS = "0xa312114b5795dff9b8db50474dd57701aa78ad1e"

# 7-day window ending today (2026-02-07).
_TODAY = datetime(2026, 2, 7)
DATE_TO = _TODAY.strftime("%Y-%m-%d")
DATE_FROM = (_TODAY - timedelta(days=7)).strftime("%Y-%m-%d")


# ------------------------------------------------------------------
# Leaderboard
# ------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_KEY, reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_fetch_leaderboard() -> None:
    """Leaderboard returns a non-empty list of LeaderboardEntry objects."""
    async with NansenClient() as client:
        entries = await client.fetch_leaderboard(
            date_from=DATE_FROM,
            date_to=DATE_TO,
            pagination={"page": 1, "per_page": 5},
        )

    assert isinstance(entries, list)
    assert len(entries) > 0, "Expected at least one leaderboard entry"

    for entry in entries:
        assert isinstance(entry, LeaderboardEntry)
        assert isinstance(entry.trader_address, str)
        assert entry.trader_address.startswith("0x")
        # total_pnl and roi are floats (can be negative)
        assert isinstance(entry.total_pnl, (int, float))
        assert isinstance(entry.roi, (int, float))
        assert isinstance(entry.account_value, (int, float))


# ------------------------------------------------------------------
# Address trades — single page
# ------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_KEY, reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_fetch_address_trades() -> None:
    """Address trades returns a list of Trade objects with expected fields."""
    async with NansenClient() as client:
        trades = await client.fetch_address_trades(
            address=TEST_ADDRESS,
            date_from=DATE_FROM,
            date_to=DATE_TO,
            pagination={"page": 1, "per_page": 10},
        )

    assert isinstance(trades, list)
    # The known address may or may not have trades in every 7-day window.
    # We only validate schema if we got results back.
    for trade in trades:
        assert isinstance(trade, Trade)
        # The API returns various action types including Buy/Sell in
        # addition to Open/Close/Add/Reduce.
        assert isinstance(trade.action, str)
        assert len(trade.action) > 0
        assert isinstance(trade.closed_pnl, (int, float))
        assert isinstance(trade.token_symbol, str)
        assert len(trade.token_symbol) > 0


# ------------------------------------------------------------------
# Address positions
# ------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_KEY, reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_fetch_address_positions() -> None:
    """Positions endpoint returns a PositionSnapshot with asset_positions."""
    async with NansenClient() as client:
        snapshot = await client.fetch_address_positions(address=TEST_ADDRESS)

    assert isinstance(snapshot, PositionSnapshot)
    assert isinstance(snapshot.asset_positions, list)

    # Validate account-level fields exist (may be None for addresses
    # with no open positions but the field itself should be present).
    assert hasattr(snapshot, "margin_summary_account_value_usd")

    for ap in snapshot.asset_positions:
        pos = ap.position
        assert isinstance(pos.token_symbol, str)
        assert isinstance(pos.entry_price_usd, str)
        assert isinstance(pos.size, str)


# ------------------------------------------------------------------
# PnL leaderboard
# ------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_KEY, reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_fetch_pnl_leaderboard() -> None:
    """Per-token PnL leaderboard returns entries with trader_address."""
    async with NansenClient() as client:
        entries = await client.fetch_pnl_leaderboard(
            token_symbol="BTC",
            date_from=DATE_FROM,
            date_to=DATE_TO,
            pagination={"page": 1, "per_page": 5},
        )

    assert isinstance(entries, list)
    assert len(entries) > 0, "Expected at least one PnL leaderboard entry for BTC"

    for entry in entries:
        assert isinstance(entry, PnlLeaderboardEntry)
        assert isinstance(entry.trader_address, str)
        assert entry.trader_address.startswith("0x")


# ------------------------------------------------------------------
# Auto-pagination
# ------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_KEY, reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_fetch_address_trades_auto_paginate() -> None:
    """Auto-pagination fetches all trades when no pagination arg is given.

    We use a narrow 1-day window to keep the number of API calls manageable
    and avoid rate limiting.  The test verifies that the auto-paginated
    result set is at least as large as a single page of 10 items (when the
    address has >= 10 trades in that window), OR is identical to a
    single-page fetch when fewer than 10 exist.
    """
    # Use a narrow 1-day window to limit pagination depth.
    narrow_from = (_TODAY - timedelta(days=1)).strftime("%Y-%m-%d")
    narrow_to = DATE_TO

    async with NansenClient() as client:
        # Single page -- limited to 10
        single_page = await client.fetch_address_trades(
            address=TEST_ADDRESS,
            date_from=narrow_from,
            date_to=narrow_to,
            pagination={"page": 1, "per_page": 10},
        )

        # Auto-paginated -- should get everything
        all_trades = await client.fetch_address_trades(
            address=TEST_ADDRESS,
            date_from=narrow_from,
            date_to=narrow_to,
        )

    assert isinstance(all_trades, list)
    # Auto-paginated result should include at least everything from
    # the first page.
    assert len(all_trades) >= len(single_page)

    # Sanity: every item is a Trade
    for trade in all_trades:
        assert isinstance(trade, Trade)
