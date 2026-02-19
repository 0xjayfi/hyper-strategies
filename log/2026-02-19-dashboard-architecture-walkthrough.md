# Dashboard Architecture Walkthrough

**Date:** 2026-02-19
**Session focus:** Understanding the 4 dashboard pages, debugging leaderboard 500 error, tracing data sources

---

## 1. Four Dashboard Pages — Workflows

### 1.1 Market Overview

**Frontend:** `frontend/src/pages/MarketOverview.tsx`
**Backend:** `GET /api/v1/market-overview` → `backend/routers/market.py`
**Data source:** Live Nansen API (not DB)

**Workflow:**
- Fires concurrent Nansen requests for 4 tokens (BTC, ETH, SOL, HYPE): `smart_money` + `all_traders` perp positions per token, plus perp screener for funding/OI/volume
- Aggregates per-token: L/S ratio, total position value, top trader (by size), funding rate, OI, 24h volume
- Computes **smart money consensus** per token — direction (Bullish/Bearish/Neutral) and confidence % based on smart money long vs short value
- Computes **aggregate smart money flow** across all tokens (net long/short USD + direction)

**UI renders:** Token cards grid, consensus indicator chips, smart money flow summary bar
**Auto-refresh:** Every 5 minutes (positions interval, 60s stale)

---

### 1.2 Position Explorer

**Frontend:** `frontend/src/pages/PositionExplorer.tsx`
**Backend:** `GET /api/v1/positions?token=X&label_type=Y&side=Z` → `backend/routers/positions.py`
**Data source:** Live Nansen API (`fetch_token_perp_positions`)

**Workflow:**
- User selects token (default BTC), optionally filters by side (Long/Short) and smart money toggle
- Fetches up to 100 positions from Nansen, cached by TTL (5min)
- Server-side filters by side and min position USD, truncates to limit
- Computes meta stats: total long value, total short value, L/S ratio, smart money count
- Each position: address, label, side, size, leverage, entry/mark/liquidation prices, funding, uPnL

**UI renders:** Filter bar, meta summary strip, sortable position table with expandable row details
**Auto-refresh:** Every 5 minutes

---

### 1.3 Trader Leaderboard

**Frontend:** `frontend/src/pages/TraderLeaderboard.tsx`
**Backend:** `GET /api/v1/leaderboard?timeframe=X&token=Y&sort_by=Z` → `backend/routers/leaderboard.py`
**Data source:** Dual-source (DB first, Nansen fallback)

**Workflow — Path 1 (DataStore, preferred):**
- If the allocation engine has run, pulls from SQLite: computed scores, metrics (win rate, profit factor, trade count, PnL, ROI), allocation weights, anti-luck status
- Sorts by score (default), PnL, or ROI

**Workflow — Path 2 (Nansen fallback):**
- If no DataStore scores exist, falls back to Nansen leaderboard/PnL-leaderboard endpoints

**Features:**
- Timeframe toggle (7d/30d/90d) and token filter (All/BTC/ETH/SOL/HYPE)
- Selecting a trader row shows a radar chart sidebar (ROI, Sharpe, win rate, consistency, smart money, risk management)
- Info banner prompts to run allocation engine if no scores available

**Auto-refresh:** Every 1 hour (5min stale)

---

### 1.4 Allocation Dashboard

**Frontend:** `frontend/src/pages/AllocationDashboard.tsx`
**Backend:** Two endpoints called in parallel:
- `GET /api/v1/allocations` → `backend/routers/allocations.py`
- `GET /api/v1/allocations/strategies` → same router

**Data source:** SQLite DB only (no Nansen calls). Falls back to mock data if DB is empty.

**Six UI components (see detailed breakdown below)**
**Auto-refresh:** Every 1 hour

---

## 2. Allocation Dashboard — Card-by-Card Breakdown

### 2.1 Allocation Weights (Donut Chart)

**Component:** `frontend/src/components/allocation/WeightsDonut.tsx`
**Data:** `allocations` array from `GET /api/v1/allocations`

- Each slice = one trader, sized by their `weight` (softmax output from scoring engine)
- Labels from Nansen (or truncated `0x...` if no label)
- Hover tooltip shows weight as percentage
- Center text shows total trader count
- Legend below lists every trader with color dot + weight %
- Weights are raw output of `softmax(scores, T=2.0)`, sum to 1.0

### 2.2 Risk Caps (4 Gauge Bars)

**Component:** `frontend/src/components/allocation/RiskGauges.tsx`
**Data:** `risk_caps` object from `GET /api/v1/allocations`

Four horizontal progress bars showing proximity to safety limits from `src/config.py`:

| Gauge | `current` | `max` (from config) | Format |
|---|---|---|---|
| Position Count | number of allocated traders | `MAX_TOTAL_POSITIONS` | integer |
| Max Token Exposure | single largest trader weight | `MAX_EXPOSURE_PER_TOKEN` | percentage |
| Long Directional | estimated long exposure (total_weight * 0.5) | `MAX_LONG_EXPOSURE` | percentage |
| Short Directional | estimated short exposure (total_weight * 0.5) | `MAX_SHORT_EXPOSURE` | percentage |

Color coding: Green (<70%), Yellow (70-90%), Red (>=90%)

**Caveat:** Long/short directional values are estimated as naive 50/50 split. Placeholder until real directional exposure is aggregated from position snapshots.

### 2.3 Allocation Over Time (Stacked Area Chart)

**Component:** `frontend/src/components/allocation/AllocationTimeline.tsx`
**Data:** Same `allocations` array

- Currently only has **one data point** (current snapshot)
- Note at bottom: "Historical data will be available after multiple allocation cycles"
- Becomes useful once multiple allocation snapshots are stored and queried over time

### 2.4 Index Portfolio (Tab 1)

**Component:** `frontend/src/components/allocation/IndexPortfolioTable.tsx`
**Data:** `index_portfolio` from `GET /api/v1/allocations/strategies`

Answers: "If I followed all tracked traders proportionally, what would my combined portfolio look like?"

- Columns: Token | Side (Long/Short) | Target Weight | Target USD
- Built by `strategy_interface.build_index_portfolio(allocations, trader_positions, account_value=$100k)`
- Weight-averages all trader positions by allocation weight
- Footer shows total weight (~100%) and total USD
- Falls back to mock data if no position snapshots exist

### 2.5 Consensus (Tab 2)

**Component:** `frontend/src/components/allocation/ConsensusCards.tsx`
**Data:** `consensus` from `GET /api/v1/allocations/strategies`

One card per token showing weight-weighted directional vote:

- **Direction** — "Long" or "Short" (whichever side has more weight-weighted votes)
- **Arrow icon** — green up for Long, red down for Short
- **Confidence bar** — `max(long_weight, short_weight) / total_weight`
- **Voter count** — number of allocated traders holding position in this token
- Built by `strategy_interface.weighted_consensus(token, allocations, trader_positions)`

### 2.6 Sizing Calculator (Tab 3)

**Component:** `frontend/src/components/allocation/SizingCalculator.tsx`
**Data:** `sizing_params` from `GET /api/v1/allocations/strategies`

Interactive calculator for position sizing:

- **Inputs:** Trader dropdown + Account Value (default $100k)
- **Outputs:**
  - Weight — trader's softmax allocation weight
  - ROI Tier Multiplier — from scoring engine (0.5x, 0.75x, 1.0x, or 1.25x)
  - Max Size (API) — pre-computed `weight * $100k`
  - Computed Position (highlighted) — `accountValue * weight * roi_tier` (live recalculation)

---

## 3. Bug Fix: Leaderboard 500 Internal Server Error

**Root cause:** `profit_factor = inf` for traders with `gross_loss = 0` (never lost a trade).

**Chain of failure:**
1. `_build_datastore_leaderboard()` reads metrics from DB
2. Some traders have `gross_loss = 0` → `profit_factor = gross_profit / 0 = inf`
3. Pydantic's `model_dump()` preserves `inf` as Python float
4. FastAPI's `JSONResponse` calls `json.dumps()` which rejects `inf` → 500 error

**Fix applied** in `backend/routers/leaderboard.py:51-52`:
```python
# Before:
profit_factor = metrics.profit_factor if metrics else None

# After:
pf = metrics.profit_factor if metrics else None
profit_factor = pf if pf is not None and pf != float("inf") else None
```

---

## 4. Data Sources — Where Everything Comes From

### The Allocation Dashboard makes ZERO Nansen API calls. It reads entirely from SQLite.

**DB location:** `data/pnl_weighted.db`
**Populated by:** Scheduler runs between Feb 13 – Feb 17

| Table | Rows | Date Range | What fills it |
|---|---|---|---|
| `traders` | 51 | — | Scheduler via Nansen Leaderboard API |
| `leaderboard_snapshots` | 590 | Feb 13 – Feb 17 | Scheduler via Nansen Leaderboard API |
| `trade_metrics` | 643 | Feb 13 – Feb 17 | Scheduler via Nansen Address Perp Trades API → local computation |
| `trader_scores` | 456 | Feb 16 – Feb 17 | Scoring engine (pure local math, no API) |
| `position_snapshots` | 37,252 | Feb 16 – Feb 17 | Scheduler via Nansen Token Perp Positions API |
| `allocations` | 19 | Feb 17 (3 batches) | Allocation engine (pure local softmax, no API) |

### Per-endpoint data flow:

- **Weights Donut + Risk Caps** → `allocations` + `trader_scores` + `traders` tables. No Nansen calls.
- **Allocation Over Time** → Same as above, currently single data point.
- **Index Portfolio + Consensus + Sizing** → `allocations` + `position_snapshots` → local `strategy_interface` functions. No Nansen calls.

---

## 5. Running the Project — 3 Processes

```
┌─────────────────────────────────────────────────────────┐
│  Terminal 1: SCHEDULER (background, long-running)       │
│                                                         │
│  Option A (one-shot):                                   │
│    python scripts/stage6_scheduler_cycle.py \           │
│      --db data/pnl_weighted.db                          │
│                                                         │
│  Option B (continuous loop via src/scheduler.py):       │
│    Calls Nansen API → writes to SQLite DB               │
│    Schedule:                                            │
│      - Every 24h: leaderboard refresh                   │
│      - Every 6h:  full recompute (metrics→scores→alloc) │
│      - Every 15min: position monitoring                 │
│      - Every 24h: DB cleanup                            │
└────────────────────────┬────────────────────────────────┘
                         │ writes to
                         ▼
                  ┌──────────────┐
                  │  SQLite DB   │
                  │  data/       │
                  │  pnl_weighted│
                  │  .db         │
                  └──────┬───────┘
                         │ reads from
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Terminal 2: BACKEND API SERVER                         │
│  python backend/run.py                                  │
│                                                         │
│  FastAPI on :8000                                       │
│  - Market Overview & Position Explorer: live Nansen API │
│  - Leaderboard & Allocations: reads from SQLite DB      │
└────────────────────────┬────────────────────────────────┘
                         │ serves JSON to
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Terminal 3: FRONTEND DEV SERVER                        │
│  cd frontend && npm run dev                             │
│                                                         │
│  Vite on :5173                                          │
│  React Query auto-polls:                                │
│    - Positions/Market: every 5 minutes                  │
│    - Leaderboard/Allocations: every 1 hour              │
└─────────────────────────────────────────────────────────┘
```

### Scheduler pipeline (what happens each cycle):

```
Nansen Leaderboard API ──→ leaderboard_snapshots table
                               │
                               ▼
                        traders table (upsert)
                               │
Nansen Address Perp Trades ──→ trade_metrics table
                               │ (win_rate, profit_factor, sharpe, etc.)
                               ▼
Nansen Token Perp Positions ──→ position_snapshots table
                               │
                               ▼
              Scoring engine (local math) ──→ trader_scores table
                               │
                               ▼
              Allocation engine (softmax) ──→ allocations table
```

The dashboard is a **read-only view** on top of this pipeline. The scheduler is the "engine" that calls Nansen, crunches numbers, and writes results.

---

## 6. Key File Locations

### Backend
- `backend/main.py` — FastAPI app, lifespan, middleware
- `backend/run.py` — Uvicorn entry point (port 8000)
- `backend/config.py` — env vars (API key, cache TTLs, ports)
- `backend/dependencies.py` — DI for NansenClient, DataStore, CacheLayer
- `backend/schemas.py` — all Pydantic models
- `backend/routers/market.py` — Market Overview endpoint
- `backend/routers/positions.py` — Position Explorer endpoint
- `backend/routers/leaderboard.py` — Leaderboard endpoint (dual-source)
- `backend/routers/allocations.py` — Allocations + Strategies endpoints
- `backend/cache.py` — in-memory cache layer
- `backend/mock_data.py` — mock data generators for dev mode

### Core Engine
- `src/scheduler.py` — continuous scheduler loop
- `src/nansen_client.py` — async Nansen API client
- `src/datastore.py` — SQLite wrapper (all table operations)
- `src/metrics.py` — trade metrics computation
- `src/scoring.py` — trader scoring (composite score)
- `src/filters.py` — eligibility / anti-luck filters
- `src/allocation.py` — softmax allocation computation
- `src/position_monitor.py` — liquidation detection
- `src/strategy_interface.py` — index portfolio + weighted consensus
- `src/config.py` — risk limits, softmax temperature, intervals

### Frontend
- `frontend/src/App.tsx` — router setup
- `frontend/src/api/hooks.ts` — React Query hooks (all API calls)
- `frontend/src/api/client.ts` — HTTP client
- `frontend/src/api/types.ts` — TypeScript types
- `frontend/src/lib/constants.ts` — tokens, refresh intervals, colors
- `frontend/src/pages/MarketOverview.tsx`
- `frontend/src/pages/PositionExplorer.tsx`
- `frontend/src/pages/TraderLeaderboard.tsx`
- `frontend/src/pages/AllocationDashboard.tsx`

### Scripts
- `scripts/stage6_scheduler_cycle.py` — one-shot full pipeline run

### Data
- `data/pnl_weighted.db` — production SQLite database
