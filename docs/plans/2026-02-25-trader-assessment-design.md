# Trader Assessment Feature — Design Document

Date: 2026-02-25

## Overview

Add a trader assessment feature to the dashboard. Users input any trader address and receive an independent quality evaluation across 10 scoring strategies, with an overall confidence tier based on how many strategies the address passes.

## Architecture: Hybrid (Shared Metrics, Separate Strategies)

The existing `src/metrics.py` serves as the shared data layer. A new `src/assessment/` package contains 10 independent strategy modules that consume `TradeMetrics`. Assessment logic is fully decoupled from the allocation-focused `src/scoring.py` pipeline — they share data but not scoring logic.

### New Files

```
src/assessment/
├── __init__.py
├── engine.py                  # AssessmentEngine — orchestrates all strategies
├── base.py                    # BaseStrategy ABC
├── strategies/
│   ├── __init__.py
│   ├── roi.py                 # ROI Performance
│   ├── sharpe.py              # Risk-Adjusted Returns
│   ├── profit_factor.py       # Profit Factor
│   ├── win_rate.py            # Win Rate Quality
│   ├── anti_luck.py           # Anti-Luck Filter
│   ├── consistency.py         # Consistency
│   ├── drawdown.py            # Drawdown Resilience
│   ├── leverage.py            # Leverage Discipline
│   ├── position_sizing.py     # Position Sizing
│   └── trend.py               # Profitability Trend

backend/routers/
├── assess.py                  # GET /api/v1/assess/{address}
```

### BaseStrategy Interface

```python
class BaseStrategy(ABC):
    name: str
    description: str
    category: str  # "Core Performance" | "Behavioral Quality" | "Risk Discipline" | "Pattern Quality"

    @abstractmethod
    def evaluate(self, metrics: TradeMetrics, positions: list) -> StrategyResult
```

Each strategy returns:

```python
@dataclass
class StrategyResult:
    name: str
    category: str
    score: int        # 0-100
    passed: bool
    explanation: str
```

### Data Flow

1. Request hits `GET /api/v1/assess/{address}`
2. Router checks datastore for cached `trade_metrics` + `trader_scores` (leaderboard shortcut)
3. If cache miss → fetch trades from Nansen `profiler/perp-trades` + positions from `profiler/perp-positions`
4. Pass raw trades to existing `src/metrics.py` → `TradeMetrics` object
5. `AssessmentEngine.assess(trade_metrics, positions)` runs all 10 strategies
6. Engine aggregates into `AssessmentResult`

## Scoring Strategies (10 total)

### Tier 1 — Core Performance

| Strategy | Measures | Pass Threshold | Score Basis |
|----------|----------|----------------|-------------|
| ROI Performance | Raw returns relative to capital | ROI >= 0% (30d) | Normalized ROI, 10%+ -> max |
| Risk-Adjusted Returns | Pseudo-Sharpe ratio | Sharpe >= 0.5 | Normalized, 3.0+ -> max |
| Profit Factor | Gross profit / gross loss | PF >= 1.1 | Scaled 1.0-3.0 range |

### Tier 2 — Behavioral Quality

| Strategy | Measures | Pass Threshold | Score Basis |
|----------|----------|----------------|-------------|
| Win Rate Quality | Success rate in healthy bounds | WR in [0.30, 0.85] | Distance from optimal ~55% band |
| Anti-Luck Filter | Statistical significance | >= 10 trades in 30d, PnL >= $500, WR in [0.25, 0.90] | Binary pass + margin score |
| Consistency | Multi-timeframe profitability | Profitable in >= 2 windows | Variance across 7d/30d windows |

### Tier 3 — Risk Discipline

| Strategy | Measures | Pass Threshold | Score Basis |
|----------|----------|----------------|-------------|
| Drawdown Resilience | Worst peak-to-trough decline | Max DD < 30% of peak PnL | Inverse of max drawdown depth |
| Leverage Discipline | Leverage consistency | Avg leverage < 20x, no trade > 50x | Std dev of leverage + max cap |
| Position Sizing | No single trade dominates PnL | Largest trade < 40% of total PnL | Herfindahl-like concentration index |

### Tier 4 — Pattern Quality

| Strategy | Measures | Pass Threshold | Score Basis |
|----------|----------|----------------|-------------|
| Profitability Trend | PnL trajectory direction | Recent-half PnL >= 50% of first-half | Slope of rolling PnL windows |

## Confidence Score

- **Confidence** = strategies passed / total strategies
- **Tiers**: 9-10 = Elite, 7-8 = Strong, 5-6 = Moderate, 3-4 = Weak, 0-2 = Avoid
- **Edge case**: 0 trades → all strategies score 0, all fail, tier = "Insufficient Data"

## API Contract

### `GET /api/v1/assess/{address}`

**Query params:**
- `window_days` (optional, default 30) — trade history lookback

**Response (200):**

```json
{
  "address": "0xabc...",
  "is_cached": true,
  "window_days": 30,
  "trade_count": 47,
  "confidence": {
    "passed": 8,
    "total": 10,
    "tier": "Strong"
  },
  "strategies": [
    {
      "name": "ROI Performance",
      "category": "Core Performance",
      "score": 82,
      "passed": true,
      "explanation": "30d ROI of 8.2%, above 0% threshold"
    }
  ],
  "computed_at": "2026-02-25T12:00:00Z"
}
```

**Error cases:**
- No trades found: 200 with `trade_count: 0`, all strategies score 0, tier "Insufficient Data"
- Invalid address format: 400
- Nansen API error: 502 with retry message

## Cached vs. Live Data Path

### Leaderboard address (cached):
1. Query datastore for `trade_metrics` (30d window) and `trader_scores`
2. If found and `computed_at` < 6 hours old, use cached data
3. Pass cached `TradeMetrics` to `AssessmentEngine` — no Nansen API calls
4. Response: `is_cached: true`

### Unknown address (live):
1. No cached data found
2. Fetch trades from `profiler/perp-trades` (~7s, rate-limited)
3. Fetch positions from `profiler/perp-positions` (parallelizable)
4. Compute `TradeMetrics` via `src/metrics.py`
5. Run all 10 strategies
6. Response: `is_cached: false`
7. Results are NOT persisted — one-shot assessment

### TradeMetrics Extension

Extend `TradeMetrics` with 4 new derived fields to support full caching for leaderboard addresses:
- `max_leverage` — highest leverage used across all trades
- `leverage_std` — standard deviation of leverage across trades
- `largest_trade_pnl_ratio` — largest single trade PnL as fraction of total PnL
- `pnl_trend_slope` — linear regression slope of rolling PnL windows

These are computed during the normal 6-hour recompute cycle.

## Frontend Design

### Routes

1. **`/assess`** — Input page
   - Centered text input for address (hex validation)
   - "Assess Trader" button
   - Recent assessment history from localStorage below input
   - On submit: navigate to `/assess/:address`

2. **`/assess/:address`** — Results page
   - **Header**: Truncated address, confidence tier badge (color-coded), "X/10 passed"
   - **Radar chart**: All 10 strategy scores on radial axes, color-grouped by tier (Core=blue, Behavioral=green, Risk=orange, Pattern=purple)
   - **Scorecard table**: Strategy name, Category, Score (0-100 color bar), Pass/Fail badge, Explanation
   - **Loading state**: Skeleton UI with progress message ("Fetching trades..." -> "Computing strategies...")
   - **Navigation**: "Assess another" link back to `/assess`. If address is on leaderboard, link to TraderDeepDive page.

### Sidebar Navigation

Add "Assess" entry to sidebar nav alongside Leaderboard, Allocations, Market, Positions.

### Tech Stack

Same as existing dashboard — React Query hook, Recharts RadarChart, TanStack table. No new dependencies.

## UX for Slow Responses

Synchronous request with loading state. For unknown addresses, the Nansen fetch takes ~15 seconds. The frontend shows a skeleton UI with progressive status messages. No async job queue — the wait is short enough that a loading indicator suffices.
