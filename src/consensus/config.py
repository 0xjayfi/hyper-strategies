"""Strategy configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class StrategyConfig(BaseSettings):
    """All strategy constants, overridable via CONSENSUS_* env vars."""

    # --- API Keys ---
    NANSEN_API_KEY: str = ""
    HL_PRIVATE_KEY: str = ""
    TYPEFULLY_API_KEY: str = ""

    # --- Watchlist ---
    WATCHLIST_SIZE: int = 15
    MIN_TRADES_FOR_SCORING: int = 50
    SCORING_LOOKBACK_DAYS: int = 90
    LEADERBOARD_REFRESH_INTERVAL: str = "daily"

    # --- Consensus ---
    MIN_CONSENSUS_TRADERS: int = 3
    VOLUME_DOMINANCE_RATIO: float = 2.0
    FRESHNESS_HALF_LIFE_HOURS: float = 4.0
    MIN_POSITION_WEIGHT: float = 0.10

    # --- Size Thresholds (USD) ---
    SIZE_THRESHOLDS: dict = Field(default={
        "BTC": 50_000,
        "ETH": 25_000,
        "SOL": 10_000,
        "HYPE": 5_000,
        "_default": 5_000,
    })

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
    COPY_RATIO: float = 0.5

    # --- Polling Intervals (seconds) ---
    POLL_TRADES_INTERVAL: int = 300
    POLL_POSITIONS_INTERVAL: int = 900

    # --- Cluster Detection ---
    COPY_WINDOW_MINUTES: int = 10
    COPY_THRESHOLD: float = 0.40

    model_config = {
        "env_prefix": "CONSENSUS_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
