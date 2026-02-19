# Hyper-Signals Dashboard

Web-based UI dashboard for the Hyper-Signals Hyperliquid perpetual trading intelligence system.

## Prerequisites

- **Node.js** >= 20
- **Python** >= 3.11
- **Nansen API key** (set in `.env` at project root)

## Setup

From the project root:

```bash
# Install all dependencies (backend + frontend)
make install

# Or install separately:
pip install -e ".[backend]"
cd frontend && npm install
```

Copy `.env.example` to `.env` and set your API key:

```
NANSEN_API_KEY=your_key_here
```

### Optional env vars

| Variable | Default | Description |
|---|---|---|
| `MOCK_STRATEGY_DATA` | `false` | Set `true` to use mock Strategy #9 scores/allocations |
| `CACHE_TTL_POSITIONS` | `300` | Position cache TTL in seconds |
| `CACHE_TTL_LEADERBOARD` | `3600` | Leaderboard cache TTL in seconds |
| `BACKEND_PORT` | `8000` | Backend server port |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowed origin |

## Running Locally

### Both services at once

```bash
make dev
```

### Separately

```bash
# Terminal 1 — Backend (FastAPI on :8000)
make backend

# Terminal 2 — Frontend (Vite on :5173)
make frontend
```

Then open **http://localhost:5173**.

The Vite dev server proxies `/api` requests to the backend automatically.

## Pages

| Path | Page | Description |
|---|---|---|
| `/` | Market Overview | Token cards, consensus direction, smart money flows |
| `/positions` | Position Explorer | Filterable/sortable top positions table |
| `/leaderboard` | Trader Leaderboard | Ranked traders with score breakdowns |
| `/traders/:address` | Trader Deep Dive | PnL curve, trade history, allocation weight |
| `/allocations` | Allocation Dashboard | Weights donut, risk gauges, sizing calculator |

### Keyboard shortcuts

- `1`–`5` — Navigate to pages
- `r` — Refresh current page data

## Production Build

```bash
make build   # Outputs to frontend/dist/
```

## Docker

```bash
make docker-up    # Build and start both services
make docker-down  # Stop
```

## Tech Stack

- **Frontend**: React 19, TypeScript, Vite 7, TailwindCSS 4, TanStack Query/Table, Recharts, Lightweight Charts
- **Backend**: FastAPI, Pydantic v2, async Nansen API client with TTL cache
