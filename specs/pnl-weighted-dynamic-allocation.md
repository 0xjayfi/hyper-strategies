# PnL-Weighted Dynamic Allocation — Implementation Plan

> **Strategy #9** — Dynamically allocate capital across tracked traders based on composite scoring of recent PnL performance, feeding allocation weights into Strategies #2 (Index Portfolio), #3 (Consensus Voting), and #5 (Per-Trade Sizing).

---

## Problem Statement

A copytrading system that allocates equally to all tracked traders ignores the fact that trader performance varies over time. A trader who was profitable last month may be on a losing streak now. We need a scoring and allocation engine that:

1. Computes a multi-factor composite score for each tracked trader using Nansen data.
2. Converts scores into normalized allocation weights.
3. Applies momentum multipliers (7d ROI tiers) and decay functions so stale data fades.
4. Enforces anti-luck filters and blacklist gates before any capital flows.
5. Respects hard risk constraints (max positions, directional caps, per-token limits).
6. Re-evaluates on a schedule and exposes a clean interface for downstream strategies.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Scheduler (cron)                      │
│  daily: refresh_leaderboard()                           │
│  every 6h: recompute_trade_metrics()                    │
│  every 15m: monitor_positions()                         │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
           ▼              ▼              ▼
┌──────────────┐ ┌────────────────┐ ┌──────────────────┐
│ NansenClient │ │ MetricsEngine  │ │ PositionMonitor  │
│  (API layer) │ │ (scoring)      │ │ (liquidation     │
│              │ │                │ │  detection)       │
└──────┬───────┘ └───────┬────────┘ └────────┬─────────┘
       │                 │                    │
       ▼                 ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                     DataStore (SQLite)                   │
│  traders, trade_metrics, scores, allocations, blacklist  │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  AllocationEngine                        │
│  get_trader_allocation(trader_id) -> weight              │
│  get_all_allocations() -> {trader_id: weight}            │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
           ▼              ▼              ▼
     Strategy #2    Strategy #3    Strategy #5
     (Index Rebal)  (Consensus)    (Per-Trade)
```

---

## Phase 1: Nansen API Client & Data Ingestion

**Depends on:** None

- [x] Create `src/nansen_client.py` — thin async wrapper around Nansen endpoints with retry/rate-limit handling (429 backoff).
- [x] Implement `fetch_leaderboard(date_from, date_to, filters, pagination)` — calls `POST /api/v1/perp-leaderboard`. Returns `list[LeaderboardEntry]` with fields: `trader_address`, `trader_address_label`, `total_pnl`, `roi`, `account_value`.
- [x] Implement `fetch_address_trades(address, date_from, date_to, pagination)` — calls `POST /api/v1/profiler/perp-trades`. Auto-paginates to fetch all pages. Returns `list[Trade]` with fields: `action`, `closed_pnl`, `price`, `side`, `size`, `timestamp`, `token_symbol`, `value_usd`, `fee_usd`, `start_position`.
- [x] Implement `fetch_address_positions(address)` — calls `POST /api/v1/profiler/perp-positions`. Returns `PositionSnapshot` with `asset_positions` list and `margin_summary_account_value_usd`.
- [x] Implement `fetch_pnl_leaderboard(token_symbol, date_from, date_to, filters, pagination)` — calls `POST /api/v1/tgm/perp-pnl-leaderboard`. Returns per-token PnL data with `roi_percent_realised`, `roi_percent_unrealised`, `nof_trades`, etc.
- [x] Create Pydantic models for all API responses: `LeaderboardEntry`, `Trade`, `Position`, `PositionSnapshot`, `PnlLeaderboardEntry`.
- [x] Add `.env` config for `NANSEN_API_KEY` and `NANSEN_BASE_URL`.
- [x] Write integration smoke test that hits each endpoint with a known address and asserts schema.

---

## Phase 2: Data Store & Trader Registry

**Depends on:** Phase 1

- [x] Create `src/datastore.py` using SQLite (via `aiosqlite` or sync `sqlite3`).
- [x] Define schema:

```sql
CREATE TABLE traders (
    address         TEXT PRIMARY KEY,
    label           TEXT,
    first_seen      TEXT NOT NULL,       -- ISO date
    is_active       INTEGER DEFAULT 1,
    style           TEXT,                -- HFT | SWING | POSITION
    notes           TEXT
);

CREATE TABLE leaderboard_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at     TEXT NOT NULL,        -- ISO datetime
    date_from       TEXT NOT NULL,
    date_to         TEXT NOT NULL,
    address         TEXT NOT NULL REFERENCES traders(address),
    total_pnl       REAL,
    roi             REAL,
    account_value   REAL
);

CREATE TABLE trade_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT NOT NULL REFERENCES traders(address),
    computed_at     TEXT NOT NULL,        -- ISO datetime
    window_days     INTEGER NOT NULL,     -- 7, 30, or 90
    total_trades    INTEGER,
    winning_trades  INTEGER,
    losing_trades   INTEGER,
    win_rate        REAL,
    gross_profit    REAL,
    gross_loss      REAL,
    profit_factor   REAL,
    avg_return      REAL,
    std_return      REAL,
    pseudo_sharpe   REAL,
    total_pnl       REAL,
    roi_proxy       REAL,                 -- sum(closed_pnl) / account_value
    max_drawdown_proxy REAL               -- worst single-trade loss / account_value
);

CREATE TABLE trader_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT NOT NULL REFERENCES traders(address),
    computed_at     TEXT NOT NULL,
    normalized_roi          REAL,
    normalized_sharpe       REAL,
    normalized_win_rate     REAL,
    consistency_score       REAL,
    smart_money_bonus       REAL,
    risk_management_score   REAL,
    style_multiplier        REAL,
    recency_decay           REAL,
    raw_composite_score     REAL,         -- before decay/style
    final_score             REAL,         -- after all multipliers
    roi_tier_multiplier     REAL,         -- 1.0 / 0.75 / 0.5
    passes_anti_luck        INTEGER       -- 0 or 1
);

CREATE TABLE allocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at     TEXT NOT NULL,
    address         TEXT NOT NULL REFERENCES traders(address),
    raw_weight      REAL,                 -- after softmax, before caps
    capped_weight   REAL,                 -- after risk caps
    final_weight    REAL                  -- after renormalization
);

CREATE TABLE blacklist (
    address         TEXT NOT NULL REFERENCES traders(address),
    reason          TEXT NOT NULL,         -- "liquidation" | "manual"
    blacklisted_at  TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    PRIMARY KEY (address, blacklisted_at)
);

CREATE TABLE position_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    address         TEXT NOT NULL REFERENCES traders(address),
    captured_at     TEXT NOT NULL,
    token_symbol    TEXT NOT NULL,
    side            TEXT,                 -- derived from sign of size
    position_value_usd REAL,
    entry_price     REAL,
    leverage_value  REAL,
    leverage_type   TEXT,
    liquidation_price REAL,
    unrealized_pnl  REAL,
    account_value   REAL
);
```

- [x] Implement CRUD helpers: `upsert_trader()`, `insert_leaderboard_snapshot()`, `insert_trade_metrics()`, `insert_score()`, `insert_allocation()`, `add_to_blacklist()`, `is_blacklisted()`, `get_latest_metrics(address, window)`, `get_latest_score(address)`, `get_latest_allocations()`.
- [x] Implement `get_position_history(address, token, lookback_hours)` for liquidation detection.
- [x] Add data retention policy: keep last 90 days of snapshots, archive older.

---

## Phase 3: Metrics Engine — Derived Trade Metrics

**Depends on:** Phase 1, Phase 2

- [x] Create `src/metrics.py`.
- [x] Implement `compute_trade_metrics(trades: list[Trade], account_value: float, window_days: int) -> TradeMetrics`:

```python
def compute_trade_metrics(trades, account_value, window_days):
    """Compute derived metrics from a list of trades within a rolling window."""
    close_trades = [t for t in trades if t.action in ("Close", "Reduce") and t.closed_pnl != 0]

    total_trades = len(close_trades)
    if total_trades == 0:
        return TradeMetrics.empty(window_days)

    winning = [t for t in close_trades if t.closed_pnl > 0]
    losing  = [t for t in close_trades if t.closed_pnl < 0]

    win_rate = len(winning) / total_trades

    gross_profit = sum(t.closed_pnl for t in winning)
    gross_loss   = abs(sum(t.closed_pnl for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Per-trade returns as fraction of trade value
    returns = []
    for t in close_trades:
        if t.value_usd > 0:
            returns.append(t.closed_pnl / t.value_usd)

    avg_return = np.mean(returns) if returns else 0.0
    std_return = np.std(returns, ddof=1) if len(returns) > 1 else 0.0
    pseudo_sharpe = avg_return / std_return if std_return > 0 else 0.0

    total_pnl = sum(t.closed_pnl for t in close_trades)

    # ROI proxy: total realized PnL / account value at start of window
    roi_proxy = (total_pnl / account_value * 100) if account_value > 0 else 0.0

    # Drawdown proxy: worst single-trade loss as % of account
    worst_loss = min((t.closed_pnl for t in close_trades), default=0)
    max_drawdown_proxy = abs(worst_loss) / account_value if account_value > 0 else 0.0

    return TradeMetrics(
        window_days=window_days,
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_return=avg_return,
        std_return=std_return,
        pseudo_sharpe=pseudo_sharpe,
        total_pnl=total_pnl,
        roi_proxy=roi_proxy,
        max_drawdown_proxy=max_drawdown_proxy,
    )
```

- [x] Implement ROI proxy fallback: when the leaderboard doesn't provide per-timeframe realized ROI, use `roi_proxy = sum(closed_pnl over window) / account_value_at_window_start * 100`. Account value at window start is approximated from the earliest leaderboard snapshot within the window, or from the current `account_value - total_pnl` as a fallback.

- [x] Implement batch computation: `recompute_all_metrics(trader_addresses, windows=[7, 30, 90])` that fetches trades for each window, calls `compute_trade_metrics`, and stores results.

---

## Phase 4: Composite Scoring Engine

**Depends on:** Phase 2, Phase 3

- [x] Create `src/scoring.py`.
- [x] Implement all component scores:

### 4.1 Normalized ROI

```python
def normalized_roi(roi: float) -> float:
    """Scale ROI to [0, 1]. Cap at 100%."""
    return min(1.0, max(0.0, roi / 100.0))
```

### 4.2 Normalized Sharpe

```python
def normalized_sharpe(pseudo_sharpe: float) -> float:
    """Scale pseudo-Sharpe to [0, 1]. Sharpe of 3.0+ maps to 1.0."""
    return min(1.0, max(0.0, pseudo_sharpe / 3.0))
```

### 4.3 Normalized Win Rate

```python
def normalized_win_rate(win_rate: float) -> float:
    """Scale win rate to [0, 1]. Already in [0, 1] but apply floor at 0.35."""
    if win_rate < 0.35 or win_rate > 0.85:
        return 0.0  # Fails anti-luck bounds; will be caught by filter too
    return (win_rate - 0.35) / (0.85 - 0.35)  # Rescale [0.35, 0.85] -> [0, 1]
```

### 4.4 Consistency Score

```python
def consistency_score(roi_7d: float, roi_30d: float, roi_90d: float) -> float:
    """
    Multi-timeframe consistency.
    roi_* values are percentage returns for each window.
    """
    if roi_7d > 0 and roi_30d > 0 and roi_90d > 0:
        base = 0.7
        # Normalize to weekly rate for variance comparison
        variance = np.var([roi_7d, roi_30d / 4, roi_90d / 12])
        consistency_bonus = max(0.0, 0.3 - (variance / 100.0))
        return base + consistency_bonus
    elif sum([roi_7d > 0, roi_30d > 0, roi_90d > 0]) >= 2:
        return 0.5
    else:
        return 0.2
```

### 4.5 Smart Money Bonus

```python
def smart_money_bonus(label: str) -> float:
    if not label:
        return 0.0
    label_lower = label.lower()
    if "fund" in label_lower:
        return 1.0
    elif "smart" in label_lower:
        return 0.8
    elif label:  # Any known label
        return 0.5
    return 0.0
```

### 4.6 Risk Management Score

```python
def risk_management_score(avg_leverage: float, max_leverage: float,
                          uses_isolated: bool, max_drawdown_proxy: float) -> float:
    """
    Score trader's risk discipline.
    Lower leverage + isolated margin + smaller drawdowns = higher score.
    """
    # Leverage discipline: lower is better
    leverage_score = max(0.0, 1.0 - (avg_leverage / 20.0))  # 20x+ -> 0

    # Margin type: isolated preferred
    margin_score = 1.0 if uses_isolated else 0.5

    # Drawdown: smaller is better
    drawdown_score = max(0.0, 1.0 - (max_drawdown_proxy / 0.20))  # 20%+ -> 0

    return (leverage_score * 0.4 + margin_score * 0.2 + drawdown_score * 0.4)
```

### 4.7 Style Multiplier

```python
STYLE_MULTIPLIERS = {
    "SWING": 1.0,     # Ideal for copytrading
    "POSITION": 0.85,  # Good but low frequency
    "HFT": 0.4,        # Too hard to copy
}

def classify_trader_style(trades_per_day: float, avg_hold_hours: float) -> str:
    if trades_per_day > 5 and avg_hold_hours < 4:
        return "HFT"
    elif trades_per_day >= 0.3 and avg_hold_hours < 336:
        return "SWING"
    else:
        return "POSITION"
```

### 4.8 Recency Decay

```python
def recency_decay(hours_since_last_trade: float, half_life_hours: float = 168.0) -> float:
    """
    Exponential decay. half_life_hours=168 means 7-day half-life.
    A trader who hasn't traded in 14 days gets 0.25x weight.
    """
    return math.exp(-0.693 * hours_since_last_trade / half_life_hours)
```

### 4.9 Composite Score Assembly

```python
WEIGHTS = {
    "roi": 0.25,
    "sharpe": 0.20,
    "win_rate": 0.15,
    "consistency": 0.20,
    "smart_money": 0.10,
    "risk_mgmt": 0.10,
}

def compute_trader_score(metrics_7d, metrics_30d, metrics_90d,
                         leaderboard_entry, label, positions,
                         hours_since_last_trade) -> TraderScore:
    """Full composite score computation."""

    # Use 30d metrics as the primary scoring window
    m = metrics_30d

    n_roi       = normalized_roi(m.roi_proxy)
    n_sharpe    = normalized_sharpe(m.pseudo_sharpe)
    n_win_rate  = normalized_win_rate(m.win_rate)
    c_score     = consistency_score(metrics_7d.roi_proxy, metrics_30d.roi_proxy, metrics_90d.roi_proxy)
    sm_bonus    = smart_money_bonus(label)
    rm_score    = risk_management_score(
        avg_leverage=avg_leverage_from_positions(positions),
        max_leverage=max_leverage_from_positions(positions),
        uses_isolated=any_isolated_margin(positions),
        max_drawdown_proxy=m.max_drawdown_proxy,
    )

    raw_composite = (
        WEIGHTS["roi"]        * n_roi +
        WEIGHTS["sharpe"]     * n_sharpe +
        WEIGHTS["win_rate"]   * n_win_rate +
        WEIGHTS["consistency"] * c_score +
        WEIGHTS["smart_money"] * sm_bonus +
        WEIGHTS["risk_mgmt"]  * rm_score
    )

    style = classify_trader_style(
        trades_per_day=m.total_trades / max(m.window_days, 1),
        avg_hold_hours=estimate_avg_hold_hours(metrics_30d),
    )
    style_mult = STYLE_MULTIPLIERS[style]

    decay = recency_decay(hours_since_last_trade)

    final_score = raw_composite * style_mult * decay

    # 7d ROI tier multiplier (applied at allocation stage, stored here)
    roi_7d = metrics_7d.roi_proxy
    if roi_7d > 10:
        roi_tier = 1.0
    elif roi_7d >= 0:
        roi_tier = 0.75
    else:
        roi_tier = 0.5  # Could also return 0.0 to skip entirely

    return TraderScore(
        normalized_roi=n_roi,
        normalized_sharpe=n_sharpe,
        normalized_win_rate=n_win_rate,
        consistency_score=c_score,
        smart_money_bonus=sm_bonus,
        risk_management_score=rm_score,
        style_multiplier=style_mult,
        recency_decay=decay,
        raw_composite_score=raw_composite,
        final_score=final_score,
        roi_tier_multiplier=roi_tier,
        passes_anti_luck=True,  # Set by filter gate
    )
```

---

## Phase 5: Anti-Luck Filters & Blacklist Gates

**Depends on:** Phase 3, Phase 4

- [x] Create `src/filters.py`.
- [x] Implement `apply_anti_luck_filter(metrics_7d, metrics_30d, metrics_90d) -> (bool, str)`:

```python
def apply_anti_luck_filter(m7, m30, m90) -> tuple[bool, str]:
    """Returns (passes, reason_if_failed)."""

    # Multi-timeframe profitability gates
    if not (m7.total_pnl > 0 and m7.roi_proxy > 5):
        return False, f"7d gate: pnl={m7.total_pnl:.0f}, roi={m7.roi_proxy:.1f}%"
    if not (m30.total_pnl > 10_000 and m30.roi_proxy > 15):
        return False, f"30d gate: pnl={m30.total_pnl:.0f}, roi={m30.roi_proxy:.1f}%"
    if not (m90.total_pnl > 50_000 and m90.roi_proxy > 30):
        return False, f"90d gate: pnl={m90.total_pnl:.0f}, roi={m90.roi_proxy:.1f}%"

    # Win rate bounds
    if m30.win_rate > 0.85:
        return False, f"Win rate too high: {m30.win_rate:.2f} (possible manipulation)"
    if m30.win_rate < 0.35:
        # Allow trend trader exception: low win rate but high profit factor
        if m30.profit_factor < 2.5:
            return False, f"Win rate {m30.win_rate:.2f} with PF {m30.profit_factor:.1f} (not trend trader)"
        # Trend trader passes

    # Profit factor gate
    if m30.profit_factor < 1.5:
        # Trend trader variant: win<40% but PF>2.5 is OK (already handled above)
        if not (m30.win_rate < 0.40 and m30.profit_factor > 2.5):
            return False, f"Profit factor {m30.profit_factor:.2f} < 1.5"

    # Minimum trade count for statistical significance
    if m30.total_trades < 20:
        return False, f"Insufficient trades: {m30.total_trades} < 20"

    return True, "passed"
```

- [x] Implement blacklist check:

```python
LIQUIDATION_COOLDOWN_DAYS = 14

def is_trader_eligible(address: str, datastore) -> tuple[bool, str]:
    """Check blacklist status."""
    if datastore.is_blacklisted(address):
        entry = datastore.get_blacklist_entry(address)
        return False, f"Blacklisted until {entry.expires_at} ({entry.reason})"
    return True, "eligible"

def blacklist_trader(address: str, reason: str, datastore):
    expires = datetime.utcnow() + timedelta(days=LIQUIDATION_COOLDOWN_DAYS)
    datastore.add_to_blacklist(address, reason, expires)
```

- [x] Implement combined eligibility gate:

```python
def is_fully_eligible(address, m7, m30, m90, datastore) -> tuple[bool, str]:
    ok, reason = is_trader_eligible(address, datastore)
    if not ok:
        return False, reason

    ok, reason = apply_anti_luck_filter(m7, m30, m90)
    if not ok:
        return False, reason

    return True, "eligible"
```

---

## Phase 6: Allocation Engine

**Depends on:** Phase 4, Phase 5

- [x] Create `src/allocation.py`.

### 6.1 Score-to-Weight Conversion: Softmax

**Justification:** Linear normalization (score_i / sum(scores)) makes allocation proportional to raw scores, but a single high-scoring trader would dominate. Softmax with temperature parameter provides:
- Smoother distribution (no single trader gets 90% weight)
- Temperature controls concentration: high T -> uniform, low T -> winner-takes-all
- Well-defined behavior for edge cases (all-same scores -> equal allocation)

```python
def scores_to_weights_softmax(scores: dict[str, float], temperature: float = 2.0) -> dict[str, float]:
    """
    Convert {trader_address: final_score} into allocation weights via softmax.

    Temperature T:
      T=1.0: standard softmax (moderate concentration)
      T=2.0: smoother (recommended default — prevents over-concentration)
      T=0.5: aggressive (high score dominance)
    """
    if not scores:
        return {}

    addresses = list(scores.keys())
    vals = np.array([scores[a] for a in addresses])

    # Softmax with temperature
    scaled = vals / temperature
    scaled -= scaled.max()  # Numerical stability
    exp_vals = np.exp(scaled)
    weights = exp_vals / exp_vals.sum()

    return {addr: float(w) for addr, w in zip(addresses, weights)}
```

### 6.2 Apply ROI Tier Multiplier

```python
def apply_roi_tier(weights: dict[str, float],
                   tier_multipliers: dict[str, float]) -> dict[str, float]:
    """
    Multiply each weight by the trader's 7d ROI tier (1.0 / 0.75 / 0.5).
    Then renormalize so weights sum to 1.
    """
    adjusted = {addr: w * tier_multipliers.get(addr, 0.5) for addr, w in weights.items()}

    # Remove traders with multiplier 0 (skip tier)
    adjusted = {a: w for a, w in adjusted.items() if w > 0}

    total = sum(adjusted.values())
    if total == 0:
        return {}
    return {a: w / total for a, w in adjusted.items()}
```

### 6.3 Apply Risk Caps

```python
@dataclass
class RiskConfig:
    max_total_open_usd: float       # account_value * 0.50
    max_total_positions: int = 5
    max_exposure_per_token: float = 0.15  # 15% of account per token
    max_long_exposure: float = 0.60
    max_short_exposure: float = 0.60

def apply_risk_caps(weights: dict[str, float],
                    trader_positions: dict[str, list],  # current positions per trader
                    config: RiskConfig) -> dict[str, float]:
    """
    Enforce hard caps:
    1. Max N positions total
    2. Per-token cap
    3. Directional cap
    Truncates and renormalizes.
    """
    # 1. Keep top N by weight
    sorted_traders = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_traders) > config.max_total_positions:
        sorted_traders = sorted_traders[:config.max_total_positions]

    capped = dict(sorted_traders)

    # 2. Cap individual weights (no single trader > 40%)
    MAX_SINGLE_WEIGHT = 0.40
    for addr in capped:
        capped[addr] = min(capped[addr], MAX_SINGLE_WEIGHT)

    # Renormalize
    total = sum(capped.values())
    if total > 0:
        capped = {a: w / total for a, w in capped.items()}

    return capped
```

### 6.4 Performance-Chasing Guardrails

```python
MAX_WEIGHT_CHANGE_PER_DAY = 0.15  # Max 15 percentage points change per trader per day
REBALANCE_COOLDOWN_HOURS = 24      # Minimum time between allocation changes

def apply_turnover_limits(new_weights: dict[str, float],
                          old_weights: dict[str, float]) -> dict[str, float]:
    """
    Limit daily allocation changes to prevent performance-chasing whipsaws.
    """
    result = {}
    all_addrs = set(new_weights.keys()) | set(old_weights.keys())

    for addr in all_addrs:
        new_w = new_weights.get(addr, 0.0)
        old_w = old_weights.get(addr, 0.0)

        delta = new_w - old_w
        if abs(delta) > MAX_WEIGHT_CHANGE_PER_DAY:
            clamped_delta = MAX_WEIGHT_CHANGE_PER_DAY if delta > 0 else -MAX_WEIGHT_CHANGE_PER_DAY
            result[addr] = old_w + clamped_delta
        else:
            result[addr] = new_w

    # Remove zero/negative weights, renormalize
    result = {a: w for a, w in result.items() if w > 0.001}
    total = sum(result.values())
    if total > 0:
        result = {a: w / total for a, w in result.items()}

    return result
```

### 6.5 Full Allocation Pipeline

```python
def compute_allocations(eligible_traders: list[str],
                        scores: dict[str, TraderScore],
                        old_allocations: dict[str, float],
                        trader_positions: dict[str, list],
                        risk_config: RiskConfig,
                        softmax_temperature: float = 2.0) -> dict[str, float]:
    """End-to-end allocation computation."""

    # 1. Build score dict for eligible traders only
    score_map = {addr: scores[addr].final_score for addr in eligible_traders
                 if addr in scores and scores[addr].final_score > 0}

    if not score_map:
        return {}

    # 2. Softmax -> raw weights
    weights = scores_to_weights_softmax(score_map, temperature=softmax_temperature)

    # 3. Apply 7d ROI tier multiplier
    tier_map = {addr: scores[addr].roi_tier_multiplier for addr in weights}
    weights = apply_roi_tier(weights, tier_map)

    # 4. Apply risk caps
    weights = apply_risk_caps(weights, trader_positions, risk_config)

    # 5. Apply turnover limits
    weights = apply_turnover_limits(weights, old_allocations)

    return weights
```

---

## Phase 7: Position Monitor & Liquidation Detection

**Depends on:** Phase 1, Phase 2

- [x] Create `src/position_monitor.py`.
- [x] Implement liquidation detection:

```python
async def detect_liquidations(tracked_traders: list[str],
                               datastore, nansen_client) -> list[str]:
    """
    Compare current positions against last snapshot.
    If a position disappeared without a Close/Reduce trade, treat as liquidation.
    Returns list of addresses that were likely liquidated.
    """
    liquidated = []

    for address in tracked_traders:
        # Get previous position snapshot
        prev_positions = datastore.get_latest_position_snapshot(address)
        if not prev_positions:
            continue

        # Fetch current positions
        current = await nansen_client.fetch_address_positions(address)
        current_tokens = {p.token_symbol for p in current.asset_positions}

        # Fetch recent trades to check for Close actions
        recent_trades = await nansen_client.fetch_address_trades(
            address,
            date_from=(datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d"),
            date_to=datetime.utcnow().strftime("%Y-%m-%d"),
        )
        recent_close_tokens = {
            t.token_symbol for t in recent_trades
            if t.action in ("Close", "Reduce")
        }

        for prev_pos in prev_positions:
            if prev_pos.token_symbol not in current_tokens:
                # Position disappeared
                if prev_pos.token_symbol not in recent_close_tokens:
                    # No Close trade found -> probable liquidation
                    liquidated.append(address)
                    blacklist_trader(address, "liquidation", datastore)
                    break

    return liquidated
```

- [x] Schedule position monitoring every 15 minutes.
- [x] On liquidation detection, emit event for downstream strategy to close copied positions.

---

## Phase 8: Scheduler & Orchestration

**Depends on:** Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Phase 6, Phase 7

- [x] Create `src/scheduler.py` using `APScheduler` or simple `asyncio` loop.
- [x] Define update schedule:

| Task | Frequency | What it does |
|------|-----------|--------------|
| `refresh_leaderboard` | Daily at 00:00 UTC | Fetch leaderboard for 7d, 30d, 90d windows. Store snapshots. Discover new traders. |
| `recompute_trade_metrics` | Every 6 hours | For each tracked trader, fetch trades for 7d/30d/90d windows. Compute metrics. Store. |
| `recompute_scores` | Every 6 hours (after metrics) | Run composite scoring for all traders. Store scores. |
| `recompute_allocations` | Every 6 hours (after scores) | Run full allocation pipeline. Store allocations. |
| `monitor_positions` | Every 15 minutes | Fetch positions for all tracked traders. Detect liquidations. Store snapshots. |
| `cleanup_blacklist` | Daily | Remove expired blacklist entries. |

- [x] Implement the orchestration function:

```python
async def full_recompute_cycle(nansen_client, datastore, risk_config):
    """Run the complete scoring and allocation pipeline."""

    # 1. Get all tracked traders
    traders = datastore.get_active_traders()

    # 2. Recompute trade metrics for each window
    for addr in traders:
        for window in [7, 30, 90]:
            date_to = datetime.utcnow().strftime("%Y-%m-%d")
            date_from = (datetime.utcnow() - timedelta(days=window)).strftime("%Y-%m-%d")

            trades = await nansen_client.fetch_address_trades(addr, date_from, date_to)
            positions = await nansen_client.fetch_address_positions(addr)
            account_value = float(positions.margin_summary_account_value_usd or 0)

            metrics = compute_trade_metrics(trades, account_value, window)
            datastore.insert_trade_metrics(addr, metrics)

    # 3. Compute scores
    scores = {}
    for addr in traders:
        m7  = datastore.get_latest_metrics(addr, 7)
        m30 = datastore.get_latest_metrics(addr, 30)
        m90 = datastore.get_latest_metrics(addr, 90)

        if not all([m7, m30, m90]):
            continue

        # Check eligibility
        eligible, reason = is_fully_eligible(addr, m7, m30, m90, datastore)

        label = datastore.get_trader_label(addr)
        positions = datastore.get_latest_position_snapshot(addr)
        last_trade_time = datastore.get_last_trade_time(addr)
        hours_since = (datetime.utcnow() - last_trade_time).total_seconds() / 3600

        score = compute_trader_score(m7, m30, m90, None, label, positions, hours_since)
        score.passes_anti_luck = eligible

        datastore.insert_score(addr, score)

        if eligible:
            scores[addr] = score

    # 4. Compute allocations
    old_allocations = datastore.get_latest_allocations()
    eligible_addrs = list(scores.keys())
    trader_positions = {a: datastore.get_latest_position_snapshot(a) for a in eligible_addrs}

    new_allocations = compute_allocations(
        eligible_addrs, scores, old_allocations, trader_positions, risk_config
    )

    datastore.insert_allocations(new_allocations)
    return new_allocations
```

---

## Phase 9: Strategy Interfaces

**Depends on:** Phase 6

- [x] Create `src/strategy_interface.py`.

### 9.1 Core Interface

```python
def get_trader_allocation(trader_id: str, datastore) -> float:
    """
    Returns the current allocation weight [0, 1] for a trader.
    Returns 0 if trader is not in the current allocation set.
    """
    allocations = datastore.get_latest_allocations()
    return allocations.get(trader_id, 0.0)

def get_all_allocations(datastore) -> dict[str, float]:
    """Returns {trader_address: weight} for all allocated traders."""
    return datastore.get_latest_allocations()
```

### 9.2 Strategy #2 — Index Portfolio Rebalancing

```python
def build_index_portfolio(allocations: dict[str, float],
                          trader_positions: dict[str, list],
                          my_account_value: float) -> dict[str, float]:
    """
    Build a target portfolio by weighting each trader's positions by their allocation weight.

    Returns {token_symbol: target_position_usd} — positive = long, negative = short.
    """
    portfolio = defaultdict(float)

    for trader_addr, weight in allocations.items():
        positions = trader_positions.get(trader_addr, [])
        for pos in positions:
            # Weighted contribution
            direction = 1.0 if float(pos.size) > 0 else -1.0
            target_usd = float(pos.position_value_usd) * weight * direction
            portfolio[pos.token_symbol] += target_usd

    # Scale to our account size (proportional)
    total_exposure = sum(abs(v) for v in portfolio.values())
    if total_exposure > 0:
        scale = (my_account_value * 0.50) / total_exposure  # 50% max deployment
        portfolio = {k: v * scale for k, v in portfolio.items()}

    return dict(portfolio)
```

### 9.3 Strategy #3 — Consensus Voting

```python
def weighted_consensus(token: str,
                       allocations: dict[str, float],
                       trader_positions: dict[str, list]) -> dict:
    """
    Compute weighted consensus for a token.
    Each trader's vote is weighted by their allocation weight * position size.

    Returns {
        "signal": "STRONG_LONG" | "STRONG_SHORT" | "MIXED",
        "long_weight": float,
        "short_weight": float,
        "participating_traders": int,
    }
    """
    long_weight = 0.0
    short_weight = 0.0
    participants = 0

    for trader_addr, alloc_weight in allocations.items():
        positions = trader_positions.get(trader_addr, [])
        for pos in positions:
            if pos.token_symbol == token:
                participants += 1
                value = abs(float(pos.position_value_usd))
                weighted_value = value * alloc_weight

                if float(pos.size) > 0:
                    long_weight += weighted_value
                else:
                    short_weight += weighted_value

    total = long_weight + short_weight
    if total == 0:
        return {"signal": "MIXED", "long_weight": 0, "short_weight": 0, "participating_traders": 0}

    if long_weight > 2 * short_weight and participants >= 3:
        signal = "STRONG_LONG"
    elif short_weight > 2 * long_weight and participants >= 3:
        signal = "STRONG_SHORT"
    else:
        signal = "MIXED"

    return {
        "signal": signal,
        "long_weight": long_weight,
        "short_weight": short_weight,
        "participating_traders": participants,
    }
```

### 9.4 Strategy #5 — Per-Trade Sizing

```python
def size_copied_trade(trader_addr: str,
                      trade_value_usd: float,
                      trader_account_value: float,
                      my_account_value: float,
                      allocations: dict[str, float]) -> float:
    """
    Size a copied trade based on:
    1. Trader's allocation weight
    2. Proportional sizing (their % of account -> our % of account)

    Returns target_position_usd for our account.
    """
    weight = allocations.get(trader_addr, 0.0)
    if weight == 0:
        return 0.0

    # What fraction of their account is this trade?
    if trader_account_value > 0:
        trader_alloc_pct = trade_value_usd / trader_account_value
    else:
        trader_alloc_pct = 0.0

    # Our position = our_account * trader_alloc_pct * weight * copy_ratio
    COPY_RATIO = 0.5
    target = my_account_value * trader_alloc_pct * weight * COPY_RATIO

    # Hard cap: no single position > 10% of account
    MAX_SINGLE_POSITION = my_account_value * 0.10
    target = min(target, MAX_SINGLE_POSITION)

    return target
```

---

## Phase 10: Backtesting Framework

**Depends on:** Phase 3, Phase 4, Phase 5, Phase 6

- [x] Create `src/backtest.py`.
- [x] Implement historical allocation simulation:

```python
def backtest_allocations(historical_trades: dict[str, list],
                         historical_leaderboard: list,
                         start_date: str,
                         end_date: str,
                         rebalance_frequency_days: int = 1) -> BacktestResult:
    """
    Simulate allocation changes over time and evaluate:
    - Portfolio return
    - Turnover (sum of absolute weight changes per rebalance)
    - Stability (std dev of weights over time)
    - Max drawdown
    """
    results = []
    current_allocations = {}
    portfolio_value = 100_000  # Starting value

    for date in date_range(start_date, end_date, rebalance_frequency_days):
        # Compute metrics as of this date
        # ... (replay scoring pipeline with data up to `date`)

        new_allocations = compute_allocations(...)

        # Turnover
        turnover = sum(
            abs(new_allocations.get(a, 0) - current_allocations.get(a, 0))
            for a in set(new_allocations) | set(current_allocations)
        ) / 2  # Divide by 2 since it's double-counted

        # Simulate PnL for this period
        period_pnl = 0
        for addr, weight in new_allocations.items():
            trader_pnl = sum(
                t.closed_pnl for t in historical_trades.get(addr, [])
                if t.timestamp in current_period
            )
            period_pnl += trader_pnl * weight

        portfolio_value += period_pnl
        results.append({
            "date": date,
            "portfolio_value": portfolio_value,
            "turnover": turnover,
            "num_traders": len(new_allocations),
            "allocations": dict(new_allocations),
        })

        current_allocations = new_allocations

    return BacktestResult(
        timeline=results,
        total_return=(portfolio_value - 100_000) / 100_000,
        max_drawdown=compute_max_drawdown(results),
        avg_turnover=np.mean([r["turnover"] for r in results]),
        sharpe=compute_portfolio_sharpe(results),
    )
```

- [x] Implement evaluation metrics:
  - **Turnover**: Sum of absolute weight changes per rebalance. Target: < 30% per rebalance.
  - **Stability**: Standard deviation of each trader's weight over time. Lower is better.
  - **Drawdown**: Maximum peak-to-trough decline in simulated portfolio.
  - **Performance-chasing detection**: If allocation changes are correlated with *past* returns but not *future* returns, the system is chasing. Metric: correlation of `delta_weight(t)` with `return(t+1)`.

---

## Phase 11: Tests

**Depends on:** Phase 3, Phase 4, Phase 5, Phase 6, Phase 7

- [x] Create `tests/` directory with `conftest.py` for fixtures.

### 11.1 Metric Calculation Tests (`tests/test_metrics.py`)

```python
def test_win_rate_basic():
    trades = [make_trade(closed_pnl=100), make_trade(closed_pnl=-50), make_trade(closed_pnl=200)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.win_rate == pytest.approx(2/3)

def test_profit_factor():
    trades = [make_trade(closed_pnl=300), make_trade(closed_pnl=-100)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    assert m.profit_factor == pytest.approx(3.0)

def test_pseudo_sharpe():
    # Known returns: [0.1, -0.05, 0.08]
    trades = [make_trade(closed_pnl=100, value_usd=1000),   # 10%
              make_trade(closed_pnl=-50, value_usd=1000),   # -5%
              make_trade(closed_pnl=80, value_usd=1000)]    # 8%
    m = compute_trade_metrics(trades, account_value=10000, window_days=7)
    expected_mean = (0.1 - 0.05 + 0.08) / 3
    expected_std = np.std([0.1, -0.05, 0.08], ddof=1)
    assert m.pseudo_sharpe == pytest.approx(expected_mean / expected_std, rel=1e-4)

def test_empty_trades():
    m = compute_trade_metrics([], account_value=10000, window_days=7)
    assert m.total_trades == 0
    assert m.win_rate == 0.0
    assert m.profit_factor == 0.0

def test_roi_proxy():
    trades = [make_trade(closed_pnl=500), make_trade(closed_pnl=-200)]
    m = compute_trade_metrics(trades, account_value=10000, window_days=30)
    assert m.roi_proxy == pytest.approx(3.0)  # 300/10000*100
```

### 11.2 Anti-Luck Filter Tests (`tests/test_filters.py`)

```python
def test_passes_all_gates():
    m7  = make_metrics(total_pnl=500, roi_proxy=8, win_rate=0.55, profit_factor=2.0, total_trades=30)
    m30 = make_metrics(total_pnl=15000, roi_proxy=20, win_rate=0.55, profit_factor=2.0, total_trades=50)
    m90 = make_metrics(total_pnl=60000, roi_proxy=35, win_rate=0.55, profit_factor=2.0, total_trades=100)
    ok, _ = apply_anti_luck_filter(m7, m30, m90)
    assert ok is True

def test_fails_7d_gate():
    m7 = make_metrics(total_pnl=-100, roi_proxy=-2)
    ok, reason = apply_anti_luck_filter(m7, good_m30, good_m90)
    assert ok is False
    assert "7d gate" in reason

def test_high_win_rate_rejected():
    m30 = make_metrics(win_rate=0.90, profit_factor=1.1, total_trades=50)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "too high" in reason

def test_trend_trader_exception():
    """Win rate < 35% but profit factor > 2.5 should pass."""
    m30 = make_metrics(win_rate=0.32, profit_factor=3.0, total_trades=50,
                       total_pnl=15000, roi_proxy=20)
    ok, _ = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is True

def test_insufficient_trades_rejected():
    m30 = make_metrics(total_trades=10)
    ok, reason = apply_anti_luck_filter(good_m7, m30, good_m90)
    assert ok is False
    assert "Insufficient" in reason
```

### 11.3 Blacklist & Cooldown Tests (`tests/test_blacklist.py`)

```python
def test_blacklist_blocks_trader():
    ds = InMemoryDatastore()
    blacklist_trader("0xABC", "liquidation", ds)
    ok, reason = is_trader_eligible("0xABC", ds)
    assert ok is False
    assert "liquidation" in reason

def test_blacklist_expires():
    ds = InMemoryDatastore()
    # Manually set expiry in the past
    ds.add_to_blacklist("0xABC", "liquidation",
                        expires_at=datetime.utcnow() - timedelta(hours=1))
    ok, _ = is_trader_eligible("0xABC", ds)
    assert ok is True

def test_cooldown_14_days():
    ds = InMemoryDatastore()
    blacklist_trader("0xABC", "liquidation", ds)
    entry = ds.get_blacklist_entry("0xABC")
    expected = datetime.utcnow() + timedelta(days=14)
    assert abs((entry.expires_at - expected).total_seconds()) < 60
```

### 11.4 Allocation Tests (`tests/test_allocation.py`)

```python
def test_allocations_sum_to_one():
    scores = {"A": 0.8, "B": 0.6, "C": 0.4}
    weights = scores_to_weights_softmax(scores)
    assert sum(weights.values()) == pytest.approx(1.0)

def test_max_positions_cap():
    scores = {f"trader_{i}": 0.5 + i*0.01 for i in range(10)}
    weights = scores_to_weights_softmax(scores)
    config = RiskConfig(max_total_open_usd=50000, max_total_positions=5)
    capped = apply_risk_caps(weights, {}, config)
    assert len(capped) <= 5

def test_roi_tier_applied():
    weights = {"A": 0.5, "B": 0.5}
    tiers = {"A": 1.0, "B": 0.5}  # B is underperforming
    result = apply_roi_tier(weights, tiers)
    assert result["A"] > result["B"]

def test_turnover_limit():
    old = {"A": 0.5, "B": 0.5}
    new = {"A": 0.9, "B": 0.1}  # Dramatic shift
    limited = apply_turnover_limits(new, old)
    assert abs(limited["A"] - old["A"]) <= MAX_WEIGHT_CHANGE_PER_DAY + 0.01
    assert abs(limited["B"] - old["B"]) <= MAX_WEIGHT_CHANGE_PER_DAY + 0.01

def test_single_trader_weight_cap():
    scores = {"A": 10.0, "B": 0.1}  # A is way better
    weights = scores_to_weights_softmax(scores, temperature=1.0)
    config = RiskConfig(max_total_open_usd=50000)
    capped = apply_risk_caps(weights, {}, config)
    assert capped["A"] <= 0.40  # Hard cap
```

### 11.5 Scoring Tests (`tests/test_scoring.py`)

```python
def test_consistency_all_positive():
    score = consistency_score(roi_7d=10, roi_30d=20, roi_90d=50)
    assert score >= 0.7

def test_consistency_two_positive():
    score = consistency_score(roi_7d=-5, roi_30d=20, roi_90d=50)
    assert score == 0.5

def test_consistency_all_negative():
    score = consistency_score(roi_7d=-5, roi_30d=-10, roi_90d=-20)
    assert score == 0.2

def test_normalized_roi_capped():
    assert normalized_roi(150) == 1.0
    assert normalized_roi(50) == 0.5
    assert normalized_roi(-10) == 0.0

def test_smart_money_fund():
    assert smart_money_bonus("Paradigm Fund [0x1234]") == 1.0

def test_smart_money_labeled():
    assert smart_money_bonus("Smart Money Whale") == 0.8
```

---

## File Structure

```
src/
  __init__.py
  nansen_client.py        # Phase 1: API wrapper
  models.py               # Phase 1: Pydantic models
  datastore.py            # Phase 2: SQLite store
  metrics.py              # Phase 3: Derived trade metrics
  scoring.py              # Phase 4: Composite scoring
  filters.py              # Phase 5: Anti-luck + blacklist
  allocation.py           # Phase 6: Score -> weights
  position_monitor.py     # Phase 7: Liquidation detection
  scheduler.py            # Phase 8: Orchestration
  strategy_interface.py   # Phase 9: Downstream strategy API
  backtest.py             # Phase 10: Backtesting
  config.py               # Centralized constants

tests/
  conftest.py             # Shared fixtures
  test_metrics.py
  test_scoring.py
  test_filters.py
  test_blacklist.py
  test_allocation.py
  test_strategy_interface.py
  test_backtest.py

specs/
  pnl-weighted-dynamic-allocation.md  # This file
```

---

## Configuration Constants (`src/config.py`)

```python
# Scoring weights
SCORE_WEIGHTS = {
    "roi": 0.25,
    "sharpe": 0.20,
    "win_rate": 0.15,
    "consistency": 0.20,
    "smart_money": 0.10,
    "risk_mgmt": 0.10,
}

# Style multipliers
STYLE_MULTIPLIERS = {"SWING": 1.0, "POSITION": 0.85, "HFT": 0.4}

# Recency decay half-life
RECENCY_HALF_LIFE_HOURS = 168  # 7 days

# Softmax temperature
SOFTMAX_TEMPERATURE = 2.0

# 7d ROI tier thresholds
ROI_TIER_HIGH = 10      # >10% -> 1.0x
ROI_TIER_MEDIUM = 0     # 0-10% -> 0.75x
                         # <0% -> 0.5x (or skip)

# Anti-luck gates
ANTI_LUCK_7D  = {"min_pnl": 0, "min_roi": 5}
ANTI_LUCK_30D = {"min_pnl": 10_000, "min_roi": 15}
ANTI_LUCK_90D = {"min_pnl": 50_000, "min_roi": 30}
WIN_RATE_BOUNDS = (0.35, 0.85)
MIN_PROFIT_FACTOR = 1.5
TREND_TRADER_PF = 2.5
MIN_TRADES_30D = 20

# Blacklist
LIQUIDATION_COOLDOWN_DAYS = 14

# Risk caps
MAX_TOTAL_POSITIONS = 5
MAX_TOTAL_OPEN_RATIO = 0.50      # account_value * 0.50
MAX_EXPOSURE_PER_TOKEN = 0.15
MAX_LONG_EXPOSURE = 0.60
MAX_SHORT_EXPOSURE = 0.60
MAX_SINGLE_WEIGHT = 0.40

# Turnover
MAX_WEIGHT_CHANGE_PER_DAY = 0.15
REBALANCE_COOLDOWN_HOURS = 24

# Scheduling
LEADERBOARD_REFRESH_CRON = "0 0 * * *"       # Daily midnight UTC
METRICS_RECOMPUTE_HOURS = 6
POSITION_MONITOR_MINUTES = 15
```

---

## Potential Challenges & Mitigations

| Challenge | Mitigation |
|-----------|------------|
| Nansen rate limits (429) | Exponential backoff with jitter; cache leaderboard daily; batch trade fetches |
| Missing 7d/90d ROI from leaderboard | Use `roi_proxy = sum(closed_pnl) / account_value` computed from trades |
| Trader with no 90d history | Relax 90d gate for new traders (< 60 days tracked); use available window with adjusted thresholds |
| All traders fail anti-luck | Return empty allocation (hold cash); log warning; fallback to top-2 by score with reduced sizing |
| Softmax over-concentrates | Temperature=2.0 provides smooth distribution; can increase to 3.0 if needed |
| Performance chasing whipsaws | 15% max daily weight change; 24h cooldown between rebalances |
| Stale data after API outage | Recency decay naturally reduces weight; add explicit "data_freshness" check |

---

## Success Criteria

1. Allocation weights sum to 1.0 (or 0.0 if no eligible traders).
2. No trader exceeds 40% weight.
3. Max 5 traders in allocation set.
4. Blacklisted traders get zero weight for 14 days.
5. Anti-luck filters reject traders who fail any gate.
6. Turnover between consecutive rebalances < 30%.
7. Backtest shows positive risk-adjusted returns vs equal-weight baseline.
8. All downstream strategies (#2, #3, #5) correctly incorporate weights.
9. Liquidation detection triggers within 15 minutes of position disappearance.
10. All tests pass with > 90% line coverage on `metrics.py`, `scoring.py`, `filters.py`, `allocation.py`.
