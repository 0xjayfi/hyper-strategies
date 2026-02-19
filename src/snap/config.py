"""Configuration constants for the Snap copytrading system.

All constants from Section 5 of the specification. Values are loaded at import
time.  The NANSEN_API_KEY is read from the environment (or a .env file via
python-dotenv) so that secrets never appear in source control.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from the project root (two levels up from this file, or cwd)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_FILE)

# ---------------------------------------------------------------------------
# API Key
# ---------------------------------------------------------------------------
NANSEN_API_KEY: str = os.environ.get("NANSEN_API_KEY", "")

# ---------------------------------------------------------------------------
# Nansen API base URL
# ---------------------------------------------------------------------------
NANSEN_BASE_URL: str = "https://api.nansen.ai/api/v1"

# ===========================================================================
# Risk Management (Agent 1)
# ===========================================================================
COPY_RATIO: float = 0.5
MAX_SINGLE_POSITION_PCT: float = 0.10
MAX_SINGLE_POSITION_HARD_CAP: float = 50_000
MAX_TOTAL_EXPOSURE_PCT: float = 0.50
MAX_POSITIONS_PER_TOKEN: int = 1
MAX_TOTAL_POSITIONS: int = 5
MAX_EXPOSURE_PER_TOKEN_PCT: float = 0.15
MAX_LONG_EXPOSURE_PCT: float = 0.60
MAX_SHORT_EXPOSURE_PCT: float = 0.60
MAX_LEVERAGE: int = 5
MARGIN_TYPE: str = "isolated"
STOP_LOSS_PERCENT: float = 5.0
TRAILING_STOP_PERCENT: float = 8.0
MAX_POSITION_DURATION_HOURS: int = 96

# ===========================================================================
# Trader Selection (Agent 2)
# ===========================================================================
# Percentile cutoff for dynamic thresholds (0.0 to 1.0)
# 0.5 = median (top 50% pass each gate), 0.75 = top 25% pass
FILTER_PERCENTILE: float = 0.50

# Hard floor for the leaderboard API filter (avoids fetching every trader)
MIN_ACCOUNT_VALUE: float = 25_000

# Safety bounds (not percentile-based — these are absolute limits)
WIN_RATE_MIN: float = 0.30
WIN_RATE_MAX: float = 0.95
TREND_TRADER_MIN_PF: float = 2.5
TREND_TRADER_MAX_WR: float = 0.40

TOP_N_TRADERS: int = 15

# Trade cache TTL (hours) — skip API fetch if cached data is fresher
TRADE_CACHE_TTL_HOURS: int = 48

# ===========================================================================
# Scoring Weights
# ===========================================================================
W_ROI: float = 0.25
W_SHARPE: float = 0.20
W_WIN_RATE: float = 0.15
W_CONSISTENCY: float = 0.20
W_SMART_MONEY: float = 0.10
W_RISK_MGMT: float = 0.10

# ===========================================================================
# Rebalance
# ===========================================================================
REBALANCE_INTERVAL_HOURS: int = 4
REBALANCE_BAND: float = 0.10  # 10% tolerance before rebalancing a position

# ===========================================================================
# Polling Cadences
# ===========================================================================
POLL_POSITIONS_MINUTES: int = 15
POLL_TRADES_MINUTES: int = 5
POLL_LEADERBOARD_HOURS: int = 24
MONITOR_INTERVAL_SECONDS: int = 60

# ===========================================================================
# Slippage allowances (basis points per token)
# ===========================================================================
# ===========================================================================
# Nansen API Rate Limits (per endpoint type)
# ===========================================================================
# Leaderboard endpoint — slow server responses (~1-2s/page), no 429 risk
NANSEN_RATE_LIMIT_LEADERBOARD_PER_SECOND: int = 20
NANSEN_RATE_LIMIT_LEADERBOARD_PER_MINUTE: int = 300
NANSEN_RATE_LIMIT_LEADERBOARD_MIN_INTERVAL: float = 0.0

# Profiler endpoints (perp-trades, perp-positions) — fast responses, 429 risk
NANSEN_RATE_LIMIT_PROFILER_PER_SECOND: int = 1
NANSEN_RATE_LIMIT_PROFILER_PER_MINUTE: int = 9
NANSEN_RATE_LIMIT_PROFILER_MIN_INTERVAL: float = 7.0

# ===========================================================================
# Slippage allowances (basis points per token)
# ===========================================================================
SLIPPAGE_BPS: dict[str, int] = {
    "BTC": 3,
    "ETH": 5,
    "SOL": 10,
    "HYPE": 20,
    "DEFAULT": 15,
}

# ===========================================================================
# Observability & Alerts (Phase 7)
# ===========================================================================
DRAWDOWN_WARNING_PCT: float = 8.0
DRAWDOWN_CRITICAL_PCT: float = 15.0
EXPOSURE_BREACH_PCT: float = 55.0  # warn above 55% of account
REBALANCE_STALE_HOURS: float = 6.0
DIVERGENCE_WARNING_PCT: float = 25.0
FILL_RATE_WARNING_PCT: float = 95.0
API_CONSECUTIVE_FAILURES: int = 3
HEALTH_CHECK_FILE: str = os.environ.get("SNAP_HEALTH_FILE", "/tmp/snap_health.json")

# ===========================================================================
# Paper Trade / Live Mode (Phase 9)
# ===========================================================================
PAPER_TRADE: bool = os.environ.get("SNAP_PAPER_TRADE", "true").lower() in ("true", "1", "yes")
DB_PATH: str = os.environ.get("SNAP_DB_PATH", "snap.db")
DATA_DB_PATH: str = os.environ.get("SNAP_DATA_DB_PATH", "")
STRATEGY_DB_PATH: str = os.environ.get("SNAP_STRATEGY_DB_PATH", "")
ACCOUNT_VALUE: float = float(os.environ.get("SNAP_ACCOUNT_VALUE", "10000"))
LOG_FILE: str | None = os.environ.get("SNAP_LOG_FILE")
DASHBOARD_FILE: str | None = os.environ.get("SNAP_DASHBOARD_FILE")
