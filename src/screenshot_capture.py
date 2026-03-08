"""Dashboard screenshot capture for wallet spotlight posts.

Uses Playwright to take headless screenshots of the live Vercel dashboard.
Replaces the matplotlib chart_generator with real dashboard visuals.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

# Default viewport: wide enough for desktop layout (leaderboard needs it)
VIEWPORT = {"width": 1440, "height": 900}

# Timeout for waiting on data-loading elements (ms)
WAIT_TIMEOUT = 30_000


async def capture_screenshots(
    payload_path: str,
    output_dir: str,
    dashboard_url: str | None = None,
) -> list[str]:
    """Capture 3 dashboard screenshots and save as PNGs.

    Returns list of output file paths:
      - leaderboard_top5.png
      - trader_radar.png
      - trader_positions.png
    """
    url = dashboard_url or os.environ.get(
        "DASHBOARD_URL", "https://hyper-strategies-pnl-vercel.vercel.app"
    )
    url = url.rstrip("/")

    with open(payload_path) as f:
        payload = json.load(f)

    address = payload["wallet"]["address"]
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport=VIEWPORT)

        # --- Screenshot 1: Leaderboard top 5 ---
        await page.goto(f"{url}/leaderboard", wait_until="networkidle")
        await page.wait_for_selector(
            '[data-testid="leaderboard-table"]', timeout=WAIT_TIMEOUT
        )
        leaderboard_path = str(out / "leaderboard_top5.png")
        table = page.locator('[data-testid="leaderboard-table"]')
        await table.screenshot(path=leaderboard_path)
        paths.append(leaderboard_path)

        # --- Navigate to trader deep dive ---
        await page.goto(
            f"{url}/traders/{address}", wait_until="networkidle"
        )

        # --- Screenshot 2: Radar chart + metrics ---
        await page.wait_for_selector(
            '[data-testid="trader-radar"]', timeout=WAIT_TIMEOUT
        )
        radar_path = str(out / "trader_radar.png")
        radar = page.locator('[data-testid="trader-radar"]')
        await radar.screenshot(path=radar_path)
        paths.append(radar_path)

        # --- Screenshot 3: Trader overview (header + metrics + positions) ---
        await page.wait_for_selector(
            '[data-testid="trader-overview"]', timeout=WAIT_TIMEOUT
        )
        overview_path = str(out / "trader_positions.png")
        overview = page.locator('[data-testid="trader-overview"]')
        await overview.screenshot(path=overview_path)
        paths.append(overview_path)

        await browser.close()

    return paths


# ── CLI entry-point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    payload_path = Path(__file__).resolve().parent.parent / "data" / "content_payload.json"
    chart_dir = Path(__file__).resolve().parent.parent / "data" / "charts"

    paths = asyncio.run(
        capture_screenshots(
            payload_path=str(payload_path),
            output_dir=str(chart_dir),
        )
    )
    for p in paths:
        print(f"Captured: {p}")
