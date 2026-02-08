"""Entry sizing with position and portfolio-level caps."""

from __future__ import annotations

from consensus.config import StrategyConfig
from consensus.models import OurPosition, TokenConsensus


def calculate_entry_size(
    token: str,
    side: str,
    consensus: TokenConsensus,
    account_value: float,
    existing_positions: list[OurPosition],
    config: StrategyConfig,
) -> float | None:
    """Compute position size in USD, or None if caps prevent entry.

    Sizing formula:
    1. Base = account_value * 5% * COPY_RATIO, scaled by consensus strength.
    2. Apply single-position absolute cap.
    3. Apply portfolio-level caps (total exposure, position count, token
       exposure, directional exposure).
    4. Return None if result is below $100 dust threshold.
    """
    # Position count cap (checked first — no point computing size)
    if len(existing_positions) >= config.MAX_TOTAL_POSITIONS:
        return None

    # Step 1: Base size scaled by consensus strength
    base_size = account_value * 0.05 * config.COPY_RATIO

    cluster_count = (
        consensus.long_cluster_count if side == "Long"
        else consensus.short_cluster_count
    )
    strength_mult = min(2.0, cluster_count / config.MIN_CONSENSUS_TRADERS)
    base_size *= strength_mult

    # Step 2: Single-position absolute cap
    max_single = min(
        account_value * config.MAX_SINGLE_POSITION_RATIO,
        config.MAX_SINGLE_POSITION_HARD_CAP,
    )
    size = min(base_size, max_single)

    # Step 3: Portfolio-level caps

    # Total exposure cap
    total_exposure = sum(p.size_usd for p in existing_positions)
    max_total = account_value * config.MAX_TOTAL_EXPOSURE_RATIO
    if total_exposure + size > max_total:
        size = max(0.0, max_total - total_exposure)

    # Token exposure cap
    token_exposure = sum(
        p.size_usd for p in existing_positions if p.token_symbol == token
    )
    max_token = account_value * config.MAX_EXPOSURE_PER_TOKEN
    if token_exposure + size > max_token:
        size = max(0.0, max_token - token_exposure)

    # Directional exposure cap
    if side == "Long":
        dir_exposure = sum(p.size_usd for p in existing_positions if p.side == "Long")
        max_dir = account_value * config.MAX_LONG_EXPOSURE
    else:
        dir_exposure = sum(p.size_usd for p in existing_positions if p.side == "Short")
        max_dir = account_value * config.MAX_SHORT_EXPOSURE

    if dir_exposure + size > max_dir:
        size = max(0.0, max_dir - dir_exposure)

    # Dust prevention — $100 minimum
    return size if size >= 100 else None


def select_leverage(
    consensus_traders_avg_leverage: float,
    config: StrategyConfig,
) -> int:
    """Cap leverage at MAX_ALLOWED_LEVERAGE, minimum 1."""
    return max(1, min(int(consensus_traders_avg_leverage), config.MAX_ALLOWED_LEVERAGE))


def select_order_type(
    action: str,
    signal_age_seconds: float,
    current_price: float,
    trader_entry_price: float,
    token: str,
) -> tuple[str, float | None]:
    """Select order type and optional limit price.

    Returns ``(order_type, limit_price_or_None)`` where order_type is one of
    ``"market"``, ``"limit"``, or ``"skip"``.
    """
    age_min = signal_age_seconds / 60

    # Exits are always market orders
    if action == "Close":
        return ("market", None)

    if age_min < 2:
        # Fresh signal — market order
        return ("market", None)
    elif age_min < 10:
        # Check price drift from trader's entry
        drift_pct = (
            abs(current_price - trader_entry_price) / trader_entry_price * 100
        )
        if drift_pct < 0.3:
            return ("limit", current_price)
        else:
            return ("skip", None)
    else:
        return ("skip", None)
