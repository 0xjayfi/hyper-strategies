# Parallelized Execution Plan

**Source**: `specs/pnl-weighted-dynamic-allocation.md`
**Generated**: 2026-02-07
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

```
Phase 1  -> (no dependencies)
Phase 2  -> Phase 1
Phase 3  -> Phase 2                (Phase 1 implied via Phase 2)
Phase 7  -> Phase 2                (Phase 1 implied via Phase 2)
Phase 4  -> Phase 3                (Phase 2 implied via Phase 3)
Phase 5  -> Phase 4                (Phase 3 implied via Phase 4)
Phase 6  -> Phase 5                (Phase 4 implied via Phase 5)
Phase 9  -> Phase 6
Phase 10 -> Phase 6                (Phases 3-5 implied via Phase 6)
Phase 11 -> Phase 6, Phase 7       (Phases 3-5 implied via Phase 6)
Phase 8  -> Phase 6, Phase 7       (all prior phases implied)
```

Note: Transitive reduction applied. E.g., Phase 8's declared dependency on Phases 1-7 reduces to just Phase 6 + Phase 7, since Phase 6 transitively depends on 5→4→3→2→1 and Phase 7 depends on 2→1.

---

## Completed Phases (Skipped)

- **Phase 1** (Track 1) — All 8 tasks completed.
- **Phase 2** (Track 2) — All 5 tasks completed.

---

## Track 1: Foundation — API Client

Phases in this track run **in parallel**.

### Phase 1: Nansen API Client & Data Ingestion (agents: 2)

- [x] Create `src/nansen_client.py` — thin async wrapper around Nansen endpoints with retry/rate-limit handling (429 backoff).
- [x] Implement `fetch_leaderboard(date_from, date_to, filters, pagination)` — calls `POST /api/v1/perp-leaderboard`. Returns `list[LeaderboardEntry]` with fields: `trader_address`, `trader_address_label`, `total_pnl`, `roi`, `account_value`.
- [x] Implement `fetch_address_trades(address, date_from, date_to, pagination)` — calls `POST /api/v1/profiler/perp-trades`. Auto-paginates to fetch all pages. Returns `list[Trade]` with fields: `action`, `closed_pnl`, `price`, `side`, `size`, `timestamp`, `token_symbol`, `value_usd`, `fee_usd`, `start_position`.
- [x] Implement `fetch_address_positions(address)` — calls `POST /api/v1/profiler/perp-positions`. Returns `PositionSnapshot` with `asset_positions` list and `margin_summary_account_value_usd`.
- [x] Implement `fetch_pnl_leaderboard(token_symbol, date_from, date_to, filters, pagination)` — calls `POST /api/v1/tgm/perp-pnl-leaderboard`. Returns per-token PnL data with `roi_percent_realised`, `roi_percent_unrealised`, `nof_trades`, etc.
- [x] Create Pydantic models for all API responses: `LeaderboardEntry`, `Trade`, `Position`, `PositionSnapshot`, `PnlLeaderboardEntry`.
- [x] Add `.env` config for `NANSEN_API_KEY` and `NANSEN_BASE_URL`.
- [x] Write integration smoke test that hits each endpoint with a known address and asserts schema.

---

## Track 2: Data Store

Phases in this track run **in parallel**. Starts after Track 1 completes.

### Phase 2: Data Store & Trader Registry (agents: 2)

- [x] Create `src/datastore.py` using SQLite (via `aiosqlite` or sync `sqlite3`).
- [x] Define schema (all 7 tables: traders, leaderboard_snapshots, trade_metrics, trader_scores, allocations, blacklist, position_snapshots).
- [x] Implement CRUD helpers: `upsert_trader()`, `insert_leaderboard_snapshot()`, `insert_trade_metrics()`, `insert_score()`, `insert_allocation()`, `add_to_blacklist()`, `is_blacklisted()`, `get_latest_metrics(address, window)`, `get_latest_score(address)`, `get_latest_allocations()`.
- [x] Implement `get_position_history(address, token, lookback_hours)` for liquidation detection.
- [x] Add data retention policy: keep last 90 days of snapshots, archive older.

---

## Track 3: Metrics, Scoring & Position Monitoring

Phases in this track run **in parallel**. Starts after Track 2 completes.

### Phase 3: Metrics Engine — Derived Trade Metrics (agents: 1)

- [ ] Create `src/metrics.py`.
- [ ] Implement `compute_trade_metrics(trades: list[Trade], account_value: float, window_days: int) -> TradeMetrics` with win_rate, profit_factor, pseudo_sharpe, roi_proxy, max_drawdown_proxy.
- [ ] Implement ROI proxy fallback: when the leaderboard doesn't provide per-timeframe realized ROI, use `roi_proxy = sum(closed_pnl over window) / account_value_at_window_start * 100`. Account value at window start is approximated from the earliest leaderboard snapshot within the window, or from the current `account_value - total_pnl` as a fallback.
- [ ] Implement batch computation: `recompute_all_metrics(trader_addresses, windows=[7, 30, 90])` that fetches trades for each window, calls `compute_trade_metrics`, and stores results.

### Phase 7: Position Monitor & Liquidation Detection (agents: 1)

- [ ] Create `src/position_monitor.py`.
- [ ] Implement liquidation detection: compare current positions against last snapshot; if a position disappeared without a Close/Reduce trade, treat as probable liquidation and blacklist trader.
- [ ] Schedule position monitoring every 15 minutes.
- [ ] On liquidation detection, emit event for downstream strategy to close copied positions.

---

## Track 4: Scoring & Filters

Phases in this track run **in parallel**. Starts after Track 3 completes.

### Phase 4: Composite Scoring Engine (agents: 2)

- [ ] Create `src/scoring.py`.
- [ ] Implement all component score functions: `normalized_roi()`, `normalized_sharpe()`, `normalized_win_rate()`, `consistency_score()`, `smart_money_bonus()`, `risk_management_score()`.
- [ ] Implement `classify_trader_style()` and style multiplier lookup.
- [ ] Implement `recency_decay()` with configurable half-life.
- [ ] Implement `compute_trader_score()` — full composite score assembly with all 6 weighted components, style multiplier, recency decay, and 7d ROI tier multiplier.

---

## Track 5: Anti-Luck Filters

Phases in this track run **in parallel**. Starts after Track 4 completes.

### Phase 5: Anti-Luck Filters & Blacklist Gates (agents: 1)

- [ ] Create `src/filters.py`.
- [ ] Implement `apply_anti_luck_filter(metrics_7d, metrics_30d, metrics_90d)` with multi-timeframe profitability gates (7d/30d/90d), win rate bounds (reject >85% or <35% unless trend trader), profit factor gate (>1.5, trend trader variant), and minimum trade count.
- [ ] Implement blacklist check: `is_trader_eligible()` and `blacklist_trader()` with 14-day cooldown.
- [ ] Implement combined eligibility gate: `is_fully_eligible()`.

---

## Track 6: Allocation Engine & Config

Phases in this track run **in parallel**. Starts after Track 5 completes.

### Phase 6: Allocation Engine (agents: 2)

- [ ] Create `src/allocation.py`.
- [ ] Implement `scores_to_weights_softmax()` with temperature parameter (T=2.0 default).
- [ ] Implement `apply_roi_tier()` — multiply weights by 7d ROI tier (1.0/0.75/0.5), renormalize.
- [ ] Implement `RiskConfig` dataclass and `apply_risk_caps()` — enforce max 5 positions, max 40% single weight, truncate and renormalize.
- [ ] Implement `apply_turnover_limits()` — cap daily weight changes at 15 percentage points, renormalize.
- [ ] Implement `compute_allocations()` — end-to-end pipeline: softmax -> ROI tier -> risk caps -> turnover limits.
- [ ] Create `src/config.py` — centralized constants for all scoring weights, thresholds, risk caps, and scheduling parameters.

---

## Track 7: Interfaces, Backtesting, Tests & Orchestration

Phases in this track run **in parallel**. Starts after Track 6 completes.

### Phase 9: Strategy Interfaces (agents: 2)

- [ ] Create `src/strategy_interface.py`.
- [ ] Implement core interface: `get_trader_allocation(trader_id)` and `get_all_allocations()`.
- [ ] Implement Strategy #2 — `build_index_portfolio()`: weight each trader's positions by allocation, scale to account size with 50% max deployment.
- [ ] Implement Strategy #3 — `weighted_consensus()`: compute weighted long/short signals per token with STRONG_LONG/STRONG_SHORT/MIXED classification.
- [ ] Implement Strategy #5 — `size_copied_trade()`: proportional sizing with weight, copy_ratio, and 10% per-position hard cap.

### Phase 10: Backtesting Framework (agents: 1)

- [ ] Create `src/backtest.py`.
- [ ] Implement `backtest_allocations()` — historical allocation simulation with portfolio return tracking.
- [ ] Implement evaluation metrics: turnover, stability (std dev of weights), max drawdown, performance-chasing detection (correlation of delta_weight with future returns).

### Phase 11: Tests (agents: 3)

- [ ] Create `tests/` directory with `conftest.py` for fixtures (shared `make_trade()`, `make_metrics()`, `InMemoryDatastore` helpers).
- [ ] Implement metric calculation tests (`tests/test_metrics.py`): win_rate_basic, profit_factor, pseudo_sharpe, empty_trades, roi_proxy.
- [ ] Implement anti-luck filter tests (`tests/test_filters.py`): passes_all_gates, fails_7d_gate, high_win_rate_rejected, trend_trader_exception, insufficient_trades_rejected.
- [ ] Implement blacklist & cooldown tests (`tests/test_blacklist.py`): blacklist_blocks_trader, blacklist_expires, cooldown_14_days.
- [ ] Implement allocation tests (`tests/test_allocation.py`): allocations_sum_to_one, max_positions_cap, roi_tier_applied, turnover_limit, single_trader_weight_cap.
- [ ] Implement scoring tests (`tests/test_scoring.py`): consistency_all_positive, consistency_two_positive, consistency_all_negative, normalized_roi_capped, smart_money_fund, smart_money_labeled.
- [ ] Implement strategy interface tests (`tests/test_strategy_interface.py`) and backtest tests (`tests/test_backtest.py`).

### Phase 8: Scheduler & Orchestration (agents: 1)

- [ ] Create `src/scheduler.py` using `APScheduler` or simple `asyncio` loop.
- [ ] Define update schedule: leaderboard daily, metrics/scores/allocations every 6h, position monitor every 15m, blacklist cleanup daily.
- [ ] Implement `full_recompute_cycle()` — orchestrate metrics recomputation, scoring, eligibility filtering, and allocation pipeline for all tracked traders.

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1: Foundation — API Client | Phase 1 | 2 | 8 |
| Track 2: Data Store | Phase 2 | 2 | 5 |
| Track 3: Metrics & Position Monitoring | Phase 3, Phase 7 | 2 | 8 |
| Track 4: Scoring | Phase 4 | 2 | 5 |
| Track 5: Anti-Luck Filters | Phase 5 | 1 | 4 |
| Track 6: Allocation Engine & Config | Phase 6 | 2 | 7 |
| Track 7: Interfaces, Backtesting, Tests & Orchestration | Phase 9, Phase 10, Phase 11, Phase 8 | 7 | 18 |
| **Total** | **11 phases** | — | **55 tasks** |
