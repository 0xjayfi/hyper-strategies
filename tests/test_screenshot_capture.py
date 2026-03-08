"""Tests for screenshot_capture module."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.screenshot_capture import capture_screenshots


SAMPLE_PAYLOAD = {
    "post_worthy": True,
    "wallet": {"address": "0xabc123def456", "label": "Test Trader"},
}


@pytest.fixture
def payload_file(tmp_path: Path) -> Path:
    p = tmp_path / "content_payload.json"
    p.write_text(json.dumps(SAMPLE_PAYLOAD))
    return p


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "charts"
    d.mkdir()
    return d


@pytest.mark.asyncio
async def test_capture_screenshots_returns_three_paths(payload_file, output_dir):
    """capture_screenshots should produce exactly 3 PNG files."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.locator = MagicMock()

    mock_locator = MagicMock()
    async def fake_screenshot(**kwargs):
        Path(kwargs["path"]).write_bytes(b"fake png")
    mock_locator.screenshot = AsyncMock(side_effect=fake_screenshot)
    mock_page.locator.return_value = mock_locator

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch("src.screenshot_capture.async_playwright") as mock_async_pw:
        mock_async_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_async_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        paths = await capture_screenshots(
            payload_path=str(payload_file),
            output_dir=str(output_dir),
            dashboard_url="https://example.com",
        )

    assert len(paths) == 3
    assert all(p.endswith(".png") for p in paths)


@pytest.mark.asyncio
async def test_capture_screenshots_navigates_to_correct_urls(payload_file, output_dir):
    """Should navigate to /leaderboard and /traders/{address}."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_selector = AsyncMock()
    mock_page.locator = MagicMock()
    mock_locator = MagicMock()
    async def fake_screenshot(**kwargs):
        Path(kwargs["path"]).write_bytes(b"fake png")
    mock_locator.screenshot = AsyncMock(side_effect=fake_screenshot)
    mock_page.locator.return_value = mock_locator

    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

    with patch("src.screenshot_capture.async_playwright") as mock_async_pw:
        mock_async_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_async_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        await capture_screenshots(
            payload_path=str(payload_file),
            output_dir=str(output_dir),
            dashboard_url="https://example.com",
        )

    goto_calls = [c.args[0] for c in mock_page.goto.call_args_list]
    assert "https://example.com/leaderboard" in goto_calls
    assert "https://example.com/traders/0xabc123def456" in goto_calls
