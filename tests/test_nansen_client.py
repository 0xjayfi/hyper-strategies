"""Unit tests for the NansenClient async HTTP client.

Tests cover:
- Single-page and multi-page (paginated) responses for all endpoints
- Retry behaviour on 429 (rate limit) and 500 (server error)
- Maximum retry exhaustion raising appropriate exceptions
- Auth errors (401) NOT being retried
- Bad request errors (400) NOT being retried
"""

from __future__ import annotations

import pytest
import httpx
import respx

from snap.nansen_client import (
    NansenClient,
    NansenAPIError,
    NansenRateLimitError,
    NansenAuthError,
)

BASE_URL = "https://api.nansen.ai/api/v1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_key():
    return "test-api-key-12345"


@pytest.fixture
async def client(api_key):
    async with NansenClient(api_key=api_key, base_url=BASE_URL) as c:
        yield c


# ---------------------------------------------------------------------------
# Leaderboard tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_leaderboard_single_page(client):
    """A single-page leaderboard response is correctly returned."""
    mock_data = {
        "data": [
            {
                "trader_address": "0xaaa111",
                "trader_address_label": "Trader A",
                "total_pnl": 50000.0,
                "roi": 25.5,
                "account_value": 100000.0,
            },
            {
                "trader_address": "0xbbb222",
                "trader_address_label": "",
                "total_pnl": 30000.0,
                "roi": 18.2,
                "account_value": 75000.0,
            },
        ],
        "pagination": {"page": 1, "per_page": 100, "is_last_page": True},
    }

    route = respx.post(f"{BASE_URL}/perp-leaderboard").mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    result = await client.get_leaderboard("2025-09-01", "2025-10-01")

    assert route.called
    assert len(result) == 2
    assert result[0]["trader_address"] == "0xaaa111"
    assert result[0]["total_pnl"] == 50000.0
    assert result[1]["roi"] == 18.2


@respx.mock
async def test_get_leaderboard_pagination(client):
    """Multi-page leaderboard is fully collected via pagination."""
    page1_data = {
        "data": [
            {
                "trader_address": "0xaaa111",
                "trader_address_label": "Trader A",
                "total_pnl": 50000.0,
                "roi": 25.5,
                "account_value": 100000.0,
            },
        ],
        "pagination": {"page": 1, "per_page": 100, "is_last_page": False},
    }

    page2_data = {
        "data": [
            {
                "trader_address": "0xbbb222",
                "trader_address_label": "Trader B",
                "total_pnl": 30000.0,
                "roi": 18.2,
                "account_value": 75000.0,
            },
        ],
        "pagination": {"page": 2, "per_page": 100, "is_last_page": True},
    }

    route = respx.post(f"{BASE_URL}/perp-leaderboard").mock(
        side_effect=[
            httpx.Response(200, json=page1_data),
            httpx.Response(200, json=page2_data),
        ]
    )

    result = await client.get_leaderboard("2025-09-01", "2025-10-01")

    assert route.call_count == 2
    assert len(result) == 2
    assert result[0]["trader_address"] == "0xaaa111"
    assert result[1]["trader_address"] == "0xbbb222"


# ---------------------------------------------------------------------------
# Positions tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_perp_positions(client):
    """Positions response is correctly parsed and returned."""
    mock_data = {
        "data": {
            "asset_positions": [
                {
                    "position": {
                        "token_symbol": "BTC",
                        "entry_price_usd": "45000.0",
                        "leverage_type": "cross",
                        "leverage_value": 3,
                        "liquidation_price_usd": "35000.0",
                        "margin_used_usd": "15000.0",
                        "position_value_usd": "45000.0",
                        "size": "1.0",
                        "unrealized_pnl_usd": "5000.0",
                    },
                    "position_type": "oneWay",
                },
                {
                    "position": {
                        "token_symbol": "ETH",
                        "entry_price_usd": "3000.0",
                        "leverage_type": "isolated",
                        "leverage_value": 5,
                        "liquidation_price_usd": "2500.0",
                        "margin_used_usd": "6000.0",
                        "position_value_usd": "30000.0",
                        "size": "-10.0",
                        "unrealized_pnl_usd": "-500.0",
                    },
                    "position_type": "oneWay",
                },
            ],
            "margin_summary_account_value_usd": "200000.0",
            "timestamp": 1700000000000,
        }
    }

    route = respx.post(f"{BASE_URL}/profiler/perp-positions").mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    result = await client.get_perp_positions("0xabc123")

    assert route.called
    assert len(result["asset_positions"]) == 2
    assert result["asset_positions"][0]["position"]["token_symbol"] == "BTC"
    assert result["asset_positions"][1]["position"]["size"] == "-10.0"
    assert result["margin_summary_account_value_usd"] == "200000.0"


# ---------------------------------------------------------------------------
# Trades tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_perp_trades_single_page(client):
    """Single-page trades response is correctly returned."""
    mock_data = {
        "data": [
            {
                "action": "Open",
                "block_number": 100,
                "closed_pnl": 0,
                "crossed": True,
                "fee_token_symbol": "USDC",
                "fee_usd": 2.5,
                "oid": 12345,
                "price": 45000.0,
                "side": "Long",
                "size": 0.1,
                "start_position": 0,
                "timestamp": "2025-10-01T12:00:00.000000",
                "token_symbol": "BTC",
                "transaction_hash": "0xdef456",
                "user": "0xabc123",
                "value_usd": 4500.0,
            },
        ],
        "pagination": {"page": 1, "per_page": 100, "is_last_page": True},
    }

    route = respx.post(f"{BASE_URL}/profiler/perp-trades").mock(
        return_value=httpx.Response(200, json=mock_data)
    )

    result = await client.get_perp_trades("0xabc123", "2025-09-01", "2025-10-01")

    assert route.called
    assert len(result) == 1
    assert result[0]["action"] == "Open"
    assert result[0]["token_symbol"] == "BTC"
    assert result[0]["value_usd"] == 4500.0


@respx.mock
async def test_get_perp_trades_pagination(client):
    """Multi-page trades response is fully collected."""
    page1 = {
        "data": [
            {
                "action": "Open",
                "closed_pnl": 0,
                "fee_usd": 1.0,
                "price": 45000.0,
                "side": "Long",
                "size": 0.1,
                "timestamp": "2025-10-01T12:00:00.000000",
                "token_symbol": "BTC",
                "value_usd": 4500.0,
            },
        ],
        "pagination": {"page": 1, "per_page": 100, "is_last_page": False},
    }

    page2 = {
        "data": [
            {
                "action": "Close",
                "closed_pnl": 500.0,
                "fee_usd": 1.0,
                "price": 50000.0,
                "side": "Long",
                "size": 0.1,
                "timestamp": "2025-10-05T14:00:00.000000",
                "token_symbol": "BTC",
                "value_usd": 5000.0,
            },
        ],
        "pagination": {"page": 2, "per_page": 100, "is_last_page": True},
    }

    route = respx.post(f"{BASE_URL}/profiler/perp-trades").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    result = await client.get_perp_trades("0xabc123", "2025-09-01", "2025-10-05")

    assert route.call_count == 2
    assert len(result) == 2
    assert result[0]["action"] == "Open"
    assert result[1]["action"] == "Close"
    assert result[1]["closed_pnl"] == 500.0


# ---------------------------------------------------------------------------
# Retry & error handling tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_retry_on_429(client):
    """A 429 on the first attempt is retried and succeeds on the second."""
    mock_success = {
        "data": [
            {
                "trader_address": "0xaaa111",
                "trader_address_label": "",
                "total_pnl": 10000.0,
                "roi": 10.0,
                "account_value": 60000.0,
            },
        ],
        "pagination": {"page": 1, "per_page": 100, "is_last_page": True},
    }

    route = respx.post(f"{BASE_URL}/perp-leaderboard").mock(
        side_effect=[
            httpx.Response(429, text="Rate limited"),
            httpx.Response(200, json=mock_success),
        ]
    )

    result = await client.get_leaderboard("2025-09-01", "2025-10-01")

    assert route.call_count == 2
    assert len(result) == 1
    assert result[0]["trader_address"] == "0xaaa111"


@respx.mock
async def test_retry_on_500(client):
    """A 500 on the first attempt is retried and succeeds on the second."""
    mock_success = {
        "data": {
            "asset_positions": [],
            "margin_summary_account_value_usd": "100000.0",
        }
    }

    route = respx.post(f"{BASE_URL}/profiler/perp-positions").mock(
        side_effect=[
            httpx.Response(500, text="Internal Server Error"),
            httpx.Response(200, json=mock_success),
        ]
    )

    result = await client.get_perp_positions("0xabc123")

    assert route.call_count == 2
    assert result["margin_summary_account_value_usd"] == "100000.0"


@respx.mock
async def test_max_retries_exceeded(client):
    """When all 3 retry attempts return 429, NansenRateLimitError is raised."""
    route = respx.post(f"{BASE_URL}/perp-leaderboard").mock(
        side_effect=[
            httpx.Response(429, text="Rate limited"),
            httpx.Response(429, text="Rate limited"),
            httpx.Response(429, text="Rate limited"),
        ]
    )

    with pytest.raises(NansenRateLimitError) as exc_info:
        await client.get_leaderboard("2025-09-01", "2025-10-01")

    assert route.call_count == 3
    assert exc_info.value.status_code == 429


@respx.mock
async def test_auth_error_no_retry(client):
    """A 401 raises NansenAuthError immediately with no retries."""
    route = respx.post(f"{BASE_URL}/perp-leaderboard").mock(
        return_value=httpx.Response(401, text="Unauthorized: invalid API key")
    )

    with pytest.raises(NansenAuthError) as exc_info:
        await client.get_leaderboard("2025-09-01", "2025-10-01")

    # Only 1 call: no retry on auth errors
    assert route.call_count == 1
    assert exc_info.value.status_code == 401
    assert "Unauthorized" in exc_info.value.message


@respx.mock
async def test_bad_request_no_retry(client):
    """A 400 raises NansenAPIError immediately with no retries."""
    route = respx.post(f"{BASE_URL}/profiler/perp-trades").mock(
        return_value=httpx.Response(400, text="Bad Request: missing date field")
    )

    with pytest.raises(NansenAPIError) as exc_info:
        await client.get_perp_trades("0xabc123", "2025-09-01", "2025-10-01")

    assert route.call_count == 1
    assert exc_info.value.status_code == 400
    assert "Bad Request" in exc_info.value.message
