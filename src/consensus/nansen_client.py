"""Async Nansen API client for Hyperliquid endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from consensus.config import StrategyConfig

logger = logging.getLogger(__name__)

BASE_URL = "https://api.nansen.ai"

# Retry settings
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 1.0
BACKOFF_MULTIPLIER = 2.0


class NansenAPIError(Exception):
    """Raised when the Nansen API returns a non-2xx response."""

    def __init__(self, status: int, body: Any, url: str) -> None:
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"Nansen API {status} at {url}: {body}")


class NansenClient:
    """Async client for Nansen Hyperliquid API endpoints."""

    def __init__(self, config: StrategyConfig, session: aiohttp.ClientSession | None = None) -> None:
        self._api_key = config.NANSEN_API_KEY
        self._owns_session = session is None
        self._session = session

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> NansenClient:
        await self._ensure_session()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal: POST with retry + backoff
    # ------------------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to Nansen API with retry on 429."""
        session = await self._ensure_session()
        url = f"{BASE_URL}{path}"
        headers = {
            "apiKey": self._api_key,
            "Content-Type": "application/json",
        }

        backoff = INITIAL_BACKOFF_SECONDS
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            logger.debug("Nansen POST %s attempt=%d payload=%s", path, attempt, payload)
            async with session.post(url, json=payload, headers=headers) as resp:
                body = await resp.json(content_type=None)
                logger.debug("Nansen POST %s status=%d body_keys=%s", path, resp.status, list(body.keys()) if isinstance(body, dict) else type(body).__name__)

                if resp.status == 200:
                    return body

                if resp.status == 429:
                    logger.warning("Nansen 429 rate limited on %s, backing off %.1fs (attempt %d/%d)", path, backoff, attempt, MAX_RETRIES)
                    last_error = NansenAPIError(resp.status, body, url)
                    await asyncio.sleep(backoff)
                    backoff *= BACKOFF_MULTIPLIER
                    continue

                raise NansenAPIError(resp.status, body, url)

        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Internal: paginated fetch
    # ------------------------------------------------------------------

    async def _fetch_paginated(
        self,
        path: str,
        payload: dict[str, Any],
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated endpoint."""
        all_data: list[dict[str, Any]] = []
        page = 1

        while True:
            payload_page = {
                **payload,
                "pagination": {"page": page, "per_page": per_page},
            }
            result = await self._post(path, payload_page)

            data = result.get("data", [])
            if isinstance(data, list):
                all_data.extend(data)
            else:
                # positions endpoint wraps data differently
                return [result]

            pagination = result.get("pagination", {})
            if pagination.get("is_last_page", True):
                break

            page += 1

        return all_data

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    async def fetch_leaderboard(
        self,
        date_from: str,
        date_to: str,
        filters: dict[str, Any] | None = None,
        pagination: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch perp trading leaderboard.

        Args:
            date_from: Start date YYYY-MM-DD.
            date_to: End date YYYY-MM-DD.
            filters: Optional filters (account_value, total_pnl, trader_address_label).
            pagination: If provided, fetch only that page. If None, auto-paginate all.
            order_by: Sort order, e.g. [{"field": "total_pnl", "direction": "DESC"}].

        Returns:
            List of leaderboard records.
        """
        payload: dict[str, Any] = {
            "date": {"from": date_from, "to": date_to},
        }
        if filters:
            payload["filters"] = filters
        if order_by:
            payload["order_by"] = order_by

        if pagination:
            payload["pagination"] = pagination
            result = await self._post("/api/v1/perp-leaderboard", payload)
            return result.get("data", [])

        return await self._fetch_paginated("/api/v1/perp-leaderboard", payload)

    async def fetch_address_trades(
        self,
        address: str,
        date_from: str,
        date_to: str,
        filters: dict[str, Any] | None = None,
        pagination: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch perp trades for a specific address.

        Args:
            address: 42-char hex address.
            date_from: Start date YYYY-MM-DD.
            date_to: End date YYYY-MM-DD.
            filters: Optional filters (size, value_usd, type).
            pagination: If provided, fetch only that page. If None, auto-paginate all.
            order_by: Sort order.

        Returns:
            List of trade records.
        """
        payload: dict[str, Any] = {
            "address": address,
            "date": {"from": date_from, "to": date_to},
        }
        if filters:
            payload["filters"] = filters
        if order_by:
            payload["order_by"] = order_by

        if pagination:
            payload["pagination"] = pagination
            result = await self._post("/api/v1/profiler/perp-trades", payload)
            return result.get("data", [])

        return await self._fetch_paginated("/api/v1/profiler/perp-trades", payload)

    async def fetch_address_positions(
        self,
        address: str,
        filters: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Fetch current perp positions for a specific address.

        Note: This endpoint is NOT paginated — it returns all positions at once.

        Args:
            address: 42-char hex address.
            filters: Optional filters (position_value_usd, unrealized_pnl_usd).
            order_by: Sort order.

        Returns:
            Full response dict with 'data' containing asset_positions and account summary.
        """
        payload: dict[str, Any] = {"address": address}
        if filters:
            payload["filters"] = filters
        if order_by:
            payload["order_by"] = order_by

        result = await self._post("/api/v1/profiler/perp-positions", payload)
        return result.get("data", result)
