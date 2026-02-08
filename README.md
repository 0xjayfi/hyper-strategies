# Hyper Strategies — Entry-Only Signal Generator

Copy smart money "Open" entries on Hyperliquid perps via Nansen, manage exits independently.

## How It Works

```
Nansen Leaderboard ──> Trader Scoring ──> Tracked Set (top 10-15)
                                              │
                                    Poll trades every 5 min
                                              │
                                              ▼
                              9-Step Signal Pipeline
                    (action, size, weight, delay, slippage,
                     timing, consensus, portfolio, sizing)
                                              │
                                              ▼
                          Execute on Hyperliquid (isolated margin)
                                              │
                                              ▼
                           Position Monitor (every 30s)
                    ┌──────────┬──────────┬──────────────┐
                    │ Trailing │  Time    │   Profit     │
                    │  Stops   │  Stops   │   Taking     │
                    └──────────┴──────────┴──────────────┘
```

1. **Score traders** daily from Nansen leaderboard (ROI, Sharpe, win rate, consistency, risk management)
2. **Detect entries** — poll tracked traders for "Open" / qualifying "Add" actions
3. **Filter signals** through confidence, size, freshness, and slippage gates
4. **Size positions** using trader allocation, ROI tiers, leverage penalty, and hard caps
5. **Execute** on Hyperliquid with isolated margin and immediate stop-loss placement
6. **Manage exits** autonomously — trailing stops, 72h time-stops, profit-taking tiers, liquidation detection

## Project Structure

```
src/
  config.py              # All constants + pydantic-settings (.env)
  models.py              # Pydantic data models
  db.py                  # SQLite schema + CRUD
  nansen_client.py       # Async Nansen API wrapper
  trader_scorer.py       # Daily scoring + style classification
  trade_ingestion.py     # Polling loop + signal evaluation pipeline
  sizing.py              # Multi-factor entry sizing algorithm
  executor.py            # Hyperliquid order execution
  position_monitor.py    # Exit management loop
  backtest.py            # Historical simulation + paper trading
  main.py                # Orchestrator / entry point

tests/
  test_sizing.py         # Tiered sizing + leverage penalty + caps
  test_stops.py          # Stop placement + trailing stop logic
  test_filters.py        # Action filter (Open/Add/Close/Reduce)
  test_slippage.py       # Slippage gate checks
  test_time_stop.py      # 72h time-based stop
  test_liquidation.py    # Trader liquidation detection
  test_integration.py    # End-to-end with mocked Nansen API

specs/                   # Design specs and parallelized build plan
ai_docs/                 # Nansen API reference docs
```

## Setup

### Requirements

- Python 3.11+
- A [Nansen](https://www.nansen.ai/) API key
- A Hyperliquid account + private key (for live/paper execution)

### Install Dependencies

```bash
pip install httpx aiosqlite pydantic-settings structlog pytest pytest-asyncio
```

### Configure

Create a `.env` file in the project root:

```env
NANSEN_API_KEY=your_nansen_api_key

# Optional overrides (defaults shown)
PAPER_MODE=true
COPY_RATIO=0.5
MAX_TOTAL_POSITIONS=5
STOP_LOSS_PERCENT=5.0
TRAILING_STOP_PERCENT=8.0
MAX_POSITION_DURATION_HOURS=72
```

All settings are defined in `src/config.py` and can be overridden via environment variables.

## Usage

### Paper Trading (default)

```bash
python -m src.main
```

`PAPER_MODE=true` by default — simulates execution without placing real orders.

### Run Tests

```bash
pytest tests/ -v
```

### Backtest

```python
from src.backtest import Backtester

bt = Backtester(
    start_date="2025-01-01",
    end_date="2025-06-01",
    initial_capital=100_000,
)
await bt.run()
```

Outputs: total return, max drawdown, Sharpe ratio, win rate, profit factor, avg trade duration, and a comparison of our exits vs. copying trader exits.

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `COPY_DELAY_MINUTES` | 15 | Wait before copying to confirm conviction |
| `MAX_PRICE_SLIPPAGE_PERCENT` | 2.0% | Max allowed price drift from trade |
| `COPY_RATIO` | 0.5 | Scale factor on trader's allocation % |
| `MAX_SINGLE_POSITION_USD` | $50,000 | Hard cap per position |
| `MAX_TOTAL_POSITIONS` | 5 | Max concurrent positions |
| `STOP_LOSS_PERCENT` | 5.0% | Hard stop-loss from entry |
| `TRAILING_STOP_PERCENT` | 8.0% | Trailing stop distance |
| `MAX_POSITION_DURATION_HOURS` | 72 | Time-based stop |
| `PROFIT_TAKE_TIER_1/2/3` | 10/20/40% | Profit-taking levels |
