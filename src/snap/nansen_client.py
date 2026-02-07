"""Async HTTP client for the Nansen API with rate limiting, pagination, and retry logic."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class NansenAPIError(Exception):
    """Base exception for Nansen API errors."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Nansen API error {status_code}: {message}")


class NansenRateLimitError(NansenAPIError):
    """Raised when rate limit is exceeded and all retries are exhausted."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(status_code=429, message=message)


class NansenAuthError(NansenAPIError):
    """Raised on 401/403 authentication or authorization failures."""

    def __init__(self, status_code: int, message: str = "Authentication failed") -> None:
        super().__init__(status_code=status_code, message=message)


# ---------------------------------------------------------------------------
# Status code sets for retry classification
# ---------------------------------------------------------------------------

_NO_RETRY_CLIENT_ERRORS = frozenset({400, 401, 403, 404, 422})

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_DEFAULT_BASE_URL = "https://api.nansen.ai/api/v1"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_SCHEDULE = (1.0, 2.0, 4.0)  # seconds per retry attempt
_DEFAULT_PAGE_SIZE = 100


class NansenClient:
    """Async HTTP client for the Nansen perp data API.

    Usage::

        async with NansenClient(api_key="your-key") as client:
            leaders = await client.get_leaderboard("2025-09-01", "2025-10-01")
            positions = await client.get_perp_positions("0xabc...")
            trades = await client.get_perp_trades("0xabc...", "2025-09-01", "2025-10-01")
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"apiKey": api_key, "Content-Type": "application/json"},
        )
        # Rate-limiter state: timestamp of last request completion.
        self._last_request_time: float = 0.0

    # -- async context manager ------------------------------------------------

    async def __aenter__(self) -> NansenClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    # -- core request engine --------------------------------------------------

    async def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Make a rate-limited, retried POST request to the given *endpoint*.

        Parameters
        ----------
        endpoint:
            Path relative to *base_url* (e.g. ``"/perp-leaderboard"``).
        payload:
            JSON body for the POST request.

        Returns
        -------
        dict
            Parsed JSON response body.

        Raises
        ------
        NansenAuthError
            On 401 or 403 (no retry).
        NansenRateLimitError
            On 429 after all retries exhausted.
        NansenAPIError
            On other non-retryable client errors or server errors after
            retries exhausted.
        """
        url = f"{self._base_url}{endpoint}"
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            backoff = _BACKOFF_SCHEDULE[attempt] if attempt < len(_BACKOFF_SCHEDULE) else _BACKOFF_SCHEDULE[-1]

            logger.debug(
                "Nansen request attempt=%d endpoint=%s",
                attempt + 1,
                endpoint,
            )

            try:
                response = await self._client.post(url, json=payload)
                self._last_request_time = time.monotonic()
            except httpx.HTTPError as exc:
                # Network-level errors (timeout, connection reset, etc.)
                last_exc = exc
                logger.warning(
                    "Nansen request network error attempt=%d endpoint=%s error=%s",
                    attempt + 1,
                    endpoint,
                    exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                continue

            status = response.status_code

            # --- success ---
            if 200 <= status < 300:
                return response.json()

            # --- auth errors: never retry ---
            if status in (401, 403):
                body_text = response.text
                logger.error(
                    "Nansen auth error status=%d endpoint=%s body=%s",
                    status,
                    endpoint,
                    body_text,
                )
                raise NansenAuthError(status_code=status, message=body_text)

            # --- other non-retryable client errors ---
            if status in _NO_RETRY_CLIENT_ERRORS:
                body_text = response.text
                logger.error(
                    "Nansen client error status=%d endpoint=%s body=%s",
                    status,
                    endpoint,
                    body_text,
                )
                raise NansenAPIError(status_code=status, message=body_text)

            # --- rate limit (429): wait using Retry-After or backoff ---
            if status == 429:
                retry_after = _parse_retry_after(response, fallback=backoff)
                logger.warning(
                    "Nansen rate limit hit attempt=%d endpoint=%s retry_after=%.1fs",
                    attempt + 1,
                    endpoint,
                    retry_after,
                )
                last_exc = NansenRateLimitError(
                    message=f"429 on attempt {attempt + 1} for {endpoint}"
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(retry_after)
                continue

            # --- server errors (5xx): retry with backoff ---
            if status >= 500:
                body_text = response.text
                logger.warning(
                    "Nansen server error status=%d attempt=%d endpoint=%s body=%s",
                    status,
                    attempt + 1,
                    endpoint,
                    body_text,
                )
                last_exc = NansenAPIError(status_code=status, message=body_text)
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                continue

            # --- unexpected status code: treat like a non-retryable error ---
            body_text = response.text
            raise NansenAPIError(status_code=status, message=body_text)

        # All retries exhausted.
        if isinstance(last_exc, NansenRateLimitError):
            raise last_exc
        if isinstance(last_exc, NansenAPIError):
            raise last_exc
        # Network errors fall through here.
        raise NansenAPIError(
            status_code=0,
            message=f"All {_MAX_RETRIES} attempts failed for {endpoint}: {last_exc}",
        )

    # -- pagination helper ----------------------------------------------------

    async def _paginate(
        self,
        endpoint: str,
        base_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Paginate through all pages of *endpoint*, accumulating ``data`` items.

        The caller supplies a *base_payload* which may already contain a
        ``pagination`` key (it will be overwritten by this method).

        Returns
        -------
        list[dict]
            All ``data`` items concatenated across every page.
        """
        all_items: list[dict[str, Any]] = []
        page = 1

        while True:
            payload = {
                **base_payload,
                "pagination": {"page": page, "per_page": _DEFAULT_PAGE_SIZE},
            }
            result = await self._request(endpoint, payload)

            data = result.get("data")
            if isinstance(data, list):
                all_items.extend(data)
            elif data is not None:
                # Some endpoints wrap data differently; treat as single item.
                all_items.append(data)

            pagination = result.get("pagination", {})
            is_last_page = pagination.get("is_last_page", True)

            logger.debug(
                "Paginate endpoint=%s page=%d items_this_page=%d total_so_far=%d is_last=%s",
                endpoint,
                page,
                len(data) if isinstance(data, list) else 1,
                len(all_items),
                is_last_page,
            )

            if is_last_page:
                break

            page += 1

        return all_items

    # -- public API methods ---------------------------------------------------

    async def get_leaderboard(
        self,
        date_from: str,
        date_to: str,
        min_account_value: float = 50_000,
        min_total_pnl: float = 0,
    ) -> list[dict[str, Any]]:
        """Fetch the full paginated perp leaderboard for a date range.

        Parameters
        ----------
        date_from, date_to:
            Date strings in ``YYYY-MM-DD`` format.
        min_account_value:
            Minimum account value filter (USD). Default 50 000.
        min_total_pnl:
            Minimum total PnL filter (USD). Default 0.

        Returns
        -------
        list[dict]
            Each dict contains ``trader_address``, ``trader_address_label``,
            ``total_pnl``, ``roi``, ``account_value``, etc.
        """
        base_payload: dict[str, Any] = {
            "date": {"from": date_from, "to": date_to},
            "filters": {
                "account_value": {"min": min_account_value},
                "total_pnl": {"min": min_total_pnl},
            },
        }
        return await self._paginate("/perp-leaderboard", base_payload)

    async def get_perp_positions(self, address: str) -> dict[str, Any]:
        """Fetch current perp positions for a single address.

        Returns the full ``data`` object from the API which includes:
        - ``asset_positions``: list of position objects
        - ``margin_summary_account_value_usd``: account value as string
        - ``timestamp``: UNIX epoch seconds

        Position numeric fields (``entry_price_usd``, ``size``, ``leverage_value``,
        ``liquidation_price_usd``, ``margin_used_usd``, ``position_value_usd``,
        ``unrealized_pnl_usd``) are returned as **strings** by the API.  The
        caller is responsible for parsing them to float.

        Returns
        -------
        dict
            The ``data`` portion of the API response (not a list).
        """
        result = await self._request(
            "/profiler/perp-positions",
            {"address": address},
        )
        return result.get("data", {})

    async def get_perp_trades(
        self,
        address: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """Fetch full paginated perp trade history for an address.

        Parameters
        ----------
        address:
            Trader wallet address (``0x...``).
        date_from, date_to:
            Date strings in ``YYYY-MM-DD`` format.

        Returns
        -------
        list[dict]
            Each dict contains ``action``, ``closed_pnl``, ``fee_usd``,
            ``price``, ``side``, ``size``, ``timestamp``, ``token_symbol``,
            ``value_usd``.
        """
        base_payload: dict[str, Any] = {
            "address": address,
            "date": {"from": date_from, "to": date_to},
        }
        return await self._paginate("/profiler/perp-trades", base_payload)

    # -- lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_retry_after(response: httpx.Response, fallback: float) -> float:
    """Extract a ``Retry-After`` value from the response headers.

    Falls back to *fallback* seconds when the header is absent or unparseable.
    """
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw is None:
        return fallback
    try:
        return max(0.0, float(raw))
    except (ValueError, TypeError):
        return fallback
