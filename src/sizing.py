from __future__ import annotations

from src.config import settings


def compute_copy_size(
    trader_position_value: float,
    trader_account_value: float,
    our_account_value: float,
    trader_roi_7d: float,
    leverage: float | None,
) -> float:
    """
    Calculate position size for copying a trader's position.

    Combines 4 factors:
    1. Base size from trader allocation
    2. Track-record weighting (ROI tiers)
    3. Leverage penalty
    4. Apply caps

    Args:
        trader_position_value: USD value of trader's position
        trader_account_value: Total USD value of trader's account
        our_account_value: Total USD value of our account
        trader_roi_7d: Trader's 7-day ROI percentage
        leverage: Trader's leverage (None if not leveraged)

    Returns:
        Position size in USD (0 if below minimum)
    """
    # 1. Base size from trader allocation
    if trader_account_value > 0:
        trader_alloc_pct = trader_position_value / trader_account_value
    else:
        trader_alloc_pct = 0.05  # fallback: assume 5%
    base_size = our_account_value * trader_alloc_pct * settings.COPY_RATIO

    # 2. Track-record weighting (ROI tiers)
    if trader_roi_7d > 10:
        roi_multiplier = 1.00   # 100% — hot trader
    elif trader_roi_7d >= 0:
        roi_multiplier = 0.75   # 75% — lukewarm
    else:
        roi_multiplier = 0.50   # 50% — cold
    size = base_size * roi_multiplier

    # 3. Leverage penalty (only if leverage is not None and > 1)
    if leverage is not None and leverage > 1:
        # Anchor points for interpolation
        leverage_penalty_table = {
            1: 1.00,
            2: 0.90,
            3: 0.80,
            5: 0.60,
            10: 0.40,
            20: 0.20,
        }

        if leverage > 20:
            penalty = 0.10
        elif leverage == 20:
            penalty = 0.20
        elif leverage in leverage_penalty_table:
            # Exact match
            penalty = leverage_penalty_table[leverage]
        else:
            # Linear interpolation between bracketing keys
            sorted_keys = sorted(leverage_penalty_table.keys())
            # Find bracketing keys
            lower_key = None
            upper_key = None
            for i in range(len(sorted_keys) - 1):
                if sorted_keys[i] < leverage < sorted_keys[i + 1]:
                    lower_key = sorted_keys[i]
                    upper_key = sorted_keys[i + 1]
                    break

            if lower_key is not None and upper_key is not None:
                # Interpolate
                lower_penalty = leverage_penalty_table[lower_key]
                upper_penalty = leverage_penalty_table[upper_key]
                t = (leverage - lower_key) / (upper_key - lower_key)
                penalty = lower_penalty + t * (upper_penalty - lower_penalty)
            else:
                # Should not happen, but fallback
                penalty = 1.00

        size = size * penalty

    # 4. Apply caps
    max_single = min(our_account_value * 0.10, settings.MAX_SINGLE_POSITION_USD)
    size = min(size, max_single)

    # Floor at $100 to avoid dust orders
    if size < 100:
        return 0

    return round(size, 2)


def get_leverage_from_positions(positions_response: dict, token: str) -> float | None:
    """
    Extract leverage_value from the profiler/perp-positions response for the given token.

    Args:
        positions_response: API response dict from profiler/perp-positions endpoint
        token: Token symbol to search for (e.g., "BTC")

    Returns:
        Leverage value as float, or None if not found or not available
    """
    for ap in positions_response.get("data", {}).get("asset_positions", []):
        pos = ap.get("position", {})
        if pos.get("token_symbol") == token:
            lev = pos.get("leverage_value")
            return float(lev) if lev is not None else None
    return None
