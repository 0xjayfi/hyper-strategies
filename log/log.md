# PnL-Weighted Pipeline — Validation Log

## Rate Limiting Implementation (2026-02-11)

Ported battle-tested rate limiting from `hyper-strategies-snap`. Key design:

- **Dual-tier limiters**: leaderboard (20/sec, 300/min, no throttle) vs profiler (1/sec, 9/min, 7s interval)
- **Persistent state**: `/tmp/pnl_weighted_rate_leaderboard.json` and `/tmp/pnl_weighted_rate_profiler.json`
- **Global cooldown**: on 429, all subsequent profiler requests block until deadline
- **Backoff**: (2s, 5s, 15s) tuple schedule, 3 max retries
- **Custom exceptions**: `NansenRateLimitError`, `NansenAuthError`
- **169 tests pass** (137 existing + 32 new rate limiter tests)

---

## Progressive Validation Plan

Run each stage in order. Fix issues before proceeding to the next.

```bash
export NANSEN_API_KEY=your_key
```

### Stage 1: Smoke Test — Single API Calls
**~30s | 5 API calls | Validates: connectivity, data shape, model parsing**

```bash
python scripts/stage1_smoke.py
```

Pass criteria: All 5 smoke tests green.

---

### Stage 2: Single Trader End-to-End
**~30s | ~4 profiler calls | Validates: positions, trades, metrics, SQLite**

```bash
python scripts/stage2_single_trader.py
```

Pass criteria: Metrics printed for all 3 windows (7d, 30d, 90d), no 429 errors.

---

### Stage 3: Small Cohort — 5 Traders
**~3 min | ~20 profiler calls | Validates: scoring, filtering, allocation**

```bash
python scripts/stage3_small_cohort.py
```

Pass criteria: Pipeline completes, allocations generated (or all filtered — OK for 5 traders).

---

### Stage 4: Position Monitor Dry Run
**~3 min | ~15 profiler calls | Validates: liquidation detection, false positives**

```bash
python scripts/stage4_position_monitor.py
```

Pass criteria: No false liquidation detections.

---

### Stage 5: Full Leaderboard — Stress Test
**1-3 hours | hundreds of calls | Validates: rate limiting under load**

```bash
# Quick test (20 traders, ~10 min):
python scripts/stage5_full_leaderboard.py --max-traders 20

# Full test (all traders):
python scripts/stage5_full_leaderboard.py
```

Pass criteria: <5 retried 429s, >95% traders with metrics, runtime within bounds.

---

### Stage 6: Scheduler — Single Full Cycle
**3-4 hours | full volume | Validates: complete orchestration**

```bash
# Quick test (20 traders):
python scripts/stage6_scheduler_cycle.py --max-traders 20

# Full test (persistent DB):
python scripts/stage6_scheduler_cycle.py --db data/stage6_test.db
```

Pass criteria: Allocations generated, DB queryable, >90% metrics success rate.

Inspect results after:
```bash
sqlite3 data/stage6_test.db '.tables'
sqlite3 data/stage6_test.db 'SELECT COUNT(*) FROM traders'
sqlite3 data/stage6_test.db 'SELECT address, final_weight FROM allocations ORDER BY final_weight DESC LIMIT 10'
```

---

## Test Results

| Stage | Date | Result | Notes |
|-------|------|--------|-------|
| 1     |      |        |       |
| 2     |      |        |       |
| 3     |      |        |       |
| 4     |      |        |       |
| 5     |      |        |       |
| 6     |      |        |       |
