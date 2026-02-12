"""Unit tests for the _RateLimiter, custom exceptions, and _parse_retry_after.

These tests run entirely offline — no real HTTP calls are made.  Time is
controlled via ``unittest.mock.patch`` to avoid any real sleeping.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.nansen_client import (
    NansenAPIError,
    NansenAuthError,
    NansenRateLimitError,
    _RateLimiter,
    _parse_retry_after,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_limiter(
    per_second: int = 2,
    per_minute: int = 10,
    min_interval: float = 0.0,
    state_file: str | None = None,
) -> _RateLimiter:
    """Create a rate limiter with no persistence and no min-interval by default."""
    return _RateLimiter(
        per_second=per_second,
        per_minute=per_minute,
        state_file=state_file,
        min_interval=min_interval,
    )


# ---------------------------------------------------------------------------
# Exception hierarchy tests
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """Verify custom exception classes and their relationships."""

    def test_nansen_api_error_fields(self) -> None:
        exc = NansenAPIError(status_code=500, detail="server error")
        assert exc.status_code == 500
        assert exc.detail == "server error"
        assert "500" in str(exc)
        assert "server error" in str(exc)

    def test_rate_limit_error_is_api_error(self) -> None:
        exc = NansenRateLimitError()
        assert isinstance(exc, NansenAPIError)
        assert exc.status_code == 429
        assert exc.detail == "Rate limit exceeded"

    def test_rate_limit_error_custom_detail(self) -> None:
        exc = NansenRateLimitError(detail="429 on attempt 2 for /foo")
        assert exc.status_code == 429
        assert "attempt 2" in exc.detail

    def test_auth_error_is_api_error(self) -> None:
        exc = NansenAuthError(status_code=401)
        assert isinstance(exc, NansenAPIError)
        assert exc.status_code == 401
        assert exc.detail == "Authentication failed"

    def test_auth_error_403(self) -> None:
        exc = NansenAuthError(status_code=403, detail="Forbidden")
        assert exc.status_code == 403
        assert exc.detail == "Forbidden"


# ---------------------------------------------------------------------------
# _parse_retry_after tests
# ---------------------------------------------------------------------------


class TestParseRetryAfter:
    """Verify the Retry-After header parser."""

    def _make_response(self, headers: dict[str, str]) -> httpx.Response:
        """Build a minimal httpx.Response with the given headers."""
        return httpx.Response(
            status_code=429,
            headers=headers,
        )

    def test_valid_header(self) -> None:
        resp = self._make_response({"Retry-After": "5"})
        assert _parse_retry_after(resp, fallback=10.0) == 5.0

    def test_valid_float_header(self) -> None:
        resp = self._make_response({"Retry-After": "2.5"})
        assert _parse_retry_after(resp, fallback=10.0) == 2.5

    def test_lowercase_header(self) -> None:
        # httpx normalises headers to lowercase internally, so
        # both forms should work via our explicit fallback lookup.
        resp = self._make_response({"retry-after": "3"})
        assert _parse_retry_after(resp, fallback=10.0) == 3.0

    def test_missing_header_returns_fallback(self) -> None:
        resp = self._make_response({})
        assert _parse_retry_after(resp, fallback=7.0) == 7.0

    def test_unparseable_header_returns_fallback(self) -> None:
        resp = self._make_response({"Retry-After": "not-a-number"})
        assert _parse_retry_after(resp, fallback=12.0) == 12.0

    def test_negative_value_clamped_to_zero(self) -> None:
        resp = self._make_response({"Retry-After": "-3"})
        assert _parse_retry_after(resp, fallback=10.0) == 0.0


# ---------------------------------------------------------------------------
# _RateLimiter — per-second enforcement
# ---------------------------------------------------------------------------


class TestRateLimiterPerSecond:
    """Verify the per-second sliding window gate."""

    @pytest.mark.asyncio
    async def test_allows_up_to_limit(self) -> None:
        """Two requests within 1 second should not sleep (per_second=2)."""
        limiter = _make_limiter(per_second=2, per_minute=100)

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()
            await limiter.acquire()

        # No sleep should have been triggered by the per-second gate.
        # (The timestamps are written in real time so both are within 1s.)
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blocks_when_exceeded(self) -> None:
        """Third request within 1 second should trigger a sleep (per_second=2)."""
        limiter = _make_limiter(per_second=2, per_minute=100)

        # Pre-fill two timestamps at "now" so the next acquire() sees the window full.
        now = time.time()
        limiter._timestamps.extend([now, now])

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        # The per-second gate should have triggered at least one sleep.
        assert mock_sleep.await_count >= 1


# ---------------------------------------------------------------------------
# _RateLimiter — per-minute enforcement
# ---------------------------------------------------------------------------


class TestRateLimiterPerMinute:
    """Verify the per-minute sliding window gate."""

    @pytest.mark.asyncio
    async def test_blocks_when_exceeded(self) -> None:
        """When per_minute timestamps are full, acquire() should sleep."""
        limiter = _make_limiter(per_second=100, per_minute=3)

        # Pre-fill 3 timestamps within the last 60 seconds.
        now = time.time()
        limiter._timestamps.extend([now - 30, now - 20, now - 10])

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        # The per-minute gate should have triggered a sleep.
        assert mock_sleep.await_count >= 1

    @pytest.mark.asyncio
    async def test_old_timestamps_purged(self) -> None:
        """Timestamps older than 60s should be evicted, freeing capacity."""
        limiter = _make_limiter(per_second=100, per_minute=3)

        # All timestamps are older than 60s — they should be purged.
        now = time.time()
        limiter._timestamps.extend([now - 120, now - 90, now - 70])

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        # No sleep needed — the stale entries were evicted.
        mock_sleep.assert_not_awaited()
        # Old entries should be gone, only the new one remains.
        assert len(limiter._timestamps) == 1


# ---------------------------------------------------------------------------
# _RateLimiter — min interval enforcement
# ---------------------------------------------------------------------------


class TestRateLimiterMinInterval:
    """Verify the minimum interval between consecutive requests."""

    @pytest.mark.asyncio
    async def test_enforces_min_interval(self) -> None:
        """When the last request was recent, acquire() should sleep."""
        limiter = _make_limiter(per_second=100, per_minute=100, min_interval=5.0)

        # Simulate a recent request 1 second ago.
        now = time.time()
        limiter._timestamps.append(now - 1.0)

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        # Should sleep roughly 4 seconds (5.0 - 1.0).
        assert mock_sleep.await_count >= 1
        slept = mock_sleep.call_args_list[0][0][0]
        assert 3.5 <= slept <= 4.5

    @pytest.mark.asyncio
    async def test_no_sleep_when_interval_satisfied(self) -> None:
        """When enough time has passed, no interval sleep needed."""
        limiter = _make_limiter(per_second=100, per_minute=100, min_interval=1.0)

        # Last request was 10 seconds ago — well past the 1s interval.
        now = time.time()
        limiter._timestamps.append(now - 10.0)

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        mock_sleep.assert_not_awaited()


# ---------------------------------------------------------------------------
# _RateLimiter — global cooldown (notify_rate_limited)
# ---------------------------------------------------------------------------


class TestRateLimiterCooldown:
    """Verify the global cooldown via notify_rate_limited()."""

    @pytest.mark.asyncio
    async def test_cooldown_causes_sleep(self) -> None:
        """After notify_rate_limited, acquire() should sleep until the deadline."""
        limiter = _make_limiter(per_second=100, per_minute=100)

        # Set a 5-second cooldown.
        await limiter.notify_rate_limited(5.0)

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()

        # Should have slept for the cooldown period.
        assert mock_sleep.await_count >= 1
        slept = mock_sleep.call_args_list[0][0][0]
        assert 4.0 <= slept <= 6.0

    @pytest.mark.asyncio
    async def test_cooldown_clears_timestamps(self) -> None:
        """After sleeping through the cooldown, timestamps should be cleared."""
        limiter = _make_limiter(per_second=100, per_minute=100)

        # Pre-fill some timestamps.
        now = time.time()
        limiter._timestamps.extend([now - 5, now - 3, now - 1])

        # Set a cooldown that is currently active.
        limiter._cooldown_until = now + 1.0

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock):
            await limiter.acquire()

        # After cooldown sleep, old timestamps should be cleared,
        # and only the new one from this acquire() remains.
        assert len(limiter._timestamps) == 1

    @pytest.mark.asyncio
    async def test_larger_cooldown_wins(self) -> None:
        """Calling notify_rate_limited twice should keep the later deadline."""
        limiter = _make_limiter(per_second=100, per_minute=100)

        await limiter.notify_rate_limited(2.0)
        first_deadline = limiter._cooldown_until

        await limiter.notify_rate_limited(10.0)
        second_deadline = limiter._cooldown_until

        assert second_deadline > first_deadline

    @pytest.mark.asyncio
    async def test_smaller_cooldown_ignored(self) -> None:
        """A shorter cooldown should not overwrite a longer existing one."""
        limiter = _make_limiter(per_second=100, per_minute=100)

        await limiter.notify_rate_limited(10.0)
        expected = limiter._cooldown_until

        await limiter.notify_rate_limited(1.0)
        assert limiter._cooldown_until == expected


# ---------------------------------------------------------------------------
# _RateLimiter — persistent state
# ---------------------------------------------------------------------------


class TestRateLimiterPersistence:
    """Verify state load/save to the JSON file."""

    @pytest.mark.asyncio
    async def test_save_and_load_state(self, tmp_path: Path) -> None:
        """State round-trips through JSON correctly."""
        state_file = str(tmp_path / "rate_state.json")
        limiter = _make_limiter(per_second=100, per_minute=100, state_file=state_file)

        # Acquire once to record a timestamp.
        await limiter.acquire()
        assert len(limiter._timestamps) == 1
        saved_ts = list(limiter._timestamps)

        # Create a new limiter from the same state file.
        limiter2 = _make_limiter(per_second=100, per_minute=100, state_file=state_file)
        assert len(limiter2._timestamps) == 1
        # The loaded timestamp should be very close to the saved one.
        assert abs(limiter2._timestamps[0] - saved_ts[0]) < 1.0

    @pytest.mark.asyncio
    async def test_cooldown_persisted(self, tmp_path: Path) -> None:
        """Cooldown deadline survives across restarts."""
        state_file = str(tmp_path / "rate_state.json")
        limiter = _make_limiter(per_second=100, per_minute=100, state_file=state_file)

        # Set a cooldown 30 seconds in the future.
        await limiter.notify_rate_limited(30.0)
        saved_cooldown = limiter._cooldown_until

        # Reload from file.
        limiter2 = _make_limiter(per_second=100, per_minute=100, state_file=state_file)
        assert abs(limiter2._cooldown_until - saved_cooldown) < 1.0

    @pytest.mark.asyncio
    async def test_expired_timestamps_not_loaded(self, tmp_path: Path) -> None:
        """Timestamps older than 60s should be discarded on load."""
        state_file = str(tmp_path / "rate_state.json")

        # Write state with very old timestamps.
        old_data = {
            "timestamps": [time.time() - 300, time.time() - 200],
            "cooldown_until": 0.0,
        }
        Path(state_file).write_text(json.dumps(old_data))

        limiter = _make_limiter(per_second=100, per_minute=100, state_file=state_file)
        assert len(limiter._timestamps) == 0

    @pytest.mark.asyncio
    async def test_expired_cooldown_not_loaded(self, tmp_path: Path) -> None:
        """A cooldown in the past should be discarded on load."""
        state_file = str(tmp_path / "rate_state.json")

        old_data = {
            "timestamps": [],
            "cooldown_until": time.time() - 100,
        }
        Path(state_file).write_text(json.dumps(old_data))

        limiter = _make_limiter(per_second=100, per_minute=100, state_file=state_file)
        assert limiter._cooldown_until == 0.0

    def test_missing_state_file_is_fine(self, tmp_path: Path) -> None:
        """If the state file does not exist, limiter starts fresh."""
        state_file = str(tmp_path / "does_not_exist.json")
        limiter = _make_limiter(state_file=state_file)
        assert len(limiter._timestamps) == 0
        assert limiter._cooldown_until == 0.0

    def test_corrupt_state_file_is_fine(self, tmp_path: Path) -> None:
        """If the state file is corrupt, limiter starts fresh."""
        state_file = str(tmp_path / "corrupt.json")
        Path(state_file).write_text("not valid json {{{")
        limiter = _make_limiter(state_file=state_file)
        assert len(limiter._timestamps) == 0
        assert limiter._cooldown_until == 0.0

    def test_no_state_file_disables_persistence(self) -> None:
        """When state_file=None, no file operations happen."""
        limiter = _make_limiter(state_file=None)
        # Should not raise even though no file is configured.
        limiter._save_state()
        limiter._load_state()
        assert len(limiter._timestamps) == 0

    @pytest.mark.asyncio
    async def test_atomic_write(self, tmp_path: Path) -> None:
        """Save uses atomic write (tempfile + rename), file should be valid JSON."""
        state_file = str(tmp_path / "atomic_test.json")
        limiter = _make_limiter(per_second=100, per_minute=100, state_file=state_file)
        await limiter.acquire()

        # File should exist and be valid JSON.
        data = json.loads(Path(state_file).read_text())
        assert "timestamps" in data
        assert "cooldown_until" in data
        assert len(data["timestamps"]) == 1


# ---------------------------------------------------------------------------
# _RateLimiter — concurrent access serialization
# ---------------------------------------------------------------------------


class TestRateLimiterConcurrency:
    """Verify that the asyncio.Lock serialises concurrent callers."""

    @pytest.mark.asyncio
    async def test_concurrent_acquires_serialized(self) -> None:
        """Multiple concurrent acquire() calls should not produce duplicate timestamps."""
        limiter = _make_limiter(per_second=100, per_minute=100)

        # Fire 5 concurrent acquires.
        tasks = [asyncio.create_task(limiter.acquire()) for _ in range(5)]
        await asyncio.gather(*tasks)

        # Each acquire should have recorded exactly one timestamp.
        assert len(limiter._timestamps) == 5

        # All timestamps should be monotonically non-decreasing.
        ts_list = list(limiter._timestamps)
        for i in range(1, len(ts_list)):
            assert ts_list[i] >= ts_list[i - 1]

    @pytest.mark.asyncio
    async def test_concurrent_notify_and_acquire(self) -> None:
        """notify_rate_limited and acquire can run concurrently without error."""
        limiter = _make_limiter(per_second=100, per_minute=100)

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock):
            tasks = [
                asyncio.create_task(limiter.notify_rate_limited(1.0)),
                asyncio.create_task(limiter.acquire()),
                asyncio.create_task(limiter.acquire()),
            ]
            await asyncio.gather(*tasks)

        # Should complete without errors.  The lock serialises the operations,
        # so both acquire() calls should each have appended a timestamp.
        # However, if notify_rate_limited runs first and sets a cooldown,
        # the acquire() calls will sleep through the cooldown and clear old
        # timestamps before appending.  Either way, we should have >= 1
        # timestamp and no exceptions.
        assert len(limiter._timestamps) >= 1


# ---------------------------------------------------------------------------
# _RateLimiter — zero min_interval
# ---------------------------------------------------------------------------


class TestRateLimiterZeroMinInterval:
    """Verify behaviour when min_interval is zero (disabled)."""

    @pytest.mark.asyncio
    async def test_no_interval_sleep(self) -> None:
        """With min_interval=0, back-to-back requests should not trigger interval sleep."""
        limiter = _make_limiter(per_second=100, per_minute=100, min_interval=0.0)

        with patch("src.nansen_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await limiter.acquire()
            await limiter.acquire()

        mock_sleep.assert_not_awaited()
