# Snap

Hyperliquid copytrading system via position snapshot rebalancing. Mirrors the aggregate positioning of a curated set of top Hyperliquid perp traders, rebalanced every 4 hours.

## How It Works

1. **Daily** - Refresh trader universe: fetch leaderboard from Nansen, apply filters, score and rank, select top 15
2. **Every 4h** - Rebalance: snapshot tracked traders' positions, compute score-weighted target portfolio, apply risk overlay, diff against current holdings, execute orders
3. **Every 60s** - Monitor: check stop-loss, trailing stop, and time-stop triggers on all open positions
4. **Every 5m** - Ingest latest trade history for tracked traders

## Architecture

```
src/snap/
  config.py          # Configuration constants (risk caps, scoring weights, slippage)
  models.py          # Pydantic models for Nansen API responses
  database.py        # SQLite schema (9 tables) and DB helpers
  nansen_client.py   # Async Nansen API client with retry/pagination/rate-limiting
  ingestion.py       # Data fetching and storage for leaderboard, positions, trades
  scoring.py         # Trader scoring engine (tier-1 filter, style classification, composite score)
  portfolio.py       # Target portfolio computation and 6-step risk overlay
  execution.py       # Order routing, slippage management, fill polling, paper trade client
  monitoring.py      # Stop-loss, trailing stop, time-stop enforcement loop
  backtesting.py     # Execution simulator and backtest metrics (Sharpe, Sortino, drawdown)
  scheduler.py       # Async tick-based scheduler with state machine and graceful shutdown
  observability.py   # Structured JSON logging, metrics, alerts, dashboard export
  audit.py           # Graduation verification (risk cap audit, stop trigger checks)
  tui.py             # Terminal UI display (rich tables for portfolio, scores, status)
  main.py            # CLI entry point with interactive command loop
```

## Setup

Requires Python 3.11+.

```bash
pip install -e .

# For development
pip install -e ".[dev]"
```

Create a `.env` file in the project root:

```
NANSEN_API_KEY=your_api_key_here
```

## Usage

```bash
# Paper trading (default)
snap

# With custom settings
snap --db-path ./data/snap.db --account-value 10000

# Live mode (sends real orders to Hyperliquid)
snap --live --account-value 5000
```

On launch, Snap displays a status bar and portfolio summary. The scheduler runs automatically in the background while you interact via keyboard commands:

| Key | Action |
|-----|--------|
| `r` | Refresh trader universe (fetch leaderboard, score, rank) |
| `b` | Run rebalance cycle (snapshot, target, risk overlay, execute) |
| `m` | Run monitor pass (check stops on all positions) |
| `s` | Show trader scores table (top 15 by composite score) |
| `p` | Show portfolio table (positions, PnL, leverage, margin) |
| `q` | Graceful shutdown (also responds to Ctrl+C / SIGTERM) |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NANSEN_API_KEY` | (required) | Nansen API key |
| `SNAP_PAPER_TRADE` | `true` | Paper trade mode toggle |
| `SNAP_DB_PATH` | `snap.db` | SQLite database path |
| `SNAP_ACCOUNT_VALUE` | `10000` | Starting account value in USD |
| `SNAP_LOG_FILE` | (none) | Optional log file path |
| `SNAP_DASHBOARD_FILE` | (none) | Optional dashboard JSON output path |
| `SNAP_HEALTH_FILE` | `/tmp/snap_health.json` | Health check file for liveness probes |

## Risk Management

| Parameter | Value |
|-----------|-------|
| Max single position | 10% of account or $50K |
| Max total exposure | 50% of account |
| Max positions | 5 |
| Max per-token exposure | 15% of account |
| Max leverage | 5x (isolated) |
| Stop-loss | 5% |
| Trailing stop | 8% |
| Max hold time | 72 hours |

## Testing

```bash
pytest
```

~340 tests covering all modules with `respx` for HTTP mocking and `tmp_path` for DB isolation.

## Data Sources

- **Nansen API**: Perp Leaderboard, Address Perp Positions, Address Perp Trades
- **Execution**: Hyperliquid perps (paper mode implemented; live client is a placeholder)
