# Parallelized Execution Plan

**Source**: specs/consensus-confluence-trading.md
**Generated**: 2026-02-07
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

Phase 0 -> (no dependencies)
Phase 1 -> Phase 0
Phase 2 -> Phase 1
Phase 3 -> Phase 2
Phase 4 -> Phase 3
Phase 5 -> Phase 4
Phase 6 -> Phase 5
Phase 7 -> Phase 6
Phase 8 -> Phase 6

---

## Completed Phases (Skipped)

Phase 0 (Track 1: Project Foundation) — completed.
Phase 1 (Track 2: API Client Layer) — completed.
Phase 2 (Track 3: Trader Intelligence) — completed.

---

## Track 1: Project Foundation

Phases in this track run **in parallel**.

### Phase 0: Project Scaffolding (agents: 1) ✓
- [x] Initialize Python project with `pyproject.toml` (deps: aiohttp, pydantic-settings, hyperliquid-python-sdk, pytest, pytest-asyncio)
- [x] Create directory structure with all source and test files under `src/consensus/` and `tests/`
- [x] Set up `.env` loading for `NANSEN_API_KEY`, `HL_PRIVATE_KEY`, `TYPEFULLY_API_KEY`
- [x] Create SQLite DB initialization script

---

## Track 2: API Client Layer

Phases in this track run **in parallel**. Starts after Track 1 completes.

### Phase 1: Nansen API Client + Data Ingestion (agents: 2) ✓
- [x] Implement `nansen_client.py` with async methods for all 3 endpoints: `fetch_leaderboard`, `fetch_address_trades`, `fetch_address_positions`
- [x] Add retry logic with exponential backoff for 429 (rate limit) responses
- [x] Add pagination auto-follow (loop until `is_last_page == true`)
- [x] Add request/response logging for debugging
- [x] Write integration test that hits real API with test addresses (gated by `NANSEN_API_KEY` env var)

---

## Track 3: Trader Intelligence

Phases in this track run **in parallel**. Starts after Track 2 completes.

### Phase 2: Trader Scoring + Watchlist Builder (agents: 2) ✓
- [x] Implement `scoring.py`: `classify_trader_style(trades, days_active) -> TraderStyle`, `compute_trader_score(trader_data, trades) -> float`, `build_watchlist(config) -> list[TrackedTrader]`
- [x] Implement `clusters.py`: `detect_copy_clusters(traders, trade_log, lookback_days) -> dict[str, int]` with Union-Find implementation for cluster grouping
- [x] Write unit tests: style classification with known trade patterns, scoring formula outputs with synthetic data, cluster detection merges correlated traders

---

## Track 4: Core Consensus Logic

Phases in this track run **in parallel**. Starts after Track 3 completes.

### Phase 3: Consensus Engine (agents: 2)
- [ ] Implement `consensus_engine.py`: `compute_token_consensus(token, positions, traders, config, now) -> TokenConsensus` and `compute_all_tokens_consensus(positions_by_token, traders, config) -> dict[str, TokenConsensus]`
- [ ] Implement freshness decay: `e^(-hours / FRESHNESS_HALF_LIFE_HOURS)`
- [ ] Implement cluster-aware counting (one vote per cluster_id)
- [ ] Implement size threshold filtering per token
- [ ] Write unit tests: 3 traders long BTC with 2:1 volume ratio → STRONG_LONG; 2 long 2 short → MIXED; 3 traders in same cluster → NOT strong; stale positions with freshness decay → MIXED; position weight < 10% → filtered out

---

## Track 5: Signal Processing

Phases in this track run **in parallel**. Starts after Track 4 completes.

### Phase 4: Signal Gate + Confirmation Window (agents: 2)
- [ ] Implement `signal_gate.py`: `process_consensus_change(token, consensus, current_price, config, now) -> PendingSignal | None` with `pending_signals` dict management, `COPY_DELAY_MINUTES` wait enforcement, `MAX_PRICE_SLIPPAGE_PERCENT` gate
- [ ] Implement Hyperliquid price feed in `hl_client.py`: WebSocket subscription to `allMids`, fallback REST polling, stale price detection (>30s)
- [ ] Write unit tests: signal confirmed after 15 min with <2% slippage → entry; price moves >2% during window → rejected; consensus breaks during window → cancelled; re-checked at 14 min → still pending

---

## Track 6: Entry Execution

Phases in this track run **in parallel**. Starts after Track 5 completes.

### Phase 5: Entry Sizing + Risk Caps (agents: 2)
- [ ] Implement `sizing.py`: `calculate_entry_size(token, side, consensus, account_value, positions, config) -> float | None`, `select_leverage(avg_trader_leverage, config) -> int`, `select_order_type(action, signal_age, current_price, trader_entry, token) -> tuple`
- [ ] Implement all cap checks: single position cap, total exposure cap, token exposure cap, directional (long/short) exposure cap, position count cap
- [ ] Write unit tests: entry at $10K with $100K account → allowed; 6th position attempt → blocked (MAX_TOTAL_POSITIONS=5); token already at 14% exposure → capped to 1%; leverage 20x from trader → capped to 5x

---

## Track 7: Position Management

Phases in this track run **in parallel**. Starts after Track 6 completes.

### Phase 6: Exit Rules + Position Monitor (agents: 2)
- [ ] Implement `risk.py`: `check_stop_loss(position, current_price, config) -> str | None`, `check_time_stop(position, now, config) -> bool`, `check_liquidation_buffer(position, current_price, liq_price, config) -> str | None`
- [ ] Implement `position_manager.py`: `monitor_positions(positions, consensus_map, prices, config, now) -> list[ExitSignal]` with priority-based exit signal emission, trailing stop high-water-mark tracking
- [ ] Write unit tests: long at $100 price drops to $95 → stop_loss; long at $100 price to $110 drops to $101.50 → trailing_stop; position held 73h → time_stop; liquidation buffer at 9% → emergency_close; buffer at 18% → reduce_50; consensus STRONG_LONG now MIXED → consensus_break

---

## Track 8: Integration & Backtesting

Phases in this track run **in parallel**. Starts after Track 7 completes.

### Phase 7: Scheduler + Paper Trading (agents: 2)
- [ ] Implement `scheduler.py`: asyncio event loop with scheduled tasks — daily `refresh_watchlist()`, every 5 min `poll_all_trader_trades()`, every 15 min `poll_all_trader_positions()`, every 15 min `recompute_consensus()` → `process_signals()` → `check_exits()`, continuous WebSocket price feed
- [ ] Implement `paper_trader.py`: simulated order execution with configurable slippage model, track simulated account balance and positions in DB, log all signals/entries/exits with timestamps, compare simulated PnL to naive single-trader mirror
- [ ] Add Typefully integration for social alerts (optional v1): post consensus signals to X via `POST /v2/social-sets/{id}/drafts`

### Phase 8: Backtesting Framework (agents: 2)
- [ ] Build historical data fetcher: fetch 90 days of trades for top 50 leaderboard wallets, store in SQLite for replay
- [ ] Build replay engine: step through historical trades chronologically, reconstruct positions at each timestamp, compute consensus snapshots, simulate entries/exits using same signal pipeline, model realistic latency (30-60s random delay), model slippage (BTC 0.03%, SOL 0.10%, HYPE 0.20%)
- [ ] Output backtest report: total return, Sharpe ratio, max drawdown, win rate, number of trades, avg hold time, avg PnL per trade, trades skipped (slippage gate, cap limits), comparison consensus strategy vs naive mirror of best single trader
- [ ] Write backtest validation tests: known scenario with hand-calculated expected PnL

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1: Project Foundation | Phase 0 | 1 | 4 |
| Track 2: API Client Layer | Phase 1 | 2 | 5 |
| Track 3: Trader Intelligence | Phase 2 | 2 | 3 |
| Track 4: Core Consensus Logic | Phase 3 | 2 | 5 |
| Track 5: Signal Processing | Phase 4 | 2 | 3 |
| Track 6: Entry Execution | Phase 5 | 2 | 3 |
| Track 7: Position Management | Phase 6 | 2 | 3 |
| Track 8: Integration & Backtesting | Phase 7, Phase 8 | 4 | 7 |
| **Total** | **9 phases** | — | **33** |
