# Entry-Only Signal Generator for Hyperliquid Perps

> **Strategy #5** — Copy smart money "Open" entries, manage our own exits.

---

## Problem Statement

Smart money traders on Hyperliquid have demonstrated alpha in **entry timing** but may have different risk tolerances, time horizons, or exit strategies than us. This system detects smart money entries via the Nansen API, filters them through a multi-layered quality gate, sizes positions with risk controls, and manages exits independently using hard stops, trailing stops, and time-based stops.

## Objectives

1. Ingest and score top Hyperliquid perp traders from Nansen leaderboard data
2. Monitor tracked traders' trades for "Open" (and qualifying "Add") actions
3. Filter signals through confidence, size, freshness, and slippage gates
4. Execute on Hyperliquid with isolated margin and independent stop orders
5. Manage all exits autonomously — never rely on the copied trader's exit

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PIPELINE FLOW                                │
│                                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐ │
│  │Leaderboard│──▶│  Scorer  │──▶│ Tracked  │──▶│ Trade Ingestion  │ │
│  │  Fetcher  │   │          │   │   Set    │   │  (polling loop)  │ │
│  └──────────┘   └──────────┘   └──────────┘   └────────┬─────────┘ │
│       daily          daily        in-memory             │           │
│                                                         ▼           │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │                   SIGNAL PIPELINE                         │       │
│  │  raw trade ──▶ action filter ──▶ size filter ──▶          │       │
│  │  confidence gate ──▶ freshness/slippage ──▶ consensus ──▶ │       │
│  │  SIGNAL OBJECT                                            │       │
│  └─────────────────────────────────┬────────────────────────┘       │
│                                    │                                 │
│                                    ▼                                 │
│  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
│  │ Entry Sizing  │──▶│    Execution     │──▶│   Risk Orders      │  │
│  │  Algorithm    │   │ (market/limit)   │   │ (stop+trailing)    │  │
│  └──────────────┘   └──────────────────┘   └────────┬───────────┘  │
│                                                      │              │
│                                    ┌─────────────────▼───────────┐  │
│                                    │     Position Monitor        │  │
│                                    │  - trailing stop update     │  │
│                                    │  - time-stop check          │  │
│                                    │  - trader liquidation check │  │
│                                    │  - profit-taking tiers      │  │
│                                    └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.11+ | Ecosystem, async support, quant libs |
| HTTP client | `httpx` (async) | Non-blocking API calls, connection pooling |
| Scheduler | `asyncio` + custom tick loop | Fine-grained polling cadence control |
| HyperLiquid SDK | `hyperliquid-python-sdk` | Official SDK for order placement |
| Data store | SQLite (via `aiosqlite`) | Lightweight, zero-config, sufficient for single-node |
| Config | `pydantic-settings` | Typed config with `.env` loading and validation |
| Logging | `structlog` | JSON-structured logs for debugging and audit |
| Testing | `pytest` + `pytest-asyncio` | Async test support |

---

## Phase 1: Core Infrastructure & Configuration

**Depends on:** None

- [x] **1.1** Set up project structure:
  ```
  src/
    config.py          # All constants + pydantic settings
    models.py          # Data models (Signal, Position, Trader, etc.)
    db.py              # SQLite schema + CRUD
  ```
- [x] **1.2** Define all configuration constants in `config.py`:
  ```python
  # --- Entry Risk (Agent 1) ---
  COPY_DELAY_MINUTES = 15
  MAX_PRICE_SLIPPAGE_PERCENT = 2.0
  COPY_RATIO = 0.5
  MAX_SINGLE_POSITION_USD = 50_000  # also capped at account_value * 0.10
  MAX_TOTAL_OPEN_POSITIONS_USD_RATIO = 0.50
  MAX_TOTAL_POSITIONS = 5
  MAX_EXPOSURE_PER_TOKEN = 0.15

  # --- Stop System (Agent 1) ---
  STOP_LOSS_PERCENT = 5.0
  TRAILING_STOP_PERCENT = 8.0
  MAX_POSITION_DURATION_HOURS = 72

  # --- Trade Filtering (Agent 3) ---
  MIN_TRADE_VALUE_USD = {
      "BTC": 50_000, "ETH": 25_000, "SOL": 10_000,
      "HYPE": 5_000, "_default": 5_000,
  }
  MIN_POSITION_WEIGHT = 0.10
  ADD_MAX_AGE_HOURS = 2  # "Add" valid only within 2h of Open

  # --- Trader Selection (Agent 2) ---
  MIN_TRADES_REQUIRED = 50
  TRADER_SCORE_WEIGHTS = {
      "normalized_roi": 0.25,
      "normalized_sharpe": 0.20,
      "normalized_win_rate": 0.15,
      "consistency_score": 0.20,
      "smart_money_bonus": 0.10,
      "risk_management_score": 0.10,
  }
  RECENCY_DECAY_HALFLIFE_DAYS = 14

  # --- Execution (Agent 4) ---
  POLLING_INTERVAL_TRADES_SEC = 60
  POLLING_INTERVAL_ADDRESS_TRADES_SEC = 300
  POLLING_INTERVAL_POSITIONS_SEC = 900
  POLLING_INTERVAL_LEADERBOARD_SEC = 86400

  # --- Liquidation Handling ---
  LIQUIDATION_COOLDOWN_DAYS = 14

  # --- Consensus (optional toggle) ---
  REQUIRE_CONSENSUS = False
  CONSENSUS_MIN_TRADERS = 2
  ```
- [x] **1.3** Define SQLite schema in `db.py`:
  ```sql
  -- Tracked traders and their scores
  CREATE TABLE traders (
      address TEXT PRIMARY KEY,
      label TEXT,
      score REAL,
      style TEXT,  -- 'SWING', 'HFT', 'POSITION'
      roi_7d REAL,
      roi_30d REAL,
      account_value REAL,
      nof_trades INTEGER,
      last_scored_at TEXT,
      blacklisted_until TEXT  -- NULL if not blacklisted
  );

  -- Known open positions per tracked trader (for liquidation detection)
  CREATE TABLE trader_positions (
      address TEXT,
      token_symbol TEXT,
      side TEXT,
      position_value_usd REAL,
      entry_price REAL,
      last_seen_at TEXT,
      PRIMARY KEY (address, token_symbol)
  );

  -- Our open positions
  CREATE TABLE our_positions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      token_symbol TEXT,
      side TEXT,
      entry_price REAL,
      size REAL,
      value_usd REAL,
      stop_price REAL,
      trailing_stop_price REAL,
      highest_price REAL,    -- for trailing stop (long)
      lowest_price REAL,     -- for trailing stop (short)
      opened_at TEXT,
      source_trader TEXT,
      source_signal_id TEXT,
      status TEXT DEFAULT 'open'  -- 'open', 'closed'
  );

  -- Signal audit log
  CREATE TABLE signals (
      id TEXT PRIMARY KEY,
      trader_address TEXT,
      token_symbol TEXT,
      side TEXT,
      action TEXT,
      value_usd REAL,
      position_weight REAL,
      timestamp TEXT,
      age_seconds REAL,
      slippage_check_passed INTEGER,
      trader_score REAL,
      copy_size_usd REAL,
      decision TEXT,  -- 'EXECUTE', 'SKIP_SLIPPAGE', 'SKIP_SIZE', etc.
      created_at TEXT
  );

  -- Processed trade hashes (dedup)
  CREATE TABLE seen_trades (
      transaction_hash TEXT PRIMARY KEY,
      seen_at TEXT
  );
  ```
- [x] **1.4** Define data models in `models.py` (Pydantic):
  ```python
  class Signal:
      id: str                  # UUID
      trader_address: str
      token_symbol: str
      side: str                # "Long" | "Short"
      action: str              # "Open" | "Add"
      value_usd: float
      position_weight: float   # value / trader account_value
      timestamp: datetime      # trade's block_timestamp
      age_seconds: float       # now - timestamp
      slippage_check: bool     # price within MAX_PRICE_SLIPPAGE_PERCENT
      trader_score: float      # composite score
      trader_roi_7d: float     # for track-record weighting
      copy_size_usd: float     # final computed size
      leverage: float | None   # if available from positions
      order_type: str          # "market" | "limit" (execution decision)
      max_slippage: float      # 0.5% or 0.3% depending on age
  ```

---

## Phase 2: Nansen API Client

**Depends on:** Phase 1

- [x] **2.1** Create `src/nansen_client.py` — async HTTP wrapper around all Nansen endpoints:
  ```python
  class NansenClient:
      base_url = "https://api.nansen.ai/api/v1"

      async def get_perp_leaderboard(self, date_from, date_to, page=1, per_page=100) -> list[dict]
      async def get_address_perp_trades(self, address, date_from, date_to, page=1, per_page=100) -> list[dict]
      async def get_address_perp_positions(self, address) -> dict
      async def get_perp_pnl_leaderboard(self, token_symbol, date_from, date_to, page=1, per_page=100) -> list[dict]
      async def get_smart_money_perp_trades(self, only_new_positions=False, page=1, per_page=100) -> list[dict]
      async def get_perp_screener(self, date_from, date_to, page=1, per_page=100) -> list[dict]
  ```
- [x] **2.2** Implement pagination helper — auto-paginate until `is_last_page=true`
- [x] **2.3** Implement rate-limit handling with exponential backoff on 429
- [x] **2.4** Map exact Nansen response field names to internal models:

  **Leaderboard response → Trader:**
  | Nansen field | Internal field |
  |---|---|
  | `trader_address` | `address` |
  | `trader_address_label` | `label` |
  | `total_pnl` | `total_pnl` |
  | `roi` | `roi` (%) |
  | `account_value` | `account_value` |

  **Address Perp Trades response → RawTrade:**
  | Nansen field | Internal field |
  |---|---|
  | `action` | `action` ("Open"/"Close"/"Add") |
  | `side` | `side` ("Long"/"Short") |
  | `token_symbol` | `token_symbol` |
  | `value_usd` | `value_usd` |
  | `price` | `price` |
  | `timestamp` | `timestamp` (ISO 8601) |
  | `transaction_hash` | `tx_hash` |
  | `start_position` | `start_position` |
  | `size` | `size` |

  **Address Perp Positions response → TraderPositionSnapshot:**
  | Nansen field | Internal field |
  |---|---|
  | `position.token_symbol` | `token_symbol` |
  | `position.position_value_usd` | `position_value_usd` (string → float) |
  | `position.entry_price_usd` | `entry_price` (string → float) |
  | `position.leverage_value` | `leverage` |
  | `position.leverage_type` | `leverage_type` ("cross"/"isolated") |
  | `position.liquidation_price_usd` | `liquidation_price` (string → float) |
  | `position.size` | `size` (string → float; negative=short) |
  | `margin_summary_account_value_usd` | `account_value` (string → float) |

  **Note:** The positions endpoint returns `position_value_usd`, `leverage_value`, and `margin_summary_account_value_usd` — these are critical for computing `position_weight` and leverage-aware sizing. All string numeric fields must be cast to float.

---

## Phase 3: Trader Scoring & Selection

**Depends on:** Phase 1, Phase 2

- [x] **3.1** Create `src/trader_scorer.py` — daily job that:
  1. Fetches perp leaderboard for 7d, 30d, 90d windows
  2. For each candidate trader, fetches their trade history via `profiler/perp-trades`
  3. Computes derived metrics and composite score
  4. Classifies trading style
  5. Writes scored traders to `traders` table

- [x] **3.2** Implement trader style classification:
  ```python
  def classify_trader_style(trades: list[dict], days_active: int) -> str:
      trades_per_day = len(trades) / max(days_active, 1)
      avg_hold_time_hours = calculate_avg_hold_time(trades)

      if trades_per_day > 5 and avg_hold_time_hours < 4:
          return "HFT"       # Skip — too fast to copy
      elif trades_per_day >= 0.3 and avg_hold_time_hours < 336:
          return "SWING"     # Ideal
      else:
          return "POSITION"  # OK but infrequent
  ```

  **`calculate_avg_hold_time` logic:**
  Match "Open" actions to subsequent "Close" actions for the same `token_symbol` and `side` using `timestamp` ordering. The hold time is `close.timestamp - open.timestamp`. If no close found, use `now - open.timestamp` as an estimate. Average across all matched pairs.

- [x] **3.3** Implement composite scoring:
  ```python
  def compute_trader_score(trader: dict, trades_90d: list) -> float:
      # --- Normalized ROI (0-1, capped at 100%) ---
      roi_90d = trader["roi"]  # from leaderboard
      normalized_roi = min(1.0, max(0, roi_90d / 100))

      # --- Pseudo-Sharpe ---
      returns = [t["closed_pnl"] / t["value_usd"]
                 for t in trades_90d
                 if t["action"] == "Close" and t["value_usd"] > 0]
      if len(returns) > 1:
          avg_ret = mean(returns)
          std_ret = stdev(returns)
          sharpe = avg_ret / std_ret if std_ret > 0 else 0
          normalized_sharpe = min(1.0, max(0, sharpe / 3))  # cap at sharpe=3
      else:
          normalized_sharpe = 0

      # --- Win Rate ---
      winning = [t for t in trades_90d if t["closed_pnl"] > 0 and t["action"] == "Close"]
      closing = [t for t in trades_90d if t["action"] == "Close"]
      win_rate = len(winning) / len(closing) if closing else 0
      # Reject extremes
      if win_rate > 0.85 or win_rate < 0.35:
          return 0  # Disqualified
      normalized_win_rate = win_rate  # already 0-1

      # --- Consistency Score (needs 7d/30d/90d ROI) ---
      # Fetch leaderboard for 7d and 30d separately
      # roi_7d, roi_30d from separate fetches; roi_90d from main fetch
      consistency = consistency_score(roi_7d, roi_30d, roi_90d)

      # --- Smart Money Bonus ---
      label = trader.get("trader_address_label", "")
      sm_bonus = 1.0 if "Fund" in label else 0.8 if "Smart" in label else 0.5 if label else 0.0

      # --- Risk Management Score ---
      avg_leverage = mean([abs(t["value_usd"] / t.get("margin_used", t["value_usd"]))
                           for t in trades_90d]) if trades_90d else 1
      # Lower leverage = better risk mgmt
      risk_score = min(1.0, max(0, 1 - (avg_leverage - 1) / 20))

      # --- Composite ---
      w = TRADER_SCORE_WEIGHTS
      raw = (
          w["normalized_roi"] * normalized_roi +
          w["normalized_sharpe"] * normalized_sharpe +
          w["normalized_win_rate"] * normalized_win_rate +
          w["consistency_score"] * consistency +
          w["smart_money_bonus"] * sm_bonus +
          w["risk_management_score"] * risk_score
      )

      # --- Recency Decay ---
      # Weight by how recently the trader was active
      last_trade_age_days = (now() - max(t["timestamp"] for t in trades_90d)).days
      decay = 2 ** (-last_trade_age_days / RECENCY_DECAY_HALFLIFE_DAYS)

      return raw * decay
  ```

- [x] **3.4** Implement consistency score:
  ```python
  def consistency_score(roi_7d, roi_30d, roi_90d) -> float:
      positives = sum([roi_7d > 0, roi_30d > 0, roi_90d > 0])
      if positives == 3:
          base = 0.7
          # Normalize to weekly for variance comparison
          weekly_equiv = [roi_7d, roi_30d / 4, roi_90d / 12]
          variance = np.var(weekly_equiv)
          bonus = max(0, 0.3 - (variance / 100))
          return base + bonus
      elif positives >= 2:
          return 0.5
      else:
          return 0.2
  ```

- [x] **3.5** Selection criteria — filter before scoring:
  ```
  PASS IF:
    nof_trades >= 50
    style != "HFT"
    account_value >= $50,000  (from leaderboard)
    roi_30d (realized) > 0
    win_rate in [0.35, 0.85]
    blacklisted_until IS NULL or < now()
  ```

- [x] **3.6** Maintain tracked set: top 10-15 traders by score (active copy), 20-30 secondary (monitoring). Store in `traders` table with a `tier` column ("primary"/"secondary").

  **Inferring `trader_account_value`:** The leaderboard endpoint returns `account_value` directly. For more precise values during trade filtering, fetch `margin_summary_account_value_usd` from the positions endpoint (`profiler/perp-positions`). Cache this value per trader refresh cycle (daily).

---

## Phase 4: Trade Ingestion & Signal Generation

**Depends on:** Phase 1, Phase 2, Phase 3

- [x] **4.1** Create `src/trade_ingestion.py` — polling loop:
  ```python
  async def poll_loop():
      while True:
          # For each tracked trader (primary tier):
          for trader in get_primary_traders():
              trades = await nansen.get_address_perp_trades(
                  address=trader.address,
                  date_from=(now() - timedelta(hours=1)).isoformat(),
                  date_to=now().isoformat()
              )
              for trade in trades:
                  if trade["transaction_hash"] in seen_trades:
                      continue
                  mark_seen(trade["transaction_hash"])
                  signal = await evaluate_trade(trade, trader)
                  if signal and signal.decision == "EXECUTE":
                      await execute_signal(signal)

          await asyncio.sleep(POLLING_INTERVAL_ADDRESS_TRADES_SEC)
  ```

- [x] **4.2** Implement signal evaluation pipeline — `evaluate_trade()`:

  ```python
  async def evaluate_trade(trade: dict, trader: TraderRow) -> Signal | None:
      action = trade["action"]
      token = trade["token_symbol"]
      side = trade["side"]
      value_usd = trade["value_usd"]
      trade_time = parse_iso(trade["timestamp"])
      age_seconds = (now() - trade_time).total_seconds()

      # ── Step 1: Action Filter (Agent 3) ──
      if action == "Open":
          pass  # Always valid
      elif action == "Add":
          # Must be within 2 hours of the original Open
          original_open = await find_original_open(trader.address, token, side)
          if not original_open:
              return skip("SKIP_ADD_NO_OPEN")
          hours_since_open = (trade_time - original_open.timestamp).total_seconds() / 3600
          if hours_since_open > ADD_MAX_AGE_HOURS:
              return skip("SKIP_ADD_TOO_OLD")
      else:
          return skip("SKIP_ACTION_TYPE")  # "Close", "Reduce" ignored

      # ── Step 2: Asset Minimum Size (Agent 3) ──
      min_size = MIN_TRADE_VALUE_USD.get(token, MIN_TRADE_VALUE_USD["_default"])
      if value_usd < min_size:
          return skip("SKIP_SIZE_TOO_SMALL")

      # ── Step 3: Position Weight (Agent 3 + Agent 1) ──
      # Use cached trader account_value from leaderboard (or fetch positions)
      account_value = trader.account_value
      if account_value and account_value > 0:
          position_weight = value_usd / account_value
      else:
          position_weight = 0
      if position_weight < MIN_POSITION_WEIGHT:
          return skip("SKIP_LOW_WEIGHT")

      # Also check Agent 1 threshold: >= 5% of account
      if position_weight < 0.05:
          return skip("SKIP_LOW_CONFIDENCE")

      # ── Step 4: Time Decay Confirmation (Agent 1) ──
      if age_seconds < COPY_DELAY_MINUTES * 60:
          # Signal is too fresh — queue for re-check after delay
          return defer(check_at=trade_time + timedelta(minutes=COPY_DELAY_MINUTES))
      # After delay, verify position still exists
      positions = await nansen.get_address_perp_positions(trader.address)
      still_open = any(
          p["position"]["token_symbol"] == token
          and ((float(p["position"]["size"]) > 0) == (side == "Long"))
          for p in positions["data"]["asset_positions"]
      )
      if not still_open:
          return skip("SKIP_REVERSED_AFTER_DELAY")

      # ── Step 5: Slippage Gate (Agent 1 + Agent 4) ──
      current_price = await get_current_price(token)  # from screener or HL SDK
      trade_price = trade["price"]
      slippage_pct = abs(current_price - trade_price) / trade_price * 100
      if slippage_pct > MAX_PRICE_SLIPPAGE_PERCENT:
          return skip("SKIP_SLIPPAGE_EXCEEDED")

      # ── Step 6: Execution Timing Decision (Agent 4) ──
      age_minutes = age_seconds / 60
      if age_minutes < 2:
          order_type = "market"
          max_slippage = 0.5
      elif age_minutes < 10:
          if slippage_pct < 0.3:
              order_type = "limit"
              max_slippage = 0.3
          else:
              return skip("SKIP_STALE_HIGH_SLIPPAGE")
      else:
          # >10 min — evaluate independently or skip
          if trader.score > 0.8 and position_weight > 0.25:
              order_type = "limit"
              max_slippage = 0.3
          else:
              return skip("SKIP_TOO_OLD")

      # ── Step 7: Consensus Check (optional) ──
      if REQUIRE_CONSENSUS:
          same_direction_count = count_traders_with_position(token, side)
          if same_direction_count < CONSENSUS_MIN_TRADERS:
              return skip("SKIP_NO_CONSENSUS")

      # ── Step 8: Portfolio Limits ──
      our_positions = await get_our_open_positions()
      if len(our_positions) >= MAX_TOTAL_POSITIONS:
          return skip("SKIP_MAX_POSITIONS")
      total_exposure = sum(p.value_usd for p in our_positions)
      our_account_value = await get_our_account_value()
      if total_exposure >= our_account_value * MAX_TOTAL_OPEN_POSITIONS_USD_RATIO:
          return skip("SKIP_MAX_EXPOSURE")
      token_exposure = sum(p.value_usd for p in our_positions if p.token_symbol == token)
      if token_exposure >= our_account_value * MAX_EXPOSURE_PER_TOKEN:
          return skip("SKIP_TOKEN_EXPOSURE")

      # ── Step 9: Compute Copy Size ──
      copy_size_usd = compute_copy_size(
          trader_position_value=value_usd,
          trader_account_value=account_value,
          our_account_value=our_account_value,
          trader_roi_7d=trader.roi_7d,
          leverage=get_leverage_from_positions(positions, token),
      )
      if copy_size_usd <= 0:
          return skip("SKIP_SIZE_ZERO")

      # ── Build Signal ──
      return Signal(
          id=uuid4(),
          trader_address=trader.address,
          token_symbol=token,
          side=side,
          action=action,
          value_usd=value_usd,
          position_weight=position_weight,
          timestamp=trade_time,
          age_seconds=age_seconds,
          slippage_check=True,
          trader_score=trader.score,
          trader_roi_7d=trader.roi_7d,
          copy_size_usd=copy_size_usd,
          leverage=get_leverage_from_positions(positions, token),
          order_type=order_type,
          max_slippage=max_slippage,
          decision="EXECUTE",
      )
  ```

- [x] **4.3** Implement deferred signal queue — signals younger than `COPY_DELAY_MINUTES` are placed in a `deferred_signals` asyncio priority queue keyed by `check_at` time. A background coroutine pops them when ready and re-runs evaluation from Step 4 onward.

---

## Phase 5: Entry Sizing Algorithm

**Depends on:** Phase 1

- [x] **5.1** Create `src/sizing.py`:
  ```python
  def compute_copy_size(
      trader_position_value: float,
      trader_account_value: float,
      our_account_value: float,
      trader_roi_7d: float,
      leverage: float | None,
  ) -> float:
      """
      Combines:
        1. Trader allocation % × COPY_RATIO
        2. Track-record weighting (7d ROI tiers)
        3. Leverage penalty (if leverage available)
        4. Hard caps and exposure limits
      """

      # ── 1. Base size from trader allocation ──
      if trader_account_value > 0:
          trader_alloc_pct = trader_position_value / trader_account_value
      else:
          trader_alloc_pct = 0.05  # fallback: assume 5%
      base_size = our_account_value * trader_alloc_pct * COPY_RATIO

      # ── 2. Track-record weighting (Agent 1) ──
      if trader_roi_7d > 10:
          roi_multiplier = 1.00   # 100% target
      elif trader_roi_7d >= 0:
          roi_multiplier = 0.75   # 75% target
      else:
          roi_multiplier = 0.50   # 50% target (or skip via config)
      size = base_size * roi_multiplier

      # ── 3. Leverage penalty (optional, Agent 1) ──
      if leverage is not None and leverage > 1:
          leverage_penalty = {
              1: 1.00, 2: 0.90, 3: 0.80, 5: 0.60,
              10: 0.40, 20: 0.20,
          }
          # Interpolate for non-exact leverage values
          sorted_keys = sorted(leverage_penalty.keys())
          if leverage >= sorted_keys[-1]:
              penalty = 0.10  # minimum for extreme leverage
          else:
              # Find bracketing keys
              lower = max(k for k in sorted_keys if k <= leverage)
              upper = min(k for k in sorted_keys if k >= leverage)
              if lower == upper:
                  penalty = leverage_penalty[lower]
              else:
                  # Linear interpolation
                  frac = (leverage - lower) / (upper - lower)
                  penalty = leverage_penalty[lower] + frac * (leverage_penalty[upper] - leverage_penalty[lower])
          size *= penalty

      # ── 4. Apply caps ──
      max_single = min(our_account_value * 0.10, MAX_SINGLE_POSITION_USD)
      size = min(size, max_single)

      # Floor at $100 to avoid dust orders
      if size < 100:
          return 0

      return round(size, 2)
  ```

- [x] **5.2** Implement `get_leverage_from_positions()`:
  ```python
  def get_leverage_from_positions(positions_response: dict, token: str) -> float | None:
      """Extract leverage_value from the profiler/perp-positions response."""
      for ap in positions_response.get("data", {}).get("asset_positions", []):
          pos = ap.get("position", {})
          if pos.get("token_symbol") == token:
              return pos.get("leverage_value")
      return None
  ```

---

## Phase 6: Execution Module

**Depends on:** Phase 1, Phase 4, Phase 5

- [ ] **6.1** Create `src/executor.py` — Hyperliquid order placement:
  ```python
  class HyperLiquidExecutor:
      def __init__(self, sdk_client):
          self.client = sdk_client

      async def execute_signal(self, signal: Signal) -> ExecutionResult:
          """Place entry order + stop order atomically."""

          # ── Place entry order ──
          if signal.order_type == "market":
              order = await self.client.market_order(
                  coin=signal.token_symbol,
                  is_buy=(signal.side == "Long"),
                  sz=self.usd_to_size(signal.copy_size_usd, signal.token_symbol),
                  slippage=signal.max_slippage / 100,
              )
          else:  # limit
              limit_price = self.compute_limit_price(
                  side=signal.side,
                  current_price=await self.get_mark_price(signal.token_symbol),
                  max_slippage=signal.max_slippage,
              )
              order = await self.client.limit_order(
                  coin=signal.token_symbol,
                  is_buy=(signal.side == "Long"),
                  sz=self.usd_to_size(signal.copy_size_usd, signal.token_symbol),
                  px=limit_price,
              )

          if not order.success:
              log.error("Entry order failed", signal_id=signal.id, error=order.error)
              return ExecutionResult(success=False)

          entry_price = order.fill_price
          size = order.fill_size

          # ── Set isolated margin ──
          await self.client.set_leverage(
              coin=signal.token_symbol,
              leverage=min(signal.leverage or 3, 5),  # cap at 5x
              margin_type="isolated",
          )

          # ── Place hard stop-loss ──
          stop_price = compute_stop_price(entry_price, signal.side)
          await self.client.stop_order(
              coin=signal.token_symbol,
              is_buy=(signal.side == "Short"),  # opposite side for stop
              sz=size,
              trigger_px=stop_price,
              order_type="market",
          )

          # ── Record position ──
          await db.insert_our_position(
              token_symbol=signal.token_symbol,
              side=signal.side,
              entry_price=entry_price,
              size=size,
              value_usd=signal.copy_size_usd,
              stop_price=stop_price,
              trailing_stop_price=compute_trailing_stop_initial(entry_price, signal.side),
              highest_price=entry_price if signal.side == "Long" else None,
              lowest_price=entry_price if signal.side == "Short" else None,
              source_trader=signal.trader_address,
              source_signal_id=str(signal.id),
          )

          return ExecutionResult(success=True, order_id=order.id)
  ```

- [ ] **6.2** Implement stop price calculation:
  ```python
  def compute_stop_price(entry_price: float, side: str) -> float:
      if side == "Long":
          return entry_price * (1 - STOP_LOSS_PERCENT / 100)
      else:
          return entry_price * (1 + STOP_LOSS_PERCENT / 100)

  def compute_trailing_stop_initial(entry_price: float, side: str) -> float:
      """Initial trailing stop is wider than hard stop."""
      if side == "Long":
          return entry_price * (1 - TRAILING_STOP_PERCENT / 100)
      else:
          return entry_price * (1 + TRAILING_STOP_PERCENT / 100)
  ```

---

## Phase 7: Position Monitor & Exit Module

**Depends on:** Phase 1, Phase 2, Phase 6

- [ ] **7.1** Create `src/position_monitor.py` — runs every 30 seconds:
  ```python
  async def monitor_loop():
      while True:
          for pos in await db.get_open_positions():
              mark_price = await get_mark_price(pos.token_symbol)

              # ── 1. Trailing Stop Update ──
              update_trailing_stop(pos, mark_price)

              # ── 2. Trailing Stop Trigger Check ──
              if trailing_stop_triggered(pos, mark_price):
                  await close_position(pos, reason="TRAILING_STOP")
                  continue

              # ── 3. Time-Based Stop ──
              hours_open = (now() - pos.opened_at).total_seconds() / 3600
              if hours_open >= MAX_POSITION_DURATION_HOURS:
                  await close_position(pos, reason="TIME_STOP")
                  continue

              # ── 4. Profit-Taking Tiers (placeholder) ──
              unrealized_pct = compute_unrealized_pct(pos, mark_price)
              if unrealized_pct >= PROFIT_TAKE_TIER_3:
                  await reduce_position(pos, pct=0.50, reason="PROFIT_TIER_3")
              elif unrealized_pct >= PROFIT_TAKE_TIER_2:
                  await reduce_position(pos, pct=0.33, reason="PROFIT_TIER_2")
              elif unrealized_pct >= PROFIT_TAKE_TIER_1:
                  await reduce_position(pos, pct=0.25, reason="PROFIT_TIER_1")

              # ── 5. Trader Liquidation / Disappearance Check ──
              await check_trader_position(pos)

          await asyncio.sleep(30)
  ```

- [ ] **7.2** Implement trailing stop logic:
  ```python
  def update_trailing_stop(pos, mark_price: float):
      if pos.side == "Long":
          if mark_price > (pos.highest_price or pos.entry_price):
              pos.highest_price = mark_price
              new_trail = mark_price * (1 - TRAILING_STOP_PERCENT / 100)
              if new_trail > pos.trailing_stop_price:
                  pos.trailing_stop_price = new_trail
                  # Update on-chain stop order too
      else:  # Short
          if mark_price < (pos.lowest_price or pos.entry_price):
              pos.lowest_price = mark_price
              new_trail = mark_price * (1 + TRAILING_STOP_PERCENT / 100)
              if new_trail < pos.trailing_stop_price:
                  pos.trailing_stop_price = new_trail

  def trailing_stop_triggered(pos, mark_price: float) -> bool:
      if pos.side == "Long":
          return mark_price <= pos.trailing_stop_price
      else:
          return mark_price >= pos.trailing_stop_price
  ```

- [ ] **7.3** Implement trader liquidation detection:
  ```python
  async def check_trader_position(our_pos):
      """Detect if trader's position disappeared without a Close action."""
      trader_positions = await nansen.get_address_perp_positions(our_pos.source_trader)
      asset_positions = trader_positions.get("data", {}).get("asset_positions", [])

      trader_still_has_position = any(
          p["position"]["token_symbol"] == our_pos.token_symbol
          and ((float(p["position"]["size"]) > 0) == (our_pos.side == "Long"))
          for p in asset_positions
      )

      if not trader_still_has_position:
          # Check if there was a Close trade recently
          recent_trades = await nansen.get_address_perp_trades(
              our_pos.source_trader,
              date_from=(now() - timedelta(hours=1)).isoformat(),
              date_to=now().isoformat(),
          )
          had_close = any(
              t["action"] == "Close"
              and t["token_symbol"] == our_pos.token_symbol
              for t in recent_trades
          )

          if not had_close:
              # Probable liquidation — exit immediately and blacklist
              await close_position(our_pos, reason="TRADER_LIQUIDATED")
              await db.blacklist_trader(
                  our_pos.source_trader,
                  until=now() + timedelta(days=LIQUIDATION_COOLDOWN_DAYS)
              )
              log.warning(
                  "Trader position disappeared without close — probable liquidation",
                  trader=our_pos.source_trader,
                  token=our_pos.token_symbol,
              )
          else:
              # Trader closed normally — we decide based on our own stops
              # (don't auto-exit just because trader exited)
              log.info("Trader closed position, our stops remain active",
                       trader=our_pos.source_trader, token=our_pos.token_symbol)
  ```

- [ ] **7.4** Define profit-taking tier placeholders:
  ```python
  # Profit-taking tiers (% unrealized gain from entry)
  PROFIT_TAKE_TIER_1 = 10.0   # Take 25% off at +10%
  PROFIT_TAKE_TIER_2 = 20.0   # Take 33% off at +20%
  PROFIT_TAKE_TIER_3 = 40.0   # Take 50% off at +40%
  # Set to None/0 to disable any tier
  ```

- [ ] **7.5** Implement `close_position()` — market order to close, cancel existing stop orders, update DB status, log reason.

---

## Phase 8: Main Orchestrator

**Depends on:** Phase 2, Phase 3, Phase 4, Phase 7

- [ ] **8.1** Create `src/main.py` — entry point:
  ```python
  async def main():
      # Init
      await db.init()
      nansen = NansenClient(api_key=settings.NANSEN_API_KEY)
      executor = HyperLiquidExecutor(sdk_client=hl_client)

      # Launch concurrent loops
      await asyncio.gather(
          leaderboard_refresh_loop(nansen),   # daily
          trade_ingestion_loop(nansen),        # every 5 min
          deferred_signal_processor(),          # continuous
          position_monitor_loop(executor),      # every 30 sec
      )
  ```

- [ ] **8.2** Implement graceful shutdown — handle SIGINT/SIGTERM, cancel all tasks, close open connections.

- [ ] **8.3** Add structured logging throughout — every signal decision, every order, every stop update logged with full context for post-mortem analysis.

---

## Phase 9: Backtest / Paper Trading Mode

**Depends on:** Phase 4, Phase 5, Phase 7

- [ ] **9.1** Create `src/backtest.py` — historical simulation:
  ```python
  class Backtester:
      def __init__(self, start_date, end_date, initial_capital):
          self.capital = initial_capital
          self.positions = []
          self.trades_log = []

      async def run(self):
          # 1. Fetch leaderboard for the period
          # 2. Score and select traders
          # 3. Fetch all trades for tracked traders in date range
          # 4. Sort all trades by timestamp
          # 5. Replay through signal pipeline
          # 6. Simulate execution with slippage model
          # 7. Simulate stops using historical price data
  ```

- [ ] **9.2** Slippage simulation model:
  ```python
  def simulate_slippage(token: str, side: str, size_usd: float) -> float:
      """Return estimated slippage in percent."""
      base_slippage = {"BTC": 0.02, "ETH": 0.03, "SOL": 0.08, "_default": 0.15}
      slippage = base_slippage.get(token, base_slippage["_default"])
      # Larger orders have more slippage
      size_factor = 1 + (size_usd / 100_000) * 0.5
      return slippage * size_factor
  ```

- [ ] **9.3** Paper trading mode — flag in config that replaces `HyperLiquidExecutor` with `PaperExecutor`:
  ```python
  class PaperExecutor:
      """Simulates execution without placing real orders."""
      async def execute_signal(self, signal: Signal) -> ExecutionResult:
          # Record in DB as if executed
          # Use current mark price as fill price + simulated slippage
          ...
  ```

- [ ] **9.4** Backtest metrics output:
  ```
  Total Return (%)
  Max Drawdown (%)
  Sharpe Ratio
  Win Rate
  Profit Factor
  Avg Trade Duration
  Number of Trades
  Comparison: our exits vs. copying trader's exits
  ```

---

## Phase 10: Testing

**Depends on:** Phase 1, Phase 5, Phase 6, Phase 7

- [ ] **10.1** Stop placement correctness:
  ```python
  def test_stop_price_long():
      stop = compute_stop_price(entry_price=100.0, side="Long")
      assert stop == 95.0  # 100 * (1 - 5/100)

  def test_stop_price_short():
      stop = compute_stop_price(entry_price=100.0, side="Short")
      assert stop == 105.0  # 100 * (1 + 5/100)

  def test_trailing_stop_updates_on_new_high():
      pos = mock_position(side="Long", entry=100, highest=110, trailing_stop=101.2)
      update_trailing_stop(pos, mark_price=115)
      assert pos.highest_price == 115
      assert pos.trailing_stop_price == 115 * (1 - 8/100)  # 105.8

  def test_trailing_stop_does_not_lower():
      pos = mock_position(side="Long", entry=100, highest=115, trailing_stop=105.8)
      update_trailing_stop(pos, mark_price=112)  # price dropped but still above trail
      assert pos.trailing_stop_price == 105.8  # unchanged
  ```

- [ ] **10.2** Time-stop test:
  ```python
  def test_time_stop_triggers_after_72h():
      pos = mock_position(opened_at=now() - timedelta(hours=73))
      assert should_time_stop(pos) is True

  def test_time_stop_does_not_trigger_before_72h():
      pos = mock_position(opened_at=now() - timedelta(hours=71))
      assert should_time_stop(pos) is False
  ```

- [ ] **10.3** Slippage gate test:
  ```python
  def test_slippage_gate_passes():
      # trade at $100, current at $101.5 → 1.5% < 2.0% threshold
      assert slippage_check(trade_price=100, current_price=101.5, max_pct=2.0) is True

  def test_slippage_gate_fails():
      # trade at $100, current at $102.5 → 2.5% > 2.0% threshold
      assert slippage_check(trade_price=100, current_price=102.5, max_pct=2.0) is False
  ```

- [ ] **10.4** Tiered sizing based on 7d ROI:
  ```python
  def test_sizing_hot_trader():
      size = compute_copy_size(
          trader_position_value=100_000,
          trader_account_value=500_000,   # 20% allocation
          our_account_value=100_000,
          trader_roi_7d=15.0,             # > 10% → 100%
          leverage=None,
      )
      # 100k * 0.20 * 0.5 * 1.00 = $10,000
      assert size == 10_000

  def test_sizing_lukewarm_trader():
      size = compute_copy_size(
          trader_position_value=100_000,
          trader_account_value=500_000,
          our_account_value=100_000,
          trader_roi_7d=5.0,              # 0-10% → 75%
          leverage=None,
      )
      # 100k * 0.20 * 0.5 * 0.75 = $7,500
      assert size == 7_500

  def test_sizing_cold_trader():
      size = compute_copy_size(
          trader_position_value=100_000,
          trader_account_value=500_000,
          our_account_value=100_000,
          trader_roi_7d=-2.0,             # < 0% → 50%
          leverage=None,
      )
      # 100k * 0.20 * 0.5 * 0.50 = $5,000
      assert size == 5_000

  def test_sizing_with_leverage_penalty():
      size = compute_copy_size(
          trader_position_value=100_000,
          trader_account_value=500_000,
          our_account_value=100_000,
          trader_roi_7d=15.0,
          leverage=20,                     # 20x → 0.20 penalty
      )
      # 10,000 * 0.20 = $2,000
      assert size == 2_000

  def test_sizing_respects_max_cap():
      size = compute_copy_size(
          trader_position_value=2_000_000,
          trader_account_value=4_000_000,  # 50% allocation
          our_account_value=500_000,
          trader_roi_7d=15.0,
          leverage=None,
      )
      # 500k * 0.50 * 0.5 * 1.00 = $125,000 → capped at min(500k*0.10, 50k) = $50,000
      assert size == 50_000
  ```

- [ ] **10.5** Action filter tests:
  ```python
  def test_open_action_passes():
      assert action_filter("Open", ...) == "PASS"

  def test_add_within_2hrs_passes():
      open_time = now() - timedelta(hours=1)
      assert action_filter("Add", open_time=open_time, trade_time=now()) == "PASS"

  def test_add_after_2hrs_rejected():
      open_time = now() - timedelta(hours=3)
      assert action_filter("Add", open_time=open_time, trade_time=now()) == "SKIP"

  def test_reduce_rejected():
      assert action_filter("Reduce", ...) == "SKIP"

  def test_close_rejected_as_entry():
      assert action_filter("Close", ...) == "SKIP"
  ```

- [ ] **10.6** Trader liquidation detection test:
  ```python
  async def test_liquidation_detection():
      # Setup: trader has BTC Long position
      mock_positions_response(has_btc_long=True)
      await check_trader_position(our_pos)
      assert our_pos.status == "open"  # still open

      # Trader position disappears, no Close trade found
      mock_positions_response(has_btc_long=False)
      mock_trades_response(has_close=False)
      await check_trader_position(our_pos)
      assert our_pos.status == "closed"
      assert our_pos.close_reason == "TRADER_LIQUIDATED"
      assert trader_is_blacklisted(our_pos.source_trader, days=14)
  ```

- [ ] **10.7** Integration test — end-to-end with mocked Nansen API:
  ```python
  async def test_full_signal_pipeline():
      # 1. Load mock leaderboard → score traders
      # 2. Inject mock trade (Open, BTC, Long, $60k, position_weight=0.15)
      # 3. Verify signal passes all gates
      # 4. Verify copy_size_usd computed correctly
      # 5. Verify paper execution places order + stop
      # 6. Simulate price increase → trailing stop updates
      # 7. Simulate price reversal → trailing stop triggers close
  ```

---

## File Structure Summary

```
hyper-strategies-entry/
├── specs/
│   └── entry-only-signal-generator.md   # this file
├── src/
│   ├── __init__.py
│   ├── main.py                # Orchestrator / entry point
│   ├── config.py              # All constants + settings
│   ├── models.py              # Pydantic data models
│   ├── db.py                  # SQLite schema + CRUD
│   ├── nansen_client.py       # Async Nansen API wrapper
│   ├── trader_scorer.py       # Scoring + style classification
│   ├── trade_ingestion.py     # Polling + signal evaluation
│   ├── sizing.py              # Entry sizing algorithm
│   ├── executor.py            # Hyperliquid order execution
│   ├── position_monitor.py    # Exit management loop
│   └── backtest.py            # Historical simulation
├── tests/
│   ├── test_sizing.py
│   ├── test_stops.py
│   ├── test_filters.py
│   ├── test_liquidation.py
│   └── test_integration.py
├── ai_docs/                   # Nansen API reference docs
├── ideas/                     # Strategy brainstorm
└── .env                       # API keys
```

---

## Signal Object Spec

```python
@dataclass
class Signal:
    id: str                    # UUID — unique signal identifier
    trader_address: str        # 0x... — source trader wallet
    token_symbol: str          # "BTC", "ETH", "SOL", etc.
    side: str                  # "Long" | "Short"
    action: str                # "Open" | "Add"
    value_usd: float           # Trader's trade value in USD
    position_weight: float     # value_usd / trader_account_value (0.0-1.0)
    timestamp: datetime        # Trade's block_timestamp (ISO 8601)
    age_seconds: float         # now() - timestamp, in seconds
    slippage_check: bool       # True if within MAX_PRICE_SLIPPAGE_PERCENT
    trader_score: float        # Composite score (0.0-1.0)
    trader_roi_7d: float       # Trader's rolling 7-day ROI (%)
    copy_size_usd: float       # Final computed position size for us
    leverage: float | None     # Trader's leverage on this position (if available)
    order_type: str            # "market" | "limit" — execution method
    max_slippage: float        # 0.5 (market) or 0.3 (limit) — percent
    decision: str              # "EXECUTE" | "SKIP_*" reason code
```

---

## Polling Cadence Summary

| Data Source | Endpoint | Interval | Purpose |
|-------------|----------|----------|---------|
| Leaderboard | `POST /perp-leaderboard` | Daily | Refresh trader scores |
| Address Trades | `POST /profiler/perp-trades` | 5 min | Detect new trades from tracked traders |
| Address Positions | `POST /profiler/perp-positions` | 15 min | Verify positions, get leverage, detect liquidations |
| Position Monitor | Hyperliquid SDK / Screener | 30 sec | Update trailing stops, check time-stops |

---

## Data Availability & Inference Notes

| Needed Data | Direct Source | Fallback / Inference |
|---|---|---|
| `trader_account_value` | `perp-leaderboard` → `account_value` | `profiler/perp-positions` → `margin_summary_account_value_usd` |
| `leverage` | `profiler/perp-positions` → `position.leverage_value` | Not available from trade endpoints; default to `None` (skip leverage penalty) |
| `position_weight` | Computed: `value_usd / account_value` | Requires `account_value` from one of above |
| `roi_7d` | `perp-leaderboard` with 7-day date range | Cache from daily scoring run |
| `current_price` | `perp-screener` → `mark_price` | Hyperliquid SDK orderbook |
| `trader style` | Derived from trade frequency + hold times | Computed during scoring phase |
| `win_rate` | Derived from `profiler/perp-trades` (count Close trades with closed_pnl > 0) | Computed during scoring phase |

---

## Success Criteria

1. System correctly identifies and scores top swing traders daily
2. Entry signals pass all quality gates (action, size, weight, freshness, slippage)
3. Positions are sized correctly per the multi-factor algorithm
4. Hard stops placed immediately on every entry
5. Trailing stops update correctly as price moves favorably
6. Time-stops close stale positions after 72 hours
7. Trader liquidation detected and position closed within one polling cycle
8. Paper trading mode produces accurate simulation results
9. All unit tests pass with >90% code coverage on core logic
10. Backtest shows measurable improvement of our exit strategy vs. copying trader exits
