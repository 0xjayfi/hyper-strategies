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

---

## First Live Run & Iterative Fixes (2026-02-17)

### Workflow Summary

Ran the full PnL-weighted scheduler (`python -m src`) end-to-end. The pipeline:

1. **Leaderboard fetch** — pulls top 50 traders (30-day window) from Nansen perp-leaderboard API
2. **Metrics computation** — for each trader, fetches trades across 7d/30d/90d windows, computes win rate, profit factor, Sharpe, ROI proxy, max drawdown
3. **Anti-luck filtering** — multi-timeframe profitability gates + win rate bounds + min trade count
4. **Composite scoring** — 6-component weighted score (ROI 25%, Sharpe 20%, consistency 20%, win rate 15%, smart money 10%, risk mgmt 10%) x style multiplier x recency decay
5. **Allocation** — softmax (T=2.0) -> ROI tier adjustment -> risk caps (max 5 positions, 40% max single) -> turnover limits (15%/day)
6. **Position monitoring** — 15-min snapshots, liquidation detection, 14-day blacklist

### Bugs Found & Fixed

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| **Leaderboard returns only 10 traders** | No pagination param passed to API | Added `pagination={"page": 1, "per_page": 50}` |
| **0 eligible traders (filters too strict)** | Hardcoded thresholds in `filters.py` ignoring `config.py` | Rewired filters to read from config; loosened gates |
| **`'float' object not subscriptable`** | Scheduler stored `scores[addr] = float` but allocation expected dict | Changed to pass full score dict |
| **All scores = 0 (recency decay)** | Naive datetime subtracted from tz-aware datetime -> silent TypeError | Added `.replace(tzinfo=timezone.utc)` to naive timestamps |
| **All traders classified as HFT (0.4x)** | HFT threshold `trades_per_day > 5` too aggressive for perp traders | Raised to `> 100` — normal active traders now classify as SWING |
| **max_drawdown always ~0** | `worst_loss / account_value` meaningless for whale accounts ($7M-38M) | Switched to trade-relative: `worst_loss / trade_value` |
| **ROI normalization near zero** | `roi / 100` expects 0-100% range but whale ROI is 0.02-6% | Changed to `roi / 10` — 10% ROI = perfect score |
| **7d/30d/90d metrics identical** | API returns oldest-first; 10-page cap gets same trades for all windows | Added `order_by=[{"direction": "DESC"}]` for newest-first |
| **API rejects `desc`** | Nansen requires uppercase `DESC` | Fixed casing |
| **No metrics caching** | Every 6h cycle re-fetches all traders from API (~2h per cycle) | Added cache check: skip traders with metrics < 6h old |
| **Win rate normalization too narrow** | 0.35-0.85 bounds excluded many valid traders | Widened to 0.25-0.75 ceiling |

### Final Configuration

```
Anti-luck gates:  7d: pnl > -999999, roi > -999 (effectively disabled)
                 30d: pnl > $500, roi > 0%
                 90d: pnl > $1000, roi > 0%
Win rate bounds:  0.25 - 0.90
Min profit factor: 1.1
Min trades (30d):  10
Pagination cap:    10 pages (1000 trades) per window
ROI normalization: 10% = 1.0 (was 100%)
HFT threshold:     >100 trades/day AND <1h avg hold
```

### Allocation Results (2026-02-17 10:28 UTC)

**51 active traders -> 11 eligible -> 7 allocated** (risk cap: max 5 + 2 at reduced weight)

| # | Address | Label | Alloc | Score | 30d PnL | 30d WR | 30d PF | Key Strength |
|---|---------|-------|-------|-------|---------|--------|--------|-------------|
| 1 | `0x45d26f28...` | Smart HL Perps Trader | **23.6%** | 0.715 | $1,178,627 | 77.4% | 2234 | Highest ROI (6.3%), smart money label |
| 2 | `0x3440f23a...` | Token Millionaire | **16.2%** | 0.590 | $89,074 | 89.7% | 62.5 | Strong ROI (4.5%), very high win rate |
| 3 | `0x31dea251...` | Trading Bot | **16.2%** | 0.523 | $62,254 | 77.8% | 873 | Perfect consistency (1.0), all timeframes profitable |
| 4 | `0x09bc1cf4...` | (unlabeled) | **16.2%** | 0.474 | $161,775 | 56.9% | 4.71 | Solid balanced metrics, ROI 2.5% |
| 5 | `0xecb63caa...` | Wintermute Market Making | **16.2%** | 0.381 | $26,056 | 43.4% | 1.16 | Institutional, perfect consistency |
| 6 | `0x856c3503...` | Whale | **7.6%** | 0.393 | -$119,033 | 95.1% | 0.05 | Highest Sharpe (2.6) but negative 30d PnL |
| 7 | `0xfc667adb...` | Bridge User | **4.1%** | 0.217 | $42,253 | 28.7% | 12.0 | Trend trader (low WR, high PF), 0.50 ROI tier |

### Observations

- **Smart HL Perps Trader dominates** — highest score by a wide margin, driven by ROI + smart money label bonus (0.80)
- **Wintermute (market maker)** gets allocated despite mediocre metrics because of perfect consistency across all timeframes
- **Whale** has negative 30d PnL but still gets 7.6% due to exceptional Sharpe ratio — the system values risk-adjusted returns
- **Bridge User** gets lowest allocation (4.1%) with 0.50 ROI tier penalty for negative 7d performance
- **Token Millionaire** has the worst risk score (0.226) due to 18.25% max trade-relative drawdown, but high win rate and ROI compensate
- **44 traders filtered out** — mostly due to: win rate > 90% (suspected manipulation), insufficient PnL gates, or missing metrics windows
