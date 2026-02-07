from src.risk.types import MarginType

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

# --- Minimum Position ---
MIN_POSITION_USD: float = 10.0  # Below this is dust
