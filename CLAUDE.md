# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Hyperliquid copytrading system that mirrors aggregate positioning of top perp traders via position snapshot rebalancing. Python 3.12, src layout, SQLite (WAL mode).

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run all tests (306 tests, ~5s)
pytest

# Run a single test file
pytest tests/test_scoring.py

# Run a single test by name
pytest tests/test_scoring.py -k "test_tier1_filter"

# Run with verbose output
pytest -v

# Run the system (paper trade mode, default)
snap
# or
python -m snap.main --db-path ./data/snap.db --account-value 10000
```

No linter or formatter is configured. No CI pipeline exists.

## Architecture

The system runs as a single async process with a tick-based scheduler (`scheduler.py`) coordinating four cadences:

1. **Daily 00:00 UTC** — `refresh_trader_universe()`: fetch Nansen leaderboard → filter → score → select top 15
2. **Every 4h** — Rebalance: snapshot positions → compute weighted targets → risk overlay → diff → execute orders
3. **Every 60s** — Monitor: check stop-loss, trailing stop, time-stop on all open positions
4. **Every 5m** — Ingest: fetch latest trade history for tracked traders

### Data flow

```
Nansen API → ingestion.py → SQLite (9 tables)
                                ↓
scoring.py (filter + rank) → trader_scores table
                                ↓
portfolio.py (target + risk overlay) → RebalanceAction[]
                                ↓
execution.py (order routing) → orders/positions tables
                                ↓
monitoring.py (stop enforcement) → closes positions via execution
```

### Key module responsibilities

- **`config.py`** — All constants (risk caps, scoring weights, slippage, cadences). Env vars loaded via `python-dotenv` from project root `.env`.
- **`models.py`** — Pydantic models for 3 Nansen API endpoints. Nansen returns numeric fields as strings; models coerce to float.
- **`database.py`** — `init_db(path)` creates all 9 tables; `get_connection(path)` returns a WAL-mode `sqlite3.Connection`.
- **`nansen_client.py`** — Async httpx client with sliding-window rate limiter, retry with backoff, pagination. Two rate limit tiers: leaderboard (fast) and profiler (7s min interval).
- **`scoring.py`** — Multi-stage pipeline: tier-1 filter → consistency gate → trade metrics → quality gate → normalized scores → composite score with recency decay and style multiplier.
- **`portfolio.py`** — `compute_target_portfolio()` aggregates score-weighted positions. `apply_risk_overlay()` applies 6 sequential caps. `compute_rebalance_diff()` produces OPEN/CLOSE/ADJUST/NOOP actions.
- **`execution.py`** — `HyperliquidClient` ABC with `PaperTradeClient` implementation. `execute_rebalance()` orchestrates order placement with slippage management and fill polling.
- **`monitoring.py`** — Continuous loop checking stops. Shares `rebalance_lock` (asyncio.Lock) with scheduler to prevent concurrent position modifications.
- **`scheduler.py`** — `SystemScheduler` with `SchedulerState` enum. Priority order: refresh > rebalance > ingestion > monitor. Persists last-run timestamps to `system_state` table for startup recovery.
- **`observability.py`** — Structured JSON logging, metrics collection, 6 alert conditions, dashboard export, health-check file.
- **`audit.py`** — Pre-go-live verification: `audit_risk_caps()`, `verify_stop_triggers()`, `compare_paper_pnl()`, markdown report generation.

### Concurrency model

All IO is async (httpx for HTTP, asyncio for scheduling). The `rebalance_lock` mutex in `monitoring.py` is shared between the monitor loop and the rebalance cycle to prevent race conditions on position state. The scheduler uses `asyncio.Event` (`stop_event`) for graceful SIGINT/SIGTERM shutdown.

## Testing conventions

- **`conftest.py`** provides a `db_conn` fixture → in-memory SQLite with all tables created
- HTTP mocking via `respx` (not `unittest.mock` for HTTP)
- All async tests run automatically via `pytest-asyncio` with `asyncio_mode = "auto"`
- Tests use `tmp_path` for any file-based DB needs
- Test files mirror source: `test_scoring.py` tests `scoring.py`, etc.

## Important gotchas

- Nansen API returns position fields as **strings** that must be parsed to float (handled by Pydantic models in `models.py`)
- Position side is derived from the **sign of `size`** field: negative = Short, positive = Long
- The Nansen profiler endpoints have aggressive rate limiting (~10 req/60s window). The `_RateLimiter` uses a 7-second minimum interval and persistent state file at `/tmp/snap_nansen_rate_state_*.json`
- `config.py` constants are imported directly (e.g., `from snap.config import MAX_LEVERAGE`), not accessed through a config object
- Paper trade mode is the default (`SNAP_PAPER_TRADE=true`). Live client is a placeholder ABC — `PaperTradeClient` is the only concrete implementation.
