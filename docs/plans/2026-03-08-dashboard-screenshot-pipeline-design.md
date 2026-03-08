# Dashboard Screenshot Pipeline Design

## Problem

The current content pipeline generates charts via matplotlib (`src/chart_generator.py`) — radar, heatmap, delta bars, etc. These look synthetic and don't match the real dashboard. We want to replace them with actual screenshots from the live Vercel-hosted dashboard for more authentic, professional social media posts.

## Approach

Replace `src/chart_generator.py` with a new `src/screenshot_capture.py` module that uses Playwright to capture real dashboard screenshots from the Vercel frontend. Everything downstream (writer agents, Typefully upload) stays the same — PNGs land in `data/charts/` with the same conventions.

## Screenshots Captured

For each pipeline run, capture **3 images**:

1. **`leaderboard_top5.png`** — Leaderboard page, cropped to the top 5 rows of the table
2. **`trader_radar.png`** — Trader Deep Dive page for the spotlight wallet, cropped to the radar chart + metrics cards section
3. **`trader_positions.png`** — Same page, cropped to the current positions table

## Flow

```
content_pipeline.py detects mover → wallet address known
    ↓
screenshot_capture.py runs:
    1. Launch headless Chromium via Playwright
    2. Navigate to {DASHBOARD_URL}/leaderboard
    3. Wait for table rows to render, screenshot top 5 rows
    4. Navigate to {DASHBOARD_URL}/traders/{address}
    5. Wait for radar + metrics + positions to render (skip PnL curve / trade history)
    6. Screenshot radar+metrics section
    7. Screenshot positions table section
    8. Save all 3 to data/charts/
    ↓
Writer agents reference these PNGs in the thread
    ↓
Typefully client uploads them as before
```

## Config

- `DASHBOARD_URL` env var — stable Vercel domain
- Element selectors for cropping based on existing component DOM structure

## Changes

- **Delete**: `src/chart_generator.py` (matplotlib charts)
- **New**: `src/screenshot_capture.py` (Playwright captures)
- **Update**: `scripts/run-content-pipeline.sh` — replace `python -m src.chart_generator` with `python -m src.screenshot_capture`
- **Update**: `scripts/content-prompt.md` — update chart references to describe dashboard screenshots instead

## Dependencies

- Add `playwright` to requirements
- One-time `playwright install chromium` on the server

## What Stays the Same

- `src/content_pipeline.py` — mover detection unchanged
- `src/typefully_client.py` — upload logic unchanged
- `scripts/content-prompt.md` — writer agent team structure unchanged (just update image descriptions)
- `x_writer/writing_style.md` — style rules unchanged
- Output path `data/charts/` — same directory, same PNG convention
