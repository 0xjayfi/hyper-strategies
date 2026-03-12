"""Tests for the angle-aware screenshot capture module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.content.angles import ALL_ANGLES
from src.content.base import ScreenshotConfig
from src.content.screenshot import capture_angle_screenshots


# ---------------------------------------------------------------------------
# ScreenshotConfig validation tests
# ---------------------------------------------------------------------------


class TestScreenshotConfigValidation:
    """Validate that each angle's ScreenshotConfig has sane values."""

    def test_all_angles_have_valid_routes_and_selectors(self):
        """Each PageCapture must have non-empty route, wait_selector,
        capture_selector, and filename."""
        for angle in ALL_ANGLES:
            config = angle.screenshot_config()
            assert isinstance(config, ScreenshotConfig), (
                f"{angle.angle_type} screenshot_config() did not return a ScreenshotConfig"
            )
            assert len(config.pages) > 0, (
                f"{angle.angle_type} has an empty pages list"
            )
            for pc in config.pages:
                assert pc.route and isinstance(pc.route, str), (
                    f"{angle.angle_type}: route must be a non-empty string, got {pc.route!r}"
                )
                assert pc.wait_selector and isinstance(pc.wait_selector, str), (
                    f"{angle.angle_type}: wait_selector must be a non-empty string"
                )
                assert pc.capture_selector and isinstance(pc.capture_selector, str), (
                    f"{angle.angle_type}: capture_selector must be a non-empty string"
                )
                assert pc.filename and isinstance(pc.filename, str), (
                    f"{angle.angle_type}: filename must be a non-empty string"
                )

    def test_filenames_do_not_collide_across_angles(self):
        """No two angles should produce the same output filename."""
        seen: dict[str, str] = {}
        for angle in ALL_ANGLES:
            config = angle.screenshot_config()
            for pc in config.pages:
                if pc.filename in seen:
                    pytest.fail(
                        f"Filename collision: {pc.filename!r} used by both "
                        f"{seen[pc.filename]!r} and {angle.angle_type!r}"
                    )
                seen[pc.filename] = angle.angle_type


# ---------------------------------------------------------------------------
# capture_angle_screenshots tests (mocked Playwright)
# ---------------------------------------------------------------------------


class TestCaptureAngleScreenshots:
    """Test the capture function with a fully mocked Playwright stack."""

    @pytest.mark.asyncio
    async def test_unknown_angle_type_raises(self):
        """Passing an unknown angle_type should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown angle_type"):
            await capture_angle_screenshots("nonexistent_angle")

    @pytest.mark.asyncio
    async def test_capture_navigates_waits_and_screenshots(self, tmp_path):
        """Verify the function navigates to each route, waits for the
        selector, executes pre_capture_js, and takes a screenshot."""
        # Use wallet_spotlight which has 3 page captures
        angle_type = "wallet_spotlight"

        # Find the angle and get its config for assertions
        angle = next(a for a in ALL_ANGLES if a.angle_type == angle_type)
        config = angle.screenshot_config()

        # Build mock Playwright objects
        mock_locator = MagicMock()
        mock_locator.screenshot = AsyncMock()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_locator)

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw = MagicMock()
        mock_pw.chromium = mock_chromium

        # async context manager for async_playwright()
        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.content.screenshot.async_playwright",
            return_value=mock_pw_ctx,
        ):
            paths = await capture_angle_screenshots(
                angle_type,
                output_dir=str(tmp_path),
                dashboard_url="http://test:5173",
            )

        # Should return one path per PageCapture
        assert len(paths) == len(config.pages)

        # Verify navigated to correct URLs
        goto_calls = mock_page.goto.call_args_list
        for i, pc in enumerate(config.pages):
            expected_url = f"http://test:5173{pc.route}"
            assert goto_calls[i].args[0] == expected_url

        # Verify waited for correct selectors
        wait_calls = mock_page.wait_for_selector.call_args_list
        for i, pc in enumerate(config.pages):
            assert wait_calls[i].args[0] == pc.wait_selector

        # Verify pre_capture_js was evaluated when set
        evaluate_calls = mock_page.evaluate.call_args_list
        js_pages = [pc for pc in config.pages if pc.pre_capture_js]
        assert len(evaluate_calls) == len(js_pages)
        for call, pc in zip(evaluate_calls, js_pages):
            assert call.args[0] == pc.pre_capture_js

        # Verify locator used capture_selector
        locator_calls = mock_page.locator.call_args_list
        for i, pc in enumerate(config.pages):
            assert locator_calls[i].args[0] == pc.capture_selector

        # Verify screenshot called for each page
        assert mock_locator.screenshot.call_count == len(config.pages)

    @pytest.mark.asyncio
    async def test_capture_single_page_angle(self, tmp_path):
        """Test with a single-page angle (leaderboard_shakeup)."""
        angle_type = "leaderboard_shakeup"

        mock_locator = MagicMock()
        mock_locator.screenshot = AsyncMock()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_locator)

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw = MagicMock()
        mock_pw.chromium = mock_chromium

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.content.screenshot.async_playwright",
            return_value=mock_pw_ctx,
        ):
            paths = await capture_angle_screenshots(
                angle_type,
                output_dir=str(tmp_path),
                dashboard_url="http://test:5173",
            )

        assert len(paths) == 1
        assert paths[0].endswith("leaderboard_shakeup.png")
        mock_page.goto.assert_called_once()
        mock_locator.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_uses_default_url_from_env(self, tmp_path):
        """When no dashboard_url is passed, falls back to env var."""
        mock_locator = MagicMock()
        mock_locator.screenshot = AsyncMock()

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.locator = MagicMock(return_value=mock_locator)

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw = MagicMock()
        mock_pw.chromium = mock_chromium

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "src.content.screenshot.async_playwright",
            return_value=mock_pw_ctx,
        ), patch.dict("os.environ", {"DASHBOARD_URL": "https://my-app.vercel.app"}):
            paths = await capture_angle_screenshots(
                "leaderboard_shakeup",
                output_dir=str(tmp_path),
            )

        # Verify it used the env var URL
        goto_url = mock_page.goto.call_args_list[0].args[0]
        assert goto_url.startswith("https://my-app.vercel.app")
