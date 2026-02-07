import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from src.risk.types import PositionSnapshot, Side

logger = logging.getLogger(__name__)

NANSEN_BASE_URL = "https://api.nansen.ai"
NANSEN_ADDRESS_PERP_POSITIONS_PATH = "/api/beta/hyperliquid/address-perp-positions"

# Rate limit backoff config
BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 30.0
MAX_RETRIES = 5


@dataclass
class NansenPerpPosition:
    """Raw parsed position from Nansen Address Perp Positions API."""
    token: str
    side: str                           # "Long" or "Short"
    leverage_value: Optional[float]     # numeric leverage (may be None)
    liquidation_price_usd: float
    margin_used_usd: float
    position_value_usd: float
    mark_price_usd: float
    entry_price_usd: float


class NansenClient:
    """
    Async client for Nansen Hyperliquid API endpoints.

    Uses the Address Perp Positions endpoint to fetch position data
    including leverage, liquidation prices, and margin info.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = NANSEN_BASE_URL,
        timeout_s: float = 10.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("NANSEN_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_s,
                headers={"apiKey": self.api_key, "Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _post_with_backoff(self, path: str, payload: dict) -> dict:
        """POST with exponential backoff on 429 rate limit."""
        client = await self._get_client()
        delay = BACKOFF_BASE_S

        for attempt in range(MAX_RETRIES):
            response = await client.post(path, json=payload)

            if response.status_code == 429:
                logger.warning(
                    "Nansen rate limited (429), backing off %.1fs (attempt %d/%d)",
                    delay, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, BACKOFF_MAX_S)
                continue

            response.raise_for_status()
            return response.json()

        raise httpx.HTTPStatusError(
            f"Nansen rate limited after {MAX_RETRIES} retries",
            request=response.request,
            response=response,
        )

    async def fetch_address_perp_positions(
        self, address: str
    ) -> list[NansenPerpPosition]:
        """
        Fetch perp positions for a given address.

        Nansen Address Perp Positions API returns fields:
          - token_symbol (str)
          - side (str: "Long" / "Short")
          - leverage_value (float or null)
          - liquidation_price_usd (float)
          - margin_used_usd (float)
          - position_value_usd (float)
          - mark_price_usd (float)
          - entry_price_usd (float)
        """
        payload = {"address": address}
        data = await self._post_with_backoff(
            NANSEN_ADDRESS_PERP_POSITIONS_PATH, payload
        )

        return self._parse_positions(data)

    @staticmethod
    def _parse_positions(data: dict) -> list[NansenPerpPosition]:
        """Parse raw API response into NansenPerpPosition list."""
        positions: list[NansenPerpPosition] = []
        items = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            items = [items] if items else []

        for item in items:
            try:
                # leverage_value is numeric in Address Perp Positions
                leverage_raw = item.get("leverage_value")
                leverage_value: Optional[float] = None
                if leverage_raw is not None:
                    leverage_value = float(leverage_raw)

                positions.append(NansenPerpPosition(
                    token=item.get("token_symbol", item.get("token", "")),
                    side=item.get("side", "Long"),
                    leverage_value=leverage_value,
                    liquidation_price_usd=float(item.get("liquidation_price_usd", 0)),
                    margin_used_usd=float(item.get("margin_used_usd", 0)),
                    position_value_usd=float(item.get("position_value_usd", 0)),
                    mark_price_usd=float(item.get("mark_price_usd", item.get("mark_price", 0))),
                    entry_price_usd=float(item.get("entry_price_usd", item.get("entry_price", 0))),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.warning("Failed to parse Nansen position: %s — %s", item, e)
                continue

        return positions

    @staticmethod
    def to_position_snapshot(
        nansen_pos: NansenPerpPosition,
        mark_price_override: Optional[float] = None,
    ) -> PositionSnapshot:
        """
        Convert a NansenPerpPosition to a PositionSnapshot for monitoring.

        Args:
            nansen_pos: Raw position from Nansen API.
            mark_price_override: If provided, use this instead of Nansen's mark price
                                 (e.g. from Hyperliquid fallback).
        """
        mark = mark_price_override if mark_price_override is not None else nansen_pos.mark_price_usd

        return PositionSnapshot(
            token=nansen_pos.token,
            side=Side(nansen_pos.side),
            mark_price=mark,
            liquidation_price=nansen_pos.liquidation_price_usd,
            position_value_usd=nansen_pos.position_value_usd,
            entry_price=nansen_pos.entry_price_usd,
        )
