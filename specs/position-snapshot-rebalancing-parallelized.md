# Parallelized Execution Plan

**Source**: `specs/position-snapshot-rebalancing.md`
**Generated**: 2026-02-07
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

```
Phase 1 -> (no dependencies)
Phase 2 -> Phase 1
Phase 3 -> Phase 2
Phase 4 -> Phase 3
Phase 5 -> Phase 4
Phase 6 -> Phase 5
Phase 7 -> Phase 6
Phase 8 -> Phase 3
Phase 9 -> Phase 7, Phase 8
```

---

## Completed Phases (Skipped)

- Phase 1 — Data Layer & Ingestion (completed 2026-02-07).
- Phase 2 — Scoring Engine (completed 2026-02-07).
- Phase 3 — Target Portfolio & Risk Overlay (completed 2026-02-07).
- Phase 4 — Execution Engine (completed 2026-02-07).
- Phase 8 — Backtesting Engine (completed 2026-02-07).

---

## Track 1: Foundation — Data Layer & Ingestion

Phases in this track run **in parallel**.

### Phase 1: Data Layer & Ingestion (agents: 3)

- [x] Set up project structure (Python, pyproject.toml, src layout)
- [x] Define configuration module with all constants from Section 5
- [x] Create database schema (SQLite for dev) with migrations
- [x] Implement Nansen API client with rate limiter (respect 429s, exponential backoff)
- [x] Implement Nansen API client pagination helper (iterate until `is_last_page`)
- [x] Implement Nansen API client retry logic (3 attempts, 1s/2s/4s backoff)
- [x] Implement ingestion for Perp Leaderboard (3 date ranges)
- [x] Implement ingestion for Address Perp Positions
- [x] Implement ingestion for Address Perp Trades
- [x] Write unit tests for API client (mocked responses)
- [x] Write integration test: fetch real data for 1 known address, verify schema

---

## Track 2: Scoring Engine

Phases in this track run **in parallel**. Starts after Track 1 completes.

### Phase 2: Scoring Engine (agents: 3)

- [x] Implement tier-1 filter logic
- [x] Implement multi-timeframe consistency gate
- [x] Implement win rate / profit factor / pseudo-Sharpe calculators
- [x] Implement hold-time pairing algorithm (Open -> Close matching by token)
- [x] Implement style classification (HFT / SWING / POSITION)
- [x] Implement composite score formula with all 6 components
- [x] Implement recency decay and style multiplier
- [x] Implement `refresh_trader_universe()` orchestrator
- [x] Write unit tests: Test tier-1 filter with edge cases (exactly at thresholds)
- [x] Write unit tests: Test win rate bounds rejection (>85%, <35%)
- [x] Write unit tests: Test profit factor with trend-trader exception
- [x] Write unit tests: Test style classification boundary cases
- [x] Write unit tests: Test composite score normalization (all components in [0,1])
- [x] Write unit tests: Test with zero-trade, zero-variance, and single-trade edge cases
- [x] Write regression test: given fixed input data, score output is deterministic

---

## Track 3: Target Portfolio & Risk Overlay

Phases in this track run **in parallel**. Starts after Track 2 completes.

### Phase 3: Target Portfolio & Risk Overlay (agents: 3)

- [x] Implement `compute_target_portfolio()` — score-weighted aggregation
- [x] Implement `apply_risk_overlay()` — all 6 steps
- [x] Implement `calculate_copy_size()` with COPY_RATIO
- [x] Implement rebalance banding (10% tolerance)
- [x] Implement rebalance diff computation (OPEN/CLOSE/ADJUST cases)
- [x] Write unit tests: Test MAX_SINGLE_POSITION_USD cap with various account sizes
- [x] Write unit tests: Test per-token exposure cap
- [x] Write unit tests: Test directional caps (all-long portfolio scaled correctly)
- [x] Write unit tests: Test total exposure cap
- [x] Write unit tests: Test MAX_TOTAL_POSITIONS = 5 truncation
- [x] Write unit tests: Test rebalance band: 8% change skip, 12% change execute
- [x] Write unit tests: Test close+open when side flips
- [x] Write property test: no output ever violates any cap

---

## Track 4: Execution & Backtesting

Phases in this track run **in parallel**. Starts after Track 3 completes.

### Phase 4: Execution Engine (agents: 3)

- [x] Implement Hyperliquid SDK integration (order placement, cancellation, status)
- [x] Implement order type selection logic (market vs limit based on urgency)
- [x] Implement slippage allowance calculation per token
- [x] Implement fill polling loop (30s intervals, 5m timeout for limits)
- [x] Implement isolated margin and leverage setting
- [x] Implement `execute_rebalance()` orchestrator
- [x] Implement paper-trade mode (simulated fills, no real orders)
- [x] Write unit tests: Test order type selection: close=market, large open=market, small adjust=limit
- [x] Write unit tests: Test slippage calculation per token
- [x] Write unit tests: Test fill timeout cancellation flow
- [x] Write integration test with paper-trade mode: full rebalance cycle end-to-end

### Phase 8: Backtesting Engine (agents: 3)

- [x] Implement historical data fetcher (bulk leaderboard + positions over date range)
- [x] Implement simulation loop (daily refresh, 4h rebalance, 1m monitoring)
- [x] Implement execution simulator (latency, slippage, missed fills, partial fills)
- [x] Implement performance metrics calculator (return, drawdown, Sharpe, Sortino, turnover)
- [x] Generate backtest report (markdown + CSV output)
- [x] Validate backtest against paper-trade results for same period

---

## Track 5: Monitoring & Stop System

Phases in this track run **in parallel**. Starts after Track 4 completes.

### Phase 5: Monitoring & Stop System (agents: 2)

- [ ] Implement stop-loss price calculation and placement
- [ ] Implement trailing stop logic (update trailing_high, check trigger)
- [ ] Implement time-stop enforcement
- [ ] Implement `monitor_positions()` loop (60s cadence)
- [ ] Implement mutex between monitoring and rebalancing
- [ ] Implement emergency close flow
- [ ] Write unit tests: Test stop-loss trigger for long and short
- [ ] Write unit tests: Test trailing stop ratchet: price rises, trailing_high updates, then drops to trigger
- [ ] Write unit tests: Test time-stop: position opened 73h ago closed
- [ ] Write unit tests: Test that monitoring pauses during rebalance

---

## Track 6: Scheduler & Orchestration

Phases in this track run **in parallel**. Starts after Track 5 completes.

### Phase 6: Scheduler & Orchestration (agents: 2)

- [ ] Implement scheduler (APScheduler or cron-based) with daily trader refresh at 00:00 UTC
- [ ] Implement scheduler 4h rebalance cycle
- [ ] Implement scheduler 5m trade ingestion
- [ ] Implement scheduler 60s monitoring
- [ ] Implement state machine transitions and locking
- [ ] Implement graceful shutdown (complete current cycle, close orders)
- [ ] Implement startup recovery (load state from DB, resume)
- [ ] Write integration test: simulate 24h of operation with mocked APIs

---

## Track 7: Observability & Alerts

Phases in this track run **in parallel**. Starts after Track 6 completes.

### Phase 7: Observability & Alerts (agents: 2)

- [ ] Implement structured JSON logging
- [ ] Implement metrics emission (stdout / file for MVP, Prometheus optional)
- [ ] Implement alert conditions with configurable thresholds
- [ ] Implement notification delivery (log-based for MVP, webhook/Telegram later)
- [ ] Implement dashboard data export (JSON snapshots for external dashboards)
- [ ] Build health-check endpoint / status file

---

## Track 8: Paper Trading & Go-Live

Phases in this track run **in parallel**. Starts after Track 7 completes.

### Phase 9: Paper Trading & Go-Live (agents: 1)

- [ ] Run paper trading for minimum 14 days
- [ ] Audit all risk caps via log analysis
- [ ] Verify stop triggers (at least 1 of each type)
- [ ] Compare paper P&L to tracked traders' actual performance
- [ ] Review and tune configuration constants
- [ ] Implement live mode toggle (paper_trade = false)
- [ ] Deploy with initial small account_value ($5K-$10K)
- [ ] Monitor for 7 days at small size before scaling

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1: Foundation | Phase 1 | 3 | 11 |
| Track 2: Scoring Engine | Phase 2 | 3 | 15 |
| Track 3: Target Portfolio & Risk | Phase 3 | 3 | 13 |
| Track 4: Execution & Backtesting | Phase 4, Phase 8 | 6 | 17 |
| Track 5: Monitoring & Stops | Phase 5 | 2 | 10 |
| Track 6: Scheduler | Phase 6 | 2 | 8 |
| Track 7: Observability | Phase 7 | 2 | 6 |
| Track 8: Paper Trading & Go-Live | Phase 9 | 1 | 8 |
| **Total** | **9 phases** | — | **88** |
