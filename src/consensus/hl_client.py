"""Hyperliquid price feed (WebSocket + REST fallback) and order execution."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

HL_WS_URL = "wss://api.hyperliquid.xyz/ws"
HL_REST_URL = "https://api.hyperliquid.xyz/info"

# Stale price threshold in seconds
STALE_PRICE_THRESHOLD = 30.0
# REST fallback poll interval in seconds
REST_POLL_INTERVAL = 5.0


class HyperliquidPriceFeed:
    """Real-time price feed from Hyperliquid via WebSocket with REST fallback.

    Primary: WebSocket subscription to ``allMids`` channel.
    Fallback: REST ``POST /info`` with ``{"type": "allMids"}`` every 5s.
    """

    def __init__(self) -> None:
        self._prices: dict[str, float] = {}
        self._last_update: float = 0.0
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._running: bool = False
        self._ws_connected: bool = False

    @property
    def prices(self) -> dict[str, float]:
        """Current mid prices keyed by token symbol."""
        return dict(self._prices)

    @property
    def last_update_time(self) -> float:
        """Monotonic timestamp of the last price update."""
        return self._last_update

    def is_stale(self) -> bool:
        """Return True if prices haven't been updated in >30 seconds."""
        if self._last_update == 0.0:
            return True
        return (time.monotonic() - self._last_update) > STALE_PRICE_THRESHOLD

    def get_price(self, token: str) -> float | None:
        """Get the current mid price for a token, or None if unavailable."""
        return self._prices.get(token)

    async def start(self) -> None:
        """Start the price feed (WebSocket primary, REST fallback)."""
        self._running = True
        self._session = aiohttp.ClientSession()
        # Run both; WS task handles reconnection, REST fills gaps
        await asyncio.gather(
            self._ws_loop(),
            self._rest_fallback_loop(),
            return_exceptions=True,
        )

    async def stop(self) -> None:
        """Gracefully shut down the price feed."""
        self._running = False
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _ws_loop(self) -> None:
        """Maintain a WebSocket connection, reconnecting on failure."""
        while self._running:
            try:
                await self._ws_connect()
            except Exception:
                logger.warning("WebSocket error, reconnecting in 5s", exc_info=True)
                self._ws_connected = False
                await asyncio.sleep(5)

    async def _ws_connect(self) -> None:
        """Connect to the Hyperliquid WebSocket and process messages."""
        assert self._session is not None
        async with self._session.ws_connect(HL_WS_URL) as ws:
            self._ws = ws
            self._ws_connected = True
            # Subscribe to allMids
            await ws.send_json({
                "method": "subscribe",
                "subscription": {"type": "allMids"},
            })
            logger.info("WebSocket connected and subscribed to allMids")

            async for msg in ws:
                if not self._running:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_ws_message(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break

        self._ws_connected = False

    def _handle_ws_message(self, raw: str) -> None:
        """Parse a WebSocket message and update prices."""
        try:
            data = json.loads(raw)
            if data.get("channel") == "allMids":
                mids = data.get("data", {}).get("mids", {})
                for token, price_str in mids.items():
                    self._prices[token] = float(price_str)
                self._last_update = time.monotonic()
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("Failed to parse WS message: %s", raw[:200])

    async def _rest_fallback_loop(self) -> None:
        """Poll REST endpoint when WebSocket is disconnected."""
        while self._running:
            if not self._ws_connected:
                await self._fetch_rest_prices()
            await asyncio.sleep(REST_POLL_INTERVAL)

    async def _fetch_rest_prices(self) -> None:
        """Fetch prices via REST POST /info with {"type": "allMids"}."""
        if self._session is None or self._session.closed:
            return
        try:
            async with self._session.post(
                HL_REST_URL,
                json={"type": "allMids"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # REST returns {"mids": {"BTC": "97000.5", ...}}
                    # or directly {"BTC": "97000.5", ...} depending on version
                    mids = data.get("mids", data) if isinstance(data, dict) else {}
                    for token, price_str in mids.items():
                        self._prices[token] = float(price_str)
                    self._last_update = time.monotonic()
                else:
                    logger.warning("REST price fetch returned %d", resp.status)
        except Exception:
            logger.warning("REST price fetch failed", exc_info=True)
