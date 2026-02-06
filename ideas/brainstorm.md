# Hyperliquid Copytrading Strategy Brainstorm

> **Context:** Brainstorming session exploring copytrading strategy directions that can be developed into tools using the Nansen Hyperliquid API.

---

## Initial Prompt

> "When done, read that doc CAREFULLY and THINK about multiple distinct directions of copytrading strategies that can be developed to a tool."

---

## Copytrading Strategy Directions

Based on the available APIs (Leaderboard, Positions, Trades), here are **distinct strategic directions** that could be developed into tools:

---

### **Category A: Direct Replication Strategies**

#### 1. Real-Time Trade Mirror
The basic approach from the docs - poll trades every 30-60 min, replicate Open/Add/Close/Reduce actions proportionally.

- **Input**: Tracked wallet addresses
- **Output**: Trade execution signals
- **Key challenge**: Latency (you're always behind), slippage

#### 2. Position Snapshot Rebalancing
Instead of copying individual trades, periodically snapshot top traders' portfolios and rebalance to match their aggregate allocation.

- Poll positions every 4-6 hours
- Calculate weighted-average portfolio across N traders
- Rebalance your portfolio to match
- Like an **"index fund" of smart money positions**

**Difference from #1**: Smoother, less reactive, fewer transactions

---

### **Category B: Signal Aggregation Strategies**

#### 3. Consensus/Confluence Trading
Only enter when **multiple smart money wallets** agree on direction.

- Track 10-20 top traders
- Signal fires when N traders are all long (or short) on same token
- Exit when consensus breaks
- Weight signals by historical PnL or ROI

**Key insight**: Reduces single-point-of-failure, more robust but slower

#### 4. Token Flow Sentiment
Aggregate smart money positioning **per token** rather than per wallet.

- Use Token Perp Positions to see all positions on BTC, ETH, SOL
- Calculate net long/short ratio among smart money
- Enter based on aggregate sentiment shifts

**Difference from wallet-following**: Token-centric view, directional bias signals

---

### **Category C: Selective/Filtered Strategies**

#### 5. Entry-Only Signal Generator
Use smart money entries as signals, but **apply your own exit strategy**.

- Copy "Open" actions only
- Manage exits yourself (trailing stop, take-profit, time-based)
- Decouple entry detection from position management

**Why**: Smart money might have different risk tolerance, time horizons

#### 6. High-Conviction Filter
Only copy trades that meet conviction thresholds:

- Large position sizes (value_usd > $50K)
- "Add" actions on existing positions (doubling down)
- Ignore small exploratory trades

**Key insight**: Filter signal from noise

#### 7. Action-Type Specialization
Build separate strategies for different action types:

- **Open-only copier**: Fresh positions = clearest signal
- **Add-only copier**: Adding = high conviction on existing thesis
- **Close watcher**: Learn when smart money takes profits

---

### **Category D: Risk-Adjusted Strategies**

#### 8. Leverage-Aware Scaling
Adjust your position size based on the copied trader's leverage.

- 40x leverage trader → scale down 80%
- 3x leverage trader → match or scale up
- Factor in liquidation_price distance

**Why**: Same dollar amount at 40x vs 3x has vastly different risk profiles

#### 9. PnL-Weighted Dynamic Allocation
Dynamically adjust how much you follow each trader based on recent performance.

- Rolling 7-day or 30-day closed_pnl
- Winning traders → increase allocation
- Losing traders → reduce or pause

**Key insight**: Trader performance varies over time

---

### **Category E: Contrarian Strategies**

#### 10. Crowded Position Fader
When smart money is **overwhelmingly one-sided**, fade the trade.

- If 90% of tracked wallets are long BTC → consider short
- Based on theory that crowded trades unwind violently
- Requires strong risk management

**High risk, high reward** - contrarian by nature

#### 11. Liquidation Anticipator
Monitor positions approaching liquidation.

- Track high-leverage positions where mark_price is moving toward liquidation_price
- Anticipate liquidation cascades
- Position to profit from forced selling/buying

---

### **Category F: Non-Trading Tools**

#### 12. Alert/Notification System
Don't auto-trade - generate alerts for human decision-making.

- Telegram/Discord/X notifications when smart money acts
- Dashboard showing real-time positions
- Educational rather than automated

**Use case**: Users who want signals but prefer manual execution

#### 13. Backtesting Engine
Build a tool to **backtest copytrading strategies** on historical data.

- Fetch historical trades via date ranges
- Simulate different strategies
- Calculate returns, drawdowns, Sharpe ratio
- Compare: direct copy vs consensus vs filtered

**Use case**: Data-driven strategy selection before going live

---

### **Summary Matrix**

| # | Strategy | Complexity | Risk | Latency Sensitivity |
|---|----------|------------|------|---------------------|
| 1 | Real-Time Mirror | Low | Medium | High |
| 2 | Snapshot Rebalance | Low | Low | Low |
| 3 | Consensus Trading | Medium | Low | Medium |
| 4 | Token Flow Sentiment | Medium | Medium | Low |
| 5 | Entry-Only Signals | Low | Medium | High |
| 6 | High-Conviction Filter | Low | Medium | High |
| 7 | Action-Type Specialization | Medium | Medium | High |
| 8 | Leverage-Aware Scaling | Medium | Low | High |
| 9 | PnL-Weighted Allocation | High | Low | Low |
| 10 | Crowded Position Fader | High | High | Low |
| 11 | Liquidation Anticipator | High | High | High |
| 12 | Alert System | Low | None | Medium |
| 13 | Backtesting Engine | High | None | None |

---

---

# Deep Dive Analysis: Five Agent Perspectives

## Agent 1: Risk Management Perspective

### Copytrading Risk Management Analysis for Hyperliquid

#### Executive Summary

Copytrading perpetual positions on Hyperliquid introduces significant risk vectors that differ from traditional spot copytrading. The leverage, liquidation mechanics, funding rates, and position timing create compounding risk factors that require robust safeguards. This analysis provides a framework for protecting capital while still capturing alpha from following successful traders.

---

### 1. Protection Against Following Bad Trades

#### The Problem
A trader may have an excellent historical track record but still execute losing trades. Following every trade blindly exposes you to:
- Temporary poor judgment
- Trades that work at their scale but not yours
- Position sizing errors
- Emotional/revenge trades

#### Risk Mitigation Strategies

##### 1.1 Signal Filtering Based on Trader Confidence
```
CRITERIA FOR TRADE REPLICATION:
- Minimum position size threshold: Only copy trades where trader commits >= 5% of their account
- Confirm with multiple traders: Require 2+ tracked traders taking same direction
- Filter by action type: Prioritize "Open" actions over "Add" (fresh conviction vs. averaging down)
```

##### 1.2 Time Decay Validation
Do not immediately copy. Implement a "confirmation window":
- Wait 15-30 minutes after detecting the trade
- Verify position is still open (not immediately reversed)
- Check if price has moved significantly (avoid chasing)

**Implementation Logic:**
```python
COPY_DELAY_MINUTES = 15
MAX_PRICE_SLIPPAGE_PERCENT = 2.0  # Skip if price moved >2% since trader's entry
```

##### 1.3 Track Record Weighted Copying
Weight your position size by the trader's recent performance:
```
IF trader's 7-day ROI > 10%: copy at 100% of your target size
IF trader's 7-day ROI 0-10%: copy at 75% of your target size
IF trader's 7-day ROI < 0%: copy at 50% of your target size OR skip
```

---

### 2. Position Size Safeguards

#### The Problem
Nansen API shows traders with positions worth millions. Copying proportionally could mean oversized positions relative to your account.

#### Risk Mitigation Strategies

##### 2.1 Absolute Maximum Position Limits
```
MAX_SINGLE_POSITION_USD = min(
    account_value * 0.10,  # Never exceed 10% of account per position
    $50,000               # Hard cap regardless of account size
)
```

##### 2.2 Total Exposure Limits
```
MAX_TOTAL_OPEN_POSITIONS_USD = account_value * 0.50  # Max 50% deployed
MAX_POSITIONS_PER_TOKEN = 1  # Only one position per asset at a time
MAX_TOTAL_POSITIONS = 5      # Maximum 5 concurrent positions
```

##### 2.3 Proportional Sizing Formula
Instead of copying dollar amounts, copy by percentage of trader's account:
```python
def calculate_copy_size(trader_position_usd, trader_account_value, my_account_value):
    trader_allocation_pct = trader_position_usd / trader_account_value
    my_position_usd = my_account_value * trader_allocation_pct * COPY_RATIO

    # Apply caps
    my_position_usd = min(my_position_usd, MAX_SINGLE_POSITION_USD)
    return my_position_usd

COPY_RATIO = 0.5  # Copy at 50% of their allocation percentage
```

---

### 3. Stop Loss Implementation

#### The Problem
The trader you're copying may have different risk tolerance, time horizons, or the ability to monitor positions 24/7.

#### Risk Mitigation Strategies

##### 3.1 Automatic Stop Loss on Every Position
```
STOP_LOSS_PERCENT = 5.0  # Exit if position drops 5% from entry
TRAILING_STOP_PERCENT = 8.0  # Trailing stop once in profit
```

##### 3.2 Time-Based Stop Loss
```
MAX_POSITION_DURATION_HOURS = 72  # Close position if held >3 days without exit signal
```

This prevents being stuck in stagnant trades that tie up capital.

##### 3.3 Independent Stop Loss (Don't Rely on Trader's Exit)
**Critical Rule:** Set your own stop loss immediately upon entry. Do not wait for the copied trader to exit their losing position.

```python
def on_position_open(entry_price, position_side):
    if position_side == "Long":
        stop_price = entry_price * (1 - STOP_LOSS_PERCENT / 100)
    else:  # Short
        stop_price = entry_price * (1 + STOP_LOSS_PERCENT / 100)

    place_stop_order(stop_price)
```

---

### 4. Leverage Risk Management

#### The Problem
The API shows traders using leverage from 1x to 50x+. High-leverage traders can:
- Generate massive returns (attractive to copy)
- Get liquidated rapidly (catastrophic for copiers)

#### Risk Mitigation Strategies

##### 4.1 Leverage Caps
```
MAX_ALLOWED_LEVERAGE = 5x  # Never exceed 5x regardless of copied trader's leverage

# If trader uses 20x leverage, you still use max 5x
effective_leverage = min(trader_leverage, MAX_ALLOWED_LEVERAGE)
```

##### 4.2 Leverage-Adjusted Position Sizing
Higher leverage = smaller position size:
```python
def adjust_position_for_leverage(base_position_usd, leverage):
    leverage_penalty = {
        1: 1.00,   # No penalty
        2: 0.90,
        3: 0.80,
        5: 0.60,
        10: 0.40,
        20: 0.20,  # Severe reduction
    }
    multiplier = leverage_penalty.get(leverage, 0.10)
    return base_position_usd * multiplier
```

##### 4.3 Leverage Type Preference
The API distinguishes between `cross` and `isolated` margin:
- **Prefer isolated margin** for copied positions to limit loss to that position only
- Cross margin means one bad position can liquidate your entire account

```
USE_MARGIN_TYPE = "isolated"  # Always use isolated margin for copytrading
```

##### 4.4 Liquidation Buffer Monitoring
Monitor the distance to liquidation price:
```python
def check_liquidation_risk(mark_price, liquidation_price, side):
    if side == "Long":
        buffer_pct = (mark_price - liquidation_price) / mark_price * 100
    else:
        buffer_pct = (liquidation_price - mark_price) / mark_price * 100

    if buffer_pct < 10:  # Less than 10% buffer
        trigger_emergency_close()
    elif buffer_pct < 20:
        reduce_position_by(50)
```

---

### 5. Handling Trader Liquidations

#### The Problem
If a copied trader gets liquidated, you may:
- Not receive an exit signal (position gone, no "Close" action)
- Still be in the same losing position
- Have no guidance on what to do next

#### Risk Mitigation Strategies

##### 5.1 Liquidation Detection
Monitor for sudden position disappearance:
```python
def check_trader_positions(trader_address, token_symbol):
    positions = fetch_perp_positions(trader_address)

    # If we're tracking a position and it disappears without a "Close" action
    if tracked_position_exists(trader_address, token_symbol):
        if not position_found_in_response(positions, token_symbol):
            # Possible liquidation - exit immediately
            close_my_position(token_symbol)
            log_warning(f"Trader {trader_address} position disappeared - possible liquidation")
```

##### 5.2 Pre-emptive Exit Before Liquidation
Use your own liquidation price monitoring:
```python
LIQUIDATION_PROXIMITY_TRIGGER = 0.15  # Exit at 15% above liquidation price

def monitor_liquidation_proximity():
    for position in my_positions:
        if position.side == "Long":
            danger_zone = position.liquidation_price * (1 + LIQUIDATION_PROXIMITY_TRIGGER)
            if position.mark_price <= danger_zone:
                close_position(position)
```

##### 5.3 Blacklist Recently Liquidated Traders
```python
LIQUIDATION_COOLDOWN_DAYS = 14

def on_trader_liquidation(trader_address):
    blacklist[trader_address] = datetime.now()

def is_trader_eligible(trader_address):
    if trader_address in blacklist:
        cooldown_end = blacklist[trader_address] + timedelta(days=LIQUIDATION_COOLDOWN_DAYS)
        if datetime.now() < cooldown_end:
            return False
    return True
```

---

### 6. Correlation Risk Management

#### The Problem
Multiple "top traders" may all be trading the same thesis, creating hidden correlation risk.

#### Risk Mitigation Strategies

##### 6.1 Maximum Exposure Per Token
```
MAX_EXPOSURE_PER_TOKEN = 0.15  # Max 15% of account per token
```

##### 6.2 Directional Exposure Limits
```
MAX_LONG_EXPOSURE = 0.60   # Max 60% of account in long positions
MAX_SHORT_EXPOSURE = 0.60  # Max 60% in short positions
```

---

### Key Insights Summary

| Risk Area | Recommended Action |
|-----------|-------------------|
| Bad Trades | 5% minimum position weight, 15-min confirmation delay |
| Position Size | 10% max per position, 50% max total exposure |
| Stop Loss | Independent 5% stop loss on every position |
| Leverage | Cap at 5x, use isolated margin |
| Liquidation | Exit at 15% buffer, blacklist for 14 days after liquidation |
| Correlation | 15% max per token, 60% max directional |

**Novel Contribution:** Position sizing formula that scales DOWN based on copied trader's leverage:
```
40x trader → copy at 20% size
5x trader → copy at 60% size
3x trader → copy at 80% size
```

---

---

## Agent 2: Trader Selection & Scoring Perspective

### Trader Selection & Scoring Strategy for Hyperliquid Copytrading

#### Executive Summary

Building a successful copytrading system requires moving beyond simple "highest PnL" rankings to a multi-dimensional scoring system that identifies traders with genuine, repeatable skill rather than those who were simply lucky in a bull market. This analysis provides a framework for trader selection using the available Nansen API endpoints.

---

### 1. Core Metrics for Trader Evaluation

#### 1.1 Available Metrics from Nansen API

| Metric | Source Endpoint | What It Reveals |
|--------|-----------------|-----------------|
| `total_pnl` | Perp Leaderboard | Absolute profit (scale of success) |
| `roi` / `roi_percent_total` | Perp Leaderboard / PnL Leaderboard | Risk-adjusted return |
| `roi_percent_realised` | PnL Leaderboard | Actually locked-in profits |
| `roi_percent_unrealised` | PnL Leaderboard | Open position quality |
| `nof_trades` | PnL Leaderboard | Trade frequency / activity level |
| `account_value` | Perp Leaderboard | Trader capitalization |
| `still_holding_balance_ratio` | PnL Leaderboard | Position management style |
| `trader_address_label` | All endpoints | Smart Money designation |

#### 1.2 Metric Importance Hierarchy

**Tier 1 - Essential (Must Pass):**
- **Realized ROI > 15%** over 30+ days - Demonstrates actual ability to close profitable trades
- **Account Value > $50,000** - Filters out noise from small accounts with asymmetric risk
- **Trade Count > 20** - Ensures statistical significance

**Tier 2 - Quality Indicators:**
- **Win Rate** (derived from trade history) - Consistency indicator
- **Profit Factor** (gross profits / gross losses) - Risk/reward quality
- **Average Trade Duration** - Trading style classification

**Tier 3 - Risk Management:**
- **Maximum Drawdown** (reconstructed from trade history)
- **Leverage Usage Patterns** - Higher isn't better
- **Position Sizing Consistency** - Professionals size positions consistently

---

### 2. Distinguishing Skill from Luck

#### 2.1 The Luck Problem

A trader who:
- Made 3 large bets on BTC during a bull run
- Used 20x leverage
- Got lucky on timing

...will appear at the top of leaderboards but is NOT someone to copy.

#### 2.2 Skill Indicators

**Statistical Significance Tests:**

```
Minimum Sample Size Formula:
n = (Z^2 * p * (1-p)) / E^2

Where:
- Z = 1.96 (95% confidence)
- p = expected win rate (0.5 for unknown)
- E = acceptable margin of error (0.1)

Result: Minimum ~96 trades for statistical confidence
```

**Recommendation:** Require traders to have 50+ trades minimum (practical compromise) and preferably 100+ for high-confidence selection.

#### 2.3 Anti-Luck Filters

| Filter | Implementation | Rationale |
|--------|----------------|-----------|
| **Multi-Token Performance** | Check if profitable across BTC, ETH, AND altcoins | Reduces single-asset luck |
| **Multi-Timeframe Consistency** | Compare 7d vs 30d vs 90d performance | True skill persists |
| **Win Rate Bounds** | Reject win rates > 85% OR < 35% | Extremes often indicate luck or manipulation |
| **Sharpe Ratio Equivalent** | (Avg Return - Risk Free) / Std Dev of Returns | Risk-adjusted skill measure |
| **Profit Factor** | Gross Profit / Gross Loss > 1.5 | Sustainable edge indicator |

#### 2.4 Calculating Derived Metrics

**Win Rate Calculation:**
```python
# Fetch all trades for a trader over 90 days
trades = fetch_perp_trades(address, date_range)

# Count winning vs losing trades
winning_trades = [t for t in trades if t['closed_pnl'] > 0]
losing_trades = [t for t in trades if t['closed_pnl'] < 0]

win_rate = len(winning_trades) / len(trades)
```

**Pseudo-Sharpe Calculation:**
```python
# Calculate return per trade
returns = [t['closed_pnl'] / t['value_usd'] for t in trades if t['action'] == 'Close']

avg_return = mean(returns)
std_return = std(returns)

sharpe_equivalent = avg_return / std_return if std_return > 0 else 0
```

---

### 3. High-Frequency vs Position Traders

#### 3.1 Trade Style Classification

**High-Frequency Traders (HFT-style):**
- 10+ trades per day
- Hold times < 4 hours
- Typically lower win rate (40-55%) with high profit factor
- Hard to copy due to latency requirements

**Swing Traders:**
- 2-10 trades per week
- Hold times: 1-14 days
- Win rate typically 45-60%
- **Ideal for copytrading** - gives you time to react

**Position Traders:**
- 1-5 trades per month
- Hold times: weeks to months
- Higher win rate (55-70%) with larger per-trade PnL
- Easy to copy but fewer signals

#### 3.2 Recommendation: Prioritize Swing Traders

**Why swing traders are optimal for copytrading:**

1. **Reaction Time**: You have 30-60 minutes to see and replicate their entry
2. **Slippage**: Lower urgency means less slippage on your entries
3. **Position Sizing**: Easier to scale your position appropriately
4. **Signal Frequency**: Enough trades to stay active without overwhelming

**Classification Algorithm:**
```python
def classify_trader_style(trades, days_active):
    trades_per_day = len(trades) / days_active

    avg_hold_time = calculate_avg_hold_time(trades)

    if trades_per_day > 5 and avg_hold_time < 4:  # hours
        return "HFT"  # Avoid - too hard to copy
    elif trades_per_day >= 0.3 and avg_hold_time < 336:  # < 2 weeks in hours
        return "SWING"  # Ideal
    else:
        return "POSITION"  # Good but low frequency
```

---

### 4. Composite Scoring System

#### 4.1 Scoring Formula

```
TRADER_SCORE = (
    w1 * NORMALIZED_ROI +
    w2 * NORMALIZED_SHARPE +
    w3 * NORMALIZED_WIN_RATE +
    w4 * CONSISTENCY_SCORE +
    w5 * SMART_MONEY_BONUS +
    w6 * RISK_MANAGEMENT_SCORE
) * STYLE_MULTIPLIER * RECENCY_DECAY
```

#### 4.2 Recommended Weights

| Component | Weight | Rationale |
|-----------|--------|-----------|
| `NORMALIZED_ROI` | 0.25 | Raw performance matters |
| `NORMALIZED_SHARPE` | 0.20 | Risk-adjusted performance |
| `NORMALIZED_WIN_RATE` | 0.15 | Consistency of execution |
| `CONSISTENCY_SCORE` | 0.20 | Performance across time periods |
| `SMART_MONEY_BONUS` | 0.10 | Nansen's labeling has value |
| `RISK_MANAGEMENT_SCORE` | 0.10 | Leverage and sizing discipline |

#### 4.3 Component Calculations

**Normalized ROI (0-1 scale):**
```python
# Min-max normalization with cap at 100% ROI
normalized_roi = min(1.0, max(0, roi / 100))
```

**Consistency Score:**
```python
# Compare 7d, 30d, 90d performance
def consistency_score(roi_7d, roi_30d, roi_90d):
    # All positive = high consistency
    if roi_7d > 0 and roi_30d > 0 and roi_90d > 0:
        base = 0.7
        # Bonus for similar magnitudes
        variance = np.var([roi_7d, roi_30d/4, roi_90d/12])  # Normalize to weekly
        consistency_bonus = max(0, 0.3 - (variance / 100))
        return base + consistency_bonus
    elif sum([roi_7d > 0, roi_30d > 0, roi_90d > 0]) >= 2:
        return 0.5
    else:
        return 0.2
```

**Smart Money Bonus:**
```python
def smart_money_bonus(label):
    if "Fund" in label:
        return 1.0
    elif "Smart" in label:
        return 0.8
    elif label:  # Any known label
        return 0.5
    else:
        return 0.0
```

---

### Key Insights Summary

- Require **50+ trades minimum** for statistical significance (96 ideal)
- Multi-timeframe consistency: must be profitable across 7d, 30d, AND 90d
- **Swing traders are optimal** for copytrading (hold time 1-24 hours)
- HFT traders (>5 trades/day) are nearly impossible to copy profitably
- Calculate pseudo-Sharpe: `avg_return / std_return`

**Watchlist recommendation:** 10-15 primary (active copy), 20-30 secondary (monitoring)

---

---

## Agent 3: Signal Quality & Filtering Perspective

### Copytrading Signal Quality & Filtering Analysis

#### Executive Summary

The challenge of copytrading is not finding trades to copy - it is filtering the **noise from conviction**. Based on the Nansen Hyperliquid API capabilities, this outlines a comprehensive signal quality framework that distinguishes high-probability trades from random market activity.

---

### 1. Trader Selection: Skill vs Luck

#### Multi-Timeframe Consistency

Query the **Perp Leaderboard** across multiple date ranges and require profitability in EACH:

```
| Timeframe   | Minimum PnL | Minimum ROI |
|-------------|-------------|-------------|
| 7 days      | > 0         | > 5%        |
| 30 days     | > $10,000   | > 15%       |
| 90 days     | > $50,000   | > 30%       |
```

**Rationale**: Lucky traders rarely maintain positive PnL across all timeframes. Skill compounds; luck regresses to mean.

#### Win Rate vs Profit Factor

```python
total_trades = count(all_trades)
winning_trades = count(trades where closed_pnl > 0)
win_rate = winning_trades / total_trades

gross_profit = sum(closed_pnl where closed_pnl > 0)
gross_loss = abs(sum(closed_pnl where closed_pnl < 0))
profit_factor = gross_profit / gross_loss
```

**Quality Thresholds**:
- Win rate > 50% AND profit factor > 1.5 = **High conviction trader**
- Win rate < 40% but profit factor > 2.5 = **Trend trader** (few big wins, many small losses - still valid)
- Win rate > 70% but profit factor < 1.2 = **Scalper** (needs high frequency, harder to copy)

---

### 2. Trade-Level Signal Filtering

#### Size-Based Filtering

**Recommended Thresholds by Asset:**

```
| Token   | Minimum Value USD | Rationale                           |
|---------|-------------------|-------------------------------------|
| BTC     | $50,000           | Noise floor for institutional size  |
| ETH     | $25,000           | Slightly lower threshold            |
| SOL     | $10,000           | More volatile, smaller positions OK |
| HYPE    | $5,000            | Lower liquidity asset               |
| Others  | $5,000            | Default minimum                     |
```

**Why size matters**: Small trades are often:
- DCA entries (not conviction)
- Risk management adjustments (noise)
- Testing/exploration (not their main thesis)

Large trades signal real commitment.

#### Position Size Relative to Account

```python
position_weight = position_value_usd / margin_summary_account_value_usd

# Signal quality tiers:
if position_weight > 0.25:
    signal_strength = "HIGH"  # 25%+ of account = major conviction
elif position_weight > 0.10:
    signal_strength = "MEDIUM"  # 10-25% = meaningful position
else:
    signal_strength = "LOW"  # <10% = minor/speculative
```

#### Action Type Filtering

| Action | Copy? | Rationale |
|--------|-------|-----------|
| Open | YES | Clear conviction, fresh thesis |
| Add | YES* | Copy if within 2hrs of Open; skip if days later |
| Reduce | NO | Unclear intent; could be profit-taking or fear |
| Close | YES | Important for position management, not entry |

*For "Add" actions, check `start_position` - if the position was already large before the add, it may be dollar-cost averaging (lower conviction).

#### Order Type Signals

| Type | Signal Interpretation | Copy Priority |
|------|----------------------|---------------|
| Market | Urgent conviction - trader willing to pay spread | HIGH |
| Limit | Patient entry - may never fill, not urgent | MEDIUM |

**Strategy**: Prioritize market orders for immediate copying. For limit orders, consider waiting to see if they actually fill before copying.

---

### 3. Signal Freshness Decay

**Signal freshness decay formula:**
```
weight = e^(-hours/4)  // 4-hour half-life
After 4h: 37% weight
After 8h: 13% weight
After 12h: 5% weight
```

---

### 4. Consensus & Divergence Signals

#### Smart Money Consensus

When multiple independent smart money traders take the same position simultaneously, signal strength compounds.

```python
long_traders = set(trades where side == "Long")
short_traders = set(trades where side == "Short")
long_volume = sum(value_usd where side == "Long")
short_volume = sum(value_usd where side == "Short")

if len(long_traders) >= 3 and long_volume > 2 * short_volume:
    consensus = "STRONG_LONG"
elif len(short_traders) >= 3 and short_volume > 2 * long_volume:
    consensus = "STRONG_SHORT"
else:
    consensus = "MIXED"  # Lower confidence
```

**Copy Rule**: Only copy when consensus is STRONG in one direction.

#### Handling Conflicting Signals

| Scenario | Action |
|----------|--------|
| Top 3 traders long, #4-5 short | Follow the majority by volume |
| Equal volume both directions | SKIP - market is uncertain |
| Your #1 ranked trader disagrees with consensus | Weight by historical accuracy |

---

### Key Insights Summary

- Size thresholds by asset: BTC >$50K, ETH >$25K, SOL >$10K, others >$5K
- **Action type hierarchy**: Open > Add > Close > Reduce (for signal value)
- Market orders = urgency/conviction; Limit orders = patience/speculation
- Require **position weight >10%** of trader's account for meaningful signals
- Win rate bounds: reject >85% OR <35% (extremes indicate luck or manipulation)

---

---

## Agent 4: Execution & Timing Perspective

### Key Insights

**Hybrid polling strategy:**
- Smart Money Trades: every 60 seconds
- Address Trades: every 5 minutes
- Positions: every 15 minutes
- Leaderboard: daily

**Target latency**: <500ms from detection to order

Use market orders for "Open" actions, limit orders for "Add" actions

**Expected slippage**: BTC 0.01-0.05%, SOL 0.05-0.15%, HYPE 0.1-0.3%

**Execution decision tree:**
```
If action=Open AND age<2min → Market order (0.5% max slippage)
If action=Open AND age<10min → Limit order (check if price moved <0.3%)
If action=Open AND age>10min → Evaluate independently or skip
If action=Close → Always market order (exit priority > price)
```

---

---

## Agent 5: Novel & Unconventional Approaches

### Contrarian Strategies

#### 1. Crowded Trade Fade
When crowding_ratio >3.0 and funding >0.01%, SHORT

```
Algorithm:
1. Use Perp Screener with only_smart_money=true
2. Calculate: crowding_ratio = smart_money_longs_count / smart_money_shorts_count
3. When crowding_ratio > 3.0 (heavily long) AND funding > 0.01%:
   - FADE: Open SHORT position
4. When crowding_ratio < 0.33 (heavily short) AND funding < -0.01%:
   - FADE: Open LONG position
```

**Rationale:**
- Smart money consensus often marks local tops/bottoms
- Extreme funding rates indicate crowded positioning that must eventually unwind

#### 2. Inverse Leaderboard
Fade last month's top performers (mean reversion)

```
Algorithm:
1. Query Perp Leaderboard for top 10 traders in PREVIOUS 30 days
2. For each top trader, fetch their CURRENT positions
3. Take the OPPOSITE position of their aggregate bias
4. Size inversely to their recent outperformance
```

#### 3. Liquidation Cascade Anticipator
Map liquidation walls, position for cascades

```
Algorithm:
1. Query Token Perp Positions for a given token
2. Identify clusters of liquidation_price values
3. Map "liquidation walls" - price levels where many positions would liquidate
4. When price approaches a liquidation wall from above:
   - SHORT with tight stop above the wall (bet on cascade)
5. When price approaches from below:
   - LONG with tight stop below the wall (bet on cascade)
```

---

### Meta Strategies

#### 4. Front-Run the Copiers
Enter immediately, exit before copying wave peaks (T+10min to T+1hr)

**Key Timing:**
- Famous trader opens: T+0
- Nansen API updates: T+5 to T+30 seconds
- Casual copiers react: T+30 minutes to T+2 hours
- Your exit window: T+10 minutes to T+1 hour

#### 5. Copy the Best Copiers
Second-order following (copiers who time entries/exits better)

```
Algorithm:
1. Identify top traders from leaderboard (the "originals")
2. For each original, find wallets that traded THE SAME DIRECTION within 1-6 hours
3. Track which "copiers" have the best timing (enter after original but exit before reversal)
4. Copy the best copiers, not the originals
```

#### 6. Avoid the Copied
Skip trades that many others are already copying (edge arbitraged away)

---

### Multi-Signal Fusion

#### 7. Funding Rate Divergence
When smart money pays premium (positive funding but still long) = HIGH CONVICTION

```python
# From perp-screener
funding = response['data']['funding']
sm_longs = response['data']['current_smart_money_position_longs_usd']
sm_shorts = response['data']['current_smart_money_position_shorts_usd']

# Conviction signal
if funding > 0 and sm_longs > sm_shorts * 1.5:
    # Smart money paying premium to be long = HIGH CONVICTION LONG
    signal = "STRONG_LONG"
elif funding < 0 and sm_shorts > sm_longs * 1.5:
    # Smart money paying premium to be short = HIGH CONVICTION SHORT
    signal = "STRONG_SHORT"
```

#### 8. Slow Exit Pattern
3+ "Reduce" actions in 48h without "Add" = distribution signal, fade

---

### Most Promising (per Agent 5)

1. **Funding Rate Divergence** - clean signal, actionable
2. **Fresh Smart Money** - inactive wallets suddenly trading = high conviction
3. **Crowded Trade Fade** - contrarian edge in extremes

---

---

# Cross-Agent Synthesis: Top Strategic Directions

| Strategy | Risk | Complexity | Edge Source |
|----------|------|------------|-------------|
| **Consensus Swing Trading** | Low | Medium | Multiple traders agreeing |
| **Funding Divergence** | Medium | Low | Smart money paying premium |
| **Leverage-Scaled Copying** | Low | Low | Risk-adjusted position sizing |
| **Fresh Smart Money Alerts** | Medium | Medium | High-conviction re-entries |
| **Crowded Trade Fade** | High | Medium | Mean reversion at extremes |
| **Liquidation Cascade** | High | High | Forced selling anticipation |

---

## Next Steps

Potential directions to develop into full implementation specs:
1. Build a consensus-based swing trading tool
2. Develop a funding rate divergence signal system
3. Create a leverage-aware copy sizing calculator
4. Design an alert system for fresh smart money activity
