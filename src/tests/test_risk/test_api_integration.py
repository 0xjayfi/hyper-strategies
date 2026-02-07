import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.risk.nansen_client import NansenClient, NansenPerpPosition
from src.risk.hyperliquid_client import HyperliquidClient
from src.risk.position_fetcher import PositionFetcher
from src.risk.types import PositionSnapshot, Side


# ---------------------------------------------------------------------------
# Sample API responses
# ---------------------------------------------------------------------------

NANSEN_RESPONSE = {
    "data": [
        {
            "token_symbol": "BTC",
            "side": "Long",
            "leverage_value": 3.0,
            "liquidation_price_usd": 58000.0,
            "margin_used_usd": 20000.0,
            "position_value_usd": 60000.0,
            "mark_price_usd": 65000.0,
            "entry_price_usd": 62000.0,
        },
        {
            "token_symbol": "ETH",
            "side": "Short",
            "leverage_value": 5.0,
            "liquidation_price_usd": 4200.0,
            "margin_used_usd": 3000.0,
            "position_value_usd": 15000.0,
            "mark_price_usd": 3500.0,
            "entry_price_usd": 3600.0,
        },
    ]
}

HL_ALL_MIDS_RESPONSE = {
    "BTC": "65100.5",
    "ETH": "3480.2",
    "SOL": "175.3",
}


# ---------------------------------------------------------------------------
# Nansen Client — Parsing
# ---------------------------------------------------------------------------

class TestNansenParsing:
    def test_parse_positions_basic(self):
        """Parse standard Nansen response with two positions."""
        positions = NansenClient._parse_positions(NANSEN_RESPONSE)
        assert len(positions) == 2

        btc = positions[0]
        assert btc.token == "BTC"
        assert btc.side == "Long"
        assert btc.leverage_value == 3.0
        assert btc.liquidation_price_usd == 58000.0
        assert btc.margin_used_usd == 20000.0
        assert btc.position_value_usd == 60000.0
        assert btc.mark_price_usd == 65000.0
        assert btc.entry_price_usd == 62000.0

        eth = positions[1]
        assert eth.token == "ETH"
        assert eth.side == "Short"
        assert eth.leverage_value == 5.0

    def test_parse_positions_null_leverage(self):
        """leverage_value can be None."""
        data = {"data": [{"token_symbol": "SOL", "side": "Long",
                          "leverage_value": None, "liquidation_price_usd": 150.0,
                          "margin_used_usd": 1000.0, "position_value_usd": 5000.0,
                          "mark_price_usd": 175.0, "entry_price_usd": 170.0}]}
        positions = NansenClient._parse_positions(data)
        assert len(positions) == 1
        assert positions[0].leverage_value is None

    def test_parse_positions_empty_data(self):
        """Empty data returns empty list."""
        assert NansenClient._parse_positions({"data": []}) == []

    def test_parse_positions_missing_data_key(self):
        """If top-level is a list, parse directly."""
        data = [{"token_symbol": "BTC", "side": "Long", "leverage_value": 2.0,
                 "liquidation_price_usd": 58000.0, "margin_used_usd": 20000.0,
                 "position_value_usd": 60000.0, "mark_price_usd": 65000.0,
                 "entry_price_usd": 62000.0}]
        positions = NansenClient._parse_positions(data)
        assert len(positions) == 1

    def test_parse_positions_malformed_item_skipped(self):
        """Malformed items are logged and skipped."""
        data = {"data": [{"bad": "data"}, {"token_symbol": "ETH", "side": "Short",
                "leverage_value": 5.0, "liquidation_price_usd": 4200.0,
                "margin_used_usd": 3000.0, "position_value_usd": 15000.0,
                "mark_price_usd": 3500.0, "entry_price_usd": 3600.0}]}
        positions = NansenClient._parse_positions(data)
        assert len(positions) >= 1  # at least the good one


# ---------------------------------------------------------------------------
# Nansen Client — Conversion to PositionSnapshot
# ---------------------------------------------------------------------------

class TestNansenToSnapshot:
    def test_to_position_snapshot(self):
        npos = NansenPerpPosition(
            token="BTC", side="Long", leverage_value=3.0,
            liquidation_price_usd=58000.0, margin_used_usd=20000.0,
            position_value_usd=60000.0, mark_price_usd=65000.0,
            entry_price_usd=62000.0,
        )
        snap = NansenClient.to_position_snapshot(npos)
        assert isinstance(snap, PositionSnapshot)
        assert snap.token == "BTC"
        assert snap.side == Side.LONG
        assert snap.mark_price == 65000.0
        assert snap.liquidation_price == 58000.0
        assert snap.position_value_usd == 60000.0
        assert snap.entry_price == 62000.0

    def test_to_position_snapshot_with_mark_override(self):
        npos = NansenPerpPosition(
            token="BTC", side="Long", leverage_value=3.0,
            liquidation_price_usd=58000.0, margin_used_usd=20000.0,
            position_value_usd=60000.0, mark_price_usd=65000.0,
            entry_price_usd=62000.0,
        )
        snap = NansenClient.to_position_snapshot(npos, mark_price_override=64000.0)
        assert snap.mark_price == 64000.0  # Override used


# ---------------------------------------------------------------------------
# Nansen Client — Rate Limit Backoff
# ---------------------------------------------------------------------------

class TestNansenBackoff:
    @pytest.mark.asyncio
    async def test_backoff_retries_on_429(self):
        """Should retry with backoff on 429, succeed on next attempt."""
        client = NansenClient(api_key="test-key")

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.request = MagicMock()

        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.raise_for_status = MagicMock()
        mock_response_ok.json.return_value = {"data": []}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=[mock_response_429, mock_response_ok])
        mock_http.is_closed = False
        client._client = mock_http

        with patch("src.risk.nansen_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._post_with_backoff("/test", {})

        assert result == {"data": []}
        assert mock_http.post.call_count == 2

    @pytest.mark.asyncio
    async def test_backoff_exhausts_retries(self):
        """Should raise after MAX_RETRIES 429s."""
        import httpx
        client = NansenClient(api_key="test-key")

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.request = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response_429)
        mock_http.is_closed = False
        client._client = mock_http

        with patch("src.risk.nansen_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await client._post_with_backoff("/test", {})


# ---------------------------------------------------------------------------
# Hyperliquid Client
# ---------------------------------------------------------------------------

class TestHyperliquidClient:
    @pytest.mark.asyncio
    async def test_fetch_all_mids(self):
        """Parse string prices to float."""
        hl = HyperliquidClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = HL_ALL_MIDS_RESPONSE

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        hl._client = mock_http

        result = await hl.fetch_all_mids()
        assert result["BTC"] == pytest.approx(65100.5)
        assert result["ETH"] == pytest.approx(3480.2)
        assert result["SOL"] == pytest.approx(175.3)

    @pytest.mark.asyncio
    async def test_fetch_mark_price_single(self):
        hl = HyperliquidClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = HL_ALL_MIDS_RESPONSE

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        hl._client = mock_http

        price = await hl.fetch_mark_price("ETH")
        assert price == pytest.approx(3480.2)

    @pytest.mark.asyncio
    async def test_fetch_mark_price_missing_token(self):
        hl = HyperliquidClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = HL_ALL_MIDS_RESPONSE

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.is_closed = False
        hl._client = mock_http

        price = await hl.fetch_mark_price("DOGE")
        assert price is None


# ---------------------------------------------------------------------------
# PositionFetcher — Wiring
# ---------------------------------------------------------------------------

class TestPositionFetcher:
    @pytest.mark.asyncio
    async def test_fetch_uses_nansen_primary(self):
        """Normal case: Nansen succeeds, no HL fallback."""
        nansen_positions = [
            NansenPerpPosition(
                token="BTC", side="Long", leverage_value=3.0,
                liquidation_price_usd=58000.0, margin_used_usd=20000.0,
                position_value_usd=60000.0, mark_price_usd=65000.0,
                entry_price_usd=62000.0,
            )
        ]

        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=nansen_positions)
        # Need the real static method
        nansen.to_position_snapshot = NansenClient.to_position_snapshot

        hl = AsyncMock(spec=HyperliquidClient)
        hl.fetch_all_mids = AsyncMock(return_value={})

        fetcher = PositionFetcher(address="0xABC", nansen_client=nansen, hl_client=hl)
        snapshots = await fetcher.fetch_positions()

        assert len(snapshots) == 1
        assert snapshots[0].token == "BTC"
        assert snapshots[0].side == Side.LONG
        assert snapshots[0].mark_price == 65000.0
        hl.fetch_all_mids.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_nansen_failure(self):
        """If Nansen fails and no prior data, return empty list."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(side_effect=Exception("API down"))

        hl = AsyncMock(spec=HyperliquidClient)

        fetcher = PositionFetcher(address="0xABC", nansen_client=nansen, hl_client=hl)
        snapshots = await fetcher.fetch_positions()

        assert snapshots == []

    @pytest.mark.asyncio
    async def test_nansen_failure_tracking(self):
        """Tracks when Nansen first started failing."""
        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(side_effect=Exception("429"))

        hl = AsyncMock(spec=HyperliquidClient)

        fetcher = PositionFetcher(address="0xABC", nansen_client=nansen, hl_client=hl)
        assert fetcher._nansen_fail_since is None

        await fetcher.fetch_positions()
        assert fetcher._nansen_fail_since is not None

    @pytest.mark.asyncio
    async def test_nansen_success_resets_failure_tracking(self):
        """Successful Nansen call resets failure timestamp."""
        import time
        nansen_positions = [
            NansenPerpPosition(
                token="ETH", side="Short", leverage_value=5.0,
                liquidation_price_usd=4200.0, margin_used_usd=3000.0,
                position_value_usd=15000.0, mark_price_usd=3500.0,
                entry_price_usd=3600.0,
            )
        ]

        nansen = AsyncMock(spec=NansenClient)
        nansen.fetch_address_perp_positions = AsyncMock(return_value=nansen_positions)
        nansen.to_position_snapshot = NansenClient.to_position_snapshot

        hl = AsyncMock(spec=HyperliquidClient)

        fetcher = PositionFetcher(address="0xABC", nansen_client=nansen, hl_client=hl)
        fetcher._nansen_fail_since = time.monotonic() - 100  # simulate old failure

        await fetcher.fetch_positions()
        assert fetcher._nansen_fail_since is None  # Reset on success
