# Position-Based Scoring & Scheduler Integration Design

**Date:** 2026-02-26
**Branch:** feat/pnl-weighted

## Problem

The current scheduler fetches trades for every tracked trader every 6 hours. The trades endpoint (`profiler/perp-trades`) has a strict 7s rate limit and auto-paginates up to 1000 records. With 50 traders across 3 windows (7d/30d/90d), a full recompute cycle takes 30+ minutes and burns through API quota. Meanwhile, the positions endpoint (`profiler/perp-positions`) returns a complete snapshot in one fast call and is far less rate-limited.

## Solution

Two-tier scoring system in a single backend process:

1. **Scheduler (hourly, positions-only):** Snapshot positions for 100 traders, score them using position-derived metrics, compute allocations. Zero trades endpoint calls.
2. **Assess page (on-demand, trades-based):** When a user evaluates a specific address, fetch trades for the full 10-strategy assessment. Unchanged from today.
3. **Scheduler integrated into FastAPI lifespan** via `asyncio.create_task` — no more separate `python -m src` process.

## Architecture

```
FastAPI Backend (single process)
├── HTTP Routers (11 endpoints)
│   └── Shared: NansenClient + DataStore + CacheLayer
├── Background Scheduler (asyncio.create_task)
│   ├── Task 1: Leaderboard refresh (daily, top 100 = 2 pages)
│   ├── Task 2: Position sweep (every 1 hour, 100 traders)
│   ├── Task 3: Score + allocate (every 1 hour, after sweep, 0 API calls)
│   └── Task 4: Cleanup (daily)
```

### Rate Limiter Split

The NansenClient gets 3 separate rate limiters:

| Limiter | Endpoints | Config | Used by |
|---------|-----------|--------|---------|
| Leaderboard | `perp-leaderboard`, `tgm/*`, `perp-screener` | 20/s, 300/min, 0s gap | Leaderboard refresh, market overview |
| Position | `profiler/perp-positions` | 5/s, 100/min, 0s gap | Hourly position sweep, assess page |
| Trade | `profiler/perp-trades` | 1/s, 9/min, 7s gap | Assess page only |

Routing logic in `_request()`:
- `/profiler/perp-positions` → position limiter
- `/profiler/perp-trades` → trade limiter
- Everything else → leaderboard limiter

### API Call Budget

| Endpoint | Calls/day | Peak calls/min |
|----------|-----------|----------------|
| `profiler/perp-positions` | 2,400 | ~100 (during sweep burst) |
| `profiler/perp-trades` | 50-200 | <1 (assess page only) |
| `perp-leaderboard` | 2 | <1 |
| **Total** | **~2,600** | |

## Position-Based Scoring Engine

Replaces the old 6-component trade-based composite score for the scheduler's allocation pipeline. All metrics derived from the `position_snapshots` DB table — zero API calls during scoring.

### 6 Components

#### 1. Account Growth (30%)

Primary signal. Tracks `account_value` over 30 days from hourly snapshots.

**Calculation:**
- Compute raw growth: `(current_account_value - start_account_value) / start_account_value`
- Validate against position-level PnL: sum unrealized PnL deltas + inferred realized PnL from closed positions
- **Deposit/withdrawal detection:** If account value delta diverges from position-level PnL by > $1,000 AND > 10% of account value in a single snapshot interval, flag as deposit/withdrawal and exclude that delta
- Position disappears between snapshots → infer close, estimate realized PnL from last known unrealized PnL
- **Normalization:** 10%+ monthly growth = 1.0, 0% = 0.0, negative = 0.0

#### 2. Drawdown Discipline (20%)

Max peak-to-trough drawdown in account value over 30 days.

**Calculation:**
- Track running peak of `account_value` across snapshots
- Drawdown at each snapshot: `(peak - current) / peak`
- Max drawdown = worst observed
- Exclude snapshots flagged as deposit/withdrawal events
- **Normalization:** 0% drawdown = 1.0, 25% = 0.5, 50%+ = 0.0

#### 3. Leverage Discipline (15%)

Average effective portfolio leverage across all snapshots.

**Calculation:**
- Per snapshot: `total_position_value / account_value` = effective leverage
- Average across the scoring window
- **Normalization:** 1-3x average = 1.0, 10x = 0.5, 20x+ = 0.0
- Penalizes leverage volatility: `std(leverage) > threshold` reduces score

#### 4. Liquidation Distance (15%)

How far positions sit from liquidation on average.

**Calculation:**
- Per position: `|entry_price - liquidation_price| / entry_price` (weighted by position value)
- Average across all positions across all snapshots in the window
- **Normalization:** 30%+ average distance = 1.0, 10% = 0.5, <5% = 0.0

#### 5. Position Diversity (10%)

Concentration risk across tokens.

**Calculation:**
- Per snapshot: compute HHI (Herfindahl-Hirschman Index) across position values
- `HHI = sum((position_value_i / total_value)^2)`
- HHI = 1.0 means single position, HHI = 0.2 means 5 equal positions
- Average across snapshots
- **Normalization:** HHI < 0.25 = 1.0 (well-diversified), HHI = 1.0 = 0.2 (single position)

#### 6. Consistency (10%)

Steadiness of account growth — Sharpe-like ratio.

**Calculation:**
- Compute daily account value deltas (excluding flagged deposit/withdrawal events)
- `consistency = mean(daily_deltas) / std(daily_deltas)` if std > 0, else 0
- **Normalization:** ratio >= 1.0 = 1.0, 0 = 0.0

### Score Formula

```
raw_score = 0.30 * account_growth
          + 0.20 * drawdown_discipline
          + 0.15 * leverage_discipline
          + 0.15 * liquidation_distance
          + 0.10 * position_diversity
          + 0.10 * consistency

final_score = raw_score * smart_money_bonus * recency_decay
```

- `smart_money_bonus`: 1.1 if Nansen "Smart Money" label, else 1.0
- `recency_decay`: based on last snapshot with open positions, 7-day half-life (same as today)

### Anti-Luck Filters (Position-Based)

Adapted gates using position-derived data:

| Gate | Condition | Rationale |
|------|-----------|-----------|
| Minimum snapshots | >= 48 snapshots (2 days) in 30-day window | Need enough data to score |
| Account growth positive | 30-day account growth > 0 (after deposit/withdrawal exclusion) | Must be profitable |
| Max leverage | Average effective leverage < 25x | Excessive leverage = gambling |
| Blacklist check | Not on blacklist | Unchanged |
| Min account value | Latest account_value > $1,000 | Filter dust accounts |

## Scheduler Integration

### FastAPI Lifespan

```python
@asynccontextmanager
async def lifespan(app):
    # Initialize shared instances
    nansen_client = NansenClient(...)
    datastore = DataStore(...)
    cache = CacheLayer(...)
    risk_config = RiskConfig(...)

    # Store on app.state (for router dependency injection)
    app.state.nansen_client = nansen_client
    app.state.datastore = datastore
    app.state.cache = cache

    # Launch scheduler as background task
    scheduler_task = asyncio.create_task(
        run_scheduler(nansen_client, datastore, risk_config)
    )

    yield

    # Shutdown
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    await nansen_client.close()
    datastore.close()
```

### Startup Sequence

1. FastAPI boots, initializes NansenClient, DataStore, CacheLayer
2. `run_scheduler()` starts as background task
3. **Immediate initial sweep:** snapshot all 100 traders' positions (~2 min)
4. **Immediate initial scoring:** compute scores from available snapshots
5. API starts serving real data
6. Enter periodic loop (1-hour position sweeps, 1-hour scoring, daily leaderboard)

### Revised Scheduler Loop

```
while True:
    sleep(60)  # check every minute

    if hourly_interval_elapsed:
        1. Position sweep: snapshot 100 traders
        2. Liquidation detection: compare to previous snapshots
        3. Position scoring: compute 6-component scores from DB
        4. Allocation: softmax → risk caps → turnover limits → store

    if daily_interval_elapsed:
        5. Leaderboard refresh: fetch top 100 (2 pages)
        6. Cleanup: expire blacklist, enforce 90-day retention
```

## What Changes vs What Stays

### Stays the same
- All frontend pages and components
- Assess page and its 10-strategy trade-based engine
- DataStore schema (`position_snapshots` table already has all needed fields)
- Allocation engine (softmax, risk caps, turnover limits)
- API endpoint contracts and response shapes

### Changes

| File | Change |
|------|--------|
| `src/config.py` | New position limiter config. New scoring weights. Intervals: snapshot=1h, score=1h, leaderboard top 100 (2 pages). |
| `src/nansen_client.py` | Split profiler limiter into position + trade. 3-way routing logic. |
| `src/scheduler.py` | Rewrite: hourly position sweep + scoring, daily leaderboard. Remove trades fetching from cycle. |
| `src/filters.py` | Adapt anti-luck gates to position-based thresholds. Keep trade-based filters for assess page. |
| `backend/main.py` | Integrate scheduler into lifespan via `asyncio.create_task`. |
| `src/__main__.py` | Deprecate or convert to thin wrapper that starts uvicorn. |

### New files

| File | Purpose |
|------|---------|
| `src/position_metrics.py` | Derive metrics from snapshot time series: account growth, drawdown, effective leverage, liquidation distance, concentration, consistency. Deposit/withdrawal detection. |
| `src/position_scoring.py` | 6-component scoring engine. Normalization functions. Smart money bonus + recency decay. |

### Preserved for assess page

| File | Status |
|------|--------|
| `src/metrics.py` | `compute_trade_metrics()` stays — used by assess page |
| `src/scoring.py` | Old trade-based scoring stays — used by assess page's composite score display |
| `src/assessment/` | Entire assessment engine unchanged |
