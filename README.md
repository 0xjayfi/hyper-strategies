# Hyper Strategies — PnL-Weighted Dynamic Allocation

A Hyperliquid copytrading system that dynamically allocates capital across tracked traders based on composite scoring of recent PnL performance. Uses [Nansen](https://www.nansen.ai/) API endpoints for on-chain trader intelligence.

## Overview

Instead of allocating equally to all tracked traders, this system computes a multi-factor composite score for each trader and converts scores into normalized allocation weights. The allocation engine feeds into three downstream copytrading strategies:

- **Strategy #2 — Index Portfolio Rebalancing**: Aggregate weighted positions into a single target portfolio
- **Strategy #3 — Consensus Voting**: Weighted long/short signal per token across traders
- **Strategy #5 — Per-Trade Sizing**: Proportionally size copied trades by allocation weight

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Scheduler (cron)                      │
│  daily: refresh_leaderboard()                           │
│  every 6h: recompute_trade_metrics()                    │
│  every 15m: monitor_positions()                         │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
           ▼              ▼              ▼
┌──────────────┐ ┌────────────────┐ ┌──────────────────┐
│ NansenClient │ │ MetricsEngine  │ │ PositionMonitor  │
│  (API layer) │ │ (scoring)      │ │ (liquidation     │
│              │ │                │ │  detection)       │
└──────┬───────┘ └───────┬────────┘ └────────┬─────────┘
       │                 │                    │
       ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                     DataStore (SQLite)                   │
│  traders, trade_metrics, scores, allocations, blacklist  │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  AllocationEngine                        │
│  get_trader_allocation(trader_id) -> weight              │
│  get_all_allocations() -> {trader_id: weight}            │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
           ▼              ▼              ▼
     Strategy #2    Strategy #3    Strategy #5
     (Index Rebal)  (Consensus)    (Per-Trade)
```

## Scoring Pipeline

Each trader receives a composite score from six weighted components:

| Component | Weight | Description |
|-----------|--------|-------------|
| ROI | 25% | Normalized 30d ROI (capped at 100%) |
| Sharpe | 20% | Pseudo-Sharpe ratio (avg return / std return) |
| Win Rate | 15% | Rescaled from [0.35, 0.85] to [0, 1] |
| Consistency | 20% | Multi-timeframe profitability (7d/30d/90d) |
| Smart Money | 10% | Bonus for Nansen-labeled addresses |
| Risk Mgmt | 10% | Leverage discipline + margin type + drawdown |

The raw score is then adjusted by:
- **Style multiplier**: SWING (1.0x), POSITION (0.85x), HFT (0.4x)
- **Recency decay**: Exponential decay with 7-day half-life
- **7d ROI tier**: 1.0x (>10%), 0.75x (0-10%), 0.5x (<0%)

## Risk Controls

- **Anti-luck filters**: Multi-timeframe profitability gates, win rate bounds, minimum trade count, profit factor thresholds
- **Blacklist**: 14-day cooldown on liquidation detection
- **Max 5 positions** in the allocation set
- **Max 40%** single trader weight
- **15% max daily weight change** to prevent performance-chasing whipsaws
- **Softmax with T=2.0** prevents over-concentration on a single trader

## Project Structure

```
src/
  nansen_client.py        # Async API wrapper with retry/rate-limit handling
  models.py               # Pydantic models for API responses
  datastore.py            # SQLite store (7 tables)
  metrics.py              # Derived trade metrics (win rate, Sharpe, PF, etc.)
  scoring.py              # Composite scoring engine (6 components)
  filters.py              # Anti-luck filters & blacklist gates
  allocation.py           # Score-to-weight conversion (softmax + risk caps)
  position_monitor.py     # Liquidation detection (15m polling)
  scheduler.py            # Orchestration & scheduling
  strategy_interface.py   # Downstream strategy APIs (#2, #3, #5)
  backtest.py             # Historical allocation simulation
  config.py               # All tunable constants

tests/
  conftest.py             # Shared fixtures (make_trade, make_metrics)
  test_metrics.py         # Metric calculation tests
  test_scoring.py         # Scoring component tests
  test_filters.py         # Anti-luck filter tests
  test_blacklist.py       # Blacklist & cooldown tests
  test_allocation.py      # Allocation pipeline tests
  test_strategy_interface.py  # Strategy interface tests
  test_backtest.py        # Backtesting framework tests
  test_datastore.py       # DataStore CRUD tests
  test_nansen_client_smoke.py  # API integration smoke tests

specs/
  pnl-weighted-dynamic-allocation.md             # Full implementation plan
  pnl-weighted-dynamic-allocation-parallelized.md # Parallelized build plan
```

## Setup

### Requirements

- Python 3.11+
- Nansen API key

### Installation

```bash
pip install -e ".[dev]"
```

### Configuration

Create a `.env` file in the project root:

```env
NANSEN_API_KEY=your_api_key_here
NANSEN_BASE_URL=https://api.nansen.ai
```

## Running Tests

```bash
# Run all unit tests
pytest

# Run with verbose output
pytest -v

# Run a specific test module
pytest tests/test_scoring.py

# Run smoke tests (requires valid API key)
pytest tests/test_nansen_client_smoke.py
```

## Scheduling

The system runs on three update cycles:

| Task | Frequency | Description |
|------|-----------|-------------|
| Leaderboard refresh | Daily 00:00 UTC | Discover traders, store snapshots |
| Metrics/Scores/Allocations | Every 6 hours | Full recompute pipeline |
| Position monitor | Every 15 minutes | Liquidation detection |
| Blacklist cleanup | Daily | Remove expired entries |

## Key Design Decisions

- **SQLite** for storage — lightweight, single-process, no external dependencies
- **Softmax (T=2.0)** for score-to-weight — smoother than linear normalization, prevents winner-takes-all
- **Exponential recency decay** — inactive traders naturally fade without hard cutoffs
- **Turnover limits** — 15% max daily weight change prevents chasing short-term performance
- **Trend trader exception** — low win rate (<35%) traders pass filters if profit factor >2.5

## License

Private — all rights reserved.
