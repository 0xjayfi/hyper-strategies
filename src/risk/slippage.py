from src.risk.constants import SLIPPAGE_MAP, SLIPPAGE_DEFAULT


def get_slippage_assumption(token: str) -> float:
    """
    Returns expected slippage percentage for asset class.

    Uses Agent 4 slippage assumptions:
      BTC: 0.05%, ETH: 0.10%, SOL: 0.15%, HYPE: 0.30%
      Default: 0.20% for unlisted tokens
    """
    return SLIPPAGE_MAP.get(token, SLIPPAGE_DEFAULT)
