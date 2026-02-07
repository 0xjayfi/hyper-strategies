import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidClient:
    """
    Async client for Hyperliquid public API.

    Provides mark price data as fallback when Nansen is rate-limited.
    No API key required.
    """

    def __init__(self, timeout_s: float = 5.0) -> None:
        self.timeout_s = timeout_s
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def fetch_all_mids(self) -> dict[str, float]:
        """
        Fetch all mid prices from Hyperliquid public API.

        POST https://api.hyperliquid.xyz/info
        Body: {"type": "allMids"}

        Returns: {token: mid_price} e.g. {"BTC": 65432.5, "ETH": 3456.7}
        """
        client = await self._get_client()
        response = await client.post(
            HYPERLIQUID_INFO_URL,
            json={"type": "allMids"},
        )
        response.raise_for_status()
        raw = response.json()

        # Parse string prices to float
        result: dict[str, float] = {}
        for token, price_str in raw.items():
            try:
                result[token] = float(price_str)
            except (ValueError, TypeError):
                logger.warning("Failed to parse HL price for %s: %s", token, price_str)
                continue

        return result

    async def fetch_mark_price(self, token: str) -> Optional[float]:
        """Fetch mark price for a single token. Returns None if unavailable."""
        mids = await self.fetch_all_mids()
        return mids.get(token)
