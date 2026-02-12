"""Async Nansen API client for Hyperliquid perpetual trading data.

Wraps four Nansen endpoints with sliding-window rate limiting, retry logic,
tuple backoff for 429/5xx errors, and auto-pagination for the address trades
endpoint.

Usage::

    async with NansenClient() as client:
        entries = await client.fetch_leaderboard("2026-01-01", "2026-01-07")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from src.config import (
    NANSEN_RATE_LIMIT_LEADERBOARD_MIN_INTERVAL,
    NANSEN_RATE_LIMIT_LEADERBOARD_PER_MINUTE,
    NANSEN_RATE_LIMIT_LEADERBOARD_PER_SECOND,
    NANSEN_RATE_LIMIT_LEADERBOARD_STATE_FILE,
    NANSEN_RATE_LIMIT_PROFILER_MIN_INTERVAL,
    NANSEN_RATE_LIMIT_PROFILER_PER_MINUTE,
    NANSEN_RATE_LIMIT_PROFILER_PER_SECOND,
    NANSEN_RATE_LIMIT_PROFILER_STATE_FILE,
)
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
_BACKOFF_SCHEDULE = (2.0, 5.0, 15.0)  # seconds per retry attempt
_AUTO_PAGE_SIZE = 100

# Status codes that should never be retried.
_NO_RETRY_CLIENT_ERRORS = frozenset({400, 401, 403, 404, 422})


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class NansenAPIError(Exception):
    """Raised when the Nansen API returns an unrecoverable error."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Nansen API error {status_code}: {detail}")


class NansenRateLimitError(NansenAPIError):
    """Raised when rate limit is exceeded and all retries are exhausted."""

    def __init__(self, detail: str = "Rate limit exceeded") -> None:
        super().__init__(status_code=429, detail=detail)


class NansenAuthError(NansenAPIError):
    """Raised on 401/403 authentication or authorization failures."""

    def __init__(self, status_code: int, detail: str = "Authentication failed") -> None:
        super().__init__(status_code=status_code, detail=detail)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_retry_after(response: httpx.Response, fallback: float) -> float:
    """Extract a ``Retry-After`` value from the response headers.

    Performs a case-insensitive header lookup with *fallback* when the header
    is absent or unparseable.
    """
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw is None:
        return fallback
    try:
        return max(0.0, float(raw))
    except (ValueError, TypeError):
        return fallback


# ---------------------------------------------------------------------------
# Sliding-window rate limiter
# ---------------------------------------------------------------------------


class _RateLimiter:
    """Async sliding-window rate limiter with persistent state across restarts.

    Uses wall-clock time (``time.time()``) so that timestamps survive process
    restarts.  State (recent request timestamps + cooldown deadline) is
    persisted to a JSON file after every mutation, and loaded on init.

    Every call to :meth:`acquire` blocks (via ``asyncio.sleep``) until the
    request can be issued without violating either limit.  An
    ``asyncio.Lock`` serialises concurrent callers so that the timestamp
    bookkeeping stays consistent.
    """

    def __init__(
        self,
        per_second: int,
        per_minute: int,
        state_file: str | None,
        min_interval: float,
    ) -> None:
        self._per_second = per_second
        self._per_minute = per_minute
        self._state_file = state_file
        self._min_interval = min_interval  # minimum seconds between any two requests
        self._lock = asyncio.Lock()
        # When the server returns 429, we set a cooldown deadline (wall-clock)
        # so ALL subsequent requests wait until the server's window resets.
        self._cooldown_until: float = 0.0

        # Load persisted state from previous runs.
        self._timestamps: deque[float] = deque()
        self._load_state()

    # -- persistence ----------------------------------------------------------

    def _load_state(self) -> None:
        """Load timestamps and cooldown from the state file, if it exists."""
        if not self._state_file:
            return
        try:
            path = Path(self._state_file)
            if not path.exists():
                return
            data = json.loads(path.read_text())
            now = time.time()

            # Load timestamps within the last 60 seconds
            saved_ts = data.get("timestamps", [])
            cutoff = now - 60.0
            recent = [t for t in saved_ts if isinstance(t, (int, float)) and t > cutoff]
            self._timestamps = deque(sorted(recent))

            # Load cooldown if still in effect
            saved_cooldown = data.get("cooldown_until", 0.0)
            if isinstance(saved_cooldown, (int, float)) and saved_cooldown > now:
                self._cooldown_until = saved_cooldown

            if self._timestamps or self._cooldown_until > now:
                logger.info(
                    "Rate limiter: loaded %d recent requests from previous run "
                    "(cooldown_remaining=%.1fs)",
                    len(self._timestamps),
                    max(0.0, self._cooldown_until - now),
                )
        except Exception:
            logger.warning("Rate limiter: failed to load state file, starting fresh", exc_info=True)

    def _save_state(self) -> None:
        """Atomically persist current timestamps and cooldown to the state file."""
        if not self._state_file:
            return
        try:
            data = {
                "timestamps": list(self._timestamps),
                "cooldown_until": self._cooldown_until,
            }
            # Atomic write: write to temp file then rename
            dir_path = os.path.dirname(self._state_file) or "/tmp"
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f)
                os.replace(tmp_path, self._state_file)
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            logger.debug("Rate limiter: failed to save state file", exc_info=True)

    # -- public API -----------------------------------------------------------

    async def notify_rate_limited(self, retry_after: float) -> None:
        """Called when the server returns 429. Sets a global cooldown."""
        async with self._lock:
            deadline = time.time() + retry_after
            if deadline > self._cooldown_until:
                self._cooldown_until = deadline
                logger.info(
                    "Rate limiter: server 429 received, global cooldown for %.1fs",
                    retry_after,
                )
                self._save_state()

    async def acquire(self) -> None:
        """Wait until a request slot is available, then record it."""
        async with self._lock:
            now = time.time()

            # --- minimum interval between requests ---
            if self._timestamps and self._min_interval > 0:
                last_request = self._timestamps[-1]
                gap = now - last_request
                if gap < self._min_interval:
                    delay = self._min_interval - gap
                    await asyncio.sleep(delay)
                    now = time.time()

            # --- server-imposed cooldown gate ---
            if self._cooldown_until > now:
                delay = self._cooldown_until - now
                logger.info("Rate limiter: cooling down for %.1fs (server 429)", delay)
                await asyncio.sleep(delay)
                now = time.time()
                # Clear old timestamps after sleeping through the cooldown
                self._timestamps.clear()

            # Purge entries older than 60 s (outside the per-minute window).
            while self._timestamps and self._timestamps[0] <= now - 60.0:
                self._timestamps.popleft()

            # --- per-minute gate ---
            if len(self._timestamps) >= self._per_minute:
                sleep_until = self._timestamps[0] + 60.0
                delay = sleep_until - now
                if delay > 0:
                    logger.debug("Rate limiter: per-minute cap reached, sleeping %.2fs", delay)
                    await asyncio.sleep(delay)
                    now = time.time()
                    while self._timestamps and self._timestamps[0] <= now - 60.0:
                        self._timestamps.popleft()

            # --- per-second gate ---
            one_sec_ago = now - 1.0
            recent = sum(1 for t in self._timestamps if t > one_sec_ago)
            if recent >= self._per_second:
                # Find the oldest timestamp within the 1-second window.
                oldest_in_window = next(t for t in self._timestamps if t > one_sec_ago)
                delay = oldest_in_window + 1.0 - now
                if delay > 0:
                    logger.debug("Rate limiter: per-second cap reached, sleeping %.3fs", delay)
                    await asyncio.sleep(delay)
                    now = time.time()

            self._timestamps.append(now)
            self._save_state()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NansenClient:
    """Async wrapper around the Nansen Hyperliquid API endpoints.

    Uses **two separate rate limiters** — one for leaderboard endpoints (fast,
    no throttling needed) and one for profiler endpoints (trades/positions —
    fast server responses trigger 429s, needs strict throttling).

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
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

        # Leaderboard — slow server responses (~1-2s/page), no 429 risk
        self._leaderboard_limiter = _RateLimiter(
            per_second=NANSEN_RATE_LIMIT_LEADERBOARD_PER_SECOND,
            per_minute=NANSEN_RATE_LIMIT_LEADERBOARD_PER_MINUTE,
            state_file=NANSEN_RATE_LIMIT_LEADERBOARD_STATE_FILE,
            min_interval=NANSEN_RATE_LIMIT_LEADERBOARD_MIN_INTERVAL,
        )

        # Profiler (perp-trades, perp-positions) — fast responses, 429 risk
        self._profiler_limiter = _RateLimiter(
            per_second=NANSEN_RATE_LIMIT_PROFILER_PER_SECOND,
            per_minute=NANSEN_RATE_LIMIT_PROFILER_PER_MINUTE,
            state_file=NANSEN_RATE_LIMIT_PROFILER_STATE_FILE,
            min_interval=NANSEN_RATE_LIMIT_PROFILER_MIN_INTERVAL,
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
        """Send a rate-limited, retried POST request to the given *endpoint*.

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
        NansenAuthError
            On 401 or 403 (no retry).
        NansenRateLimitError
            On 429 after all retries exhausted.
        NansenAPIError
            On other non-retryable client errors or server errors after
            retries exhausted.
        """
        headers = {
            "apiKey": self.api_key,
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            backoff = (
                _BACKOFF_SCHEDULE[attempt]
                if attempt < len(_BACKOFF_SCHEDULE)
                else _BACKOFF_SCHEDULE[-1]
            )

            logger.debug(
                "Nansen request attempt=%d endpoint=%s",
                attempt + 1,
                endpoint,
            )

            # Route to the correct limiter based on endpoint.
            limiter = (
                self._profiler_limiter
                if "/profiler/" in endpoint
                else self._leaderboard_limiter
            )

            try:
                await limiter.acquire()
                response = await self._client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )
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
                return response.json()  # type: ignore[no-any-return]

            # --- auth errors: never retry ---
            if status in (401, 403):
                body_text = response.text
                logger.error(
                    "Nansen auth error status=%d endpoint=%s body=%s",
                    status,
                    endpoint,
                    body_text,
                )
                raise NansenAuthError(status_code=status, detail=body_text)

            # --- other non-retryable client errors ---
            if status in _NO_RETRY_CLIENT_ERRORS:
                body_text = response.text
                logger.error(
                    "Nansen client error status=%d endpoint=%s body=%s",
                    status,
                    endpoint,
                    body_text,
                )
                raise NansenAPIError(status_code=status, detail=body_text)

            # --- rate limit (429): notify limiter and wait ---
            if status == 429:
                retry_after = _parse_retry_after(response, fallback=backoff)
                logger.warning(
                    "Nansen rate limit hit attempt=%d endpoint=%s retry_after=%.1fs",
                    attempt + 1,
                    endpoint,
                    retry_after,
                )
                # Set cooldown on the relevant limiter
                await limiter.notify_rate_limited(retry_after)
                last_exc = NansenRateLimitError(
                    detail=f"429 on attempt {attempt + 1} for {endpoint}"
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
                last_exc = NansenAPIError(status_code=status, detail=body_text)
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)
                continue

            # --- unexpected status code: treat like a non-retryable error ---
            body_text = response.text
            raise NansenAPIError(status_code=status, detail=body_text)

        # All retries exhausted.
        if isinstance(last_exc, NansenRateLimitError):
            raise last_exc
        if isinstance(last_exc, NansenAPIError):
            raise last_exc
        # Network errors fall through here.
        raise NansenAPIError(
            status_code=0,
            detail=f"All {_MAX_RETRIES} attempts failed for {endpoint}: {last_exc}",
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
