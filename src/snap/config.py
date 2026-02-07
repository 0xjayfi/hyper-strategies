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
MAX_POSITION_DURATION_HOURS: int = 72

# ===========================================================================
# Trader Selection (Agent 2)
# ===========================================================================
MIN_ROI_30D: float = 15.0
MIN_ACCOUNT_VALUE: float = 50_000
MIN_TRADE_COUNT: int = 50
IDEAL_TRADE_COUNT: int = 96
WIN_RATE_MIN: float = 0.35
WIN_RATE_MAX: float = 0.85
MIN_PROFIT_FACTOR: float = 1.5
TREND_TRADER_MIN_PF: float = 2.5
TREND_TRADER_MAX_WR: float = 0.40
TOP_N_TRADERS: int = 15

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
SLIPPAGE_BPS: dict[str, int] = {
    "BTC": 3,
    "ETH": 5,
    "SOL": 10,
    "HYPE": 20,
    "DEFAULT": 15,
}
