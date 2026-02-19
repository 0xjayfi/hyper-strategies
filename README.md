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
  collector.py       # Data-only collection (leaderboard + trades, no scoring/trading)
  variants.py        # Scoring strategy variants (V1-V5) for grid search and live runs
  tui.py             # Classic Rich-based terminal UI (tables, status bar)
  tui_app.py         # Textual TUI application (onboarding wizard + live dashboard)
  main.py            # CLI entry point, routes to Textual TUI or classic mode
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

### CLI Arguments

```bash
# Launch the Textual TUI (default) with onboarding wizard
snap

# Use the classic Rich-based TUI (no onboarding wizard, stdin command loop)
snap --classic

# Custom database and account value
snap --db-path ./data/snap.db --account-value 10000

# Split databases: separate data ingestion from strategy state
snap --data-db ./data/nansen.db --strategy-db ./data/strategy.db

# Live mode (sends real orders to Hyperliquid)
snap --live --account-value 5000
```

| Flag | Default | Description |
|------|---------|-------------|
| `--live` | off | Enable live trading (mutually exclusive with `--paper`) |
| `--paper` | on | Paper-trade mode (default when neither flag given) |
| `--db-path` | `snap.db` | SQLite database path (used when data/strategy are the same DB) |
| `--data-db` | same as `--db-path` | Separate DB for Nansen data (traders, trades, positions) |
| `--strategy-db` | same as `--db-path` | Separate DB for strategy state (scores, orders, system state) |
| `--account-value` | `10000` | Starting account value in USD |
| `--log-file` | none | Optional log file path |
| `--dashboard-file` | none | Optional dashboard JSON output path |
| `--health-file` | `/tmp/snap_health.json` | Health check file for liveness probes |
| `--classic` | off | Use the classic Rich-based TUI instead of the Textual interface |

### Textual TUI (Default)

On launch, the Textual TUI walks through a 4-step onboarding wizard:

1. **Welcome** - Overview of the system workflow and scoring parameters
2. **Strategy** - Choose a scoring variant (V1-V5), with live parameter preview
3. **Start Stage** - Pick where to begin the pipeline:
   - **Collect Data Only** - Fetch leaderboard and trade data without scoring or trading
   - **Fresh Start (Daily Flow)** - Full pipeline from scratch
   - **From Rebalancing** - Skip trader refresh, use existing scores
   - **Monitor Only** - Only check stops on existing positions
4. **Configuration** - Adjust account value, rebalance interval, max hold time, monitor interval, max positions

After onboarding, the main dashboard displays a fixed-layout grid with:
- **Status bar** - Mode, strategy variant, account value, scheduler state, session uptime, data freshness, countdown to next rebalance/refresh
- **Portfolio panel** - Live positions with entry/live price, PnL, leverage, margin, sparkline trend
- **Scores panel** - Top 15 eligible traders ranked by composite score
- **Log panel** - Streaming system logs with color-coded severity

Dashboard keyboard bindings:

| Key | Action |
|-----|--------|
| `r` | Refresh trader universe (skips API if data < 24h old, scores from cache) |
| `c` | Score from cache only (no API calls, re-scores existing data in DB) |
| `b` | Run rebalance cycle (snapshot, target, risk overlay, execute) |
| `m` | Run monitor pass (check stops on all positions) |
| `s` | Refresh scores table |
| `p` | Refresh portfolio table |
| `v` | Cycle to next scoring variant (re-scores from cache, no API calls) |
| `q` | Graceful shutdown |

### Classic TUI (`--classic`)

The classic mode uses Rich tables printed to stdout with a stdin command loop. Same keybindings as above (except `v`), entered as single characters followed by Enter.

### Scoring Variants

Five scoring strategy variants are available, selectable during onboarding or cycled live with `v`:

| Variant | Label | Description |
|---------|-------|-------------|
| V1 | Baseline | Median filter cutoffs, balanced scoring weights |
| V2 | Quality Focused | 65th percentile filter, 45%+ win rate, 3.0+ profit factor |
| V3 | Volume Relaxed | 35th percentile, accepts 25%+ win rate, wider net |
| V4 | ROI Heavy | 35% ROI + 30% Sharpe weight, favors outsized returns |
| V5 | Hybrid Balanced | 45th percentile, 0.9 position multiplier, steady exposure |

Switching variants re-scores traders from cached data instantly without additional API calls.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NANSEN_API_KEY` | (required) | Nansen API key |
| `SNAP_PAPER_TRADE` | `true` | Paper trade mode toggle |
| `SNAP_DB_PATH` | `snap.db` | SQLite database path |
| `SNAP_DATA_DB_PATH` | (none) | Separate data DB path (overrides `--data-db`) |
| `SNAP_STRATEGY_DB_PATH` | (none) | Separate strategy DB path (overrides `--strategy-db`) |
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
