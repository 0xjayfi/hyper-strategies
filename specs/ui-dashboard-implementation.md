# Hyper-Signals UI Dashboard — Implementation Plan

> Web-based dashboard for the Hyperliquid perpetual trading intelligence system. Surfaces real-time positions, trader quality scores, and allocation weights from the existing Strategy #9 backend.

---

## Problem Statement

The Hyper-Signals system currently operates as a headless pipeline — data flows through `src/scheduler.py` into SQLite, but there's no visual interface for traders to:
- See what top Hyperliquid perp traders are doing right now
- Evaluate trader quality before copying trades
- Monitor consensus direction across smart money
- Size copy-trade positions using allocation weights

The dashboard is a **read-only consumption layer** over the existing `src/` backend and Nansen API. It must work with or without Strategy #9 data populated in the database.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Browser (React)                             │
│                                                                      │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────┐ ┌──────────────┐ │
│  │   Market     │ │  Position    │ │  Trader     │ │  Allocation  │ │
│  │   Overview   │ │  Explorer    │ │  Leaderboard│ │  Dashboard   │ │
│  └──────┬──────┘ └──────┬───────┘ └──────┬──────┘ └──────┬───────┘ │
│         │               │                │               │          │
│         └───────────────┴────────────────┴───────────────┘          │
│                              │                                       │
│                   React Query (TanStack Query)                       │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │  HTTP (localhost:8000)
┌──────────────────────────────┼───────────────────────────────────────┐
│                        FastAPI Backend                                │
│                              │                                       │
│  ┌───────────────────────────┴────────────────────────────────┐     │
│  │                    /api/v1/* endpoints                      │     │
│  │  /positions, /leaderboard, /traders/{addr}, /allocations,  │     │
│  │  /market-overview, /screener                               │     │
│  └──────┬─────────────────────────────┬───────────────────────┘     │
│         │                             │                              │
│  ┌──────┴──────┐              ┌───────┴──────────┐                  │
│  │  CacheLayer │              │ src/ modules      │                  │
│  │  (in-memory │              │ - nansen_client   │                  │
│  │   + JSON)   │              │ - datastore       │                  │
│  └──────┬──────┘              │ - scoring         │                  │
│         │                     │ - allocation      │                  │
│         │                     │ - strategy_iface  │                  │
│         │                     └───────┬───────────┘                  │
│         │                             │                              │
│         └─────────────┬───────────────┘                              │
│                       │                                              │
└───────────────────────┼──────────────────────────────────────────────┘
                        │  HTTPS (api.nansen.ai)
                ┌───────┴───────┐
                │   Nansen API  │
                │  (rate-limited│
                │   POST calls) │
                └───────────────┘
```

**Data flow for a typical request:**

1. Browser → `GET /api/v1/positions?token=BTC&label_type=smart_money`
2. FastAPI checks in-memory cache (TTL-based)
3. Cache miss → calls `NansenClient.fetch_token_perp_positions()`
4. Response cached, returned as JSON to browser
5. React Query stores in client-side cache, renders components

**Data flow for Strategy #9 data:**

1. Browser → `GET /api/v1/leaderboard?timeframe=30d`
2. FastAPI reads from `DataStore` (SQLite — pre-computed by scheduler)
3. Joins trader scores, allocations, filter status from DB
4. Returns enriched JSON to browser

---

## Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Backend framework** | FastAPI 0.115+ | Async, auto-docs, matches existing async nansen_client |
| **Backend server** | uvicorn 0.32+ | Standard ASGI server for FastAPI |
| **Serialization** | Pydantic v2 (existing) | Already used in `src/models.py` |
| **Caching** | `cachetools` TTLCache + JSON files | In-memory for hot data, JSON for persistence across restarts |
| **Frontend framework** | React 19 + TypeScript 5.7 | Industry standard, strong ecosystem |
| **Build tool** | Vite 6 | Fast HMR, native TS support |
| **Styling** | TailwindCSS 4 + shadcn/ui | Utility-first CSS, dark theme components |
| **Data fetching** | TanStack Query v5 | Caching, refetch, loading/error states built-in |
| **Charts** | Recharts 2.15 (overview/gauges) + Lightweight Charts 4 (PnL curves) | Recharts for pie/bar/radar, Lightweight Charts for financial time series |
| **Routing** | React Router v7 | Client-side routing for 5 pages |
| **Table** | TanStack Table v8 | Sorting, filtering, pagination, expandable rows |
| **Icons** | Lucide React | Consistent icon set, tree-shakeable |

---

## Directory Structure (Final State)

```
hyper-strategies-pnl-weighted/
├── backend/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, CORS, lifespan
│   ├── config.py                  # Backend-specific config (cache TTLs, port)
│   ├── cache.py                   # TTLCache wrapper + JSON file persistence
│   ├── dependencies.py            # FastAPI dependency injection (NansenClient, DataStore)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── positions.py           # /api/v1/positions
│   │   ├── leaderboard.py         # /api/v1/leaderboard
│   │   ├── traders.py             # /api/v1/traders/{address}
│   │   ├── market.py              # /api/v1/market-overview
│   │   ├── allocations.py         # /api/v1/allocations
│   │   └── screener.py            # /api/v1/screener
│   └── schemas.py                 # Response models (extends src/models.py)
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── components.json            # shadcn/ui config
│   ├── public/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx                # Router + layout
│   │   ├── api/
│   │   │   ├── client.ts          # Axios/fetch wrapper
│   │   │   ├── hooks.ts           # TanStack Query hooks
│   │   │   └── types.ts           # TypeScript interfaces (mirrors backend schemas)
│   │   ├── components/
│   │   │   ├── ui/                # shadcn/ui primitives (button, table, card, etc.)
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── Header.tsx
│   │   │   │   └── PageLayout.tsx
│   │   │   ├── shared/
│   │   │   │   ├── TokenBadge.tsx
│   │   │   │   ├── SideBadge.tsx
│   │   │   │   ├── PnlDisplay.tsx
│   │   │   │   ├── SmartMoneyBadge.tsx
│   │   │   │   ├── LoadingState.tsx
│   │   │   │   ├── ErrorState.tsx
│   │   │   │   └── EmptyState.tsx
│   │   │   ├── market/
│   │   │   │   ├── TokenCard.tsx
│   │   │   │   ├── ConsensusIndicator.tsx
│   │   │   │   └── SmartMoneyFlowSummary.tsx
│   │   │   ├── positions/
│   │   │   │   ├── PositionTable.tsx
│   │   │   │   ├── PositionFilters.tsx
│   │   │   │   └── PositionRowDetail.tsx
│   │   │   ├── leaderboard/
│   │   │   │   ├── LeaderboardTable.tsx
│   │   │   │   ├── TimeframeToggle.tsx
│   │   │   │   ├── ScoreRadarChart.tsx
│   │   │   │   └── FilterBadges.tsx
│   │   │   ├── trader/
│   │   │   │   ├── TraderHeader.tsx
│   │   │   │   ├── PnlCurveChart.tsx
│   │   │   │   ├── TradeHistoryTable.tsx
│   │   │   │   ├── ScoreBreakdown.tsx
│   │   │   │   └── AllocationHistory.tsx
│   │   │   └── allocation/
│   │   │       ├── WeightsDonut.tsx
│   │   │       ├── AllocationTimeline.tsx
│   │   │       ├── IndexPortfolioTable.tsx
│   │   │       ├── ConsensusCards.tsx
│   │   │       ├── SizingCalculator.tsx
│   │   │       └── RiskGauges.tsx
│   │   ├── pages/
│   │   │   ├── MarketOverview.tsx
│   │   │   ├── PositionExplorer.tsx
│   │   │   ├── TraderLeaderboard.tsx
│   │   │   ├── TraderDeepDive.tsx
│   │   │   └── AllocationDashboard.tsx
│   │   ├── lib/
│   │   │   ├── utils.ts           # formatUsd, truncateAddress, cn()
│   │   │   ├── constants.ts       # TOKENS, COLORS, REFRESH_INTERVALS
│   │   │   └── theme.ts           # Dark theme tokens
│   │   └── styles/
│   │       └── globals.css        # Tailwind imports + custom CSS vars
│   └── .env.example               # VITE_API_URL=http://localhost:8000
├── src/                           # EXISTING — untouched
├── scripts/                       # EXISTING — untouched
├── tests/                         # EXISTING — untouched
├── specs/                         # EXISTING — untouched
├── data/                          # EXISTING — untouched
├── pyproject.toml                 # EXISTING — add backend deps
└── .env                           # EXISTING — add no new secrets
```

---

## Mock Data Strategy

Since Strategy #9 data may not be populated in the database, the backend must handle two modes:

1. **Live mode (default):** Read from `DataStore` for scores/allocations. If tables are empty, fall back to Nansen API raw data with `score: null`, `allocation_weight: null` in responses.

2. **Mock mode (`MOCK_STRATEGY_DATA=true` env var):** The backend generates deterministic mock scores and allocations for frontend development. A `backend/mock_data.py` module provides:
   - `generate_mock_scores(addresses: list[str]) -> dict[str, ScoreBreakdown]`
   - `generate_mock_allocations(addresses: list[str]) -> dict[str, float]`
   - `generate_mock_pnl_curve(address: str, days: int) -> list[PnlPoint]`

   Mock data uses seeded random generators keyed on address hash for deterministic output.

3. **Frontend:** TypeScript interfaces always include `| null` for Strategy #9 fields. Components show "Score unavailable — run allocation engine" placeholder when null.

---

## API Endpoint Definitions

### Shared Types

```python
# backend/schemas.py

class TokenEnum(str, Enum):
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    HYPE = "HYPE"

class SideEnum(str, Enum):
    LONG = "Long"
    SHORT = "Short"

class LabelTypeEnum(str, Enum):
    SMART_MONEY = "smart_money"
    WHALE = "whale"
    PUBLIC_FIGURE = "public_figure"
    ALL = "all_traders"

class TimeframeEnum(str, Enum):
    D7 = "7d"
    D30 = "30d"
    D90 = "90d"
```

### Endpoint Reference

| # | Method | Path | Source | Cache TTL |
|---|--------|------|--------|-----------|
| 1 | GET | `/api/v1/positions` | Nansen: token-perp-positions | 5 min |
| 2 | GET | `/api/v1/market-overview` | Nansen: token-perp-positions + perp-screener | 5 min |
| 3 | GET | `/api/v1/leaderboard` | DataStore + Nansen: perp-pnl-leaderboard | 1 hour |
| 4 | GET | `/api/v1/traders/{address}` | DataStore + Nansen: profiler endpoints | 10 min |
| 5 | GET | `/api/v1/traders/{address}/trades` | Nansen: profiler/perp-trades | 10 min |
| 6 | GET | `/api/v1/traders/{address}/pnl-curve` | DataStore (computed) or mock | 1 hour |
| 7 | GET | `/api/v1/allocations` | DataStore | 1 hour |
| 8 | GET | `/api/v1/allocations/strategies` | DataStore + strategy_interface | 1 hour |
| 9 | GET | `/api/v1/screener` | Nansen: perp-screener | 5 min |
| 10 | GET | `/api/v1/health` | Internal | None |

### Detailed Endpoint Specs

**1. `GET /api/v1/positions`**

Query params:
- `token: TokenEnum` (required)
- `label_type: LabelTypeEnum = "all_traders"`
- `side: SideEnum | None = None`
- `min_position_usd: float = 0`
- `limit: int = 20`

Response:
```json
{
  "token": "BTC",
  "positions": [
    {
      "rank": 1,
      "address": "0xabc...def",
      "address_label": "Wintermute",
      "side": "Long",
      "position_value_usd": 5200000.0,
      "position_size": 52.5,
      "leverage": 10.0,
      "leverage_type": "Cross",
      "entry_price": 95000.0,
      "mark_price": 98500.0,
      "liquidation_price": 85000.0,
      "funding_usd": -1200.5,
      "upnl_usd": 183750.0,
      "is_smart_money": true,
      "smart_money_labels": ["Market Maker"]
    }
  ],
  "meta": {
    "total_long_value": 42000000.0,
    "total_short_value": 38000000.0,
    "long_short_ratio": 1.105,
    "smart_money_count": 7,
    "fetched_at": "2026-02-18T12:00:00Z"
  }
}
```

**2. `GET /api/v1/market-overview`**

No params (returns all tokens).

Response:
```json
{
  "tokens": [
    {
      "symbol": "BTC",
      "long_short_ratio": 1.105,
      "total_position_value": 80000000.0,
      "top_trader_label": "Wintermute",
      "top_trader_side": "Long",
      "top_trader_size_usd": 5200000.0,
      "funding_rate": 0.0001,
      "smart_money_net_direction": "Long",
      "smart_money_confidence_pct": 72.5,
      "open_interest_usd": 120000000.0,
      "volume_24h_usd": 500000000.0
    }
  ],
  "consensus": {
    "BTC": {"direction": "Bullish", "confidence": 72.5},
    "ETH": {"direction": "Bearish", "confidence": 58.0},
    "SOL": {"direction": "Bullish", "confidence": 65.0},
    "HYPE": {"direction": "Neutral", "confidence": 51.0}
  },
  "smart_money_flow": {
    "net_long_usd": 15000000.0,
    "net_short_usd": 8000000.0,
    "direction": "Net Long"
  },
  "fetched_at": "2026-02-18T12:00:00Z"
}
```

**3. `GET /api/v1/leaderboard`**

Query params:
- `token: TokenEnum | None = None` (None = cross-token from DataStore)
- `timeframe: TimeframeEnum = "30d"`
- `limit: int = 50`
- `sort_by: str = "score"` (score | pnl | roi | win_rate)

Response:
```json
{
  "timeframe": "30d",
  "traders": [
    {
      "rank": 1,
      "address": "0xabc...def",
      "label": "Smart Whale #42",
      "pnl_usd": 250000.0,
      "roi_pct": 32.5,
      "win_rate": 0.68,
      "profit_factor": 2.8,
      "num_trades": 45,
      "score": 0.82,
      "allocation_weight": 0.15,
      "anti_luck_status": {
        "passed": true,
        "failures": []
      },
      "is_blacklisted": false,
      "is_smart_money": true
    }
  ],
  "source": "datastore"
}
```

When DataStore has no scores, `score` and `allocation_weight` are `null`, `source` is `"nansen_api"`, and `anti_luck_status` is `null`. Traders are sorted by `pnl_usd` instead.

**4. `GET /api/v1/traders/{address}`**

Response:
```json
{
  "address": "0xabc...def",
  "label": "Smart Whale #42",
  "is_smart_money": true,
  "trading_style": "SWING",
  "last_active": "2026-02-18T08:30:00Z",
  "positions": [
    {
      "token_symbol": "BTC",
      "side": "Long",
      "position_value_usd": 520000.0,
      "entry_price": 95000.0,
      "leverage_value": 10.0,
      "liquidation_price": 85000.0,
      "unrealized_pnl_usd": 18375.0
    }
  ],
  "account_value_usd": 1200000.0,
  "metrics": {
    "7d":  {"pnl": 15000, "roi": 8.5, "win_rate": 0.72, "trades": 12},
    "30d": {"pnl": 250000, "roi": 32.5, "win_rate": 0.68, "trades": 45},
    "90d": {"pnl": 800000, "roi": 95.0, "win_rate": 0.65, "trades": 120}
  },
  "score_breakdown": {
    "roi": 0.90,
    "sharpe": 0.75,
    "win_rate": 0.68,
    "consistency": 0.82,
    "smart_money": 1.0,
    "risk_mgmt": 0.70,
    "style_multiplier": 1.0,
    "recency_decay": 0.95,
    "final_score": 0.82
  },
  "allocation_weight": 0.15,
  "anti_luck_status": {"passed": true, "failures": []},
  "is_blacklisted": false
}
```

**5. `GET /api/v1/traders/{address}/trades`**

Query params:
- `days: int = 30`
- `limit: int = 100`

Response: `{ "trades": [Trade], "total": int }`

**6. `GET /api/v1/traders/{address}/pnl-curve`**

Query params:
- `days: int = 90`

Response: `{ "points": [{"timestamp": "...", "cumulative_pnl": 1234.56}] }`

**7. `GET /api/v1/allocations`**

Response:
```json
{
  "allocations": [
    {"address": "0x...", "label": "...", "weight": 0.15, "roi_tier": 1.0}
  ],
  "softmax_temperature": 2.0,
  "total_allocated_traders": 8,
  "risk_caps": {
    "position_count": {"current": 4, "max": 5},
    "max_token_exposure": {"worst": 0.12, "max": 0.15},
    "directional_long": {"current": 0.55, "max": 0.60},
    "directional_short": {"current": 0.35, "max": 0.60}
  },
  "computed_at": "2026-02-18T06:00:00Z"
}
```

**8. `GET /api/v1/allocations/strategies`**

Response:
```json
{
  "index_portfolio": [
    {"token": "BTC", "side": "Long", "target_weight": 0.35, "target_usd": 35000}
  ],
  "consensus": {
    "BTC": {"direction": "Long", "confidence": 0.78, "voter_count": 5},
    "ETH": {"direction": "Short", "confidence": 0.62, "voter_count": 3}
  },
  "sizing_params": [
    {"address": "0x...", "weight": 0.15, "roi_tier": 1.0, "max_size_usd": 15000}
  ]
}
```

---

## Phase 1: Backend API Foundation + Position Explorer

**Depends on:** None

### Backend Tasks

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

### Frontend Tasks

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
- [x] Build **Position Explorer** page (`pages/PositionExplorer.tsx`):
  - `PositionFilters.tsx` — token selector (tabs/segmented control), side toggle, smart money switch, min size slider
  - `PositionTable.tsx` — TanStack Table with columns: rank, label, wallet (truncated + copy), side badge, size (formatted USD), leverage, entry price, mark price, liq price, uPnL (PnlDisplay)
  - `PositionRowDetail.tsx` — expandable row with full address, funding USD, margin info, liquidation proximity bar
  - Table sorted by position_value_usd desc, filterable by all filter controls
- [x] Wire up: PositionExplorer fetches from `/api/v1/positions`, renders table, filters update query params
- [x] Verify: full data flow — Nansen API → backend cache → REST → React Query → rendered table

### Acceptance Criteria
- Backend starts with `python -m backend.run`, serves positions endpoint
- Frontend starts with `npm run dev`, shows Position Explorer with real data
- Filters work (token, side, smart money)
- Table sorts by any column
- Expandable rows show detail
- Loading/error/empty states render correctly
- Dark theme applied throughout

---

## Phase 2: Market Overview + Leaderboard

**Depends on:** Phase 1

### Backend Tasks

- [x] Add `NansenClient` method: `fetch_perp_screener(tokens)` → calls `POST /api/v1/perp-screener`. Returns volume, OI, funding rates, smart money activity per token
- [x] Create `backend/routers/market.py` — `GET /api/v1/market-overview`. Aggregates data from `token-perp-positions` (all 4 tokens) + `perp-screener`. Computes: long/short ratio, consensus direction (smart money volume-weighted), top trader per token. Returns `MarketOverviewResponse`
- [x] Add consensus computation logic: for each token, sum `position_value_usd` by side for `label_type=smart_money`, compute `confidence_pct = abs(long - short) / (long + short) * 100`, direction = majority side
- [x] Create `backend/routers/leaderboard.py` — `GET /api/v1/leaderboard`. Two paths:
  - **DataStore path (preferred):** Query `scores` + `allocations` + `trade_metrics` + `traders` tables. Join into `LeaderboardTrader` response items. Apply anti-luck filter status from `filters.py`
  - **Nansen fallback:** If DataStore has no scores, call `NansenClient.fetch_pnl_leaderboard()` for the given token/timeframe. Return with `score: null`, `allocation_weight: null`
- [x] Create `backend/routers/screener.py` — `GET /api/v1/screener`. Thin pass-through to `perp-screener` with caching
- [x] Add schemas: `MarketOverviewResponse`, `TokenOverview`, `ConsensusEntry`, `LeaderboardResponse`, `LeaderboardTrader`, `AntiLuckStatus`

### Frontend Tasks

- [x] Create `api/hooks.ts` additions: `useMarketOverview()`, `useLeaderboard(timeframe, token, sortBy)`
- [x] Build **Market Overview** page (`pages/MarketOverview.tsx`):
  - `TokenCard.tsx` — card for each token showing: symbol + icon, long/short ratio bar (horizontal stacked), total position value, top trader name + side + size, funding rate badge (positive=green, negative=red)
  - `ConsensusIndicator.tsx` — per-token bullish/bearish/neutral pill with confidence % and colored background (green/red/gray gradient)
  - `SmartMoneyFlowSummary.tsx` — horizontal bar showing net long vs net short across all tokens, with USD amounts
  - Layout: 4 token cards in a 2×2 grid (desktop), consensus row below, smart money flow at bottom
- [x] Build **Trader Leaderboard** page (`pages/TraderLeaderboard.tsx`):
  - `TimeframeToggle.tsx` — 7d / 30d / 90d segmented control
  - `LeaderboardTable.tsx` — TanStack Table: rank, label + smart money badge, address (truncated), PnL (PnlDisplay), ROI%, win rate, profit factor, # trades, score (color-coded bar or null placeholder), allocation weight (% or null placeholder)
  - `FilterBadges.tsx` — anti-luck pass/fail icons per trader row (checkmark/x icons with tooltip explaining which gate failed)
  - `ScoreRadarChart.tsx` — Recharts RadarChart showing 6 score components for selected/hovered trader (or top trader by default). Hidden when scores are null
  - Sort by score (default), fallback to PnL when scores unavailable
  - Click row → navigate to `/traders/{address}` (Phase 3)
- [x] Add token filter dropdown to leaderboard (optional, filters to single token)
- [x] Handle null Strategy #9 fields gracefully: show "—" in table, hide radar chart section, show info banner "Run the allocation engine to see trader scores"

### Acceptance Criteria
- Market Overview loads all 4 tokens with correct long/short ratios
- Consensus indicators show directional bias with confidence
- Smart money flow summary is accurate
- Leaderboard shows traders sorted by PnL (or score when available)
- Timeframe toggle refetches data
- Radar chart renders when score data exists, hidden when null
- Row click navigates to trader detail (route exists, page is placeholder)

---

## Phase 3: Trader Deep Dive

**Depends on:** Phase 2

### Backend Tasks

- [x] Create `backend/routers/traders.py` — `GET /api/v1/traders/{address}`. Combines:
  - `NansenClient.fetch_address_positions(address)` → current positions
  - `DataStore` lookups → trader label, style, scores, allocations, blacklist, anti-luck status
  - If no DataStore data, return positions-only response with null score fields
- [x] Add `GET /api/v1/traders/{address}/trades` endpoint in same router. Calls `NansenClient.fetch_address_trades(address, date_from, date_to)` with auto-pagination. Returns paginated trade list
- [x] Add `GET /api/v1/traders/{address}/pnl-curve` endpoint. Two paths:
  - **DataStore path:** If trade history is stored, compute cumulative PnL curve from `trade_metrics` or raw trades
  - **Nansen path:** Fetch trades for `days` window, sort by timestamp, compute running `cumulative_pnl = sum(closed_pnl)` per trade
  - **Mock path:** If `MOCK_STRATEGY_DATA=true`, generate synthetic curve
- [x] Create `backend/mock_data.py` — deterministic mock generators:
  - `generate_mock_score(address)` → `ScoreBreakdown` (seeded on address hash)
  - `generate_mock_pnl_curve(address, days)` → `list[PnlPoint]` (random walk with upward drift)
  - `generate_mock_allocation_weight(address)` → `float`

### Frontend Tasks

- [x] Add `api/hooks.ts`: `useTrader(address)`, `useTraderTrades(address, days)`, `useTraderPnlCurve(address, days)`
- [x] Build **Trader Deep Dive** page (`pages/TraderDeepDive.tsx`):
  - `TraderHeader.tsx` — large display: full address (copyable), label, smart money badge, trading style tag, last active timestamp, blacklist warning banner (if applicable)
  - `PnlCurveChart.tsx` — Lightweight Charts `LineSeries` showing cumulative PnL over time. Dark theme colors. Crosshair on hover shows exact PnL + date. Time range selector (7d/30d/90d)
  - `TradeHistoryTable.tsx` — TanStack Table: timestamp, token, action (Open/Close/Add), side badge, size USD, price, closed PnL (green/red), fee. Sortable by timestamp (desc default). Paginated (50 per page)
  - `ScoreBreakdown.tsx` — horizontal stacked bar showing 6 score components with their weights. Below: style multiplier, recency decay, final score. Or "Scores not computed" placeholder
  - `AllocationHistory.tsx` — small Recharts AreaChart showing allocation weight over time (from DataStore allocation_history table). Or placeholder
  - Layout: header → metrics summary cards (PnL, ROI, win rate, trades per timeframe) → PnL curve → score breakdown → trade history → allocation history
- [x] Current positions section within the deep dive: small table showing active positions (token, side, size, entry, PnL)
- [x] Back navigation to leaderboard with browser history

### Acceptance Criteria
- Navigate from leaderboard row click to trader detail
- Trader header shows address, label, badges
- PnL curve renders with real or mock data
- Trade history table paginates correctly
- Score breakdown shows components or placeholder
- All null/missing data handled gracefully

---

## Phase 4: Allocation & Strategy Dashboard

**Depends on:** Phase 2, Phase 3

### Backend Tasks

- [x] Create `backend/routers/allocations.py` — `GET /api/v1/allocations`. Reads `DataStore.get_latest_allocations()`, enriches with trader labels and ROI tiers. Computes risk cap utilization from current allocations
- [x] Add `GET /api/v1/allocations/strategies` endpoint. Calls `strategy_interface.py` functions:
  - `build_index_portfolio()` → target positions
  - `consensus_vote()` → direction per token (requires position data)
  - `per_trade_sizing()` → sizing params per trader
  - Falls back to mock data when allocations are empty
- [x] Add allocation history query to DataStore: `get_allocation_history(days=30)` → `list[{timestamp, address, weight}]` for timeline chart
- [x] Extend mock_data.py: `generate_mock_allocations(n_traders)`, `generate_mock_index_portfolio()`, `generate_mock_consensus()`

### Frontend Tasks

- [x] Add `api/hooks.ts`: `useAllocations()`, `useAllocationStrategies()`, `useAllocationHistory()`
- [x] Build **Allocation Dashboard** page (`pages/AllocationDashboard.tsx`):
  - `WeightsDonut.tsx` — Recharts PieChart (donut) showing allocation weights per trader. Color-coded by trader, legend with address + label + weight %. Center text: "8 traders allocated"
  - `AllocationTimeline.tsx` — Recharts AreaChart (stacked) showing allocation weights over 30 days. Each trader is a stacked area
  - `IndexPortfolioTable.tsx` — Strategy #2 output: table with token, side, target weight %, target USD amount. Summary row with total exposure
  - `ConsensusCards.tsx` — Strategy #3 output: card per token showing direction arrow (up/down/neutral), confidence bar (0-100%), voter count. Color: green for Long, red for Short, gray for Neutral
  - `SizingCalculator.tsx` — Strategy #5 interactive calculator: dropdown to select trader → shows weight, ROI tier multiplier, and computed `position_size = account_value × weight × tier`. Account value input field (default from config)
  - `RiskGauges.tsx` — 4 gauge/progress-bar visualizations:
    1. Position count (current / max 5)
    2. Worst token exposure (current % / max 15%)
    3. Long directional exposure (current % / max 60%)
    4. Short directional exposure (current % / max 60%)
    Color: green < 70% limit, yellow 70-90%, red > 90%
  - Layout: top row = donut + risk gauges | middle = timeline | bottom = strategy tabs (Index / Consensus / Sizing)
- [x] When no allocation data: show full-page placeholder with explanation and mock data toggle button (calls backend with `?mock=true`)
- [x] Softmax temperature slider (informational — shows how weights would change, doesn't persist)

### Acceptance Criteria
- Allocation donut renders with real or mock data
- Risk gauges show correct utilization percentages
- Strategy #2 table shows target positions
- Strategy #3 cards show consensus direction
- Strategy #5 calculator computes sizing correctly
- Empty state is informative, not broken
- Timeline chart shows allocation evolution

---

## Phase 5: Polish, Real-Time Updates, and Deployment

**Depends on:** Phase 1, Phase 2, Phase 3, Phase 4

### Real-Time & Refresh

- [x] Implement auto-refresh for Position Explorer: TanStack Query `refetchInterval: 5 * 60 * 1000` (5 min)
- [x] Add manual refresh button in header — calls `queryClient.invalidateQueries()` for current page's queries
- [x] Add "last updated" timestamp in page header, computed from cache metadata
- [x] Implement stale-while-revalidate pattern: show cached data immediately, background refresh, update UI when new data arrives
- [x] Add subtle loading indicator (thin progress bar at top of page) during background refetches — do not show full skeleton on refetch

### Error Handling & Edge Cases

- [x] Backend: global exception handler for Nansen 429 responses — return `503 Service Unavailable` with `Retry-After` header and user-friendly message
- [x] Backend: handle Nansen API key not set — return 503 with "Nansen API key not configured"
- [x] Frontend: `ErrorState.tsx` component variations — rate limited (show countdown), network error (show retry), API key missing (show setup instructions)
- [x] Frontend: handle empty position data per token (show "No positions found" rather than empty table)
- [x] Add connection status indicator in sidebar footer: green dot = healthy, yellow = degraded (some API errors), red = disconnected

### Performance

- [x] Backend: implement request coalescing — if 3 frontend requests hit `/positions?token=BTC` within 100ms, make only 1 Nansen API call
- [x] Frontend: virtualize long tables (>100 rows) using TanStack Virtual
- [x] Frontend: lazy-load chart libraries (Recharts, Lightweight Charts) via `React.lazy()` + Suspense
- [x] Frontend: add `<link rel="preconnect">` for backend URL in `index.html`

### UI Polish

- [x] Responsive sidebar: collapsible on tablet (icon-only mode), full on desktop
- [x] Add keyboard shortcuts: `1-5` to switch pages, `r` to refresh, `f` to focus filter
- [x] Add tooltips on all abbreviated/truncated data (full address, full numbers)
- [x] Animate number changes (PnL, scores) with counting transitions
- [x] Add favicon and page titles per route

### Deployment Setup

- [x] Create `backend/Dockerfile` — Python 3.11 slim, install deps from pyproject.toml, run uvicorn
- [x] Create `frontend/Dockerfile` — Node 20, build static assets, serve via nginx
- [x] Create `docker-compose.yml` at project root — backend + frontend services, shared `.env`
- [x] Add `Makefile` with commands: `make dev` (starts both), `make backend`, `make frontend`, `make build`, `make docker-up`
- [x] Create `frontend/vercel.json` — rewrites for SPA routing
- [x] Create `backend/Procfile` — for Railway/Fly.io: `web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- [x] Document deployment in `README.md` section (local dev + production)

### Testing

- [x] Backend: pytest tests for each router (mock NansenClient, test response schemas)
- [x] Backend: test cache layer (TTL expiry, invalidation)
- [x] Backend: test fallback behavior (no DataStore scores → Nansen fallback)
- [x] Frontend: basic component render tests with React Testing Library (ensure no crashes with null data)
- [x] E2E: one happy-path test with Playwright — load Market Overview, click into Position Explorer, filter by token, click leaderboard, click into trader detail

### Acceptance Criteria
- Auto-refresh works without full page reload
- Rate limit errors show user-friendly messages with countdown
- All pages render correctly with null Strategy #9 data
- `make dev` starts both frontend and backend
- Docker Compose runs the full stack
- Core E2E test passes

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Nansen rate limits (429)** | Positions page unusable during cooldown | Server-side cache (5-min TTL) means most requests never hit Nansen. Backend request coalescing prevents stampedes. Show cached data during rate limit with "data may be stale" warning |
| **Strategy #9 data not populated** | Leaderboard/Allocation pages have limited value | Every endpoint has a Nansen-only fallback path. UI gracefully shows null placeholders. Mock data mode for development |
| **Nansen API schema changes** | Backend breaks silently | Pydantic models with `model_config = ConfigDict(extra="ignore")` — unknown fields are ignored. Health endpoint pings each Nansen endpoint periodically |
| **Large position/trade datasets** | Slow API responses, frontend lag | Backend pagination limits (max 100 per request). Frontend virtual scrolling for tables. Cache hot paths aggressively |
| **CORS / proxy issues** | Frontend can't reach backend | FastAPI CORS middleware configured in Phase 1. Vite dev server proxy as backup. Both documented in README |
| **Chart rendering performance** | PnL curves with 1000+ points lag | Lightweight Charts handles 10K+ points natively. Downsample Recharts data to ~200 points for timelines |

### Prototype First
1. **Phase 1 positions endpoint + table** — validates full data flow end-to-end in ~1 day
2. **Consensus computation** — validate the smart money aggregation logic returns sensible results before building the UI
3. **PnL curve from trades** — test that cumulative sum of `closed_pnl` produces a reasonable curve before building the chart

---

## Development Workflow

```bash
# Terminal 1: Backend
cd hyper-strategies-pnl-weighted
pip install -e ".[backend]"    # or: pip install fastapi uvicorn cachetools
python -m backend.run           # http://localhost:8000

# Terminal 2: Frontend
cd frontend
npm install
npm run dev                     # http://localhost:5173

# Both (after Makefile)
make dev                        # starts both via concurrently/tmux
```

Frontend `.env`:
```
VITE_API_URL=http://localhost:8000
```

Backend `.env` (same existing `.env`):
```
NANSEN_API_KEY=your_key_here
NANSEN_BASE_URL=https://api.nansen.ai
MOCK_STRATEGY_DATA=false
```
