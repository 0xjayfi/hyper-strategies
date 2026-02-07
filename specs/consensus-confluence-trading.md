# Consensus/Confluence Trading Strategy — Implementation Plan

> **Strategy #3** from brainstorm.md
> Only enter when multiple smart-money traders agree on direction for a Hyperliquid perp token.

---

## 1. Problem Statement & Objectives

### Problem
Copying a single trader exposes you to their individual mistakes, emotional trades, and regime changes. A consensus approach aggregates conviction across 10-20 independently-scored traders, entering only when N agree on direction with sufficient volume, while applying strict risk controls.

### Objectives
- Build a scoring pipeline that selects 10-20 high-quality swing traders from the Nansen leaderboard.
- Continuously poll their trades and positions to compute per-token consensus signals.
- Enter positions only on STRONG consensus (count + volume), gated by confirmation delay and slippage checks.
- Exit on consensus break, independent stop-loss, trailing stop, time stop, or liquidation buffer trigger.
- Run in paper-trading mode first, then compare to a naive single-trader mirror baseline.

### Success Criteria
- Paper-trade Sharpe > 1.0 over 30-day window.
- Fewer than 5% of entries skipped due to slippage gate (indicates timely detection).
- Max drawdown < 15% of account value.
- All risk caps enforced with zero violations in test suite.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SCHEDULER (asyncio)                        │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │Leaderboard│  │ Address  │  │ Address  │  │  Price Feed      │   │
│  │ Poller   │  │ Trades   │  │Positions │  │  (HL WebSocket   │   │
│  │ (daily)  │  │ Poller   │  │ Poller   │  │   or REST poll)  │   │
│  │          │  │ (5 min)  │  │ (15 min) │  │                  │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘   │
│       │              │              │                  │             │
│       ▼              ▼              ▼                  │             │
│  ┌─────────────────────────────────────────┐          │             │
│  │           DATA STORE (in-memory + DB)   │          │             │
│  │  trader_registry, trade_log,            │          │             │
│  │  position_states, consensus_snapshots   │          │             │
│  └─────────────────┬───────────────────────┘          │             │
│                    │                                   │             │
│                    ▼                                   │             │
│  ┌─────────────────────────────────────────┐          │             │
│  │        CONSENSUS ENGINE                 │◄─────────┘             │
│  │  per-token: count + volume + freshness  │                        │
│  │  => STRONG_LONG / STRONG_SHORT / MIXED  │                        │
│  └─────────────────┬───────────────────────┘                        │
│                    │                                                 │
│                    ▼                                                 │
│  ┌─────────────────────────────────────────┐                        │
│  │        SIGNAL GATE                      │                        │
│  │  confirmation delay (15 min)            │                        │
│  │  slippage gate (< 2%)                   │                        │
│  │  risk cap checks                        │                        │
│  └─────────────────┬───────────────────────┘                        │
│                    │                                                 │
│                    ▼                                                 │
│  ┌─────────────────────────────────────────┐                        │
│  │        EXECUTION ENGINE                 │                        │
│  │  entry sizing, order type selection,    │                        │
│  │  stop-loss placement                    │                        │
│  └─────────────────┬───────────────────────┘                        │
│                    │                                                 │
│                    ▼                                                 │
│  ┌─────────────────────────────────────────┐                        │
│  │        POSITION MONITOR                 │                        │
│  │  trailing stop, time stop,              │                        │
│  │  liquidation buffer, consensus break    │                        │
│  └─────────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────┘
```

### Tech Stack
- **Language:** Python 3.11+
- **Async:** `asyncio` + `aiohttp` for non-blocking HTTP
- **Storage:** SQLite for persistence (trades, snapshots), in-memory dicts for hot state
- **Execution:** Hyperliquid Python SDK (`hyperliquid-python-sdk`) for order placement
- **Price Feed:** Hyperliquid WebSocket (`allMids` subscription) for real-time mark prices; fallback to REST `POST /info` with `{"type": "allMids"}`
- **Config:** Pydantic `BaseSettings` for all constants (env-overridable)
- **Testing:** `pytest` + `pytest-asyncio`

---

## 3. Independent Trader Definition (Anti-Copy-Cluster)

### Problem
If 5 of our 20 tracked traders are themselves copying the same whale, their "consensus" is actually one signal counted 5 times.

### Detection Method: Trade Timestamp Correlation

```python
def detect_copy_clusters(traders: list[str], lookback_days: int = 30) -> list[set[str]]:
    """
    For each pair of traders (A, B), compute the fraction of A's trades
    where B traded the same token in the same direction within COPY_WINDOW.
    If correlation > COPY_THRESHOLD for EITHER direction (A→B or B→A),
    they are in the same cluster.
    """
    COPY_WINDOW_MINUTES = 10
    COPY_THRESHOLD = 0.40  # 40% of trades correlated => likely copying

    # Build pairwise correlation matrix
    # For each trader pair:
    #   overlap_count = trades where both traded same token, same side, within window
    #   correlation = overlap_count / min(trade_count_A, trade_count_B)

    # Use Union-Find to group correlated pairs into clusters.
    # From each cluster, keep only the trader with the highest TRADER_SCORE.
```

### Heuristic Fallback (insufficient data)
When a trader has < 20 trades in the lookback window (not enough for correlation):
- Check if the trader's wallet was funded by another tracked wallet (on-chain heuristic — out of scope for v1).
- **v1 fallback:** If two traders have > 60% same-token/same-direction overlap in their current positions, flag as potential cluster and keep only the higher-scored trader.

### Implementation
- Run cluster detection **daily** after leaderboard refresh.
- Store `cluster_id` per trader; consensus engine counts only **one vote per cluster**.

---

## 4. Data Model

### 4.1 Configuration Constants

```python
from pydantic_settings import BaseSettings
from pydantic import Field

class StrategyConfig(BaseSettings):
    # --- Watchlist ---
    WATCHLIST_SIZE: int = 15               # Target number of tracked traders
    MIN_TRADES_FOR_SCORING: int = 50
    SCORING_LOOKBACK_DAYS: int = 90
    LEADERBOARD_REFRESH_INTERVAL: str = "daily"

    # --- Consensus ---
    MIN_CONSENSUS_TRADERS: int = 3         # Minimum traders for STRONG signal
    VOLUME_DOMINANCE_RATIO: float = 2.0    # long_vol > 2x short_vol
    FRESHNESS_HALF_LIFE_HOURS: float = 4.0
    MIN_POSITION_WEIGHT: float = 0.10      # 10% of trader's account

    # --- Size Thresholds (USD) ---
    SIZE_THRESHOLDS: dict = {
        "BTC": 50_000, "ETH": 25_000, "SOL": 10_000,
        "HYPE": 5_000, "_default": 5_000
    }

    # --- Risk Controls ---
    COPY_DELAY_MINUTES: int = 15
    MAX_PRICE_SLIPPAGE_PERCENT: float = 2.0
    MAX_ALLOWED_LEVERAGE: int = 5
    USE_MARGIN_TYPE: str = "isolated"
    STOP_LOSS_PERCENT: float = 5.0
    TRAILING_STOP_PERCENT: float = 8.0
    MAX_POSITION_DURATION_HOURS: int = 72

    # --- Position Caps ---
    MAX_SINGLE_POSITION_RATIO: float = 0.10
    MAX_SINGLE_POSITION_HARD_CAP: float = 50_000
    MAX_TOTAL_EXPOSURE_RATIO: float = 0.50
    MAX_TOTAL_POSITIONS: int = 5
    MAX_EXPOSURE_PER_TOKEN: float = 0.15
    MAX_LONG_EXPOSURE: float = 0.60
    MAX_SHORT_EXPOSURE: float = 0.60

    # --- Liquidation Buffer ---
    LIQUIDATION_EMERGENCY_CLOSE_PCT: float = 10.0
    LIQUIDATION_REDUCE_PCT: float = 20.0

    # --- Execution ---
    COPY_RATIO: float = 0.5  # Copy at 50% of their allocation percentage

    # --- Polling Intervals (seconds) ---
    POLL_TRADES_INTERVAL: int = 300       # 5 minutes
    POLL_POSITIONS_INTERVAL: int = 900    # 15 minutes

    class Config:
        env_prefix = "CONSENSUS_"
```

### 4.2 Core Data Structures

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class TraderStyle(Enum):
    HFT = "HFT"
    SWING = "SWING"
    POSITION = "POSITION"

class ConsensusSide(Enum):
    STRONG_LONG = "STRONG_LONG"
    STRONG_SHORT = "STRONG_SHORT"
    MIXED = "MIXED"

class SignalStrength(Enum):
    HIGH = "HIGH"      # position_weight > 0.25
    MEDIUM = "MEDIUM"  # position_weight > 0.10
    LOW = "LOW"        # position_weight <= 0.10

@dataclass
class TrackedTrader:
    address: str
    label: str
    score: float                      # Composite TRADER_SCORE
    style: TraderStyle
    cluster_id: int                   # Anti-copy-cluster group
    account_value_usd: float
    roi_7d: float
    roi_30d: float
    roi_90d: float
    trade_count: int
    last_scored_at: datetime
    is_active: bool = True
    blacklisted_until: datetime | None = None  # Post-liquidation cooldown

@dataclass
class TradeRecord:
    """Ingested from Address Perp Trades endpoint."""
    trader_address: str
    token_symbol: str
    side: str                          # "Long" or "Short"
    action: str                        # "Open", "Add", "Close", "Reduce"
    size: float
    price_usd: float
    value_usd: float
    timestamp: datetime
    fee_usd: float
    closed_pnl: float
    transaction_hash: str

@dataclass
class InferredPosition:
    """Reconstructed from trade stream or from Address Perp Positions."""
    trader_address: str
    token_symbol: str
    side: str                          # "Long" or "Short"
    entry_price_usd: float
    current_value_usd: float
    size: float
    leverage_value: int
    leverage_type: str
    liquidation_price_usd: float | None
    unrealized_pnl_usd: float
    position_weight: float             # value / account_value
    signal_strength: SignalStrength
    first_open_at: datetime            # Timestamp of initial Open action
    last_action_at: datetime           # Timestamp of most recent action
    freshness_weight: float            # e^(-hours/4)

@dataclass
class TokenConsensus:
    """Per-token consensus snapshot."""
    token_symbol: str
    timestamp: datetime
    long_traders: set[str]             # Trader addresses currently long
    short_traders: set[str]
    long_volume_usd: float             # Sum of position values (long side)
    short_volume_usd: float
    weighted_long_volume: float        # After freshness + score weighting
    weighted_short_volume: float
    consensus: ConsensusSide
    long_cluster_count: int            # Unique clusters, not raw trader count
    short_cluster_count: int

@dataclass
class OurPosition:
    """Position we hold."""
    token_symbol: str
    side: str
    entry_price_usd: float
    current_price_usd: float
    size_usd: float
    leverage: int
    margin_type: str
    stop_loss_price: float
    trailing_stop_price: float | None
    highest_price_since_entry: float   # For trailing stop
    opened_at: datetime
    consensus_side_at_entry: ConsensusSide
    order_id: str | None = None

@dataclass
class PendingSignal:
    """Signal waiting in confirmation window."""
    token_symbol: str
    consensus: ConsensusSide
    detected_at: datetime              # When consensus first reached STRONG
    avg_entry_price_at_detection: float # Weighted avg trader entry price
    confirmed: bool = False
```

### 4.3 Database Schema (SQLite)

```sql
-- Trader registry (refreshed daily)
CREATE TABLE traders (
    address TEXT PRIMARY KEY,
    label TEXT,
    score REAL,
    style TEXT,
    cluster_id INTEGER,
    account_value_usd REAL,
    roi_7d REAL,
    roi_30d REAL,
    roi_90d REAL,
    trade_count INTEGER,
    last_scored_at TEXT,
    is_active INTEGER DEFAULT 1,
    blacklisted_until TEXT
);

-- Raw trades (append-only, deduped by tx_hash)
CREATE TABLE trades (
    transaction_hash TEXT PRIMARY KEY,
    trader_address TEXT,
    token_symbol TEXT,
    side TEXT,
    action TEXT,
    size REAL,
    price_usd REAL,
    value_usd REAL,
    timestamp TEXT,
    fee_usd REAL,
    closed_pnl REAL
);
CREATE INDEX idx_trades_trader_token ON trades(trader_address, token_symbol);
CREATE INDEX idx_trades_timestamp ON trades(timestamp);

-- Consensus snapshots (for backtesting and audit trail)
CREATE TABLE consensus_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol TEXT,
    timestamp TEXT,
    consensus TEXT,
    long_count INTEGER,
    short_count INTEGER,
    long_volume_usd REAL,
    short_volume_usd REAL,
    long_cluster_count INTEGER,
    short_cluster_count INTEGER
);

-- Our positions (active and historical)
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_symbol TEXT,
    side TEXT,
    entry_price_usd REAL,
    exit_price_usd REAL,
    size_usd REAL,
    leverage INTEGER,
    stop_loss_price REAL,
    opened_at TEXT,
    closed_at TEXT,
    close_reason TEXT,  -- "consensus_break", "stop_loss", "trailing_stop", "time_stop", "liquidation_buffer", "manual"
    pnl_usd REAL
);
```

---

## 5. Signal Pipeline

### 5.1 Phase 1 — Watchlist Construction (Daily)

```
Leaderboard API (30d + 90d)
    → filter: account_value > $50K, trade_count >= 50
    → fetch Address Perp Trades for each candidate (90d lookback)
    → classify_trader_style()
    → reject HFT
    → compute TRADER_SCORE
    → detect_copy_clusters()
    → select top WATCHLIST_SIZE by score (one per cluster)
    → store in traders table
```

#### Trader Style Classification

```python
def classify_trader_style(trades: list[TradeRecord], days_active: int) -> TraderStyle:
    trades_per_day = len(trades) / max(days_active, 1)
    avg_hold_time_hours = calculate_avg_hold_time(trades)

    if trades_per_day > 5 and avg_hold_time_hours < 4:
        return TraderStyle.HFT      # Reject
    elif trades_per_day >= 0.3 and avg_hold_time_hours < 336:  # < 2 weeks
        return TraderStyle.SWING    # Ideal
    else:
        return TraderStyle.POSITION # Acceptable but low frequency
```

#### Composite Scoring

```python
import math

def compute_trader_score(trader: dict, trades: list[TradeRecord]) -> float:
    """
    TRADER_SCORE = (
        0.25 * NORMALIZED_ROI +
        0.20 * NORMALIZED_SHARPE +
        0.15 * NORMALIZED_WIN_RATE +
        0.20 * CONSISTENCY_SCORE +
        0.10 * SMART_MONEY_BONUS +
        0.10 * RISK_MANAGEMENT_SCORE
    ) * STYLE_MULTIPLIER * RECENCY_DECAY
    """
    # Normalized ROI (0-1, capped at 100%)
    normalized_roi = min(1.0, max(0, trader["roi_90d"] / 100))

    # Pseudo-Sharpe
    close_trades = [t for t in trades if t.action == "Close" and t.value_usd > 0]
    returns = [t.closed_pnl / t.value_usd for t in close_trades]
    avg_ret = sum(returns) / len(returns) if returns else 0
    std_ret = (sum((r - avg_ret)**2 for r in returns) / max(len(returns)-1, 1)) ** 0.5
    normalized_sharpe = min(1.0, max(0, (avg_ret / std_ret) if std_ret > 0 else 0))

    # Win rate
    winners = sum(1 for r in returns if r > 0)
    win_rate = winners / len(returns) if returns else 0
    normalized_win_rate = win_rate  # Already 0-1

    # Consistency (7d vs 30d vs 90d all positive)
    roi_7d, roi_30d, roi_90d = trader["roi_7d"], trader["roi_30d"], trader["roi_90d"]
    positives = sum(1 for r in [roi_7d, roi_30d, roi_90d] if r > 0)
    if positives == 3:
        consistency = 0.85
    elif positives == 2:
        consistency = 0.50
    else:
        consistency = 0.20

    # Smart money bonus
    label = trader.get("label", "")
    if "Fund" in label:
        sm_bonus = 1.0
    elif "Smart" in label:
        sm_bonus = 0.8
    elif label:
        sm_bonus = 0.5
    else:
        sm_bonus = 0.0

    # Risk management score (lower avg leverage = better)
    avg_leverage = sum(t.value_usd for t in trades) / max(sum(abs(t.size) for t in trades), 1)
    risk_score = min(1.0, max(0, 1.0 - (avg_leverage / 20)))  # Penalize high leverage

    # Style multiplier
    style = classify_trader_style(trades, 90)
    style_mult = {"SWING": 1.0, "POSITION": 0.8, "HFT": 0.0}[style.value]

    # Recency decay: weight recent performance more
    days_since_last_trade = (datetime.utcnow() - max(t.timestamp for t in trades)).days
    recency_decay = math.exp(-days_since_last_trade / 30)  # 30-day half-life

    raw_score = (
        0.25 * normalized_roi +
        0.20 * normalized_sharpe +
        0.15 * normalized_win_rate +
        0.20 * consistency +
        0.10 * sm_bonus +
        0.10 * risk_score
    )

    return raw_score * style_mult * recency_decay
```

### 5.2 Phase 2 — Continuous Trade Ingestion (Every 5 min)

For each active trader in the watchlist:

```python
async def poll_trader_trades(trader: TrackedTrader, since: datetime):
    """
    POST /api/v1/profiler/perp-trades
    {
        "address": trader.address,
        "date": {"from": since.strftime("%Y-%m-%d"), "to": today},
        "pagination": {"page": 1, "per_page": 100},
        "order_by": [{"field": "timestamp", "direction": "DESC"}]
    }
    Deduplicate by transaction_hash. Insert new trades into DB.
    """
```

**Rate limiting strategy:** With 15 traders polled every 5 min = 3 requests/min. Well within Nansen rate limits.

### 5.3 Phase 3 — Position State Reconstruction (Every 15 min)

```python
async def poll_trader_positions(trader: TrackedTrader):
    """
    POST /api/v1/profiler/perp-positions
    {
        "address": trader.address,
        "filters": {"position_value_usd": {"min": 1000}}
    }
    Returns real-time positions with leverage, liquidation price, unrealized PnL.
    Compute position_weight = position_value_usd / account_value.
    """
```

Build `InferredPosition` objects for each trader/token pair. This is the **ground truth** that overrides any drift in trade-stream reconstruction.

### 5.4 Phase 4 — Consensus Computation

```python
import math
from datetime import datetime, timedelta

def compute_token_consensus(
    token: str,
    positions: list[InferredPosition],  # All tracked traders' positions for this token
    traders: dict[str, TrackedTrader],   # address -> trader
    config: StrategyConfig,
    now: datetime
) -> TokenConsensus:
    """Core consensus algorithm with freshness weighting and cluster dedup."""

    size_threshold = config.SIZE_THRESHOLDS.get(token, config.SIZE_THRESHOLDS["_default"])

    long_traders = set()
    short_traders = set()
    long_volume = 0.0
    short_volume = 0.0
    weighted_long_vol = 0.0
    weighted_short_vol = 0.0
    long_clusters = set()
    short_clusters = set()

    for pos in positions:
        # Filter: size threshold
        if pos.current_value_usd < size_threshold:
            continue

        # Filter: position weight must be meaningful (>10%)
        if pos.position_weight < config.MIN_POSITION_WEIGHT:
            continue

        trader = traders[pos.trader_address]

        # Skip blacklisted traders
        if trader.blacklisted_until and now < trader.blacklisted_until:
            continue

        # Freshness decay: e^(-hours / half_life)
        hours_since_action = (now - pos.last_action_at).total_seconds() / 3600
        freshness = math.exp(-hours_since_action / config.FRESHNESS_HALF_LIFE_HOURS)

        # Weighted volume = position_value * freshness * trader_score
        weighted_value = pos.current_value_usd * freshness * trader.score

        if pos.side == "Long":
            long_traders.add(pos.trader_address)
            long_volume += pos.current_value_usd
            weighted_long_vol += weighted_value
            long_clusters.add(trader.cluster_id)
        elif pos.side == "Short":
            short_traders.add(pos.trader_address)
            short_volume += pos.current_value_usd
            weighted_short_vol += weighted_value
            short_clusters.add(trader.cluster_id)

    # Consensus determination (use cluster count, not raw trader count)
    if (len(long_clusters) >= config.MIN_CONSENSUS_TRADERS
            and weighted_long_vol > config.VOLUME_DOMINANCE_RATIO * weighted_short_vol):
        consensus = ConsensusSide.STRONG_LONG
    elif (len(short_clusters) >= config.MIN_CONSENSUS_TRADERS
            and weighted_short_vol > config.VOLUME_DOMINANCE_RATIO * weighted_long_vol):
        consensus = ConsensusSide.STRONG_SHORT
    else:
        consensus = ConsensusSide.MIXED

    return TokenConsensus(
        token_symbol=token,
        timestamp=now,
        long_traders=long_traders,
        short_traders=short_traders,
        long_volume_usd=long_volume,
        short_volume_usd=short_volume,
        weighted_long_volume=weighted_long_vol,
        weighted_short_volume=weighted_short_vol,
        consensus=consensus,
        long_cluster_count=len(long_clusters),
        short_cluster_count=len(short_clusters),
    )
```

### 5.5 Phase 5 — Confirmation Window + Slippage Gate

```python
# pending_signals: dict[str, PendingSignal]  (token -> signal)

async def process_consensus_change(
    token: str,
    new_consensus: TokenConsensus,
    current_price: float,
    config: StrategyConfig,
    now: datetime
):
    """
    When consensus transitions from MIXED to STRONG_*:
      1. Create PendingSignal with detected_at = now
      2. Record avg trader entry price at detection time

    After COPY_DELAY_MINUTES have elapsed:
      3. Re-verify consensus is still STRONG
      4. Check slippage gate
      5. If passes, emit entry signal
    """
    signal = pending_signals.get(token)

    if new_consensus.consensus == ConsensusSide.MIXED:
        # Consensus broke — cancel any pending signal
        pending_signals.pop(token, None)
        return None

    if signal is None:
        # New signal detected — start confirmation window
        # Compute weighted avg entry price of consensus traders
        avg_entry = compute_weighted_avg_entry(token, new_consensus)
        pending_signals[token] = PendingSignal(
            token_symbol=token,
            consensus=new_consensus.consensus,
            detected_at=now,
            avg_entry_price_at_detection=avg_entry,
        )
        return None

    # Check if confirmation window has elapsed
    elapsed_min = (now - signal.detected_at).total_seconds() / 60
    if elapsed_min < config.COPY_DELAY_MINUTES:
        return None  # Still waiting

    # Slippage gate
    price_change_pct = abs(current_price - signal.avg_entry_price_at_detection) / signal.avg_entry_price_at_detection * 100
    if price_change_pct > config.MAX_PRICE_SLIPPAGE_PERCENT:
        pending_signals.pop(token)  # Reject — price moved too much
        return None

    # Confirmed! Return entry signal
    signal.confirmed = True
    pending_signals.pop(token)
    return signal
```

### Market Price Acquisition

**Primary:** Hyperliquid WebSocket subscription to `allMids` channel — provides real-time mid prices for all perps with sub-second latency.

```python
# ws://api.hyperliquid.xyz/ws
# Subscribe: {"method": "subscribe", "subscription": {"type": "allMids"}}
# Returns: {"channel": "allMids", "data": {"mids": {"BTC": "97000.5", "ETH": "3200.1", ...}}}
```

**Fallback:** REST `POST https://api.hyperliquid.xyz/info` with `{"type": "allMids"}` — polled every 5 seconds if WebSocket disconnects. Stale price (>30s) triggers order hold until price refreshes.

---

## 6. Entry Sizing

```python
def calculate_entry_size(
    token: str,
    side: str,
    consensus: TokenConsensus,
    account_value: float,
    existing_positions: list[OurPosition],
    config: StrategyConfig,
) -> float | None:
    """
    Sizing formula:

    1. Base: avg position_weight of consensus traders * COPY_RATIO * our account
    2. Apply absolute caps
    3. Apply portfolio-level caps

    Returns position size in USD, or None if caps prevent entry.
    """
    # Step 1: Compute average position weight of agreeing traders
    if side == "Long":
        agreeing_volumes = consensus.long_volume_usd
        agreeing_count = len(consensus.long_traders)
    else:
        agreeing_volumes = consensus.short_volume_usd
        agreeing_count = len(consensus.short_traders)

    avg_position_value = agreeing_volumes / max(agreeing_count, 1)

    # Use the average consensus trader's allocation percentage
    # (approximation: avg position value / avg account value of consensus traders)
    # Simplified: just use COPY_RATIO * a fraction of our account
    base_size = account_value * 0.05 * config.COPY_RATIO  # Conservative starting point

    # Scale by consensus strength: more clusters = more conviction
    cluster_count = consensus.long_cluster_count if side == "Long" else consensus.short_cluster_count
    strength_mult = min(2.0, cluster_count / config.MIN_CONSENSUS_TRADERS)
    base_size *= strength_mult

    # Step 2: Absolute cap
    max_single = min(account_value * config.MAX_SINGLE_POSITION_RATIO, config.MAX_SINGLE_POSITION_HARD_CAP)
    size = min(base_size, max_single)

    # Step 3: Portfolio-level checks
    total_exposure = sum(p.size_usd for p in existing_positions)
    if total_exposure + size > account_value * config.MAX_TOTAL_EXPOSURE_RATIO:
        size = max(0, account_value * config.MAX_TOTAL_EXPOSURE_RATIO - total_exposure)

    if len(existing_positions) >= config.MAX_TOTAL_POSITIONS:
        return None  # At capacity

    # Token exposure check
    token_exposure = sum(p.size_usd for p in existing_positions if p.token_symbol == token)
    if token_exposure + size > account_value * config.MAX_EXPOSURE_PER_TOKEN:
        size = max(0, account_value * config.MAX_EXPOSURE_PER_TOKEN - token_exposure)

    # Directional exposure check
    long_exposure = sum(p.size_usd for p in existing_positions if p.side == "Long")
    short_exposure = sum(p.size_usd for p in existing_positions if p.side == "Short")
    if side == "Long" and long_exposure + size > account_value * config.MAX_LONG_EXPOSURE:
        size = max(0, account_value * config.MAX_LONG_EXPOSURE - long_exposure)
    if side == "Short" and short_exposure + size > account_value * config.MAX_SHORT_EXPOSURE:
        size = max(0, account_value * config.MAX_SHORT_EXPOSURE - short_exposure)

    return size if size >= 100 else None  # $100 minimum to avoid dust
```

### Leverage Selection

```python
def select_leverage(consensus_traders_avg_leverage: float, config: StrategyConfig) -> int:
    """Cap at MAX_ALLOWED_LEVERAGE, use isolated margin."""
    return min(int(consensus_traders_avg_leverage), config.MAX_ALLOWED_LEVERAGE)
```

### Order Type Selection (Agent 4 Decision Tree)

```python
def select_order_type(
    action: str,
    signal_age_seconds: float,
    current_price: float,
    trader_entry_price: float,
    token: str,
) -> tuple[str, float | None]:
    """
    Returns (order_type, limit_price_or_None).
    """
    SLIPPAGE_TARGETS = {"BTC": 0.05, "ETH": 0.08, "SOL": 0.15, "HYPE": 0.30}
    max_slippage_pct = SLIPPAGE_TARGETS.get(token, 0.30)

    age_min = signal_age_seconds / 60

    if action == "Close":
        return ("market", None)  # Always market for exits

    if age_min < 2:
        # Fresh signal — market order with 0.5% max slippage
        return ("market", None)
    elif age_min < 10:
        # Check price drift
        drift_pct = abs(current_price - trader_entry_price) / trader_entry_price * 100
        if drift_pct < 0.3:
            return ("limit", current_price)  # Limit at current price
        else:
            return ("skip", None)  # Too much drift
    else:
        return ("skip", None)  # Too old — evaluate independently
```

---

## 7. Exit Rules

Positions are monitored every tick (WebSocket price update) and every 15 minutes (position poll).

### 7.1 Consensus Break Exit

```python
def check_consensus_break(
    position: OurPosition,
    current_consensus: TokenConsensus,
) -> bool:
    """Exit if consensus no longer supports our position."""
    if position.side == "Long" and current_consensus.consensus != ConsensusSide.STRONG_LONG:
        return True
    if position.side == "Short" and current_consensus.consensus != ConsensusSide.STRONG_SHORT:
        return True
    return False
```

### 7.2 Independent Stop Loss

```python
def check_stop_loss(position: OurPosition, current_price: float, config: StrategyConfig) -> str | None:
    """Returns close_reason or None."""

    # Fixed stop loss
    if position.side == "Long":
        stop_price = position.entry_price_usd * (1 - config.STOP_LOSS_PERCENT / 100)
        if current_price <= stop_price:
            return "stop_loss"
    else:
        stop_price = position.entry_price_usd * (1 + config.STOP_LOSS_PERCENT / 100)
        if current_price >= stop_price:
            return "stop_loss"

    # Trailing stop (activates once in profit)
    if position.side == "Long":
        if current_price > position.highest_price_since_entry:
            position.highest_price_since_entry = current_price
        trail_price = position.highest_price_since_entry * (1 - config.TRAILING_STOP_PERCENT / 100)
        if current_price <= trail_price and current_price > position.entry_price_usd:
            return "trailing_stop"
    else:
        if current_price < position.highest_price_since_entry:
            position.highest_price_since_entry = current_price
        trail_price = position.highest_price_since_entry * (1 + config.TRAILING_STOP_PERCENT / 100)
        if current_price >= trail_price and current_price < position.entry_price_usd:
            return "trailing_stop"

    return None
```

### 7.3 Time Stop

```python
def check_time_stop(position: OurPosition, now: datetime, config: StrategyConfig) -> bool:
    hours_held = (now - position.opened_at).total_seconds() / 3600
    return hours_held > config.MAX_POSITION_DURATION_HOURS
```

### 7.4 Liquidation Buffer Monitor

```python
def check_liquidation_buffer(
    position: OurPosition,
    current_price: float,
    liquidation_price: float,
    config: StrategyConfig,
) -> str | None:
    """Returns action: 'emergency_close', 'reduce_50', or None."""
    if position.side == "Long":
        buffer_pct = (current_price - liquidation_price) / current_price * 100
    else:
        buffer_pct = (liquidation_price - current_price) / current_price * 100

    if buffer_pct < config.LIQUIDATION_EMERGENCY_CLOSE_PCT:
        return "emergency_close"
    elif buffer_pct < config.LIQUIDATION_REDUCE_PCT:
        return "reduce_50"
    return None
```

### 7.5 Exit Priority

When multiple exit conditions trigger simultaneously, use this priority:

1. **Liquidation buffer emergency** (< 10%) — immediate market close
2. **Stop loss** — market close
3. **Trailing stop** — market close
4. **Liquidation buffer reduce** (< 20%) — reduce 50%
5. **Time stop** — market close
6. **Consensus break** — market close

---

## 8. Implementation Phases

### Phase 0 — Project Scaffolding
**Depends on:** None

- [x] Initialize Python project with `pyproject.toml` (deps: aiohttp, pydantic-settings, hyperliquid-python-sdk, pytest, pytest-asyncio)
- [x] Create directory structure:
  ```
  src/
    consensus/
      __init__.py
      config.py          # StrategyConfig
      models.py           # All dataclasses/enums
      db.py               # SQLite setup and queries
      nansen_client.py    # Async Nansen API wrapper
      hl_client.py        # Hyperliquid price feed + order execution
      scoring.py          # Trader scoring + classification
      clusters.py         # Copy-cluster detection
      consensus_engine.py # Core consensus computation
      signal_gate.py      # Confirmation window + slippage
      sizing.py           # Entry sizing with caps
      risk.py             # Stop loss, trailing, liquidation buffer
      position_manager.py # Tracks our positions, exit checks
      scheduler.py        # Main asyncio loop orchestrating pollers
      paper_trader.py     # Paper trading execution engine
  tests/
      test_scoring.py
      test_clusters.py
      test_consensus.py
      test_signal_gate.py
      test_sizing.py
      test_risk.py
      test_position_manager.py
      test_integration.py
  ```
- [x] Set up `.env` loading for `NANSEN_API_KEY`, `HL_PRIVATE_KEY`, `TYPEFULLY_API_KEY`
- [x] Create SQLite DB initialization script

### Phase 1 — Nansen API Client + Data Ingestion
**Depends on:** Phase 0

- [x] Implement `nansen_client.py` with async methods for all 3 endpoints:
  - `fetch_leaderboard(date_from, date_to, filters, pagination)` — `POST /api/v1/perp-leaderboard`
  - `fetch_address_trades(address, date_from, date_to, filters, pagination)` — `POST /api/v1/profiler/perp-trades`
  - `fetch_address_positions(address, filters)` — `POST /api/v1/profiler/perp-positions`
- [x] Add retry logic with exponential backoff for 429 (rate limit) responses
- [x] Add pagination auto-follow (loop until `is_last_page == true`)
- [x] Add request/response logging for debugging
- [x] Write integration test that hits real API with test addresses (gated by `NANSEN_API_KEY` env var)

### Phase 2 — Trader Scoring + Watchlist Builder
**Depends on:** Phase 1

- [x] Implement `scoring.py`:
  - `classify_trader_style(trades, days_active) -> TraderStyle`
  - `compute_trader_score(trader_data, trades) -> float`
  - `build_watchlist(config) -> list[TrackedTrader]`
- [x] Implement `clusters.py`:
  - `detect_copy_clusters(traders, trade_log, lookback_days) -> dict[str, int]`
  - Union-Find implementation for cluster grouping
- [x] Write unit tests:
  - Test style classification with known trade patterns
  - Test scoring formula outputs with synthetic data
  - Test cluster detection merges correlated traders

### Phase 3 — Consensus Engine
**Depends on:** Phase 2

- [ ] Implement `consensus_engine.py`:
  - `compute_token_consensus(token, positions, traders, config, now) -> TokenConsensus`
  - `compute_all_tokens_consensus(positions_by_token, traders, config) -> dict[str, TokenConsensus]`
- [ ] Implement freshness decay: `e^(-hours / FRESHNESS_HALF_LIFE_HOURS)`
- [ ] Implement cluster-aware counting (one vote per cluster_id)
- [ ] Implement size threshold filtering per token
- [ ] Write unit tests:
  - 3 traders long BTC with 2:1 volume ratio → STRONG_LONG
  - 2 traders long, 2 short → MIXED
  - 3 traders long but in same cluster → NOT strong (only 1 cluster)
  - Stale positions (>12h) with freshness decay → volume too low for consensus
  - Position weight < 10% → filtered out

### Phase 4 — Signal Gate + Confirmation Window
**Depends on:** Phase 3

- [ ] Implement `signal_gate.py`:
  - `process_consensus_change(token, consensus, current_price, config, now) -> PendingSignal | None`
  - Manages `pending_signals` dict
  - Enforces `COPY_DELAY_MINUTES` wait
  - Enforces `MAX_PRICE_SLIPPAGE_PERCENT` gate
- [ ] Implement Hyperliquid price feed in `hl_client.py`:
  - WebSocket subscription to `allMids`
  - Fallback REST polling
  - Stale price detection (>30s)
- [ ] Write unit tests:
  - Signal created, confirmed after 15 min with <2% slippage → entry
  - Signal created, price moves >2% during window → rejected
  - Signal created, consensus breaks during window → cancelled
  - Signal created, re-checked at 14 min → still pending

### Phase 5 — Entry Sizing + Risk Caps
**Depends on:** Phase 4

- [ ] Implement `sizing.py`:
  - `calculate_entry_size(token, side, consensus, account_value, positions, config) -> float | None`
  - `select_leverage(avg_trader_leverage, config) -> int`
  - `select_order_type(action, signal_age, current_price, trader_entry, token) -> tuple`
- [ ] Implement all cap checks:
  - Single position cap
  - Total exposure cap
  - Token exposure cap
  - Directional (long/short) exposure cap
  - Position count cap
- [ ] Write unit tests:
  - Entry at $10K with $100K account → allowed
  - 6th position attempt → blocked (MAX_TOTAL_POSITIONS=5)
  - Token already at 14% exposure → capped to 1%
  - Leverage 20x from trader → capped to 5x

### Phase 6 — Exit Rules + Position Monitor
**Depends on:** Phase 5

- [ ] Implement `risk.py`:
  - `check_stop_loss(position, current_price, config) -> str | None`
  - `check_time_stop(position, now, config) -> bool`
  - `check_liquidation_buffer(position, current_price, liq_price, config) -> str | None`
- [ ] Implement `position_manager.py`:
  - `monitor_positions(positions, consensus_map, prices, config, now) -> list[ExitSignal]`
  - Priority-based exit signal emission
  - Trailing stop high-water-mark tracking
- [ ] Write unit tests:
  - Long at $100, price drops to $95 → stop_loss triggered
  - Long at $100, price goes to $110, drops to $101.50 → trailing_stop (8% from $110)
  - Position held 73 hours → time_stop
  - Liquidation buffer at 9% → emergency_close
  - Liquidation buffer at 18% → reduce_50
  - Consensus was STRONG_LONG, now MIXED → consensus_break

### Phase 7 — Scheduler + Paper Trading
**Depends on:** Phase 6

- [ ] Implement `scheduler.py`:
  - Asyncio event loop with scheduled tasks:
    - Daily: `refresh_watchlist()`
    - Every 5 min: `poll_all_trader_trades()`
    - Every 15 min: `poll_all_trader_positions()`
    - Every 15 min: `recompute_consensus()` → `process_signals()` → `check_exits()`
    - Continuous: WebSocket price feed
- [ ] Implement `paper_trader.py`:
  - Simulated order execution with configurable slippage model
  - Track simulated account balance and positions in DB
  - Log all signals, entries, exits with timestamps
  - Compare simulated PnL to naive single-trader mirror
- [ ] Add Typefully integration for social alerts (optional v1):
  - Post consensus signals to X via `POST /v2/social-sets/{id}/drafts`

### Phase 8 — Backtesting Framework
**Depends on:** Phase 1, Phase 3, Phase 6

- [ ] Build historical data fetcher:
  - Fetch 90 days of trades for top 50 leaderboard wallets
  - Store in SQLite for replay
- [ ] Build replay engine:
  - Step through historical trades chronologically
  - Reconstruct positions at each timestamp
  - Compute consensus snapshots
  - Simulate entries/exits using same signal pipeline
  - Model realistic latency: add 30-60s random delay to trade detection
  - Model slippage: apply token-specific slippage (BTC 0.03%, SOL 0.10%, HYPE 0.20%)
- [ ] Output backtest report:
  - Total return, Sharpe ratio, max drawdown, win rate
  - Number of trades, avg hold time, avg PnL per trade
  - Trades skipped (slippage gate, cap limits)
  - Comparison: consensus strategy vs naive mirror of best single trader
- [ ] Write backtest validation tests:
  - Known scenario with hand-calculated expected PnL

---

## 9. Testing Plan

### Unit Tests

| Test File | Coverage |
|-----------|----------|
| `test_scoring.py` | Style classification (HFT/SWING/POSITION boundary cases), composite score formula, normalized values clamp to [0,1], recency decay |
| `test_clusters.py` | Union-Find correctness, cluster detection with known correlated pairs, fallback heuristic for low-data traders |
| `test_consensus.py` | STRONG_LONG/STRONG_SHORT/MIXED classification, cluster-aware counting, size threshold filtering, freshness decay math, position weight filtering |
| `test_signal_gate.py` | Confirmation window timing, slippage rejection, consensus break during window, edge case: exactly at 15 min |
| `test_sizing.py` | Base sizing formula, all 6 cap types, leverage capping, order type selection tree, dust prevention ($100 minimum) |
| `test_risk.py` | Stop loss (long + short), trailing stop activation and triggering, trailing stop NOT triggering when underwater, time stop, liquidation buffer thresholds |
| `test_position_manager.py` | Exit priority ordering, simultaneous trigger handling, high-water-mark tracking across ticks |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_nansen_api.py` | Live API calls (skipped without API key), pagination follow, rate limit handling |
| `test_hl_price_feed.py` | WebSocket connection, fallback to REST, stale price detection |
| `test_end_to_end.py` | Full pipeline from mock trade data → consensus → signal → sizing → paper entry → exit |

### Property-Based Tests (Hypothesis)

```python
# Sizing never exceeds caps
@given(account_value=st.floats(1000, 1_000_000), num_positions=st.integers(0, 10))
def test_sizing_never_exceeds_caps(account_value, num_positions): ...

# Consensus is monotonic: adding a trader to the majority side never weakens consensus
@given(long_count=st.integers(0, 20), short_count=st.integers(0, 20))
def test_consensus_monotonicity(long_count, short_count): ...
```

### Specific Edge Cases

- [ ] **Blacklisted trader:** Trader was liquidated 3 days ago → excluded from consensus for 14 days
- [ ] **All traders in one cluster:** 15 traders tracked but all in same cluster → consensus never fires (cluster_count = 1)
- [ ] **Freshness at exactly 0:** All positions opened 48h ago → freshness ≈ 0.0006 → weighted volume near zero → MIXED
- [ ] **Add action 3 hours after Open:** Filtered out (>2hr rule)
- [ ] **Market price unavailable:** Price feed stale >30s → all entries held, only emergency exits on last known price

---

## 10. Monitoring & Observability

- **Structured logging:** JSON logs with fields: `event`, `token`, `trader`, `consensus`, `signal_age`, `price`, `slippage`, `size_usd`, `reason`
- **Metrics (future):** Prometheus counters/gauges for:
  - Signals detected / confirmed / rejected (by reason)
  - Active positions count
  - Total exposure USD
  - API call latency (P50/P99)
  - Price feed staleness
- **Alerts:** Log WARN on:
  - Price feed stale > 30s
  - API rate limit hit (429)
  - Liquidation buffer < 20%
  - Position at > 80% of time stop

---

## 11. File / Module Dependency Graph

```
config.py ← (used by everything)
models.py ← (used by everything)
db.py ← nansen_client, scoring, consensus_engine, position_manager
nansen_client.py ← scoring, scheduler
hl_client.py ← signal_gate, sizing, position_manager, scheduler
scoring.py ← scheduler (daily watchlist refresh)
clusters.py ← scoring
consensus_engine.py ← scheduler
signal_gate.py ← scheduler
sizing.py ← scheduler
risk.py ← position_manager
position_manager.py ← scheduler
scheduler.py ← main entry point
paper_trader.py ← scheduler (when in paper mode)
```

---

## 12. Open Questions / Future Work

1. **Execution venue:** v1 uses Hyperliquid SDK directly. Consider adding a venue abstraction for future multi-exchange support.
2. **Typefully integration depth:** v1 posts simple text alerts. Future: include charts, PnL screenshots.
3. **Dynamic N:** Currently `MIN_CONSENSUS_TRADERS = 3` is static. Could adapt based on how many traders are actively trading a given token.
4. **Funding rate overlay:** Agent 5's funding-rate-divergence signal could be a confirmation filter on top of consensus. Not in v1 scope.
5. **On-chain cluster detection:** v1 uses trade timestamp correlation. Future: check wallet funding sources for tighter cluster detection.
