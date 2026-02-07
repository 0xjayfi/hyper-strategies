# Position Snapshot Rebalancing — Implementation Plan

> **Strategy #2**: Periodically snapshot tracked traders' current perp positions and rebalance our portfolio to match a score-weighted "index" of smart money allocations on Hyperliquid.

---

## 1. Problem Statement & Objectives

**Goal**: Build a copytrading "index fund" that mirrors the aggregate positioning of a curated set of top Hyperliquid perp traders, rebalanced every 4-6 hours.

**Core Loop**:
1. Daily: refresh the trader universe (leaderboard -> filter -> score -> top N).
2. Every 4-6h: snapshot each tracked trader's positions, compute a target portfolio, diff against current holdings, execute rebalances.
3. Continuously: monitor stops, trailing stops, time-stops, exposure limits, and health.

**Data Sources** (Nansen only):

| # | Endpoint | URL | Purpose |
|---|----------|-----|---------|
| 1 | Perp Leaderboard | `POST /api/v1/perp-leaderboard` | Trader universe, `account_value`, `total_pnl`, `roi`, `trader_address_label` |
| 2 | Address Perp Positions | `POST /api/v1/profiler/perp-positions` | Per-trader current positions (entry, size, leverage, liquidation, uPnL) |
| 3 | Address Perp Trades | `POST /api/v1/profiler/perp-trades` | Trade history for derived metrics (win rate, hold time, style) |

**Execution Venue**: Hyperliquid perps — market/limit/stop orders, isolated margin.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        SCHEDULER (cron / APScheduler)            │
│  daily_refresh_traders | rebalance_4h | monitor_1m | trades_5m   │
└────────┬──────────────────┬──────────────────┬───────────────────┘
         │                  │                  │
         ▼                  ▼                  ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────────────┐
│  INGESTION     │ │ TARGET         │ │ MONITORING             │
│  SERVICE       │ │ PORTFOLIO      │ │ SERVICE                │
│                │ │ SERVICE        │ │                        │
│ - leaderboard  │ │ - aggregate    │ │ - stop-loss checker    │
│ - positions    │ │   positions    │ │ - trailing stop update │
│ - trades       │ │ - score-weight │ │ - time-stop enforcer   │
│ - rate limiter │ │ - apply caps   │ │ - exposure monitor     │
└───────┬────────┘ └───────┬────────┘ └───────────┬────────────┘
        │                  │                      │
        ▼                  ▼                      │
┌────────────────┐ ┌────────────────┐             │
│  SCORING       │ │ RISK OVERLAY   │             │
│  ENGINE        │ │ SERVICE        │◄────────────┘
│                │ │                │
│ - tier1 filter │ │ - position cap │
│ - style class  │ │ - exposure cap │
│ - composite    │ │ - directional  │
│   score calc   │ │ - leverage cap │
└───────┬────────┘ └───────┬────────┘
        │                  │
        ▼                  ▼
┌────────────────┐ ┌────────────────┐
│  DATA STORE    │ │ EXECUTION      │
│  (SQLite/PG)   │ │ ENGINE         │
│                │ │                │
│ - traders      │ │ - order router │
│ - snapshots    │ │ - slippage mgr │
│ - scores       │ │ - fill tracker │
│ - targets      │ │ - HL SDK calls │
│ - orders/fills │ └────────────────┘
│ - pnl_history  │
└────────────────┘
```

### Module Descriptions

| Module | Responsibility |
|--------|---------------|
| **Ingestion Service** | Fetches data from Nansen endpoints with rate limiting, pagination, retry. Stores raw snapshots. |
| **Scoring Engine** | Applies tier-1 filters, style classification, computes composite TRADER_SCORE. Outputs ranked trader list. |
| **Target Portfolio Service** | Aggregates tracked traders' positions into a score-weighted target allocation per token/side. |
| **Risk Overlay Service** | Applies all caps (position, exposure, directional, per-token), leverage limits, and validates target before execution. |
| **Execution Engine** | Diffs current vs target portfolio, generates orders (market/limit), sends to Hyperliquid, tracks fills. |
| **Monitoring Service** | Runs every 60s. Checks stop-loss, trailing stop, time-stop, liquidation proximity, exposure drift. |
| **Scheduler** | Orchestrates all cadences: daily trader refresh, 4-6h rebalance, 5m trade ingestion, 1m monitoring. |
| **Data Store** | Persistent storage for all state. SQLite for dev/paper, PostgreSQL for production. |

---

## 3. Data Storage Schema

### 3.1 `traders`

```sql
CREATE TABLE traders (
    address         TEXT PRIMARY KEY,          -- 0x... 42 chars
    label           TEXT,                      -- e.g. "Smart Money", "Fund"
    account_value   REAL,                      -- USD from leaderboard
    first_seen_at   TIMESTAMP DEFAULT NOW(),
    blacklisted     BOOLEAN DEFAULT FALSE,
    blacklist_reason TEXT,
    blacklist_until TIMESTAMP,
    updated_at      TIMESTAMP
);
```

### 3.2 `trader_scores`

```sql
CREATE TABLE trader_scores (
    id              SERIAL PRIMARY KEY,
    address         TEXT REFERENCES traders(address),
    scored_at       TIMESTAMP DEFAULT NOW(),
    -- raw metrics
    roi_7d          REAL,
    roi_30d         REAL,
    roi_90d         REAL,
    pnl_7d          REAL,
    pnl_30d         REAL,
    pnl_90d         REAL,
    win_rate        REAL,
    profit_factor   REAL,
    pseudo_sharpe   REAL,
    trade_count     INTEGER,
    avg_hold_hours  REAL,
    trades_per_day  REAL,
    style           TEXT,                      -- HFT / SWING / POSITION
    -- normalized components
    normalized_roi  REAL,
    normalized_sharpe REAL,
    normalized_win_rate REAL,
    consistency_score REAL,
    smart_money_bonus REAL,
    risk_mgmt_score REAL,
    -- multipliers
    style_multiplier REAL,
    recency_decay   REAL,
    -- final
    composite_score REAL,
    -- eligibility
    passes_tier1    BOOLEAN,
    passes_quality  BOOLEAN,
    is_eligible     BOOLEAN
);
CREATE INDEX idx_scores_eligible ON trader_scores(is_eligible, composite_score DESC);
```

### 3.3 `position_snapshots`

```sql
CREATE TABLE position_snapshots (
    id              SERIAL PRIMARY KEY,
    snapshot_batch  TEXT NOT NULL,              -- UUID grouping one rebalance cycle
    address         TEXT REFERENCES traders(address),
    token_symbol    TEXT NOT NULL,
    side            TEXT NOT NULL,              -- Long / Short (derived from sign of size)
    size            REAL,
    entry_price     REAL,
    mark_price      REAL,
    position_value_usd REAL,
    leverage_value  REAL,
    leverage_type   TEXT,                       -- cross / isolated
    liquidation_price REAL,
    unrealized_pnl  REAL,
    margin_used     REAL,
    account_value   REAL,                      -- margin_summary_account_value_usd
    captured_at     TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_snap_batch ON position_snapshots(snapshot_batch);
```

### 3.4 `trade_history`

```sql
CREATE TABLE trade_history (
    id              SERIAL PRIMARY KEY,
    address         TEXT REFERENCES traders(address),
    token_symbol    TEXT,
    action          TEXT,                      -- Open / Close / Add / Reduce
    side            TEXT,
    size            REAL,
    price           REAL,
    value_usd       REAL,
    closed_pnl      REAL,
    fee_usd         REAL,
    timestamp       TIMESTAMP,
    fetched_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(address, token_symbol, timestamp, action)
);
```

### 3.5 `target_allocations`

```sql
CREATE TABLE target_allocations (
    id              SERIAL PRIMARY KEY,
    rebalance_id    TEXT NOT NULL,              -- UUID for this rebalance
    token_symbol    TEXT NOT NULL,
    side            TEXT NOT NULL,
    raw_weight      REAL,                      -- before risk overlay
    capped_weight   REAL,                      -- after risk overlay
    target_usd      REAL,                      -- capped_weight * deployable capital
    target_size     REAL,                      -- target_usd / mark_price
    computed_at     TIMESTAMP DEFAULT NOW()
);
```

### 3.6 `orders`

```sql
CREATE TABLE orders (
    id              SERIAL PRIMARY KEY,
    rebalance_id    TEXT,
    token_symbol    TEXT NOT NULL,
    side            TEXT NOT NULL,
    order_type      TEXT NOT NULL,              -- MARKET / LIMIT / STOP
    intended_usd    REAL,
    intended_size   REAL,
    limit_price     REAL,
    stop_price      REAL,
    status          TEXT DEFAULT 'PENDING',     -- PENDING / SENT / FILLED / PARTIAL / CANCELLED / FAILED
    hl_order_id     TEXT,                      -- Hyperliquid order ID
    created_at      TIMESTAMP DEFAULT NOW(),
    sent_at         TIMESTAMP,
    filled_at       TIMESTAMP,
    filled_size     REAL,
    filled_avg_price REAL,
    filled_usd      REAL,
    slippage_bps    REAL,
    fee_usd         REAL,
    error_msg       TEXT
);
```

### 3.7 `our_positions`

```sql
CREATE TABLE our_positions (
    id              SERIAL PRIMARY KEY,
    token_symbol    TEXT NOT NULL UNIQUE,       -- MAX_POSITIONS_PER_TOKEN = 1
    side            TEXT NOT NULL,
    size            REAL,
    entry_price     REAL,
    current_price   REAL,
    position_usd    REAL,
    unrealized_pnl  REAL,
    stop_loss_price REAL,
    trailing_stop_price REAL,
    trailing_high   REAL,                      -- highest mark for trailing stop calc
    opened_at       TIMESTAMP,
    max_close_at    TIMESTAMP,                 -- opened_at + MAX_POSITION_DURATION_HOURS
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

### 3.8 `pnl_ledger`

```sql
CREATE TABLE pnl_ledger (
    id              SERIAL PRIMARY KEY,
    token_symbol    TEXT,
    side            TEXT,
    entry_price     REAL,
    exit_price      REAL,
    size            REAL,
    realized_pnl    REAL,
    fees_total      REAL,
    hold_hours      REAL,
    exit_reason     TEXT,                      -- REBALANCE / STOP_LOSS / TRAILING_STOP / TIME_STOP / MANUAL
    closed_at       TIMESTAMP DEFAULT NOW()
);
```

### 3.9 `system_state`

```sql
CREATE TABLE system_state (
    key             TEXT PRIMARY KEY,
    value           TEXT,
    updated_at      TIMESTAMP DEFAULT NOW()
);
-- Keys: last_rebalance_at, last_trader_refresh_at, account_value, total_exposure, etc.
```

---

## 4. Algorithms

### 4.1 Trader Universe Selection

**Cadence**: Daily at 00:00 UTC.

```
ALGORITHM: refresh_trader_universe()

1. FETCH leaderboard for 3 date ranges:
   - 7d:  (today-7d, today)
   - 30d: (today-30d, today)
   - 90d: (today-90d, today)
   Filter each: account_value.min = 50000, total_pnl.min = 0
   Paginate fully (per_page=100, iterate until is_last_page).

2. MERGE results by trader_address.
   For each trader, store roi_7d, roi_30d, roi_90d, pnl_7d, pnl_30d, pnl_90d, account_value, label.

3. APPLY Tier-1 filters:
   - roi_30d >= 15     (Realized ROI > 15% over 30+ days)
   - account_value >= 50000
   - (trade_count checked in step 5)

4. APPLY Multi-timeframe consistency gate (Agent 3):
   - 7d:  pnl_7d > 0  AND roi_7d > 5
   - 30d: pnl_30d > 10000 AND roi_30d > 15
   - 90d: pnl_90d > 50000 AND roi_90d > 30
   Traders must pass ALL three gates.
   FALLBACK: if 90d data unavailable (new trader), require 7d+30d pass
   and mark as "provisional" with 0.7x score multiplier.

5. For each passing trader, FETCH trade history (90d window):
   POST /profiler/perp-trades for each address.
   Compute:
   a) trade_count — require >= 50 (96 ideal)
   b) win_rate = count(closed_pnl > 0) / count(all closed trades)
      REJECT if win_rate > 0.85 OR win_rate < 0.35
   c) profit_factor = sum(closed_pnl where > 0) / abs(sum(closed_pnl where < 0))
      Require PF > 1.5 OR (win_rate < 0.40 AND PF > 2.5)  [trend trader exception]
   d) pseudo_sharpe:
      returns = [closed_pnl / value_usd for each Close/Reduce trade]
      pseudo_sharpe = mean(returns) / std(returns) if std > 0 else 0
   e) avg_hold_time: pair Open->Close trades by token, compute avg duration in hours
   f) trades_per_day = trade_count / 90

6. CLASSIFY style (Agent 2):
   def classify_trader_style(trades, days_active):
       trades_per_day = len(trades) / days_active
       avg_hold_time = calculate_avg_hold_time(trades)
       if trades_per_day > 5 and avg_hold_time < 4:
           return "HFT"      # REJECT
       elif trades_per_day >= 0.3 and avg_hold_time < 336:
           return "SWING"    # Ideal
       else:
           return "POSITION" # Acceptable

   STYLE_MULTIPLIER:
     HFT      -> 0.0 (excluded)
     SWING    -> 1.0
     POSITION -> 0.8

7. COMPUTE composite score (Agent 2):

   WEIGHTS:
     w1 = 0.25  # NORMALIZED_ROI
     w2 = 0.20  # NORMALIZED_SHARPE
     w3 = 0.15  # NORMALIZED_WIN_RATE
     w4 = 0.20  # CONSISTENCY_SCORE
     w5 = 0.10  # SMART_MONEY_BONUS
     w6 = 0.10  # RISK_MANAGEMENT_SCORE

   NORMALIZED_ROI = min(1.0, max(0, roi_30d / 100))

   NORMALIZED_SHARPE = min(1.0, max(0, pseudo_sharpe / 3.0))
     # Sharpe > 3 is exceptional; clamp to [0,1]

   NORMALIZED_WIN_RATE = min(1.0, max(0, (win_rate - 0.35) / (0.85 - 0.35)))
     # Linear scale from 35% (0) to 85% (1)

   CONSISTENCY_SCORE:
     if roi_7d > 0 and roi_30d > 0 and roi_90d > 0:
         base = 0.7
         weekly_equiv = [roi_7d, roi_30d/4, roi_90d/12]
         variance = np.var(weekly_equiv)
         consistency_bonus = max(0, 0.3 - (variance / 100))
         score = base + consistency_bonus
     elif sum([roi_7d>0, roi_30d>0, roi_90d>0]) >= 2:
         score = 0.5
     else:
         score = 0.2

   SMART_MONEY_BONUS:
     if "Fund" in label:     -> 1.0
     elif "Smart" in label:  -> 0.8
     elif label != "":       -> 0.5
     else:                   -> 0.0

   RISK_MANAGEMENT_SCORE:
     # Based on average leverage from positions snapshot
     avg_leverage = mean(leverage_value for all positions)
     if avg_leverage <= 3:   -> 1.0
     elif avg_leverage <= 5: -> 0.8
     elif avg_leverage <= 10:-> 0.5
     elif avg_leverage <= 20:-> 0.3
     else:                   -> 0.1
     FALLBACK: if no current positions, use 0.5

   RECENCY_DECAY:
     # Based on days since last trade
     days_since_last = (now - most_recent_trade_timestamp).days
     recency_decay = exp(-days_since_last / 30)  # 30-day half-life

   TRADER_SCORE = (
       w1 * NORMALIZED_ROI +
       w2 * NORMALIZED_SHARPE +
       w3 * NORMALIZED_WIN_RATE +
       w4 * CONSISTENCY_SCORE +
       w5 * SMART_MONEY_BONUS +
       w6 * RISK_MANAGEMENT_SCORE
   ) * STYLE_MULTIPLIER * RECENCY_DECAY

8. RANK by TRADER_SCORE DESC. Select top N = 15 for active tracking.
   Store scores in trader_scores table.
```

### 4.2 Target Portfolio Computation

**Cadence**: Every 4-6 hours (configurable, default 4h).

```
ALGORITHM: compute_target_portfolio(rebalance_id)

1. For each of the N tracked traders, FETCH current positions:
   POST /profiler/perp-positions for each address.
   Store in position_snapshots with snapshot_batch = rebalance_id.

2. For each trader t, for each position p:
   Compute the trader's allocation weight for this position:

   trader_alloc_pct = p.position_value_usd / t.account_value

   Compute our raw copy size using Agent 1 formula:
   raw_copy_usd = my_account_value * trader_alloc_pct * COPY_RATIO  (COPY_RATIO = 0.5)

3. Aggregate across ALL tracked traders per (token_symbol, side):

   For each unique (token, side) pair:
     weighted_usd = 0
     total_score_weight = 0

     For each trader t holding this (token, side):
       raw_copy = calculate_copy_size(
           p.position_value_usd, t.account_value, my_account_value
       )
       score_weight = t.composite_score / sum(all_trader_scores)
       weighted_usd += raw_copy * score_weight
       total_score_weight += score_weight

     target_usd[(token, side)] = weighted_usd

   JUSTIFICATION for score-weighting:
   Higher-scoring traders have more influence on the index.
   This is analogous to a quality-factor-weighted index rather than
   equal-weight or market-cap-weight. It rewards consistent skill
   while still diversifying across multiple traders.

4. NORMALIZE: ensure sum of all target_usd doesn't exceed
   MAX_TOTAL_OPEN_POSITIONS_USD = account_value * 0.50.

   If total > cap:
     scale_factor = cap / total
     target_usd[(token, side)] *= scale_factor for all

5. Rank positions by target_usd DESC. Keep top MAX_TOTAL_POSITIONS = 5.
   Zero out the rest.

6. Store in target_allocations table.
```

### 4.3 Risk Overlay

```
ALGORITHM: apply_risk_overlay(target_allocations)

Applied sequentially after target computation:

STEP 1: Per-position cap (Agent 1 rule 1)
  MAX_SINGLE_POSITION_USD = min(account_value * 0.10, 50000)
  For each target:
    target.capped_usd = min(target.target_usd, MAX_SINGLE_POSITION_USD)

STEP 2: Per-token cap (Agent 1 rule 4)
  MAX_EXPOSURE_PER_TOKEN = 0.15 * account_value
  For each token (may have long OR short, never both due to MAX_POSITIONS_PER_TOKEN=1):
    if target.capped_usd > MAX_EXPOSURE_PER_TOKEN:
      target.capped_usd = MAX_EXPOSURE_PER_TOKEN

STEP 3: Directional caps (Agent 1 rule 4)
  total_long = sum(capped_usd for side == "Long")
  total_short = sum(capped_usd for side == "Short")

  MAX_LONG_USD = account_value * 0.60
  MAX_SHORT_USD = account_value * 0.60

  If total_long > MAX_LONG_USD:
    scale all longs by MAX_LONG_USD / total_long
  If total_short > MAX_SHORT_USD:
    scale all shorts by MAX_SHORT_USD / total_short

STEP 4: Total exposure cap (Agent 1 rule 2)
  total_exposure = sum(all capped_usd)
  MAX_TOTAL = account_value * 0.50
  If total_exposure > MAX_TOTAL:
    scale_factor = MAX_TOTAL / total_exposure
    scale all capped_usd by scale_factor

STEP 5: Validate constraints
  assert count(targets where capped_usd > 0) <= 5  (MAX_TOTAL_POSITIONS)
  assert all targets have MAX_POSITIONS_PER_TOKEN = 1

STEP 6: Leverage cap
  For all positions: use isolated margin, max leverage = 5x.
  If a trader uses 20x, we still open at 5x.
  The position size is already scaled down by COPY_RATIO and caps,
  so the leverage cap is an additional safety layer.

RETURN: risk-adjusted target_allocations
```

### 4.4 Rebalance Logic

```
ALGORITHM: execute_rebalance(rebalance_id)

1. COMPUTE diff between target_allocations and our_positions:

   For each target (token, side):
     current = our_positions.get(token)

     CASE A: No current position, target > 0 → OPEN
       delta_usd = target.capped_usd

     CASE B: Current position, same side, target > 0 → ADJUST
       delta_usd = target.capped_usd - current.position_usd
       # Apply rebalance band to reduce churn:
       REBALANCE_BAND = 0.10  (10%)
       if abs(delta_usd) / current.position_usd < REBALANCE_BAND:
         SKIP (within tolerance)

     CASE C: Current position, opposite side → CLOSE + OPEN
       Close existing, then open new.

     CASE D: Current position, no target → CLOSE

   For each current position not in targets → CLOSE

2. PRIORITIZE order execution:
   a) CLOSE orders first (reduce exposure before adding)
   b) ADJUST orders (increase/decrease existing)
   c) OPEN orders last

3. For each order:
   Determine order type (Agent 4):
     - CLOSE → always MARKET (exit priority > price)
     - OPEN/INCREASE where delta_usd > 20% of position → MARKET
     - OPEN/INCREASE where delta_usd <= 20% → LIMIT at mark_price + slippage_allowance

   Slippage allowances (Agent 4):
     BTC:  0.03% (midpoint of 0.01-0.05%)
     ETH:  0.05%
     SOL:  0.10% (midpoint of 0.05-0.15%)
     HYPE: 0.20% (midpoint of 0.1-0.3%)
     Other: 0.15%

   Set isolated margin, leverage = min(5, computed_leverage).
   Compute size = delta_usd / mark_price.

4. SEND orders to Hyperliquid via SDK.
   Record in orders table with status=SENT.

5. POLL for fills (30s intervals, up to 5 min for limit orders).
   On fill: update our_positions, orders.status=FILLED, record slippage_bps.
   On partial fill after 5 min: cancel remainder, record PARTIAL.
   On no fill: cancel, record CANCELLED, log for review.

6. For each new/adjusted position, SET stops:
   stop_loss_price:
     Long:  entry_price * (1 - STOP_LOSS_PERCENT / 100)  = entry * 0.95
     Short: entry_price * (1 + STOP_LOSS_PERCENT / 100)  = entry * 1.05

   trailing_stop initial:
     trailing_high = entry_price (for longs), entry_price (for shorts = trailing_low)
     trailing_stop_price = trailing_high * (1 - TRAILING_STOP_PERCENT / 100) for longs

   max_close_at = now + MAX_POSITION_DURATION_HOURS (72h)

   Place actual stop-loss order on Hyperliquid.
   Trailing stop is managed by monitoring service (not native on HL).
```

### 4.5 Stop-Loss / Trailing / Time-Stop Enforcement

```
ALGORITHM: monitor_positions()  — runs every 60 seconds

For each position in our_positions:

  1. FETCH current mark price from last position snapshot or Hyperliquid.

  2. STOP LOSS CHECK:
     Long:  if mark_price <= stop_loss_price → CLOSE at MARKET
     Short: if mark_price >= stop_loss_price → CLOSE at MARKET
     exit_reason = "STOP_LOSS"

  3. TRAILING STOP UPDATE + CHECK:
     Long:
       if mark_price > trailing_high:
         trailing_high = mark_price
         trailing_stop_price = trailing_high * (1 - TRAILING_STOP_PERCENT / 100)
       if mark_price <= trailing_stop_price → CLOSE at MARKET
     Short:
       if mark_price < trailing_low:
         trailing_low = mark_price
         trailing_stop_price = trailing_low * (1 + TRAILING_STOP_PERCENT / 100)
       if mark_price >= trailing_stop_price → CLOSE at MARKET
     exit_reason = "TRAILING_STOP"

  4. TIME STOP CHECK:
     if now >= max_close_at → CLOSE at MARKET
     exit_reason = "TIME_STOP"

  5. On any close: update our_positions (remove), write to pnl_ledger.
```

---

## 5. Configuration Constants

```python
# === Risk Management (Agent 1) ===
COPY_RATIO = 0.5
MAX_SINGLE_POSITION_PCT = 0.10
MAX_SINGLE_POSITION_HARD_CAP = 50_000
MAX_TOTAL_EXPOSURE_PCT = 0.50
MAX_POSITIONS_PER_TOKEN = 1
MAX_TOTAL_POSITIONS = 5
MAX_EXPOSURE_PER_TOKEN_PCT = 0.15
MAX_LONG_EXPOSURE_PCT = 0.60
MAX_SHORT_EXPOSURE_PCT = 0.60
MAX_LEVERAGE = 5
MARGIN_TYPE = "isolated"
STOP_LOSS_PERCENT = 5.0
TRAILING_STOP_PERCENT = 8.0
MAX_POSITION_DURATION_HOURS = 72

# === Trader Selection (Agent 2) ===
MIN_ROI_30D = 15.0
MIN_ACCOUNT_VALUE = 50_000
MIN_TRADE_COUNT = 50
IDEAL_TRADE_COUNT = 96
WIN_RATE_MIN = 0.35
WIN_RATE_MAX = 0.85
MIN_PROFIT_FACTOR = 1.5
TREND_TRADER_MIN_PF = 2.5
TREND_TRADER_MAX_WR = 0.40
TOP_N_TRADERS = 15

# === Scoring Weights ===
W_ROI = 0.25
W_SHARPE = 0.20
W_WIN_RATE = 0.15
W_CONSISTENCY = 0.20
W_SMART_MONEY = 0.10
W_RISK_MGMT = 0.10

# === Rebalance ===
REBALANCE_INTERVAL_HOURS = 4
REBALANCE_BAND = 0.10  # 10% tolerance

# === Polling (Agent 4) ===
POLL_POSITIONS_MINUTES = 15
POLL_TRADES_MINUTES = 5
POLL_LEADERBOARD_HOURS = 24
MONITOR_INTERVAL_SECONDS = 60

# === Slippage (Agent 4) ===
SLIPPAGE_BPS = {
    "BTC": 3, "ETH": 5, "SOL": 10, "HYPE": 20, "DEFAULT": 15
}
```

---

## 6. Schedules & State Machine

```
STATE: IDLE ──(daily 00:00 UTC)──> REFRESHING_TRADERS
  │
  ├─ REFRESHING_TRADERS:
  │    1. Fetch leaderboard (3 date ranges)
  │    2. Fetch trades for candidates
  │    3. Score + rank
  │    4. Store top N
  │    └──> IDLE
  │
  ├─(every 4h)──> REBALANCING:
  │    1. Snapshot positions for all tracked traders
  │    2. Compute target portfolio
  │    3. Apply risk overlay
  │    4. Compute diffs
  │    5. Execute orders
  │    6. Set stops
  │    └──> IDLE
  │
  ├─(every 5m)──> INGESTING_TRADES:
  │    Fetch latest trades for tracked traders (last 6h window)
  │    Update trade_history incrementally
  │    └──> IDLE
  │
  └─(every 60s)──> MONITORING:
       Check stops, trailing stops, time stops
       Update trailing highs/lows
       Check exposure drift
       └──> IDLE (or trigger emergency close)
```

**Concurrency**: Rebalancing and monitoring are mutex-protected. Monitoring pauses during rebalance execution to avoid conflicting orders.

**Failure Handling**:
- If ingestion fails (429/500): exponential backoff, retry 3x, skip cycle if all fail, alert.
- If execution fails: cancel pending orders, log, alert, skip to next cycle.
- If monitoring detects stop trigger during rebalance: rebalance aborts, stop takes priority.

---

## 7. Backtesting & Paper-Trade Plan

### 7.1 Backtesting Engine

```
DATA COLLECTION:
  - Historical leaderboard snapshots (fetch daily for 90 days, store)
  - Historical positions for top traders (fetch at simulated 4h intervals)
  - Historical trades for scoring (already available via date ranges)

SIMULATION LOOP:
  For each day in backtest_range:
    1. Run refresh_trader_universe() with historical data
    2. Every 4h: run compute_target_portfolio() + apply_risk_overlay()
    3. Simulate execution with:
       - Latency: add 500ms to 2s random delay before execution
       - Slippage: apply configured bps + random noise (uniform ±50% of base)
       - Missed fills: 5% chance of limit order cancellation
       - Partial fills: 10% chance, fill 50-90% of intended size
    4. Simulate monitoring at 1m intervals:
       - Apply stop/trailing/time logic
    5. Track P&L per position and total

OUTPUT METRICS:
  - Total return, annualized return
  - Max drawdown, drawdown duration
  - Sharpe ratio, Sortino ratio
  - Win rate (by position)
  - Average hold time
  - Turnover (monthly rebalance churn)
  - Slippage cost as % of returns
  - Number of stop/trailing/time exits
```

### 7.2 Paper Trading

```
PAPER TRADE MODE:
  - All systems run live against real Nansen data
  - Execution engine writes to orders table but does NOT send to Hyperliquid
  - Simulated fills at mark_price + slippage
  - Runs for minimum 2 weeks before live deployment
  - Dashboard compares paper P&L vs. what tracked traders actually did

GRADUATION CRITERIA (paper -> live):
  - 14+ days of continuous operation without crashes
  - No single position loss > STOP_LOSS_PERCENT
  - Total portfolio drawdown < 10%
  - System correctly applied all risk caps (verified by audit log)
  - All stop types triggered correctly at least once
```

---

## 8. Observability

### 8.1 Metrics (emit to stdout / Prometheus / file)

| Metric | Type | Description |
|--------|------|-------------|
| `portfolio.total_exposure_usd` | gauge | Current total deployed capital |
| `portfolio.long_exposure_pct` | gauge | Long exposure as % of account |
| `portfolio.short_exposure_pct` | gauge | Short exposure as % of account |
| `portfolio.position_count` | gauge | Number of open positions |
| `portfolio.unrealized_pnl_usd` | gauge | Sum of unrealized P&L |
| `portfolio.realized_pnl_usd` | counter | Cumulative realized P&L |
| `portfolio.drawdown_pct` | gauge | Current drawdown from peak |
| `rebalance.target_divergence_pct` | gauge | % diff between target and actual |
| `rebalance.orders_sent` | counter | Orders sent per rebalance |
| `rebalance.slippage_bps_avg` | gauge | Average slippage in basis points |
| `rebalance.duration_seconds` | histogram | Time to complete rebalance |
| `traders.eligible_count` | gauge | Traders passing all filters |
| `traders.tracked_count` | gauge | Traders in active tracking |
| `traders.blacklisted_count` | gauge | Blacklisted traders |
| `ingestion.api_latency_ms` | histogram | Nansen API response time |
| `ingestion.errors` | counter | API errors by endpoint and status |
| `stops.triggered` | counter | Stop events by type |

### 8.2 Logs (structured JSON)

```json
{
  "ts": "2026-02-07T12:00:00Z",
  "level": "INFO",
  "event": "rebalance_complete",
  "rebalance_id": "abc-123",
  "orders_sent": 3,
  "orders_filled": 3,
  "target_divergence_pct": 2.1,
  "total_exposure_usd": 45000,
  "duration_s": 12.5
}
```

### 8.3 Alerts (critical conditions)

| Alert | Condition | Severity |
|-------|-----------|----------|
| Exposure breach | total_exposure > 55% of account | CRITICAL |
| Drawdown threshold | drawdown > 8% from peak | WARNING |
| Drawdown critical | drawdown > 15% from peak | CRITICAL — halt trading |
| API failure | 3 consecutive failures on any endpoint | WARNING |
| Rebalance stale | > 6h since last successful rebalance | WARNING |
| Stop-loss triggered | Any position hits stop | INFO |
| Trader blacklisted | Trader removed mid-cycle | INFO |
| Divergence high | target vs actual > 25% | WARNING |
| Order failure | Order rejected by Hyperliquid | WARNING |
| Position limit breach | > 5 positions or > 1 per token | CRITICAL — close excess |

---

## 9. Implementation Phases

### Phase 1: Data Layer & Ingestion
**Depends on:** None

- [x] Set up project structure (Python, pyproject.toml, src layout)
- [x] Define configuration module with all constants from Section 5
- [x] Create database schema (SQLite for dev) with migrations
- [x] Implement Nansen API client with:
  - [x] Rate limiter (respect 429s, exponential backoff)
  - [x] Pagination helper (iterate until `is_last_page`)
  - [x] Retry logic (3 attempts, 1s/2s/4s backoff)
- [x] Implement ingestion for Perp Leaderboard (3 date ranges)
- [x] Implement ingestion for Address Perp Positions
- [x] Implement ingestion for Address Perp Trades
- [x] Write unit tests for API client (mocked responses)
- [x] Write integration test: fetch real data for 1 known address, verify schema

### Phase 2: Scoring Engine
**Depends on:** Phase 1

- [x] Implement tier-1 filter logic
- [x] Implement multi-timeframe consistency gate
- [x] Implement win rate / profit factor / pseudo-Sharpe calculators
- [x] Implement hold-time pairing algorithm (Open -> Close matching by token)
- [x] Implement style classification (HFT / SWING / POSITION)
- [x] Implement composite score formula with all 6 components
- [x] Implement recency decay and style multiplier
- [x] Implement `refresh_trader_universe()` orchestrator
- [x] Write unit tests:
  - [x] Test tier-1 filter with edge cases (exactly at thresholds)
  - [x] Test win rate bounds rejection (>85%, <35%)
  - [x] Test profit factor with trend-trader exception
  - [x] Test style classification boundary cases
  - [x] Test composite score normalization (all components in [0,1])
  - [x] Test with zero-trade, zero-variance, and single-trade edge cases
- [x] Write regression test: given fixed input data, score output is deterministic

### Phase 3: Target Portfolio & Risk Overlay
**Depends on:** Phase 2

- [x] Implement `compute_target_portfolio()` — score-weighted aggregation
- [x] Implement `apply_risk_overlay()` — all 6 steps
- [x] Implement `calculate_copy_size()` with COPY_RATIO
- [x] Implement rebalance banding (10% tolerance)
- [x] Implement rebalance diff computation (OPEN/CLOSE/ADJUST cases)
- [x] Write unit tests:
  - [x] Test MAX_SINGLE_POSITION_USD cap with various account sizes
  - [x] Test per-token exposure cap
  - [x] Test directional caps (all-long portfolio scaled correctly)
  - [x] Test total exposure cap
  - [x] Test MAX_TOTAL_POSITIONS = 5 truncation
  - [x] Test rebalance band: 8% change → skip, 12% change → execute
  - [x] Test close+open when side flips
  - [x] Property test: no output ever violates any cap

### Phase 4: Execution Engine
**Depends on:** Phase 3

- [x] Implement Hyperliquid SDK integration (order placement, cancellation, status)
- [x] Implement order type selection logic (market vs limit based on urgency)
- [x] Implement slippage allowance calculation per token
- [x] Implement fill polling loop (30s intervals, 5m timeout for limits)
- [x] Implement isolated margin and leverage setting
- [x] Implement `execute_rebalance()` orchestrator
- [x] Implement paper-trade mode (simulated fills, no real orders)
- [x] Write unit tests:
  - [x] Test order type selection: close=market, large open=market, small adjust=limit
  - [x] Test slippage calculation per token
  - [x] Test fill timeout → cancellation flow
- [x] Write integration test with paper-trade mode: full rebalance cycle end-to-end

### Phase 5: Monitoring & Stop System
**Depends on:** Phase 4

- [ ] Implement stop-loss price calculation and placement
- [ ] Implement trailing stop logic (update trailing_high, check trigger)
- [ ] Implement time-stop enforcement
- [ ] Implement `monitor_positions()` loop (60s cadence)
- [ ] Implement mutex between monitoring and rebalancing
- [ ] Implement emergency close flow
- [ ] Write unit tests:
  - [ ] Test stop-loss trigger for long and short
  - [ ] Test trailing stop ratchet: price rises, trailing_high updates, then drops to trigger
  - [ ] Test time-stop: position opened 73h ago → closed
  - [ ] Test that monitoring pauses during rebalance

### Phase 6: Scheduler & Orchestration
**Depends on:** Phase 5

- [ ] Implement scheduler (APScheduler or cron-based):
  - [ ] Daily trader refresh at 00:00 UTC
  - [ ] 4h rebalance cycle
  - [ ] 5m trade ingestion
  - [ ] 60s monitoring
- [ ] Implement state machine transitions and locking
- [ ] Implement graceful shutdown (complete current cycle, close orders)
- [ ] Implement startup recovery (load state from DB, resume)
- [ ] Write integration test: simulate 24h of operation with mocked APIs

### Phase 7: Observability & Alerts
**Depends on:** Phase 6

- [ ] Implement structured JSON logging
- [ ] Implement metrics emission (stdout / file for MVP, Prometheus optional)
- [ ] Implement alert conditions with configurable thresholds
- [ ] Implement notification delivery (log-based for MVP, webhook/Telegram later)
- [ ] Implement dashboard data export (JSON snapshots for external dashboards)
- [ ] Build health-check endpoint / status file

### Phase 8: Backtesting Engine
**Depends on:** Phase 3

- [x] Implement historical data fetcher (bulk leaderboard + positions over date range)
- [x] Implement simulation loop (daily refresh, 4h rebalance, 1m monitoring)
- [x] Implement execution simulator (latency, slippage, missed fills, partial fills)
- [x] Implement performance metrics calculator (return, drawdown, Sharpe, Sortino, turnover)
- [x] Generate backtest report (markdown + CSV output)
- [x] Validate backtest against paper-trade results for same period

### Phase 9: Paper Trading & Go-Live
**Depends on:** Phase 7, Phase 8

- [ ] Run paper trading for minimum 14 days
- [ ] Audit all risk caps via log analysis
- [ ] Verify stop triggers (at least 1 of each type)
- [ ] Compare paper P&L to tracked traders' actual performance
- [ ] Review and tune configuration constants
- [ ] Implement live mode toggle (paper_trade = false)
- [ ] Deploy with initial small account_value ($5K-$10K)
- [ ] Monitor for 7 days at small size before scaling

---

## 10. API Data Gaps & Fallbacks

| Required Data | Ideal Source | Available? | Fallback |
|---------------|-------------|------------|----------|
| Trader ROI at multiple timeframes | Perp Leaderboard with date ranges | YES | Query 3x with different date ranges |
| Trader account_value | Perp Leaderboard `account_value` field | YES | Direct from API |
| Current positions | Address Perp Positions | YES | Direct from API |
| Trade count / win rate | Address Perp Trades (compute from history) | YES | Fetch 90d trades, compute |
| Real-time mark price | Not in Nansen (position snapshot has it) | PARTIAL | Use `mark_price` from position snapshot (up to 15m stale) |
| Trader's recent performance decay | No "last trade date" field on leaderboard | NO | Derive from Address Perp Trades: `max(timestamp)` per trader |
| Leverage used per trader | Address Perp Positions `leverage_value` | YES | From position snapshot |
| Historical positions for backtest | Address Perp Positions is point-in-time | PARTIAL | Collect snapshots over time; reconstruct from trades for deep history |

---

## 11. Testing Plan Summary

| Test Type | Scope | Count (est.) |
|-----------|-------|--------------|
| **Unit** | Sizing: `calculate_copy_size` with 10+ param combos | 10-15 |
| **Unit** | Caps: each of 6 risk overlay steps independently | 15-20 |
| **Unit** | Scoring: each component, composite, edge cases | 15-20 |
| **Unit** | Filters: tier-1, quality gates, style classification | 10-15 |
| **Unit** | Stops: stop-loss, trailing, time-stop for long + short | 8-10 |
| **Unit** | Rebalance diff: all 4 cases (open/close/adjust/flip) | 8-10 |
| **Integration** | Nansen client against mocked HTTP (all 3 endpoints) | 6-10 |
| **Integration** | Full rebalance cycle with mocked Nansen + paper execution | 3-5 |
| **Integration** | Scheduler: 24h simulation with time acceleration | 1-2 |
| **Regression** | Fixed trader data → deterministic score output | 3-5 |
| **Regression** | Fixed portfolio state → deterministic rebalance orders | 3-5 |
| **Property** | No output violates any risk cap (randomized inputs) | 5-10 |
| **E2E** | Paper trade for 14 days (manual verification) | 1 |

**Total estimated: ~90-130 automated tests + 1 extended paper-trade run.**
