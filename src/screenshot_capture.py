"""Dashboard screenshot capture for wallet spotlight posts.

Uses Playwright to take headless screenshots of the live Vercel dashboard.
Replaces the old matplotlib charts with real dashboard visuals.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

# Default viewport: wide enough for desktop layout (leaderboard needs it)
VIEWPORT = {"width": 1440, "height": 900}

# Timeout for waiting on data-loading elements (ms)
WAIT_TIMEOUT = 60_000

# Extra settle time after selector appears to let child components render (ms)
SETTLE_MS = 3_000


async def capture_screenshots(
    payload_path: str,
    output_dir: str,
    dashboard_url: str | None = None,
) -> list[str]:
    """Capture 3 dashboard screenshots and save as PNGs.

    Returns list of output file paths:
      - leaderboard_top5.png
      - trader_scoring.png   (radar + score breakdown + allocation history)
      - trader_positions.png (header + top positions, no metrics cards)
    """
    url = dashboard_url or os.environ.get(
        "DASHBOARD_URL", "http://localhost:5173"
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
        await page.goto(f"{url}/leaderboard", wait_until="domcontentloaded")
        await page.wait_for_selector(
            '[data-testid="leaderboard-table"]', timeout=WAIT_TIMEOUT
        )
        await page.wait_for_timeout(SETTLE_MS)

        # Hide rows beyond top 5 so screenshot only shows the top traders
        await page.evaluate("""
            const table = document.querySelector('[data-testid="leaderboard-table"]');
            if (table) {
                const rows = table.querySelectorAll('tbody tr');
                rows.forEach((row, i) => { if (i >= 5) row.style.display = 'none'; });
            }
        """)

        leaderboard_path = str(out / "leaderboard_top5.png")
        table = page.locator('[data-testid="leaderboard-table"]')
        await table.screenshot(path=leaderboard_path)
        paths.append(leaderboard_path)

        # --- Navigate to trader deep dive ---
        await page.goto(
            f"{url}/traders/{address}", wait_until="domcontentloaded"
        )

        # --- Screenshot 2: Full scoring region (radar + breakdown + allocation) ---
        await page.wait_for_selector(
            '[data-testid="trader-scoring"]', timeout=WAIT_TIMEOUT
        )
        await page.wait_for_timeout(SETTLE_MS)
        scoring_path = str(out / "trader_scoring.png")
        scoring = page.locator('[data-testid="trader-scoring"]')
        await scoring.screenshot(path=scoring_path)
        paths.append(scoring_path)

        # --- Screenshot 3: Trader header + top positions (no metrics cards) ---
        await page.wait_for_selector(
            '[data-testid="trader-overview"]', timeout=WAIT_TIMEOUT
        )
        await page.wait_for_timeout(SETTLE_MS)

        # Hide MetricsCards grid and limit visible position rows to top 12
        await page.evaluate("""
            const overview = document.querySelector('[data-testid="trader-overview"]');
            if (overview) {
                // Hide the 3-column metrics grid (7d/30d/90d cards)
                const metricsGrid = overview.querySelector('[class*="sm:grid-cols-3"]');
                if (metricsGrid) metricsGrid.style.display = 'none';
                // Limit position table rows to first 12
                const rows = overview.querySelectorAll('table tbody tr');
                rows.forEach((row, i) => { if (i >= 12) row.style.display = 'none'; });
            }
        """)

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
