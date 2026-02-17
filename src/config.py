"""Centralized configuration constants for the PnL-Weighted Dynamic Allocation system.

All tunable parameters — scoring weights, risk caps, scheduling intervals,
anti-luck thresholds — live here so they can be adjusted in one place.
"""

# ---------------------------------------------------------------------------
# Scoring weights (Phase 4)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Allocation (Phase 6)
# ---------------------------------------------------------------------------

# Softmax temperature
SOFTMAX_TEMPERATURE = 2.0

# 7d ROI tier thresholds
ROI_TIER_HIGH = 10    # >10% -> 1.0x
ROI_TIER_MEDIUM = 0   # 0-10% -> 0.75x
                       # <0%  -> 0.5x (or skip)

# ---------------------------------------------------------------------------
# Anti-luck gates (Phase 5)
# ---------------------------------------------------------------------------

ANTI_LUCK_7D = {"min_pnl": -999_999, "min_roi": -999}
ANTI_LUCK_30D = {"min_pnl": 500, "min_roi": 0}
ANTI_LUCK_90D = {"min_pnl": 1_000, "min_roi": 0}
WIN_RATE_BOUNDS = (0.25, 0.90)
MIN_PROFIT_FACTOR = 1.1
TREND_TRADER_PF = 2.0
MIN_TRADES_30D = 10

# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

LIQUIDATION_COOLDOWN_DAYS = 14

# ---------------------------------------------------------------------------
# Risk caps
# ---------------------------------------------------------------------------

MAX_TOTAL_POSITIONS = 5
MAX_TOTAL_OPEN_RATIO = 0.50       # account_value * 0.50
MAX_EXPOSURE_PER_TOKEN = 0.15
MAX_LONG_EXPOSURE = 0.60
MAX_SHORT_EXPOSURE = 0.60
MAX_SINGLE_WEIGHT = 0.40

# ---------------------------------------------------------------------------
# Turnover limits
# ---------------------------------------------------------------------------

MAX_WEIGHT_CHANGE_PER_DAY = 0.15
REBALANCE_COOLDOWN_HOURS = 24

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

LEADERBOARD_REFRESH_CRON = "0 0 * * *"  # Daily midnight UTC
METRICS_RECOMPUTE_HOURS = 6
POSITION_MONITOR_MINUTES = 15

# ---------------------------------------------------------------------------
# Nansen API rate limiting (per endpoint type)
# ---------------------------------------------------------------------------

# Leaderboard endpoints — slow server responses (~1-2s/page), no 429 risk
NANSEN_RATE_LIMIT_LEADERBOARD_PER_SECOND: int = 20
NANSEN_RATE_LIMIT_LEADERBOARD_PER_MINUTE: int = 300
NANSEN_RATE_LIMIT_LEADERBOARD_MIN_INTERVAL: float = 0.0
NANSEN_RATE_LIMIT_LEADERBOARD_STATE_FILE: str = "/tmp/pnl_weighted_rate_leaderboard.json"

# Profiler endpoints (perp-trades, perp-positions) — fast responses, 429 risk
NANSEN_RATE_LIMIT_PROFILER_PER_SECOND: int = 1
NANSEN_RATE_LIMIT_PROFILER_PER_MINUTE: int = 9
NANSEN_RATE_LIMIT_PROFILER_MIN_INTERVAL: float = 7.0
NANSEN_RATE_LIMIT_PROFILER_STATE_FILE: str = "/tmp/pnl_weighted_rate_profiler.json"
