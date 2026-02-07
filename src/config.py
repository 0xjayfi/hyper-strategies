"""Configuration settings for the trading signal generator.

All settings can be overridden via environment variables or a .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # API Keys
    NANSEN_API_KEY: str = ""

    # Entry Risk
    COPY_DELAY_MINUTES: int = 15
    MAX_PRICE_SLIPPAGE_PERCENT: float = 2.0
    COPY_RATIO: float = 0.5
    MAX_SINGLE_POSITION_USD: float = 50_000
    MAX_TOTAL_OPEN_POSITIONS_USD_RATIO: float = 0.50
    MAX_TOTAL_POSITIONS: int = 5
    MAX_EXPOSURE_PER_TOKEN: float = 0.15

    # Stop System
    STOP_LOSS_PERCENT: float = 5.0
    TRAILING_STOP_PERCENT: float = 8.0
    MAX_POSITION_DURATION_HOURS: int = 72

    # Trade Filtering
    MIN_TRADE_VALUE_USD: dict = {
        "BTC": 50_000,
        "ETH": 25_000,
        "SOL": 10_000,
        "HYPE": 5_000,
        "_default": 5_000,
    }
    MIN_POSITION_WEIGHT: float = 0.10
    ADD_MAX_AGE_HOURS: int = 2

    # Trader Selection
    MIN_TRADES_REQUIRED: int = 50
    TRADER_SCORE_WEIGHTS: dict = {
        "normalized_roi": 0.25,
        "normalized_sharpe": 0.20,
        "normalized_win_rate": 0.15,
        "consistency_score": 0.20,
        "smart_money_bonus": 0.10,
        "risk_management_score": 0.10,
    }
    RECENCY_DECAY_HALFLIFE_DAYS: int = 14

    # Execution / Polling
    POLLING_INTERVAL_TRADES_SEC: int = 60
    POLLING_INTERVAL_ADDRESS_TRADES_SEC: int = 300
    POLLING_INTERVAL_POSITIONS_SEC: int = 900
    POLLING_INTERVAL_LEADERBOARD_SEC: int = 86400

    # Liquidation Handling
    LIQUIDATION_COOLDOWN_DAYS: int = 14

    # Consensus (optional toggle)
    REQUIRE_CONSENSUS: bool = False
    CONSENSUS_MIN_TRADERS: int = 2

    # Profit-Taking Tiers (% unrealized gain from entry; set to None to disable)
    PROFIT_TAKE_TIER_1: float | None = 10.0  # Take 25% off at +10%
    PROFIT_TAKE_TIER_2: float | None = 20.0  # Take 33% off at +20%
    PROFIT_TAKE_TIER_3: float | None = 40.0  # Take 50% off at +40%

    # Paper Trading Mode
    PAPER_MODE: bool = True


# Module-level settings instance
settings = Settings()
