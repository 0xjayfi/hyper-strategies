# Leverage-Aware Scaling Risk Module

> **Strategy #8** — Reusable risk module for the Hyperliquid copytrading system.
> Transforms upstream signal sizes into final executable positions with leverage caps, liquidation monitoring, and exposure guardrails.

---

## 1. Problem Statement

Upstream signal strategies (Consensus Trading, Funding Divergence, Entry-Only Signals, PnL-Weighted Allocation) produce a raw `base_position_usd` that ignores the copied trader's leverage, our own account limits, and real-time liquidation proximity. Executing raw sizes directly creates unbounded risk exposure.

This module sits **between signal generation and order execution**, applying a deterministic sizing pipeline that enforces every Agent 1 risk rule and Agent 4 execution constraint.

### Objectives

1. Deterministic sizing: `base_position_usd` in, `final_position_usd` + order params out.
2. Enforce leverage cap at 5x, isolated margin always.
3. Apply leverage-penalty scaling (high leverage = smaller position).
4. Enforce per-position, per-token, per-direction, and total exposure caps.
5. Continuously monitor liquidation buffer; auto-reduce at 20%, emergency-close at 10%.
6. All emergency exits use market orders with slippage assumptions.

---

## 2. Module API Spec

### 2.1 Data Types

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "Long"
    SHORT = "Short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class MarginType(str, Enum):
    ISOLATED = "isolated"
    CROSS = "cross"


class RiskAction(str, Enum):
    NONE = "none"
    REDUCE = "reduce"
    EMERGENCY_CLOSE = "emergency_close"


@dataclass
class SizingRequest:
    """Input from upstream strategy."""
    base_position_usd: float        # Raw size from signal strategy
    token: str                       # e.g. "BTC", "ETH", "SOL"
    side: Side                       # Long or Short
    trader_leverage: Optional[float] # Copied trader's leverage (None = infer or default)
    trader_position_value_usd: Optional[float]  # For leverage inference
    trader_margin_used_usd: Optional[float]      # For leverage inference


@dataclass
class AccountState:
    """Current account snapshot."""
    account_value_usd: float             # margin_summary_account_value_usd
    total_open_positions_usd: float      # Sum of all open position values
    total_long_exposure_usd: float       # Sum of long position values
    total_short_exposure_usd: float      # Sum of short position values
    token_exposure_usd: dict[str, float] # {token: total_position_value_usd}


@dataclass
class SizingResult:
    """Output to execution layer."""
    final_position_usd: float      # After all caps and penalties
    effective_leverage: float       # Capped leverage to use
    margin_type: MarginType         # Always ISOLATED
    order_type: OrderType           # market or limit
    max_slippage_pct: float         # Expected slippage for this asset
    rejected: bool                  # True if position was rejected entirely
    rejection_reason: Optional[str] # Why rejected
    sizing_breakdown: dict          # Step-by-step audit trail


@dataclass
class PositionSnapshot:
    """For liquidation monitoring."""
    token: str
    side: Side
    mark_price: float
    liquidation_price: float
    position_value_usd: float
    entry_price: float


@dataclass
class MonitorResult:
    """Output from liquidation buffer check."""
    action: RiskAction
    buffer_pct: float
    reduce_pct: Optional[float]    # e.g. 50 for reduce_position_by(50)
    order_type: OrderType           # Always MARKET for emergency
```

### 2.2 Public Functions

#### `calculate_position_size(request: SizingRequest, account: AccountState) -> SizingResult`

Main entry point. Runs the full sizing pipeline and returns a `SizingResult`.

**Errors:**
- `ValueError` if `base_position_usd <= 0`
- `ValueError` if `token` is empty
- `ValueError` if `account_value_usd <= 0`
- Returns `SizingResult(rejected=True)` for soft failures (caps exceeded, exposure breached)

#### `check_liquidation_buffer(position: PositionSnapshot) -> MonitorResult`

Checks a single position's liquidation proximity and returns the recommended action.

**Errors:**
- `ValueError` if `mark_price <= 0` or `liquidation_price <= 0`

#### `infer_leverage(position_value_usd: float, margin_used_usd: float) -> float`

Infers effective leverage from notional/margin ratio.

**Errors:**
- Returns `MAX_ALLOWED_LEVERAGE` (5.0) if margin is zero or data is missing.

#### `get_slippage_assumption(token: str) -> float`

Returns expected slippage percentage for asset class.

---

## 3. Constants (Agent 1 Rules — Verbatim)

```python
# --- Leverage ---
MAX_ALLOWED_LEVERAGE: float = 5.0

LEVERAGE_PENALTY_MAP: dict[int, float] = {
    1: 1.00,
    2: 0.90,
    3: 0.80,
    5: 0.60,
    10: 0.40,
    20: 0.20,
}
LEVERAGE_PENALTY_DEFAULT: float = 0.10  # For any leverage not in map

# --- Margin ---
USE_MARGIN_TYPE: MarginType = MarginType.ISOLATED

# --- Position Caps ---
MAX_SINGLE_POSITION_HARD_CAP: float = 50_000.0  # $50k hard cap
MAX_SINGLE_POSITION_PCT: float = 0.10            # 10% of account
MAX_TOTAL_OPEN_POSITIONS_PCT: float = 0.50        # 50% of account
MAX_EXPOSURE_PER_TOKEN_PCT: float = 0.15          # 15% per token
MAX_LONG_EXPOSURE_PCT: float = 0.60               # 60% directional
MAX_SHORT_EXPOSURE_PCT: float = 0.60              # 60% directional

# --- Liquidation Buffer ---
EMERGENCY_CLOSE_BUFFER_PCT: float = 10.0   # <10% -> emergency close
REDUCE_BUFFER_PCT: float = 20.0            # <20% -> reduce 50%
REDUCE_POSITION_PCT: float = 50.0          # Reduce by this %

# --- Slippage Assumptions (Agent 4) ---
SLIPPAGE_MAP: dict[str, float] = {
    "BTC": 0.05,     # 0.01-0.05% — use worst case
    "ETH": 0.10,     # 0.05-0.10%
    "SOL": 0.15,     # 0.05-0.15%
    "HYPE": 0.30,    # 0.1-0.3%
}
SLIPPAGE_DEFAULT: float = 0.20  # For unlisted tokens
```

---

## 4. Internal Calculation Pipeline

The sizing pipeline runs in strict order. Each step receives the output of the previous step. Any step can reject the trade entirely.

```
Step 1: Resolve leverage
    ├── Use trader_leverage if provided
    ├── Else infer from position_value / margin_used
    └── Else default to MAX_ALLOWED_LEVERAGE (conservative)
         │
Step 2: Cap leverage
    └── effective_leverage = min(resolved_leverage, MAX_ALLOWED_LEVERAGE)
         │
Step 3: Apply leverage penalty
    └── penalized_usd = adjust_position_for_leverage(base_position_usd, resolved_leverage)
    NOTE: Penalty uses the ORIGINAL trader leverage (not the capped value).
          A 20x trader gets 0.20 multiplier even though we cap our execution at 5x.
         │
Step 4: Apply single-position cap
    └── capped_usd = min(penalized_usd, account_value * 0.10, $50,000)
         │
Step 5: Check total open positions cap
    └── remaining_capacity = (account_value * 0.50) - total_open_positions_usd
    └── if capped_usd > remaining_capacity: capped_usd = remaining_capacity
    └── if remaining_capacity <= 0: REJECT
         │
Step 6: Check per-token exposure cap
    └── token_capacity = (account_value * 0.15) - current_token_exposure_usd
    └── if capped_usd > token_capacity: capped_usd = token_capacity
    └── if token_capacity <= 0: REJECT
         │
Step 7: Check directional exposure cap
    └── if side == Long:
    │       dir_capacity = (account_value * 0.60) - total_long_exposure_usd
    └── else:
            dir_capacity = (account_value * 0.60) - total_short_exposure_usd
    └── if capped_usd > dir_capacity: capped_usd = dir_capacity
    └── if dir_capacity <= 0: REJECT
         │
Step 8: Final validation
    └── if capped_usd < MIN_POSITION_USD (e.g. $10): REJECT (dust trade)
         │
Step 9: Build result
    └── SizingResult with final_position_usd, effective_leverage, ISOLATED margin,
        order_type, slippage, and full sizing_breakdown audit dict
```

### 4.1 Leverage Inference Logic

```python
def infer_leverage(position_value_usd: float, margin_used_usd: float) -> float:
    """
    Infer effective leverage from notional / margin.

    Nansen Address Perp Positions returns:
      - position_value_usd (notional)
      - margin_used_usd
      - leverage_value (explicit, but may not always be available upstream)

    Fallback: if margin_used_usd is 0 or data missing, return MAX_ALLOWED_LEVERAGE
    as conservative default.
    """
    if margin_used_usd <= 0 or position_value_usd <= 0:
        return MAX_ALLOWED_LEVERAGE

    inferred = position_value_usd / margin_used_usd
    return round(inferred, 1)
```

**Data sources for leverage:**
- **Direct**: `leverage_value` from Address Perp Positions API (field exists on the position object)
- **Direct**: `leverage` (e.g. "5X") from Token Perp Positions API — parse the integer
- **Inferred**: `position_value_usd / margin_used_usd` from Address Perp Positions API
- **Fallback**: `MAX_ALLOWED_LEVERAGE = 5.0` (conservative)

### 4.2 Leverage Penalty Function (Verbatim Agent 1)

```python
def adjust_position_for_leverage(base_position_usd: float, leverage: float) -> float:
    """
    Apply leverage penalty to base position size.
    Uses the ORIGINAL trader leverage (not capped), because the penalty reflects
    the risk profile of the trader being copied.

    Exact Agent 1 rule:
    leverage_penalty = {1: 1.00, 2: 0.90, 3: 0.80, 5: 0.60, 10: 0.40, 20: 0.20}
    multiplier = leverage_penalty.get(leverage, 0.10)
    """
    leverage_int = int(round(leverage))
    multiplier = LEVERAGE_PENALTY_MAP.get(leverage_int, LEVERAGE_PENALTY_DEFAULT)
    return base_position_usd * multiplier
```

**Design decision — interpolation for non-mapped values:**

For v1, non-mapped leverage values fall to 0.10 (the default). This is intentionally conservative. Interpolation (e.g. 7x -> 0.50) is a v2 enhancement.

### 4.3 Liquidation Buffer Check (Verbatim Agent 1)

```python
def check_liquidation_buffer(position: PositionSnapshot) -> MonitorResult:
    """
    Verbatim Agent 1 liquidation buffer monitoring.

    Long:  buffer_pct = (mark_price - liquidation_price) / mark_price * 100
    Short: buffer_pct = (liquidation_price - mark_price) / mark_price * 100

    Actions:
      buffer < 10% -> emergency close (market order)
      buffer < 20% -> reduce position by 50% (market order)
      buffer >= 20% -> no action
    """
    if position.side == Side.LONG:
        buffer_pct = (position.mark_price - position.liquidation_price) / position.mark_price * 100
    else:
        buffer_pct = (position.liquidation_price - position.mark_price) / position.mark_price * 100

    if buffer_pct < EMERGENCY_CLOSE_BUFFER_PCT:
        return MonitorResult(
            action=RiskAction.EMERGENCY_CLOSE,
            buffer_pct=buffer_pct,
            reduce_pct=100.0,
            order_type=OrderType.MARKET,  # Agent 4: exit priority > price
        )
    elif buffer_pct < REDUCE_BUFFER_PCT:
        return MonitorResult(
            action=RiskAction.REDUCE,
            buffer_pct=buffer_pct,
            reduce_pct=REDUCE_POSITION_PCT,  # 50%
            order_type=OrderType.MARKET,  # Agent 4: use market for risk actions
        )
    else:
        return MonitorResult(
            action=RiskAction.NONE,
            buffer_pct=buffer_pct,
            reduce_pct=None,
            order_type=OrderType.MARKET,
        )
```

---

## 5. Continuous Monitoring Loop

### 5.1 Architecture

```
┌──────────────────────────┐
│   Monitoring Scheduler   │
│   (asyncio / APScheduler)│
└──────────┬───────────────┘
           │ every 15 seconds
           ▼
┌──────────────────────────┐
│  Fetch My Positions      │
│  (Nansen Address Perp    │
│   Positions API)         │
│  OR Hyperliquid WebSocket│
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  For each open position: │
│  check_liquidation_buffer│
└──────────┬───────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
  REDUCE    EMERGENCY_CLOSE
  (50%)     (100%, market)
     │           │
     ▼           ▼
┌──────────────────────────┐
│  Execution Layer         │
│  - market order          │
│  - slippage tolerance    │
│  - log + alert           │
└──────────────────────────┘
```

### 5.2 Polling Strategy

| Data Source | Method | Interval | Rationale |
|-------------|--------|----------|-----------|
| **My positions** (mark_price, liq_price) | Nansen Address Perp Positions API | 15 seconds | Need near-real-time for buffer monitoring |
| **Mark price fallback** | Hyperliquid public API (`/info` endpoint) | 5 seconds | If Nansen rate-limited, use HL directly |
| **Account state** (for cap checks on new signals) | Nansen Address Perp Positions API | 60 seconds | Less urgent, caps checked at sizing time |

**Rate limit handling:**
- Nansen API returns `429` when rate-limited. Implement exponential backoff: 1s, 2s, 4s, max 30s.
- If Nansen is rate-limited for >30s during monitoring, fall back to Hyperliquid public API for mark prices.
- Hyperliquid public info API (`POST https://api.hyperliquid.xyz/info` with `{"type": "allMids"}`) provides real-time mark prices with no API key required.

### 5.3 Monitoring Actions

| Buffer % | Action | Order Type | Details |
|----------|--------|------------|---------|
| >= 20% | None | — | Position healthy |
| 10-20% | Reduce 50% | Market | Reduce position by 50%, log warning |
| < 10% | Emergency close | Market | Close entire position, log critical alert |

**Cooldown:** After a reduce action, wait 60 seconds before re-checking the same position (avoid cascading reductions).

### 5.4 Alert Integration

The monitor emits structured events that can be consumed by a notification layer (Typefully API, logging, etc.):

```python
@dataclass
class RiskAlert:
    timestamp: str          # ISO 8601
    token: str
    side: Side
    action: RiskAction
    buffer_pct: float
    position_value_usd: float
    mark_price: float
    liquidation_price: float
```

---

## 6. Integration with Upstream Strategies

### 6.1 Strategy #2 — Position Snapshot Rebalancing

```python
# Strategy #2 calculates target portfolio allocation across N traders.
# For each target position:

from risk_module import calculate_position_size, SizingRequest, AccountState

target_usd = weighted_avg_allocation["BTC"]  # e.g. $8,000

result = calculate_position_size(
    request=SizingRequest(
        base_position_usd=target_usd,
        token="BTC",
        side=Side.LONG,
        trader_leverage=None,  # Aggregated from multiple traders, use avg or None
        trader_position_value_usd=None,
        trader_margin_used_usd=None,
    ),
    account=current_account_state(),
)

if not result.rejected:
    execute_order(token="BTC", side="Long", size_usd=result.final_position_usd,
                  leverage=result.effective_leverage, margin=result.margin_type)
```

### 6.2 Strategy #3 — Consensus Trading

```python
# Strategy #3 fires when N traders agree on direction.
# It knows the average leverage of the agreeing traders.

avg_leverage = sum(t.leverage for t in agreeing_traders) / len(agreeing_traders)

result = calculate_position_size(
    request=SizingRequest(
        base_position_usd=consensus_signal.suggested_size_usd,
        token=consensus_signal.token,
        side=consensus_signal.side,
        trader_leverage=avg_leverage,
        trader_position_value_usd=None,
        trader_margin_used_usd=None,
    ),
    account=current_account_state(),
)
```

### 6.3 Strategy #5 — Entry-Only Signals

```python
# Strategy #5 copies "Open" actions only.
# It has the specific trader's leverage from the trade signal.

result = calculate_position_size(
    request=SizingRequest(
        base_position_usd=signal.value_usd * COPY_RATIO,  # e.g. 0.5
        token=signal.token_symbol,
        side=Side(signal.side),
        trader_leverage=signal.trader_leverage,  # From Nansen position data
        trader_position_value_usd=signal.position_value_usd,
        trader_margin_used_usd=signal.margin_used_usd,
    ),
    account=current_account_state(),
)
```

### 6.4 Strategy #9 — PnL-Weighted Allocation

```python
# Strategy #9 dynamically adjusts allocation per trader based on rolling PnL.
# The base_position_usd is already PnL-weighted by the strategy.

for trader in active_traders:
    pnl_weight = calculate_pnl_weight(trader)  # 0.5 to 1.0
    base_usd = default_allocation * pnl_weight

    for position in trader.current_positions:
        result = calculate_position_size(
            request=SizingRequest(
                base_position_usd=base_usd,
                token=position.token,
                side=position.side,
                trader_leverage=position.leverage,
                trader_position_value_usd=position.value_usd,
                trader_margin_used_usd=position.margin_used_usd,
            ),
            account=current_account_state(),
        )
```

### 6.5 Integration Contract Summary

All upstream strategies call the same function:

```
calculate_position_size(SizingRequest, AccountState) -> SizingResult
```

They are responsible for:
1. Providing `base_position_usd` (their signal strength).
2. Providing `trader_leverage` if known (or `None` for conservative default).
3. Reading `SizingResult.rejected` before proceeding to execution.

The risk module is responsible for:
1. All cap enforcement.
2. Leverage capping and penalty.
3. Choosing margin type (always isolated).
4. Providing slippage expectation.
5. Audit trail in `sizing_breakdown`.

---

## 7. File & Directory Structure

```
src/
├── risk/
│   ├── __init__.py
│   ├── constants.py          # All constants from Section 3
│   ├── types.py              # Dataclasses from Section 2.1
│   ├── sizing.py             # calculate_position_size, adjust_position_for_leverage
│   ├── leverage.py           # infer_leverage, resolve_leverage
│   ├── monitoring.py         # check_liquidation_buffer, MonitoringLoop class
│   └── slippage.py           # get_slippage_assumption
├── tests/
│   └── test_risk/
│       ├── test_sizing.py
│       ├── test_leverage.py
│       ├── test_monitoring.py
│       └── test_slippage.py
```

---

## 8. Implementation Phases

### Phase 1: Core Sizing Pipeline

**Depends on:** None

- [x] Create `src/risk/constants.py` with all Agent 1 constants verbatim
- [x] Create `src/risk/types.py` with all dataclasses and enums
- [x] Implement `infer_leverage()` in `src/risk/leverage.py`
- [x] Implement `adjust_position_for_leverage()` in `src/risk/sizing.py`
- [x] Implement `get_slippage_assumption()` in `src/risk/slippage.py`
- [x] Implement `calculate_position_size()` full pipeline in `src/risk/sizing.py`
- [x] Write unit tests for Phase 1 (see Section 9)

### Phase 2: Liquidation Buffer Monitoring

**Depends on:** Phase 1

- [x] Implement `check_liquidation_buffer()` in `src/risk/monitoring.py`
- [x] Implement `MonitoringLoop` class with configurable polling interval
- [x] Add cooldown logic (60s after reduce action)
- [x] Add `RiskAlert` event emission
- [x] Write unit tests for Phase 2 (see Section 9)

### Phase 3: Nansen API Integration for Monitoring

**Depends on:** Phase 2

- [x] Implement Nansen Address Perp Positions API client (fetch my positions)
- [x] Parse `leverage_value`, `liquidation_price_usd`, `margin_used_usd`, `position_value_usd` from response
- [x] Implement Hyperliquid public API fallback for mark prices
- [x] Add rate limit handling with exponential backoff
- [x] Wire API client into `MonitoringLoop`
- [x] Write integration tests with mocked API responses

### Phase 4: Account State Management

**Depends on:** Phase 3

- [x] Implement `AccountState` builder from Nansen API responses
- [x] Track `total_open_positions_usd`, `total_long_exposure_usd`, `total_short_exposure_usd`, `token_exposure_usd` from live position data
- [x] Add periodic refresh (every 60s)
- [x] Wire into `calculate_position_size` so callers get fresh state

### Phase 5: Upstream Strategy Integration

**Depends on:** Phase 1, Phase 4

- [x] Define integration interface / adapter for strategies to call risk module
- [x] Add example integration for each strategy (#2, #3, #5, #9)
- [x] Add logging and audit trail output
- [x] End-to-end integration test: signal -> sizing -> mock execution

---

## 9. Test Plan

### 9.1 Leverage Cap Enforcement

```python
def test_leverage_cap_at_5x():
    """Trader at 20x should be capped to 5x for our execution."""
    req = SizingRequest(base_position_usd=10000, token="BTC", side=Side.LONG,
                        trader_leverage=20.0, ...)
    result = calculate_position_size(req, account)
    assert result.effective_leverage == 5.0

def test_leverage_below_cap_unchanged():
    """Trader at 3x stays at 3x."""
    req = SizingRequest(..., trader_leverage=3.0, ...)
    result = calculate_position_size(req, account)
    assert result.effective_leverage == 3.0

def test_leverage_exactly_at_cap():
    req = SizingRequest(..., trader_leverage=5.0, ...)
    result = calculate_position_size(req, account)
    assert result.effective_leverage == 5.0

def test_leverage_none_defaults_to_max():
    """When leverage unknown, default to MAX_ALLOWED_LEVERAGE."""
    req = SizingRequest(..., trader_leverage=None,
                        trader_position_value_usd=None, trader_margin_used_usd=None, ...)
    result = calculate_position_size(req, account)
    assert result.effective_leverage == 5.0
```

### 9.2 Leverage Penalty Mapping

```python
@pytest.mark.parametrize("leverage,expected_multiplier", [
    (1, 1.00), (2, 0.90), (3, 0.80), (5, 0.60),
    (10, 0.40), (20, 0.20), (50, 0.10), (7, 0.10),
])
def test_leverage_penalty(leverage, expected_multiplier):
    result = adjust_position_for_leverage(10000.0, leverage)
    assert result == pytest.approx(10000.0 * expected_multiplier)

def test_penalty_uses_original_leverage_not_capped():
    """20x trader gets 0.20 multiplier, even though we execute at 5x."""
    req = SizingRequest(base_position_usd=10000, ..., trader_leverage=20.0, ...)
    result = calculate_position_size(req, account)
    # 10000 * 0.20 = 2000 (before caps)
    assert result.sizing_breakdown["after_leverage_penalty"] == pytest.approx(2000.0)
```

### 9.3 Position and Exposure Caps

```python
def test_single_position_cap_10_pct():
    """Account $100k -> max single position $10k."""
    account = AccountState(account_value_usd=100_000, ...)
    req = SizingRequest(base_position_usd=50_000, ..., trader_leverage=1.0, ...)
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 10_000

def test_single_position_hard_cap_50k():
    """Account $1M -> 10% = $100k, but hard cap is $50k."""
    account = AccountState(account_value_usd=1_000_000, ...)
    req = SizingRequest(base_position_usd=200_000, ..., trader_leverage=1.0, ...)
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 50_000

def test_total_exposure_cap():
    """Reject when total open positions at 50% of account."""
    account = AccountState(account_value_usd=100_000, total_open_positions_usd=50_000, ...)
    req = SizingRequest(base_position_usd=5_000, ...)
    result = calculate_position_size(req, account)
    assert result.rejected is True

def test_per_token_exposure_cap():
    """15% per token cap."""
    account = AccountState(account_value_usd=100_000,
                           token_exposure_usd={"BTC": 14_000}, ...)
    req = SizingRequest(base_position_usd=5_000, token="BTC", ...)
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 1_000  # Only $1k headroom

def test_directional_long_exposure_cap():
    """60% directional cap for longs."""
    account = AccountState(account_value_usd=100_000,
                           total_long_exposure_usd=59_000, ...)
    req = SizingRequest(base_position_usd=5_000, side=Side.LONG, ...)
    result = calculate_position_size(req, account)
    assert result.final_position_usd <= 1_000

def test_directional_short_exposure_cap():
    """60% directional cap for shorts."""
    account = AccountState(account_value_usd=100_000,
                           total_short_exposure_usd=60_000, ...)
    req = SizingRequest(base_position_usd=5_000, side=Side.SHORT, ...)
    result = calculate_position_size(req, account)
    assert result.rejected is True
```

### 9.4 Liquidation Buffer Calculations

```python
def test_long_buffer_healthy():
    """Long: mark=100, liq=70 -> buffer = 30%."""
    pos = PositionSnapshot(token="ETH", side=Side.LONG,
                           mark_price=100, liquidation_price=70, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(30.0)
    assert result.action == RiskAction.NONE

def test_short_buffer_healthy():
    """Short: mark=100, liq=140 -> buffer = 40%."""
    pos = PositionSnapshot(token="ETH", side=Side.SHORT,
                           mark_price=100, liquidation_price=140, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(40.0)
    assert result.action == RiskAction.NONE

def test_long_buffer_reduce_zone():
    """Long: mark=100, liq=85 -> buffer = 15% -> REDUCE."""
    pos = PositionSnapshot(..., side=Side.LONG, mark_price=100, liquidation_price=85, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(15.0)
    assert result.action == RiskAction.REDUCE
    assert result.reduce_pct == 50.0
    assert result.order_type == OrderType.MARKET

def test_short_buffer_reduce_zone():
    """Short: mark=100, liq=115 -> buffer = 15% -> REDUCE."""
    pos = PositionSnapshot(..., side=Side.SHORT, mark_price=100, liquidation_price=115, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(15.0)
    assert result.action == RiskAction.REDUCE

def test_long_buffer_emergency():
    """Long: mark=100, liq=95 -> buffer = 5% -> EMERGENCY CLOSE."""
    pos = PositionSnapshot(..., side=Side.LONG, mark_price=100, liquidation_price=95, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(5.0)
    assert result.action == RiskAction.EMERGENCY_CLOSE
    assert result.order_type == OrderType.MARKET

def test_short_buffer_emergency():
    """Short: mark=100, liq=105 -> buffer = 5% -> EMERGENCY CLOSE."""
    pos = PositionSnapshot(..., side=Side.SHORT, mark_price=100, liquidation_price=105, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(5.0)
    assert result.action == RiskAction.EMERGENCY_CLOSE

def test_buffer_exactly_at_boundary_10():
    """Exactly 10% is NOT emergency (< 10 triggers)."""
    pos = PositionSnapshot(..., side=Side.LONG, mark_price=100, liquidation_price=90, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(10.0)
    assert result.action == RiskAction.REDUCE  # 10 < 20, so reduce

def test_buffer_exactly_at_boundary_20():
    """Exactly 20% is NOT reduce (< 20 triggers)."""
    pos = PositionSnapshot(..., side=Side.LONG, mark_price=100, liquidation_price=80, ...)
    result = check_liquidation_buffer(pos)
    assert result.buffer_pct == pytest.approx(20.0)
    assert result.action == RiskAction.NONE  # 20 is not < 20
```

### 9.5 Leverage Inference

```python
def test_infer_leverage_from_notional_margin():
    """position_value=50000, margin=10000 -> 5x."""
    lev = infer_leverage(50000.0, 10000.0)
    assert lev == pytest.approx(5.0)

def test_infer_leverage_zero_margin_fallback():
    """Zero margin -> fallback to MAX_ALLOWED_LEVERAGE."""
    lev = infer_leverage(50000.0, 0.0)
    assert lev == MAX_ALLOWED_LEVERAGE

def test_infer_leverage_missing_data():
    lev = infer_leverage(0.0, 0.0)
    assert lev == MAX_ALLOWED_LEVERAGE
```

### 9.6 Slippage Assumptions

```python
@pytest.mark.parametrize("token,expected", [
    ("BTC", 0.05), ("ETH", 0.10), ("SOL", 0.15), ("HYPE", 0.30),
    ("DOGE", 0.20), ("UNKNOWN", 0.20),
])
def test_slippage_assumptions(token, expected):
    assert get_slippage_assumption(token) == expected
```

### 9.7 Margin Type

```python
def test_margin_always_isolated():
    """Every SizingResult must have margin_type = ISOLATED."""
    req = SizingRequest(base_position_usd=1000, ...)
    result = calculate_position_size(req, account)
    assert result.margin_type == MarginType.ISOLATED
```

### 9.8 Full Pipeline Integration

```python
def test_full_pipeline_20x_trader():
    """
    20x trader, $10k base, $200k account.
    Step 1: leverage = 20 (provided)
    Step 2: effective = min(20, 5) = 5x
    Step 3: penalty = 10000 * 0.20 = $2,000
    Step 4: cap = min(2000, 200000*0.10, 50000) = $2,000
    Step 5-7: well within caps (assuming clean account)
    Result: $2,000 at 5x isolated
    """
    account = AccountState(account_value_usd=200_000, total_open_positions_usd=0,
                           total_long_exposure_usd=0, total_short_exposure_usd=0,
                           token_exposure_usd={})
    req = SizingRequest(base_position_usd=10_000, token="BTC", side=Side.LONG,
                        trader_leverage=20.0, ...)
    result = calculate_position_size(req, account)
    assert result.final_position_usd == pytest.approx(2_000.0)
    assert result.effective_leverage == 5.0
    assert result.margin_type == MarginType.ISOLATED
    assert result.rejected is False
```

---

## 10. Potential Challenges & Mitigations

| Challenge | Mitigation |
|-----------|------------|
| Nansen API rate limits during high-frequency monitoring | Fallback to Hyperliquid public API for mark prices; exponential backoff |
| Leverage value missing from Nansen response | Inference from notional/margin; conservative 5x default |
| Leverage penalty map has gaps (e.g. 7x, 15x) | Default to 0.10 (most conservative); v2 can add interpolation |
| Race condition: account state stale when sizing | Refresh account state immediately before sizing; accept brief staleness for monitoring |
| Emergency close fails (exchange down) | Retry 3 times with 1s delay; alert operator if all fail; do NOT retry indefinitely |
| Position already reduced when monitor fires again | 60-second cooldown per position after any reduce action |

---

## 11. Success Criteria

1. All 30+ unit tests pass with 100% coverage on the sizing pipeline.
2. `calculate_position_size` never returns a position exceeding any Agent 1 cap.
3. `check_liquidation_buffer` correctly classifies all boundary conditions.
4. Emergency close always produces a market order.
5. Margin type is always `isolated` — no code path ever returns `cross`.
6. The module is stateless (except monitoring loop) — all state passed as arguments.
7. Every `SizingResult` includes a `sizing_breakdown` dict showing each pipeline step's output for auditability.
