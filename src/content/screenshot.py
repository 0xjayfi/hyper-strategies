"""Angle-aware dashboard screenshot capture.

Reads a content angle's ScreenshotConfig and captures each PageCapture
to the output directory using Playwright.

Usage:
    python -m src.content.screenshot wallet_spotlight
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from playwright.async_api import async_playwright

from src.content.angles import ALL_ANGLES

logger = logging.getLogger(__name__)

# Default viewport: wide enough for desktop layout
VIEWPORT = {"width": 1440, "height": 900}

# Timeout for waiting on data-loading elements (ms)
WAIT_TIMEOUT = 60_000

# Extra settle time after selector appears to let child components render (ms)
SETTLE_MS = 3_000


async def capture_angle_screenshots(
    angle_type: str,
    output_dir: str = "data/charts",
    dashboard_url: str | None = None,
) -> list[str]:
    """Capture screenshots for a given content angle.

    Looks up the angle from ALL_ANGLES, reads its ScreenshotConfig, and
    captures each PageCapture to *output_dir* using headless Playwright.

    Returns a list of output file paths.
    """
    # Look up angle by angle_type
    angle = None
    for a in ALL_ANGLES:
        if a.angle_type == angle_type:
            angle = a
            break

    if angle is None:
        raise ValueError(
            f"Unknown angle_type {angle_type!r}. "
            f"Available: {[a.angle_type for a in ALL_ANGLES]}"
        )

    # Hydrate angle state from saved payload (needed for angles whose
    # screenshot_config depends on detection state, e.g. wallet address).
    payload_path = Path(f"data/content_payload_{angle_type}.json")
    if payload_path.exists():
        with open(payload_path) as f:
            angle.load_payload(json.load(f))

    config = angle.screenshot_config()

    url = dashboard_url or os.environ.get(
        "DASHBOARD_URL", "http://localhost:5173"
    )
    url = url.rstrip("/")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport=VIEWPORT)

        for pc in config.pages:
            target_url = f"{url}{pc.route}"
            logger.info("Navigating to %s", target_url)
            await page.goto(target_url, wait_until="domcontentloaded")

            await page.wait_for_selector(
                pc.wait_selector, timeout=WAIT_TIMEOUT
            )
            await page.wait_for_timeout(SETTLE_MS)

            if pc.pre_capture_js:
                await page.evaluate(pc.pre_capture_js)

            output_path = str(out / pc.filename)
            locator = page.locator(pc.capture_selector)
            await locator.screenshot(path=output_path)
            paths.append(output_path)
            logger.info("Captured %s", output_path)

        await browser.close()

    return paths


# ── CLI entry-point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys

    angle_type = sys.argv[1]
    paths = asyncio.run(capture_angle_screenshots(angle_type))
    for p in paths:
        print(f"Captured: {p}")
