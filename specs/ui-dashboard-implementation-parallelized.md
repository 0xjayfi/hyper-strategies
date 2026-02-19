# Parallelized Execution Plan

**Source**: specs/ui-dashboard-implementation.md
**Generated**: 2026-02-18
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

```
Phase 1 -> (no dependencies)
Phase 2 -> Phase 1
Phase 3 -> Phase 2
Phase 4 -> Phase 3
Phase 5 -> Phase 4
```

Note: Transitive reduction applied. Original explicit dependencies:
- Phase 4 declared `Phase 2, Phase 3` — Phase 2 is transitively covered via Phase 3 → Phase 2
- Phase 5 declared `Phase 1, Phase 2, Phase 3, Phase 4` — all covered transitively via Phase 4 chain

The dependency graph forms a linear chain, so each phase maps to its own sequential track. Parallelism is achieved **within** each phase via multiple agents splitting backend vs frontend work.

---

## Completed Phases (Skipped)

None — all phases have remaining work.

---

## Track 1: Backend Foundation + Frontend Scaffolding + Position Explorer

Phases in this track run **in parallel** (single phase — internal parallelism via agents).

### Phase 1: Backend API Foundation + Position Explorer (agents: 3)

**Agent split:**
- Agent 1 (Backend Core): main.py, config, cache, dependencies, schemas, health router, pyproject.toml, run.py
- Agent 2 (Backend Positions + NansenClient): positions router, NansenClient method, integration test
- Agent 3 (Frontend): Vite init, Tailwind/shadcn setup, layout, shared components, Position Explorer page, API layer

**Backend Tasks:**
- [x] Create `backend/` directory structure with `__init__.py` files
- [x] Create `backend/main.py` — FastAPI app with CORS middleware, lifespan handler that initializes `NansenClient` and `DataStore` as app state
- [x] Create `backend/config.py` — load env vars: `NANSEN_API_KEY`, `NANSEN_BASE_URL`, `MOCK_STRATEGY_DATA`, `CACHE_TTL_POSITIONS=300`, `CACHE_TTL_LEADERBOARD=3600`, `BACKEND_PORT=8000`, `FRONTEND_ORIGIN=http://localhost:5173`
- [x] Create `backend/dependencies.py` — FastAPI `Depends()` functions for `get_nansen_client()`, `get_datastore()`, `get_cache()`
- [x] Create `backend/cache.py` — `CacheLayer` class wrapping `cachetools.TTLCache` with JSON file backup. Methods: `get(key)`, `set(key, value, ttl)`, `invalidate(key)`, `invalidate_prefix(prefix)`
- [x] Create `backend/schemas.py` — Pydantic v2 response models: `PositionResponse`, `PositionMeta`, `PositionItem`, enums (`TokenEnum`, `SideEnum`, `LabelTypeEnum`)
- [x] Create `backend/routers/positions.py` — `GET /api/v1/positions` endpoint. Calls Nansen `token-perp-positions` via `NansenClient`, enriches with computed long/short ratio, caches result
- [x] Add new `NansenClient` method: `fetch_token_perp_positions(token, label_type, side, limit)` → calls `POST /api/v1/tgm/perp-positions`
- [x] Create `backend/routers/health.py` — `GET /api/v1/health` returns `{"status": "ok", "db_connected": bool, "nansen_key_set": bool}`
- [x] Update `pyproject.toml` — add `backend` optional deps: `fastapi`, `uvicorn[standard]`, `cachetools`
- [x] Add `backend/run.py` — entry point: `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload`
- [x] Test: `curl localhost:8000/api/v1/positions?token=BTC` returns valid JSON with positions

**Frontend Tasks:**
- [x] Initialize frontend: `npm create vite@latest frontend -- --template react-ts` from project root
- [x] Install deps: `tailwindcss`, `@tailwindcss/vite`, `shadcn/ui` (via `npx shadcn@latest init`), `@tanstack/react-query`, `@tanstack/react-table`, `react-router`, `lucide-react`, `recharts`, `lightweight-charts`
- [x] Configure dark theme in `tailwind.config.ts` — extend colors with project palette (`bg-surface: #0d1117`, `bg-card: #161b22`, `text-primary: #e6edf3`, `text-muted: #8b949e`, `green: #3fb950`, `red: #f85149`, `accent: #58a6ff`, `border: #30363d`)
- [x] Create `frontend/src/styles/globals.css` — Tailwind imports + CSS custom properties for dark theme + monospace font for numerics (`font-mono` utility class)
- [x] Create `frontend/src/lib/constants.ts` — `TOKENS`, `API_BASE_URL`, `REFRESH_INTERVALS`
- [x] Create `frontend/src/lib/utils.ts` — `formatUsd()`, `formatPct()`, `truncateAddress()`, `cn()` (clsx + twMerge)
- [x] Create `frontend/src/api/client.ts` — fetch wrapper with base URL from env, error handling
- [x] Create `frontend/src/api/types.ts` — TypeScript interfaces mirroring backend schemas (all Strategy #9 fields `| null`)
- [x] Create `frontend/src/api/hooks.ts` — `usePositions(token, filters)` TanStack Query hook with 5-min refetch
- [x] Create shell layout: `Sidebar.tsx` (nav links for 5 pages), `Header.tsx` (page title + refresh button), `PageLayout.tsx` (sidebar + header + content slot)
- [x] Create `frontend/src/App.tsx` — React Router with 5 routes, QueryClientProvider
- [x] Create shared components: `TokenBadge.tsx`, `SideBadge.tsx` (green Long / red Short), `PnlDisplay.tsx` (green/red with +/- prefix), `SmartMoneyBadge.tsx`, `LoadingState.tsx`, `ErrorState.tsx`, `EmptyState.tsx`
- [x] Build Position Explorer page (`pages/PositionExplorer.tsx`): `PositionFilters.tsx` (token selector, side toggle, smart money switch, min size slider), `PositionTable.tsx` (TanStack Table with all columns), `PositionRowDetail.tsx` (expandable row with full address, funding, margin, liquidation bar)
- [x] Wire up: PositionExplorer fetches from `/api/v1/positions`, renders table, filters update query params
- [x] Verify: full data flow — Nansen API → backend cache → REST → React Query → rendered table

---

## Track 2: Market Intelligence + Trader Rankings

Phases in this track run **in parallel** (single phase). Starts after Track 1 completes.

### Phase 2: Market Overview + Leaderboard (agents: 2)

**Agent split:**
- Agent 1 (Backend): market router, leaderboard router, screener router, NansenClient screener method, consensus logic, schemas
- Agent 2 (Frontend): Market Overview page (TokenCard, ConsensusIndicator, SmartMoneyFlowSummary), Leaderboard page (LeaderboardTable, TimeframeToggle, ScoreRadarChart, FilterBadges)

**Backend Tasks:**
- [x] Add `NansenClient` method: `fetch_perp_screener(tokens)` → calls `POST /api/v1/perp-screener`. Returns volume, OI, funding rates, smart money activity per token
- [x] Create `backend/routers/market.py` — `GET /api/v1/market-overview`. Aggregates data from `token-perp-positions` (all 4 tokens) + `perp-screener`. Computes: long/short ratio, consensus direction (smart money volume-weighted), top trader per token. Returns `MarketOverviewResponse`
- [x] Add consensus computation logic: for each token, sum `position_value_usd` by side for `label_type=smart_money`, compute `confidence_pct = abs(long - short) / (long + short) * 100`, direction = majority side
- [x] Create `backend/routers/leaderboard.py` — `GET /api/v1/leaderboard`. DataStore path (preferred): query scores + allocations + trade_metrics + traders tables, apply anti-luck filter status. Nansen fallback: call `fetch_pnl_leaderboard()` when no scores, return with `score: null`, `allocation_weight: null`
- [x] Create `backend/routers/screener.py` — `GET /api/v1/screener`. Thin pass-through to `perp-screener` with caching
- [x] Add schemas: `MarketOverviewResponse`, `TokenOverview`, `ConsensusEntry`, `LeaderboardResponse`, `LeaderboardTrader`, `AntiLuckStatus`

**Frontend Tasks:**
- [x] Create `api/hooks.ts` additions: `useMarketOverview()`, `useLeaderboard(timeframe, token, sortBy)`
- [x] Build Market Overview page (`pages/MarketOverview.tsx`): `TokenCard.tsx` (symbol, long/short ratio bar, total value, top trader, funding badge), `ConsensusIndicator.tsx` (bullish/bearish/neutral pill with confidence %), `SmartMoneyFlowSummary.tsx` (horizontal bar net long vs short). Layout: 2×2 token grid, consensus row, smart money flow
- [x] Build Trader Leaderboard page (`pages/TraderLeaderboard.tsx`): `TimeframeToggle.tsx` (7d/30d/90d), `LeaderboardTable.tsx` (TanStack Table with all columns), `FilterBadges.tsx` (anti-luck pass/fail icons), `ScoreRadarChart.tsx` (Recharts RadarChart for 6 score components). Click row → navigate to `/traders/{address}`
- [x] Add token filter dropdown to leaderboard (optional, filters to single token)
- [x] Handle null Strategy #9 fields gracefully: show "—" in table, hide radar chart section, show info banner "Run the allocation engine to see trader scores"
- [x] Sort leaderboard by score (default), fallback to PnL when scores unavailable

---

## Track 3: Trader Deep Dive

Phases in this track run **in parallel** (single phase). Starts after Track 2 completes.

### Phase 3: Trader Deep Dive (agents: 2)

**Agent split:**
- Agent 1 (Backend): traders router (profile + trades + PnL curve endpoints), mock_data.py
- Agent 2 (Frontend): TraderDeepDive page (TraderHeader, PnlCurveChart, TradeHistoryTable, ScoreBreakdown, AllocationHistory)

**Backend Tasks:**
- [x] Create `backend/routers/traders.py` — `GET /api/v1/traders/{address}`. Combines `NansenClient.fetch_address_positions(address)` for current positions + `DataStore` lookups for trader label, style, scores, allocations, blacklist, anti-luck status. Falls back to positions-only response with null score fields
- [x] Add `GET /api/v1/traders/{address}/trades` endpoint in same router. Calls `NansenClient.fetch_address_trades(address, date_from, date_to)` with auto-pagination. Returns paginated trade list
- [x] Add `GET /api/v1/traders/{address}/pnl-curve` endpoint. DataStore path: compute cumulative PnL curve from trade_metrics or raw trades. Nansen path: fetch trades, sort by timestamp, compute running cumulative_pnl. Mock path: generate synthetic curve when `MOCK_STRATEGY_DATA=true`
- [x] Create `backend/mock_data.py` — deterministic mock generators: `generate_mock_score(address)`, `generate_mock_pnl_curve(address, days)`, `generate_mock_allocation_weight(address)`. Seeded on address hash for deterministic output

**Frontend Tasks:**
- [x] Add `api/hooks.ts`: `useTrader(address)`, `useTraderTrades(address, days)`, `useTraderPnlCurve(address, days)`
- [x] Build Trader Deep Dive page (`pages/TraderDeepDive.tsx`): `TraderHeader.tsx` (full address, label, smart money badge, trading style, last active, blacklist warning), `PnlCurveChart.tsx` (Lightweight Charts LineSeries, dark theme, crosshair, time range selector), `TradeHistoryTable.tsx` (TanStack Table, paginated 50/page), `ScoreBreakdown.tsx` (horizontal stacked bar for 6 components + multipliers), `AllocationHistory.tsx` (Recharts AreaChart)
- [x] Build metrics summary cards section (PnL, ROI, win rate, trades per timeframe) and current positions table (token, side, size, entry, PnL) within deep dive layout
- [x] Add back navigation to leaderboard with browser history
- [x] Handle all null/missing Strategy #9 data gracefully with placeholder components

---

## Track 4: Allocation & Strategy Intelligence

Phases in this track run **in parallel** (single phase). Starts after Track 3 completes.

### Phase 4: Allocation & Strategy Dashboard (agents: 2)

**Agent split:**
- Agent 1 (Backend): allocations router (allocations + strategies endpoints), DataStore allocation history query, mock_data extensions
- Agent 2 (Frontend): AllocationDashboard page (WeightsDonut, AllocationTimeline, IndexPortfolioTable, ConsensusCards, SizingCalculator, RiskGauges)

**Backend Tasks:**
- [x] Create `backend/routers/allocations.py` — `GET /api/v1/allocations`. Reads `DataStore.get_latest_allocations()`, enriches with trader labels and ROI tiers. Computes risk cap utilization from current allocations
- [x] Add `GET /api/v1/allocations/strategies` endpoint. Calls `strategy_interface.py` functions: `build_index_portfolio()`, `consensus_vote()`, `per_trade_sizing()`. Falls back to mock data when allocations are empty
- [x] Add allocation history query to DataStore: `get_allocation_history(days=30)` → `list[{timestamp, address, weight}]` for timeline chart
- [x] Extend mock_data.py: `generate_mock_allocations(n_traders)`, `generate_mock_index_portfolio()`, `generate_mock_consensus()`

**Frontend Tasks:**
- [x] Add `api/hooks.ts`: `useAllocations()`, `useAllocationStrategies()`, `useAllocationHistory()`
- [x] Build Allocation Dashboard page (`pages/AllocationDashboard.tsx`): `WeightsDonut.tsx` (Recharts PieChart donut), `AllocationTimeline.tsx` (Recharts stacked AreaChart), `IndexPortfolioTable.tsx` (Strategy #2 target positions), `ConsensusCards.tsx` (Strategy #3 direction cards with confidence bars), `SizingCalculator.tsx` (Strategy #5 interactive calculator), `RiskGauges.tsx` (4 gauge visualizations for position count, token exposure, directional exposure)
- [x] Add empty state handling: full-page placeholder with explanation and mock data toggle button when no allocation data
- [x] Add softmax temperature slider (informational — shows how weights would change, doesn't persist)

---

## Track 5: Hardening, Polish, and Deployment

Phases in this track run **in parallel** (single phase). Starts after Track 4 completes.

### Phase 5: Polish, Real-Time Updates, and Deployment (agents: 3)

**Agent split:**
- Agent 1 (Real-Time + Error Handling + Performance): auto-refresh, manual refresh, stale-while-revalidate, loading indicators, 429 handler, error states, request coalescing, table virtualization, lazy loading
- Agent 2 (UI Polish + Frontend Testing): responsive sidebar, keyboard shortcuts, tooltips, animations, favicon, component render tests, E2E test
- Agent 3 (Deployment + Backend Testing): Dockerfiles, docker-compose, Makefile, Vercel config, Procfile, README, backend pytest tests

**Real-Time & Refresh:**
- [x] Implement auto-refresh for Position Explorer: TanStack Query `refetchInterval: 5 * 60 * 1000` (5 min)
- [x] Add manual refresh button in header — calls `queryClient.invalidateQueries()` for current page's queries
- [x] Add "last updated" timestamp in page header, computed from cache metadata
- [x] Implement stale-while-revalidate pattern: show cached data immediately, background refresh, update UI when new data arrives
- [x] Add subtle loading indicator (thin progress bar at top of page) during background refetches — do not show full skeleton on refetch

**Error Handling & Edge Cases:**
- [x] Backend: global exception handler for Nansen 429 responses — return `503 Service Unavailable` with `Retry-After` header and user-friendly message
- [x] Backend: handle Nansen API key not set — return 503 with "Nansen API key not configured"
- [x] Frontend: `ErrorState.tsx` component variations — rate limited (show countdown), network error (show retry), API key missing (show setup instructions)
- [x] Frontend: handle empty position data per token (show "No positions found" rather than empty table)
- [x] Add connection status indicator in sidebar footer: green dot = healthy, yellow = degraded (some API errors), red = disconnected

**Performance:**
- [x] Backend: implement request coalescing — if 3 frontend requests hit `/positions?token=BTC` within 100ms, make only 1 Nansen API call
- [x] Frontend: virtualize long tables (>100 rows) using TanStack Virtual
- [x] Frontend: lazy-load chart libraries (Recharts, Lightweight Charts) via `React.lazy()` + Suspense
- [x] Frontend: add `<link rel="preconnect">` for backend URL in `index.html`

**UI Polish:**
- [x] Responsive sidebar: collapsible on tablet (icon-only mode), full on desktop
- [x] Add keyboard shortcuts: `1-5` to switch pages, `r` to refresh, `f` to focus filter
- [x] Add tooltips on all abbreviated/truncated data (full address, full numbers)
- [x] Animate number changes (PnL, scores) with counting transitions
- [x] Add favicon and page titles per route

**Deployment Setup:**
- [x] Create `backend/Dockerfile` — Python 3.11 slim, install deps from pyproject.toml, run uvicorn
- [x] Create `frontend/Dockerfile` — Node 20, build static assets, serve via nginx
- [x] Create `docker-compose.yml` at project root — backend + frontend services, shared `.env`
- [x] Add `Makefile` with commands: `make dev` (starts both), `make backend`, `make frontend`, `make build`, `make docker-up`
- [x] Create `frontend/vercel.json` — rewrites for SPA routing
- [x] Create `backend/Procfile` — for Railway/Fly.io: `web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- [x] Document deployment in `README.md` section (local dev + production)

**Testing:**
- [x] Backend: pytest tests for each router (mock NansenClient, test response schemas)
- [x] Backend: test cache layer (TTL expiry, invalidation)
- [x] Backend: test fallback behavior (no DataStore scores → Nansen fallback)
- [x] Frontend: basic component render tests with React Testing Library (ensure no crashes with null data)
- [x] E2E: one happy-path test with Playwright — load Market Overview, click into Position Explorer, filter by token, click leaderboard, click into trader detail

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1: Backend Foundation + Position Explorer | Phase 1 | 3 | 27 |
| Track 2: Market Intelligence + Trader Rankings | Phase 2 | 2 | 12 |
| Track 3: Trader Deep Dive | Phase 3 | 2 | 9 |
| Track 4: Allocation & Strategy Intelligence | Phase 4 | 2 | 8 |
| Track 5: Hardening, Polish, and Deployment | Phase 5 | 3 | 31 |
| **Total** | **5 phases** | — | **87** |
