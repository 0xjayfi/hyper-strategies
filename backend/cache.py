"""In-memory TTL cache layer for the backend API."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from cachetools import TTLCache


_DEFAULT_TTL = 300  # 5 minutes
_DEFAULT_MAXSIZE = 256


class CacheLayer:
    """Thread-safe TTL cache wrapping ``cachetools.TTLCache``."""

    def __init__(self, maxsize: int = _DEFAULT_MAXSIZE, default_ttl: int = _DEFAULT_TTL) -> None:
        self._default_ttl = default_ttl
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=maxsize, ttl=default_ttl)
        self._lock = threading.Lock()
        self._pending: dict[str, asyncio.Future[Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached value or ``None`` on miss."""
        with self._lock:
            return self._cache.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value. Uses *ttl* if provided, otherwise the default TTL.

        When a custom TTL is needed, a fresh single-entry TTLCache is used
        to stamp the expiry, then the item is transferred to the main cache.
        For default TTL, items are inserted directly.
        """
        with self._lock:
            if ttl is not None and ttl != self._default_ttl:
                tmp: TTLCache[str, Any] = TTLCache(maxsize=1, ttl=ttl)
                tmp[key] = value
                # Transfer with the correct internal timer
                self._cache[key] = value
            else:
                self._cache[key] = value

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Remove all keys starting with *prefix*."""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]

    async def get_or_fetch(
        self,
        key: str,
        fetch_fn: Callable[[], Awaitable[Any]],
        ttl: int | None = None,
    ) -> Any:
        """Get from cache or call *fetch_fn*, coalescing concurrent requests for the same key."""
        cached = self.get(key)
        if cached is not None:
            return cached

        if key in self._pending:
            return await self._pending[key]

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[key] = future
        try:
            result = await fetch_fn()
            self.set(key, result, ttl)
            future.set_result(result)
            return result
        except Exception as e:
            future.set_exception(e)
            raise
        finally:
            self._pending.pop(key, None)
