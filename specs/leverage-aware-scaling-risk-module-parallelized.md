# Parallelized Execution Plan

**Source**: `specs/leverage-aware-scaling-risk-module.md`
**Generated**: 2026-02-07
**Max concurrent agents per track**: 8
**Max agents per phase**: 3

---

## Dependency Graph

```
Phase 1 -> Phase 2
Phase 2 -> Phase 3
Phase 3 -> Phase 4
Phase 1, Phase 4 -> Phase 5
```

---

## Completed Phases (Skipped)

Phase 1 (Track 1) — completed.
Phase 2 (Track 2) — completed.
Phase 3 (Track 3) — completed.
Phase 4 (Track 4) — completed.
Phase 5 (Track 5) — completed.

---

## Track 1: Core Sizing Foundation

Phases in this track run **in parallel**.

### Phase 1: Core Sizing Pipeline (agents: 3) ✅
- [x] Create `src/risk/constants.py` with all Agent 1 constants verbatim
- [x] Create `src/risk/types.py` with all dataclasses and enums
- [x] Implement `infer_leverage()` in `src/risk/leverage.py`
- [x] Implement `adjust_position_for_leverage()` in `src/risk/sizing.py`
- [x] Implement `get_slippage_assumption()` in `src/risk/slippage.py`
- [x] Implement `calculate_position_size()` full pipeline in `src/risk/sizing.py`
- [x] Write unit tests for Phase 1 (see Section 9)

---

## Track 2: Liquidation Monitoring

Phases in this track run **in parallel**. Starts after Track 1 completes.

### Phase 2: Liquidation Buffer Monitoring (agents: 2) ✅
- [x] Implement `check_liquidation_buffer()` in `src/risk/monitoring.py`
- [x] Implement `MonitoringLoop` class with configurable polling interval
- [x] Add cooldown logic (60s after reduce action)
- [x] Add `RiskAlert` event emission
- [x] Write unit tests for Phase 2 (see Section 9)

---

## Track 3: API Integration

Phases in this track run **in parallel**. Starts after Track 2 completes.

### Phase 3: Nansen API Integration for Monitoring (agents: 3) ✅
- [x] Implement Nansen Address Perp Positions API client (fetch my positions)
- [x] Parse `leverage_value`, `liquidation_price_usd`, `margin_used_usd`, `position_value_usd` from response
- [x] Implement Hyperliquid public API fallback for mark prices
- [x] Add rate limit handling with exponential backoff
- [x] Wire API client into `MonitoringLoop`
- [x] Write integration tests with mocked API responses

---

## Track 4: Account State Management

Phases in this track run **in parallel**. Starts after Track 3 completes.

### Phase 4: Account State Management (agents: 2) ✅
- [x] Implement `AccountState` builder from Nansen API responses
- [x] Track `total_open_positions_usd`, `total_long_exposure_usd`, `total_short_exposure_usd`, `token_exposure_usd` from live position data
- [x] Add periodic refresh (every 60s)
- [x] Wire into `calculate_position_size` so callers get fresh state

---

## Track 5: Strategy Integration

Phases in this track run **in parallel**. Starts after Track 4 completes.

### Phase 5: Upstream Strategy Integration (agents: 2) ✅
- [x] Define integration interface / adapter for strategies to call risk module
- [x] Add example integration for each strategy (#2, #3, #5, #9)
- [x] Add logging and audit trail output
- [x] End-to-end integration test: signal -> sizing -> mock execution

---

## Execution Summary

| Track | Phases | Total Agents | Total Tasks |
|-------|--------|-------------|-------------|
| Track 1 | Phase 1 | 3 | 7 |
| Track 2 | Phase 2 | 2 | 5 |
| Track 3 | Phase 3 | 3 | 6 |
| Track 4 | Phase 4 | 2 | 4 |
| Track 5 | Phase 5 | 2 | 4 |
| **Total** | **5 phases** | — | **26** |
