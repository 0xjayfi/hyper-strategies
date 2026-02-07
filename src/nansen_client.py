"""Async Nansen API client for Hyperliquid perpetual trading data.

Wraps four Nansen endpoints with retry logic, exponential backoff for
429/5xx errors, and auto-pagination for the address trades endpoint.

Usage::

    async with NansenClient() as client:
        entries = await client.fetch_leaderboard("2026-01-01", "2026-01-07")
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any

import httpx
from dotenv import load_dotenv

from src.models import (
    AssetPosition,
    LeaderboardEntry,
    PnlLeaderboardEntry,
    PositionSnapshot,
    Trade,
)

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.nansen.ai"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BASE_DELAY = 2.0
_AUTO_PAGE_SIZE = 100


class NansenAPIError(Exception):
    """Raised when the Nansen API returns an unrecoverable error."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Nansen API error {status_code}: {detail}")


class NansenClient:
    """Async wrapper around the Nansen Hyperliquid API endpoints.

    Parameters
    ----------
    api_key:
        Nansen API key.  Falls back to the ``NANSEN_API_KEY`` env var.
    base_url:
        API base URL.  Falls back to ``NANSEN_BASE_URL`` env var, then
        ``https://api.nansen.ai``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("NANSEN_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Nansen API key is required. Pass api_key= or set NANSEN_API_KEY."
            )

        self.base_url = (
            base_url
            or os.getenv("NANSEN_BASE_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(_DEFAULT_TIMEOUT),
        )

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> NansenClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Core request with retry
    # ------------------------------------------------------------------

    async def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a POST request with retry on 429 / 5xx.

        Parameters
        ----------
        endpoint:
            Relative path, e.g. ``/api/v1/perp-leaderboard``.
        payload:
            JSON body to send.

        Returns
        -------
        dict
            Parsed JSON response body.

        Raises
        ------
        NansenAPIError
            On non-retryable 4xx errors or after exhausting retries.
        """
        headers = {
            "apiKey": self.api_key,
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Transport error on %s (attempt %d/%d): %s — retrying in %.1fs",
                    endpoint,
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                else:
                    delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Rate-limited on %s (attempt %d/%d) — retrying in %.1fs",
                    endpoint,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                last_exc = NansenAPIError(429, "Rate limited")
                await asyncio.sleep(delay)
                continue

            if 500 <= response.status_code < 600:
                delay = _BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Server error %d on %s (attempt %d/%d) — retrying in %.1fs",
                    response.status_code,
                    endpoint,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                last_exc = NansenAPIError(response.status_code, response.text)
                await asyncio.sleep(delay)
                continue

            # Non-retryable client errors (4xx except 429)
            if 400 <= response.status_code < 500:
                raise NansenAPIError(response.status_code, response.text)

            # Success
            return response.json()  # type: ignore[no-any-return]

        # Exhausted all retries
        raise NansenAPIError(
            getattr(last_exc, "status_code", 0),
            f"Exhausted {_MAX_RETRIES} retries for {endpoint}: {last_exc}",
        )

    # ------------------------------------------------------------------
    # Leaderboard
    # ------------------------------------------------------------------

    async def fetch_leaderboard(
        self,
        date_from: str,
        date_to: str,
        filters: dict[str, Any] | None = None,
        pagination: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> list[LeaderboardEntry]:
        """Fetch the perpetual trading leaderboard.

        Parameters
        ----------
        date_from / date_to:
            Date range in ``YYYY-MM-DD`` format.
        filters:
            Optional filter dict (e.g. ``{"total_pnl": {"min": 1000}}``).
        pagination:
            Optional pagination dict (e.g. ``{"page": 1, "per_page": 10}``).
        order_by:
            Optional sort order list.

        Returns
        -------
        list[LeaderboardEntry]
        """
        payload: dict[str, Any] = {
            "date": {"from": date_from, "to": date_to},
        }
        if filters is not None:
            payload["filters"] = filters
        if pagination is not None:
            payload["pagination"] = pagination
        if order_by is not None:
            payload["order_by"] = order_by

        data = await self._request("/api/v1/perp-leaderboard", payload)
        return [LeaderboardEntry.model_validate(item) for item in data["data"]]

    # ------------------------------------------------------------------
    # Address trades (with auto-pagination)
    # ------------------------------------------------------------------

    async def fetch_address_trades(
        self,
        address: str,
        date_from: str,
        date_to: str,
        filters: dict[str, Any] | None = None,
        pagination: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> list[Trade]:
        """Fetch perpetual trades for a specific address.

        When *pagination* is ``None`` the method **auto-paginates** by
        starting at page 1 with ``per_page=100`` and accumulating results
        until ``is_last_page`` is ``True``.

        When a caller supplies an explicit *pagination* dict, only that
        single page is fetched.

        Parameters
        ----------
        address:
            42-character hex Ethereum address.
        date_from / date_to:
            Date range in ``YYYY-MM-DD`` format.
        filters:
            Optional trade filters.
        pagination:
            Optional explicit pagination dict.  If ``None``, auto-paginates.
        order_by:
            Optional sort order list.

        Returns
        -------
        list[Trade]
        """
        base_payload: dict[str, Any] = {
            "address": address,
            "date": {"from": date_from, "to": date_to},
        }
        if filters is not None:
            base_payload["filters"] = filters
        if order_by is not None:
            base_payload["order_by"] = order_by

        # Caller provided explicit pagination -- single page fetch.
        if pagination is not None:
            base_payload["pagination"] = pagination
            data = await self._request("/api/v1/profiler/perp-trades", base_payload)
            return [Trade.model_validate(item) for item in data["data"]]

        # Auto-paginate: fetch all pages.
        all_trades: list[Trade] = []
        page = 1

        while True:
            page_payload = {
                **base_payload,
                "pagination": {"page": page, "per_page": _AUTO_PAGE_SIZE},
            }
            data = await self._request("/api/v1/profiler/perp-trades", page_payload)

            items = data.get("data", [])
            all_trades.extend(Trade.model_validate(item) for item in items)

            pagination_info = data.get("pagination", {})
            if pagination_info.get("is_last_page", True):
                break

            page += 1

        return all_trades

    # ------------------------------------------------------------------
    # Address positions
    # ------------------------------------------------------------------

    async def fetch_address_positions(
        self,
        address: str,
        filters: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> PositionSnapshot:
        """Fetch current perpetual positions for an address.

        The ``data`` field in the API response is the :class:`PositionSnapshot`
        object directly (not a list).

        Parameters
        ----------
        address:
            42-character hex Ethereum address.
        filters:
            Optional position filters.
        order_by:
            Optional sort order list.

        Returns
        -------
        PositionSnapshot
        """
        payload: dict[str, Any] = {"address": address}
        if filters is not None:
            payload["filters"] = filters
        if order_by is not None:
            payload["order_by"] = order_by

        data = await self._request("/api/v1/profiler/perp-positions", payload)
        return PositionSnapshot.model_validate(data["data"])

    # ------------------------------------------------------------------
    # Per-token PnL leaderboard
    # ------------------------------------------------------------------

    async def fetch_pnl_leaderboard(
        self,
        token_symbol: str,
        date_from: str,
        date_to: str,
        filters: dict[str, Any] | None = None,
        pagination: dict[str, Any] | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> list[PnlLeaderboardEntry]:
        """Fetch the per-token PnL leaderboard.

        Parameters
        ----------
        token_symbol:
            Perpetual contract symbol (e.g. ``"BTC"``, ``"ETH"``).
        date_from / date_to:
            Date range in ``YYYY-MM-DD`` format.
        filters:
            Optional filter dict.
        pagination:
            Optional pagination dict.
        order_by:
            Optional sort order list.

        Returns
        -------
        list[PnlLeaderboardEntry]
        """
        payload: dict[str, Any] = {
            "token_symbol": token_symbol,
            "date": {"from": date_from, "to": date_to},
        }
        if filters is not None:
            payload["filters"] = filters
        if pagination is not None:
            payload["pagination"] = pagination
        if order_by is not None:
            payload["order_by"] = order_by

        data = await self._request("/api/v1/tgm/perp-pnl-leaderboard", payload)
        return [PnlLeaderboardEntry.model_validate(item) for item in data["data"]]
