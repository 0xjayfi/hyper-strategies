"""Integration tests for the Nansen API client.

These tests hit the real Nansen API and require NANSEN_API_KEY to be set.
They are skipped automatically when the key is not available.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from consensus.config import StrategyConfig
from consensus.nansen_client import NansenAPIError, NansenClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NANSEN_API_KEY = os.environ.get("NANSEN_API_KEY", os.environ.get("CONSENSUS_NANSEN_API_KEY", ""))
HAS_API_KEY = bool(NANSEN_API_KEY)

skip_no_key = pytest.mark.skipif(not HAS_API_KEY, reason="NANSEN_API_KEY not set")

TEST_ADDRESS = "0x45d26f28196d226497130c4bac709d808fed4029"


def _make_config(**overrides: str) -> StrategyConfig:
    return StrategyConfig(
        NANSEN_API_KEY=overrides.get("NANSEN_API_KEY", NANSEN_API_KEY),
        HL_PRIVATE_KEY="test",
        TYPEFULLY_API_KEY="test",
    )


# ===========================================================================
# Unit tests (mocked, always run)
# ===========================================================================


class _FakeResponse:
    """Minimal mock for aiohttp response used as async context manager."""

    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type: str | None = None) -> dict:
        return self._body


class _FakeContextManager:
    """aiohttp session.post() returns a context manager (not a coroutine)."""

    def __init__(self, resp: _FakeResponse) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeResponse:
        return self._resp

    async def __aexit__(self, *args: object) -> None:
        pass


def _mock_session_with_responses(responses: list[_FakeResponse]) -> MagicMock:
    """Build a mock session whose .post() cycles through the given responses."""
    call_count = {"n": 0}

    def post_side_effect(*args: object, **kwargs: object) -> _FakeContextManager:
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return _FakeContextManager(responses[idx])

    session = MagicMock()
    session.post = MagicMock(side_effect=post_side_effect)
    session.closed = False
    return session


class TestRetryLogic:
    """Test exponential backoff on 429 responses."""

    async def test_retries_on_429_then_succeeds(self) -> None:
        config = _make_config(NANSEN_API_KEY="fake-key")
        client = NansenClient(config)

        session = _mock_session_with_responses([
            _FakeResponse(429, {"error": "rate limited"}),
            _FakeResponse(200, {"data": [{"id": 1}], "pagination": {"is_last_page": True}}),
        ])
        client._session = session
        client._owns_session = False

        with patch("consensus.nansen_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._post("/api/v1/perp-leaderboard", {"date": {"from": "2025-01-01", "to": "2025-01-02"}})

        assert result["data"] == [{"id": 1}]
        assert session.post.call_count == 2

    async def test_raises_after_max_retries(self) -> None:
        config = _make_config(NANSEN_API_KEY="fake-key")
        client = NansenClient(config)

        session = _mock_session_with_responses([
            _FakeResponse(429, {"error": "rate limited"}),
        ])
        client._session = session
        client._owns_session = False

        with patch("consensus.nansen_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(NansenAPIError) as exc_info:
                await client._post("/api/v1/perp-leaderboard", {"date": {"from": "2025-01-01", "to": "2025-01-02"}})
            assert exc_info.value.status == 429

    async def test_raises_immediately_on_non_429_error(self) -> None:
        config = _make_config(NANSEN_API_KEY="fake-key")
        client = NansenClient(config)

        session = _mock_session_with_responses([
            _FakeResponse(401, {"error": "unauthorized"}),
        ])
        client._session = session
        client._owns_session = False

        with pytest.raises(NansenAPIError) as exc_info:
            await client._post("/api/v1/perp-leaderboard", {"date": {"from": "2025-01-01", "to": "2025-01-02"}})
        assert exc_info.value.status == 401


class TestPagination:
    """Test pagination auto-follow."""

    async def test_fetches_multiple_pages(self) -> None:
        config = _make_config(NANSEN_API_KEY="fake-key")
        client = NansenClient(config)

        pages = [
            {"data": [{"id": 1}, {"id": 2}], "pagination": {"page": 1, "per_page": 2, "is_last_page": False}},
            {"data": [{"id": 3}], "pagination": {"page": 2, "per_page": 2, "is_last_page": True}},
        ]
        call_idx = 0

        async def fake_post(path: str, payload: dict) -> dict:
            nonlocal call_idx
            result = pages[call_idx]
            call_idx += 1
            return result

        client._post = fake_post  # type: ignore[assignment]

        data = await client._fetch_paginated("/api/v1/perp-leaderboard", {"date": {"from": "2025-01-01", "to": "2025-01-02"}})
        assert len(data) == 3
        assert [d["id"] for d in data] == [1, 2, 3]
        assert call_idx == 2


# ===========================================================================
# Integration tests (live API, skipped without key)
# ===========================================================================


@skip_no_key
class TestLiveLeaderboard:

    async def test_fetch_leaderboard_returns_data(self) -> None:
        config = _make_config()
        async with NansenClient(config) as client:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            thirty_days_ago = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

            data = await client.fetch_leaderboard(
                date_from=thirty_days_ago,
                date_to=today,
                filters={"account_value": {"min": 50000}},
                pagination={"page": 1, "per_page": 5},
            )
            assert isinstance(data, list)
            assert len(data) > 0
            first = data[0]
            assert "trader_address" in first
            assert "total_pnl" in first
            assert "roi" in first
            assert "account_value" in first


@skip_no_key
class TestLiveAddressTrades:

    async def test_fetch_address_trades_returns_data(self) -> None:
        config = _make_config()
        async with NansenClient(config) as client:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            thirty_days_ago = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

            data = await client.fetch_address_trades(
                address=TEST_ADDRESS,
                date_from=thirty_days_ago,
                date_to=today,
                pagination={"page": 1, "per_page": 5},
            )
            assert isinstance(data, list)
            # May be empty if trader hasn't traded recently — just check type
            if len(data) > 0:
                first = data[0]
                assert "transaction_hash" in first
                assert "token_symbol" in first
                assert "side" in first
                assert "action" in first


@skip_no_key
class TestLiveAddressPositions:

    async def test_fetch_address_positions_returns_data(self) -> None:
        config = _make_config()
        async with NansenClient(config) as client:
            data = await client.fetch_address_positions(
                address=TEST_ADDRESS,
                filters={"position_value_usd": {"min": 100}},
            )
            assert isinstance(data, dict)
            # Should have account summary fields
            assert "margin_summary_account_value_usd" in data or "asset_positions" in data
