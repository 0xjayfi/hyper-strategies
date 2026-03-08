# Dashboard Screenshot Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace matplotlib chart generation with Playwright screenshots of the live Vercel dashboard for authentic social media visuals.

**Architecture:** New `src/screenshot_capture.py` module launches headless Chromium, navigates to the Vercel dashboard, and captures 3 cropped screenshots (leaderboard top 5, trader radar+metrics, trader positions). Output goes to `data/charts/` — same path convention as before so downstream pipeline (writer agents, Typefully upload) works unchanged.

**Tech Stack:** Playwright (Python), headless Chromium

---

### Task 1: Add Playwright Dependency

**Files:**
- Modify: `pyproject.toml:7` (dependencies array)
- Modify: `.env.example` (add DASHBOARD_URL)

**Step 1: Add playwright to pyproject.toml dependencies**

In `pyproject.toml`, add `"playwright>=1.40"` to the `dependencies` list:

```toml
dependencies = [
    "pydantic>=2.0",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "numpy>=1.26",
    "matplotlib>=3.8",
    "aiosqlite>=0.20",
    "playwright>=1.40",
]
```

**Step 2: Add DASHBOARD_URL to .env.example**

Append to `.env.example`:

```
# Dashboard URL for screenshot capture (Vercel frontend)
DASHBOARD_URL=https://hyper-strategies-pnl-vercel.vercel.app
```

Also add to your actual `.env` file with the same value.

**Step 3: Install playwright and browser**

Run:
```bash
pip install playwright
playwright install chromium
```

Expected: Downloads Chromium binary (~150MB), prints install path.

**Step 4: Commit**

```bash
git add pyproject.toml .env.example
git commit -m "chore: add playwright dependency and DASHBOARD_URL config"
```

---

### Task 2: Add data-testid Attributes to Frontend Components

The screenshot module needs stable selectors to crop specific sections. Add `data-testid` attributes to the leaderboard table and trader deep dive sections.

**Files:**
- Modify: `frontend/src/components/leaderboard/LeaderboardTable.tsx`
- Modify: `frontend/src/pages/TraderDeepDive.tsx`
- Modify: `frontend/src/components/leaderboard/ScoreRadarChart.tsx`

**Step 1: Add data-testid to LeaderboardTable**

In `frontend/src/components/leaderboard/LeaderboardTable.tsx`, on the outer `<div>` of the table (line 164):

```tsx
<div className="overflow-x-auto rounded-lg border border-border" data-testid="leaderboard-table">
```

**Step 2: Add data-testid to TraderDeepDive sections**

In `frontend/src/pages/TraderDeepDive.tsx`:

Around the radar chart (line 169), wrap it with an identifiable div:

```tsx
{trader.score_growth != null && (
  <div data-testid="trader-radar">
    <ScoreRadarChart
      scoreBreakdown={{
        growth: trader.score_growth ?? 0,
        drawdown: trader.score_drawdown ?? 0,
        leverage: trader.score_leverage ?? 0,
        liq_distance: trader.score_liq_distance ?? 0,
        diversity: trader.score_diversity ?? 0,
        consistency: trader.score_consistency ?? 0,
      }}
    />
  </div>
)}
```

Around the TraderHeader + MetricsCards + PositionsTable block (lines 142-150), add a wrapper:

```tsx
) : trader ? (
  <div data-testid="trader-overview">
    <div className="space-y-4">
      <TraderHeader trader={trader} />
      {trader.metrics && <MetricsCards metrics={trader.metrics} />}
      <PositionsTable positions={trader.positions} />
    </div>
  </div>
) : null}
```

**Step 3: Rebuild frontend**

Run:
```bash
cd frontend && npm run build
```

Expected: Clean build, no errors.

**Step 4: Commit**

```bash
git add frontend/src/components/leaderboard/LeaderboardTable.tsx frontend/src/pages/TraderDeepDive.tsx
git commit -m "feat: add data-testid attributes for screenshot selectors"
```

---

### Task 3: Write the Screenshot Capture Module — Test First

**Files:**
- Create: `tests/test_screenshot_capture.py`

**Step 1: Write failing tests**

```python
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

    # Make locator().screenshot() write a dummy file
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_screenshot_capture.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.screenshot_capture'`

**Step 3: Commit**

```bash
git add tests/test_screenshot_capture.py
git commit -m "test: add screenshot capture tests (red)"
```

---

### Task 4: Implement the Screenshot Capture Module

**Files:**
- Create: `src/screenshot_capture.py`

**Step 1: Write the implementation**

```python
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
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/test_screenshot_capture.py -v`

Expected: 2 tests PASS.

**Step 3: Commit**

```bash
git add src/screenshot_capture.py
git commit -m "feat: add Playwright screenshot capture module"
```

---

### Task 5: Update the Pipeline Runner Script

**Files:**
- Modify: `scripts/run-content-pipeline.sh:35-38`

**Step 1: Replace chart_generator with screenshot_capture**

In `scripts/run-content-pipeline.sh`, replace:

```bash
echo "[$(date -u)] Post-worthy content detected. Generating charts..."

# Step 3: Generate charts
python -m src.chart_generator

echo "[$(date -u)] Charts generated. Launching Claude Code writer team..."
```

With:

```bash
echo "[$(date -u)] Post-worthy content detected. Capturing dashboard screenshots..."

# Step 3: Capture dashboard screenshots
python -m src.screenshot_capture

echo "[$(date -u)] Screenshots captured. Launching Claude Code writer team..."
```

**Step 2: Commit**

```bash
git add scripts/run-content-pipeline.sh
git commit -m "feat: switch pipeline runner from chart_generator to screenshot_capture"
```

---

### Task 6: Update the Content Prompt for Writer Agents

**Files:**
- Modify: `scripts/content-prompt.md`

**Step 1: Update chart references to screenshot references**

In `scripts/content-prompt.md`, update these sections:

In **Step 1** (line 12), change:
```
Also list the PNG files in `data/charts/` to know what visuals are available.
```
To:
```
Also list the PNG files in `data/charts/` to see the dashboard screenshots available. These are real screenshots from the live dashboard, not generated charts. The files are:
- `leaderboard_top5.png` — Top 5 traders on the leaderboard
- `trader_radar.png` — The spotlight wallet's 6-dimension radar chart
- `trader_positions.png` — The spotlight wallet's header, metrics, and current positions
```

In **Agent 1: Drafter** (line 52), change:
```
Also decide which chart files from data/charts/ should attach to which tweet.
```
To:
```
Also decide which dashboard screenshots from data/charts/ should attach to which tweet. These are real screenshots from the live dashboard. Attach the most relevant ones — typically trader_positions.png with the position-focused tweet and trader_radar.png or leaderboard_top5.png with the score/ranking tweet.
```

In the JSON output format (line 56), change:
```json
{"tweets": [{"text": "...", "chart": "filename.png or null"}], "style_used": "..."}
```
To:
```json
{"tweets": [{"text": "...", "screenshot": "filename.png or null"}], "style_used": "..."}
```

In **Agent 4a: Fact & Data Reviewer** (line 109), change:
```
- Are the chart filenames valid (exist in data/charts/)?
```
To:
```
- Are the screenshot filenames valid? Expected files: leaderboard_top5.png, trader_radar.png, trader_positions.png
```

**Step 2: Commit**

```bash
git add scripts/content-prompt.md
git commit -m "docs: update content prompt to reference dashboard screenshots"
```

---

### Task 7: Delete the Old Chart Generator

**Files:**
- Delete: `src/chart_generator.py`

**Step 1: Remove the file**

```bash
git rm src/chart_generator.py
```

**Step 2: Check for any remaining imports/references**

Run: `grep -r "chart_generator" --include="*.py" --include="*.sh" --include="*.md" .`

Expected: No hits except in the plan files under `docs/plans/`. If there are hits in source files, update them.

**Step 3: Commit**

```bash
git commit -m "chore: remove old matplotlib chart_generator"
```

---

### Task 8: Rebuild Frontend and Push

The `data-testid` attributes from Task 2 need to be deployed to Vercel for the screenshot module to work.

**Files:**
- No new files — just build and deploy

**Step 1: Rebuild frontend**

```bash
cd frontend && npm run build
```

Expected: Clean build.

**Step 2: Commit, push, and merge to main**

```bash
git add -A
git push origin feat/pnl-weighted
```

Then merge to main:
```bash
cd /home/jsong407/hyper-strategies && git pull origin main && git merge feat/pnl-weighted && git push origin main
```

Vercel will auto-deploy from main. Wait for deployment to complete before running the screenshot module.

**Step 3: Verify Vercel deployment**

Visit the Vercel dashboard or check:
```bash
curl -s https://hyper-strategies-pnl-vercel.vercel.app/leaderboard | head -5
```

Expected: HTML response (the SPA shell).

---

### Task 9: End-to-End Smoke Test

**Step 1: Verify a content payload exists**

```bash
cat data/content_payload.json | python -c "import sys,json; d=json.load(sys.stdin); print(d['post_worthy'], d['wallet']['address'])"
```

If no payload exists, generate one:
```bash
python -m src.content_pipeline
```

**Step 2: Run screenshot capture manually**

```bash
python -m src.screenshot_capture
```

Expected output:
```
Captured: /home/jsong407/hyper-strategies-pnl-weighted/data/charts/leaderboard_top5.png
Captured: /home/jsong407/hyper-strategies-pnl-weighted/data/charts/trader_radar.png
Captured: /home/jsong407/hyper-strategies-pnl-weighted/data/charts/trader_positions.png
```

**Step 3: Visually inspect the screenshots**

```bash
ls -la data/charts/*.png
```

Each file should be >10KB (a real screenshot, not empty). Open them to verify they show the correct dashboard sections.

**Step 4: Commit any final adjustments**

```bash
git add -A
git commit -m "chore: verify screenshot pipeline end-to-end"
```
