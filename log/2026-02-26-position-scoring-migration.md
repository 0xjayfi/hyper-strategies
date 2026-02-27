# Position-Based Scoring Migration & Frontend Overhaul

**Date:** 2026-02-26
**Branch:** `feat/pnl-weighted` merged to `main`
**Scope:** 32 files changed, +3,261 / -295 lines, 283 tests passing

---

## What Changed

Migrated the entire scoring/allocation pipeline from **trade-based** (fetching historical trades per trader) to **position-based** (analyzing hourly position snapshots). This eliminates the slowest, most rate-limited API calls (7s per request) and replaces them with fast position endpoint calls. Also overhauled the frontend with Nansen branding and fixed 4 production bugs.

---

## 1. Position-Based Scoring Engine (9 Tasks)

### New Core Modules

| File | Purpose |
|------|---------|
| `src/position_metrics.py` | Computes 7 metrics from position snapshots: account growth, max drawdown, effective leverage, liquidation distance, position diversity (HHI), consistency, deposit/withdrawal detection |
| `src/position_scoring.py` | 6-component composite score with normalization, smart money bonus (1.05-1.10x), recency decay (168h half-life) |

### Score Components

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| Account Growth | 30% | Portfolio value change over time (deposit/withdrawal adjusted) |
| Drawdown | 20% | Maximum peak-to-trough decline |
| Leverage | 15% | Average effective leverage (lower = better, penalty above 10x) |
| Liquidation Distance | 15% | How close positions get to liquidation |
| Diversity | 10% | HHI across token positions (more diversified = better) |
| Consistency | 10% | Ratio of positive-growth snapshots |

### Scheduler Rewrite (`src/scheduler.py`)

Replaced `full_recompute_cycle` (trade-based, ~2h per cycle) with `position_scoring_cycle` (position-based, ~5min per cycle).

**New schedule:**
- Every 60 min: Position sweep (fetch open positions for all tracked traders)
- Every 60 min: Position scoring cycle (compute metrics → score → filter → allocate)
- Every 24h: Leaderboard refresh (top 100 traders, 2 pages)
- Every 24h: DB cleanup (stale data)

**Old schedule (removed):**
- Every 6h: Full recompute (fetch trades → metrics → score → allocate) — slow, rate-limited
- Every 15min: Position monitor — replaced by hourly sweep

### Supporting Changes

| File | Change |
|------|--------|
| `src/datastore.py` | Added `get_position_snapshot_series()`, `get_account_value_series()`, `get_latest_allocation_timestamp()` |
| `src/nansen_client.py` | Split into 3 rate limiters: leaderboard (20/s), position (5/s), trade (1/s, 7s interval) |
| `src/filters.py` | Added `is_position_eligible()` with configurable gates |
| `src/config.py` | Added position filter thresholds, scheduling intervals, split rate limiter configs |
| `backend/main.py` | Scheduler now runs as `asyncio.create_task()` inside FastAPI lifespan |

### Execution Strategy

Used **parallelized subagents in git worktrees** for isolation:

- **Wave 1** (6 agents): Tasks 1-5 + Task 8 (independent modules)
- **Wave 2** (2 agents): Tasks 6 + 9 (scoring cycle + E2E test)
- **Wave 3** (1 agent): Task 7 (scheduler integration into FastAPI)

One merge conflict (Tasks 1 & 5 both modified `config.py`) — resolved manually.

### Test Coverage

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_position_metrics.py` | 15 | All 8 metric functions + deposit detection |
| `test_position_scoring.py` | 16 | All 6 normalizers + smart money + recency decay |
| `test_position_pipeline.py` | 2 | End-to-end: metrics → scoring → filter → allocate |
| `test_filters.py` | +5 | `is_position_eligible()` gates |
| `test_datastore.py` | +3 | Snapshot series queries |
| `test_rate_limiter.py` | +4 | Split rate limiter routing |

---

## 2. Production Bug Fixes (4 Issues)

| Bug | Severity | Root Cause | Fix |
|-----|----------|-----------|-----|
| SQLite thread safety | Critical | `sqlite3.ProgrammingError` when scheduler (asyncio) and FastAPI (uvicorn threads) share same DB connection | Added `check_same_thread=False` to `sqlite3.connect()` |
| Leaderboard shows 50 not 100 | Medium | Default `limit` param was 50 | Changed to 100, matching `LEADERBOARD_TOP_N` config |
| Directional exposure cap exceeded | Medium | Short exposure 87.85% > 60% max with no enforcement | Added `cap_violations` advisory list to `/api/v1/allocations` response + `CapViolation` schema |
| `computed_at` null on allocations | Low | `_build_allocations_from_db()` returned `None` for timestamp | Added `get_latest_allocation_timestamp()` to DataStore |

---

## 3. Frontend Overhaul (12 files)

### Nansen Branding

Applied colors from `ai_docs/NansenBrandGuidelines.pdf`:

| Variable | Old | New |
|----------|-----|-----|
| `--color-surface` | `#0d1117` | `#0A0A0A` (Nansen Black) |
| `--color-card` | `#161b22` | `#1B1B1B` (Nansen Grey 14) |
| `--color-border` | `#30363d` | `#2D2D2D` (Nansen Grey 13) |
| `--color-green` | `#3fb950` | `#00FFA7` (Nansen Primary Green) |
| `--color-red` | `#f85149` | `#FF004B` (Nansen Red) |
| `--color-accent` | `#58a6ff` | `#00FFA7` (Nansen Primary Green) |
| Font | system stack | Inter (400, 500, 600, 700) |

### New Landing Page

`frontend/src/pages/LandingPage.tsx` — standalone page at `/` (no sidebar):
- Animated NansenIcon compass with pulse effect
- "Hyper Signals" title + tagline
- 4 feature cards linking to Market, Leaderboard, Allocations, Assess
- "Powered by Nansen" footer
- Mobile-responsive (cards stack vertically on phones)

### Route Changes

| Route | Before | After |
|-------|--------|-------|
| `/` | Market Overview | Landing Page |
| `/market` | (none) | Market Overview |

Keyboard shortcut `1` updated to `/market`. Sidebar + MobileNav logo changed from `BarChart3` to `NansenIcon` compass in `#00FFA7`.

### Simplified Page Descriptions

Removed multi-paragraph technical descriptions (endpoint names, data flow, implementation details) from all pages. Replaced with 1-2 sentence user-facing descriptions.

### Enhanced Refresh Indicator

- Progress bar: 0.5px shimmer → 2px pulsing Nansen green bar
- Added "Syncing data..." animated text next to "Updated X minutes ago" during refresh

---

## Final State

- **283 tests passing** (44s)
- **Frontend build clean** (zero errors, 3.14s)
- **Backend deployed** on tmux `hyper-dashboard`
- **Tunnel URL:** `https://player-courage-flower-pond.trycloudflare.com`
- **Vercel:** auto-deployed from `main` (update `VITE_API_URL` to new tunnel URL)
- **Scheduler running:** hourly position sweeps + scoring cycles, daily leaderboard refresh
