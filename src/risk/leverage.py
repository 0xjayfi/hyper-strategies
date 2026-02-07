from src.risk.constants import MAX_ALLOWED_LEVERAGE


def infer_leverage(position_value_usd: float, margin_used_usd: float) -> float:
    """
    Infer effective leverage from notional / margin.

    Nansen Address Perp Positions returns:
      - position_value_usd (notional)
      - margin_used_usd
      - leverage_value (explicit, but may not always be available upstream)

    Fallback: if margin_used_usd is 0 or data missing, return MAX_ALLOWED_LEVERAGE
    as conservative default.
    """
    if margin_used_usd <= 0 or position_value_usd <= 0:
        return MAX_ALLOWED_LEVERAGE

    inferred = position_value_usd / margin_used_usd
    return round(inferred, 1)
