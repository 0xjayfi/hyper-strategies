# Parallelized Execution Plan

**Source**: `specs/entry-only-signal-generator.md`
**Generated**: 2026-02-07
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

```
Phase 1 -> Phase 2, Phase 5
Phase 2 -> Phase 3
Phase 3 -> Phase 4
Phase 4 -> Phase 6
Phase 5 -> Phase 6
Phase 6 -> Phase 7
Phase 7 -> Phase 8, Phase 9, Phase 10
```

---

## Completed Phases (Skipped)

Phase 1 — Core Infrastructure & Configuration (Track 1)
Phase 2 — Nansen API Client (Track 2)
Phase 5 — Entry Sizing Algorithm (Track 2)
Phase 3 — Trader Scoring & Selection (Track 3)
Phase 4 — Trade Ingestion & Signal Generation (Track 4)

---

## Track 1: Foundation

Phases in this track run **in parallel**.

### Phase 1: Core Infrastructure & Configuration (agents: 2)
- [x] **1.1** Set up project structure (`src/config.py`, `src/models.py`, `src/db.py`, `src/__init__.py`) and install dependencies (`httpx`, `aiosqlite`, `pydantic-settings`, `structlog`, `pytest`, `pytest-asyncio`)
- [x] **1.2** Define all configuration constants in `config.py` using pydantic-settings with `.env` loading — includes entry risk params (COPY_DELAY_MINUTES=15, MAX_PRICE_SLIPPAGE_PERCENT=2.0, COPY_RATIO=0.5, MAX_SINGLE_POSITION_USD=50000, MAX_TOTAL_POSITIONS=5, MAX_EXPOSURE_PER_TOKEN=0.15), stop system params (STOP_LOSS_PERCENT=5.0, TRAILING_STOP_PERCENT=8.0, MAX_POSITION_DURATION_HOURS=72), trade filtering (MIN_TRADE_VALUE_USD dict, MIN_POSITION_WEIGHT=0.10, ADD_MAX_AGE_HOURS=2), trader selection (MIN_TRADES_REQUIRED=50, TRADER_SCORE_WEIGHTS dict, RECENCY_DECAY_HALFLIFE_DAYS=14), execution (polling intervals), liquidation (LIQUIDATION_COOLDOWN_DAYS=14), consensus toggle
- [x] **1.3** Define SQLite schema in `db.py` with tables: `traders` (address PK, label, score, style, roi_7d, roi_30d, account_value, nof_trades, last_scored_at, blacklisted_until), `trader_positions` (address+token PK, side, position_value_usd, entry_price, last_seen_at), `our_positions` (id PK, token, side, entry/stop/trailing prices, highest/lowest, opened_at, source_trader, source_signal_id, status), `signals` (id PK, full audit fields, decision), `seen_trades` (tx_hash PK, seen_at). Include init(), CRUD helpers for each table
- [x] **1.4** Define Pydantic data models in `models.py`: Signal (17 fields per spec), TraderRow, RawTrade, TraderPositionSnapshot, ExecutionResult, OurPosition

---

## Track 2: API Client & Sizing

Phases in this track run **in parallel**. Starts after Track 1 completes.

### Phase 2: Nansen API Client (agents: 2)
- [x] **2.1** Create `src/nansen_client.py` — async httpx wrapper with methods: `get_perp_leaderboard(date_from, date_to)`, `get_address_perp_trades(address, date_from, date_to)`, `get_address_perp_positions(address)`, `get_perp_pnl_leaderboard(token_symbol, date_from, date_to)`, `get_smart_money_perp_trades(only_new_positions)`, `get_perp_screener(date_from, date_to)`. All return parsed dicts. Auth via `apiKey` header
- [x] **2.2** Implement pagination helper — auto-paginate until `is_last_page=true`, accumulate results across pages
- [x] **2.3** Implement rate-limit handling with exponential backoff on HTTP 429 responses
- [x] **2.4** Map Nansen response field names to internal models — leaderboard→Trader (trader_address→address, account_value), trades→RawTrade (action, side, token_symbol, value_usd, price, timestamp, transaction_hash, start_position, size), positions→TraderPositionSnapshot (position.token_symbol, position.position_value_usd string→float, position.leverage_value, margin_summary_account_value_usd string→float)

### Phase 5: Entry Sizing Algorithm (agents: 1)
- [x] **5.1** Create `src/sizing.py` with `compute_copy_size(trader_position_value, trader_account_value, our_account_value, trader_roi_7d, leverage)` — combines: (1) trader_alloc_pct × COPY_RATIO, (2) ROI tier multiplier (>10%→1.0, 0-10%→0.75, <0%→0.50), (3) leverage penalty with interpolation (1x→1.0, 2x→0.9, 3x→0.8, 5x→0.6, 10x→0.4, 20x→0.2, >20x→0.1), (4) cap at min(account*0.10, $50k), floor at $100
- [x] **5.2** Implement `get_leverage_from_positions(positions_response, token)` — extract leverage_value from profiler/perp-positions response by matching token_symbol

---

## Track 3: Trader Scoring

Phases in this track run **in parallel**. Starts after Track 2 completes.

### Phase 3: Trader Scoring & Selection (agents: 2)
- [x] **3.1** Create `src/trader_scorer.py` — daily job: fetch leaderboard for 7d/30d/90d, fetch trade history per candidate via profiler/perp-trades, compute derived metrics, classify style, write to `traders` table
- [x] **3.2** Implement `classify_trader_style(trades, days_active)` — HFT if >5 trades/day AND <4h avg hold, SWING if >=0.3 trades/day AND <336h avg hold, else POSITION. Include `calculate_avg_hold_time` matching Open→Close pairs by token+side
- [x] **3.3** Implement `compute_trader_score(trader, trades_90d)` — composite of normalized_roi(0.25), pseudo_sharpe(0.20), win_rate(0.15), consistency(0.20), smart_money_bonus(0.10), risk_mgmt(0.10). Disqualify if win_rate >0.85 or <0.35. Apply RECENCY_DECAY with 14-day halflife
- [x] **3.4** Implement `consistency_score(roi_7d, roi_30d, roi_90d)` — 0.7+bonus if all positive (bonus from weekly-normalized variance), 0.5 if 2/3 positive, 0.2 otherwise
- [x] **3.5** Implement selection filter: nof_trades>=50, style!="HFT", account_value>=$50k, roi_30d>0, win_rate in [0.35,0.85], not blacklisted
- [x] **3.6** Maintain tracked set: top 10-15 primary (active copy), 20-30 secondary (monitoring). Add `tier` column to traders table

---

## Track 4: Signal Pipeline

Phases in this track run **in parallel**. Starts after Track 3 completes.

### Phase 4: Trade Ingestion & Signal Generation (agents: 2)
- [x] **4.1** Create `src/trade_ingestion.py` — polling loop over primary traders every POLLING_INTERVAL_ADDRESS_TRADES_SEC (300s), fetch trades from last hour, dedup via seen_trades table, evaluate each through signal pipeline
- [x] **4.2** Implement `evaluate_trade(trade, trader)` — 9-step pipeline: (1) action filter (Open=yes, Add=yes if within 2h of Open, else skip), (2) asset min size (BTC $50k, ETH $25k, SOL $10k, others $5k), (3) position weight >=0.10 and >=0.05, (4) time decay confirmation (defer if <15min, verify position still open after delay), (5) slippage gate (<=2.0%), (6) execution timing (<2min→market/0.5%, <10min→limit if <0.3%, >10min→skip unless score>0.8 AND weight>0.25), (7) optional consensus check, (8) portfolio limits (max 5 positions, 50% total exposure, 15% per token), (9) compute copy size. Build and return Signal object
- [x] **4.3** Implement deferred signal queue — asyncio priority queue keyed by check_at time, background coroutine pops when ready and re-evaluates from step 4 onward

---

## Track 5: Order Execution

Phases in this track run **in parallel**. Starts after Track 4 completes.

### Phase 6: Execution Module (agents: 1)
- [ ] **6.1** Create `src/executor.py` with `HyperLiquidExecutor` — `execute_signal(signal)` places market or limit entry order via hyperliquid-python-sdk, sets isolated margin with leverage capped at 5x, places hard stop-loss order (opposite side market), records position in DB with stop_price, trailing_stop_price, highest/lowest price
- [ ] **6.2** Implement `compute_stop_price(entry_price, side)` (Long: entry*(1-5/100), Short: entry*(1+5/100)) and `compute_trailing_stop_initial(entry_price, side)` (Long: entry*(1-8/100), Short: entry*(1+8/100))

---

## Track 6: Position Management

Phases in this track run **in parallel**. Starts after Track 5 completes.

### Phase 7: Position Monitor & Exit Module (agents: 2)
- [ ] **7.1** Create `src/position_monitor.py` — monitor loop every 30s: for each open position get mark_price, run trailing stop update, check trailing stop trigger, check time-stop (>=72h), check profit-taking tiers, check trader liquidation/disappearance
- [ ] **7.2** Implement trailing stop logic: `update_trailing_stop(pos, mark_price)` — Long: update highest_price and raise trailing_stop if new_trail > current; Short: update lowest_price and lower trailing_stop if new_trail < current. `trailing_stop_triggered(pos, mark_price)` — Long: mark<=trail, Short: mark>=trail
- [ ] **7.3** Implement trader liquidation detection: `check_trader_position(our_pos)` — fetch trader positions, if position gone AND no recent Close trade found → close our position with reason TRADER_LIQUIDATED, blacklist trader for LIQUIDATION_COOLDOWN_DAYS=14
- [ ] **7.4** Define profit-taking tier placeholders in config: TIER_1=10% (take 25%), TIER_2=20% (take 33%), TIER_3=40% (take 50%). Set to None/0 to disable
- [ ] **7.5** Implement `close_position(pos, reason)` — market order to close, cancel existing stop orders on exchange, update DB status to 'closed', log reason

---

## Track 7: Orchestrator, Backtest & Tests

Phases in this track run **in parallel**. Starts after Track 6 completes.

### Phase 8: Main Orchestrator (agents: 1)
- [ ] **8.1** Create `src/main.py` — init DB, NansenClient, HyperLiquidExecutor; launch concurrent loops via asyncio.gather (leaderboard_refresh daily, trade_ingestion 5min, deferred_signal_processor continuous, position_monitor 30s)
- [ ] **8.2** Implement graceful shutdown — SIGINT/SIGTERM handler, cancel all asyncio tasks, close httpx connections, flush logs
- [ ] **8.3** Add structured logging throughout with structlog — every signal decision, order placement, stop update, position close logged with full context for post-mortem

### Phase 9: Backtest / Paper Trading Mode (agents: 2)
- [ ] **9.1** Create `src/backtest.py` — Backtester class: fetch historical leaderboard, score traders, fetch all trades in date range, replay through signal pipeline chronologically, simulate execution with slippage, simulate stops using historical prices
- [ ] **9.2** Implement slippage simulation: base rates (BTC 0.02%, ETH 0.03%, SOL 0.08%, default 0.15%) scaled by size_factor = 1 + (size_usd/100k)*0.5
- [ ] **9.3** Create PaperExecutor — config flag PAPER_MODE replaces HyperLiquidExecutor; records in DB as if executed using current mark_price + simulated slippage
- [ ] **9.4** Backtest metrics output: total return, max drawdown, Sharpe ratio, win rate, profit factor, avg trade duration, trade count, comparison of our exits vs copying trader exits

### Phase 10: Testing (agents: 3)
- [ ] **10.1** Stop placement tests: `test_stop_price_long` (100→95), `test_stop_price_short` (100→105), `test_trailing_stop_updates_on_new_high` (115→trail 105.8), `test_trailing_stop_does_not_lower` (price drops but trail unchanged)
- [ ] **10.2** Time-stop tests: `test_time_stop_triggers_after_72h` (73h→True), `test_time_stop_does_not_trigger_before_72h` (71h→False)
- [ ] **10.3** Slippage gate tests: `test_slippage_gate_passes` ($100→$101.5=1.5%<2.0%), `test_slippage_gate_fails` ($100→$102.5=2.5%>2.0%)
- [ ] **10.4** Tiered sizing tests: hot trader (roi 15%→100%→$10k), lukewarm (roi 5%→75%→$7.5k), cold (roi -2%→50%→$5k), leverage penalty (20x→0.2→$2k), max cap ($125k→$50k)
- [ ] **10.5** Action filter tests: Open passes, Add within 2h passes, Add after 2h rejected, Reduce rejected, Close rejected as entry
- [ ] **10.6** Liquidation detection test: position present→open, position disappears without Close→closed+blacklisted 14 days
- [ ] **10.7** Integration test: end-to-end with mocked Nansen — score traders, inject Open trade, verify all gates pass, verify sizing, paper execute with stop, simulate price increase→trailing update, simulate reversal→trailing triggers close

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1: Foundation | Phase 1 | 2 | 4 |
| Track 2: API Client & Sizing | Phase 2, Phase 5 | 3 | 6 |
| Track 3: Trader Scoring | Phase 3 | 2 | 6 |
| Track 4: Signal Pipeline | Phase 4 | 2 | 3 |
| Track 5: Order Execution | Phase 6 | 1 | 2 |
| Track 6: Position Management | Phase 7 | 2 | 5 |
| Track 7: Orchestrator, Backtest & Tests | Phase 8, Phase 9, Phase 10 | 6 | 14 |
| **Total** | **10 phases** | — | **40 tasks** |
