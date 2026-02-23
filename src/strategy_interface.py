"""
Strategy Interfaces for Hyperliquid Copytrading System.

This module provides interfaces for various copytrading strategies that consume
allocation weights and position data from the DataStore.

Phase 9: Strategy Interfaces
- Core allocation retrieval
- Strategy #2: Index Portfolio Rebalancing
- Strategy #3: Consensus Voting
- Strategy #5: Per-Trade Sizing

All position data is dict-based with keys:
- token_symbol: str
- side: "Long" | "Short"
- position_value_usd: float
- entry_price: float
- leverage_value: float
- leverage_type: str
- liquidation_price: float
- unrealized_pnl: float
- account_value: float
"""

from collections import defaultdict
from typing import Dict, List

from src.datastore import DataStore


def get_trader_allocation(trader_id: str, datastore: DataStore) -> float:
    """
    Returns the current allocation weight [0, 1] for a trader.

    Args:
        trader_id: Trader's Hyperliquid address
        datastore: DataStore instance

    Returns:
        Allocation weight for the trader, or 0.0 if not in allocation set
    """
    allocations = datastore.get_latest_allocations()
    return allocations.get(trader_id, 0.0)


def get_all_allocations(datastore: DataStore) -> dict[str, float]:
    """
    Returns all current trader allocations.

    Args:
        datastore: DataStore instance

    Returns:
        Dictionary mapping trader addresses to allocation weights
    """
    return datastore.get_latest_allocations()


def build_index_portfolio(
    allocations: dict[str, float],
    trader_positions: dict[str, list],
    my_account_value: float
) -> dict[tuple[str, str], float]:
    """
    Build target portfolio by weighting each trader's positions by allocation weight.

    Strategy #2: Index Portfolio Rebalancing

    Constructs an aggregated portfolio where each trader's positions are scaled by
    their allocation weight.  Long and short exposures for the same token are kept
    as **separate line items** so that opposing views across traders remain visible.
    The resulting portfolio is normalized to use 50% of the account value as total
    exposure.

    Args:
        allocations: {trader_address: weight} mapping
        trader_positions: {trader_address: [position_dicts]} mapping where each
            position dict has keys: token_symbol, side, position_value_usd
        my_account_value: Total account value in USD

    Returns:
        Dictionary mapping ``(token_symbol, side)`` tuples to target position
        sizes in USD (always positive).

    Example:
        >>> allocations = {"0xabc": 0.6, "0xdef": 0.4}
        >>> positions = {
        ...     "0xabc": [{"token_symbol": "BTC", "side": "Long", "position_value_usd": 1000}],
        ...     "0xdef": [{"token_symbol": "BTC", "side": "Short", "position_value_usd": 500}]
        ... }
        >>> build_index_portfolio(allocations, positions, 10000)
        {("BTC", "Long"): 3000.0, ("BTC", "Short"): 1000.0}
    """
    portfolio: dict[tuple[str, str], float] = defaultdict(float)

    for trader_addr, weight in allocations.items():
        positions = trader_positions.get(trader_addr, [])
        for pos in positions:
            key = (pos["token_symbol"], pos["side"])
            portfolio[key] += pos["position_value_usd"] * weight

    total_exposure = sum(portfolio.values())
    if total_exposure > 0:
        scale = (my_account_value * 0.50) / total_exposure
        portfolio = {k: v * scale for k, v in portfolio.items()}

    return dict(portfolio)


def weighted_consensus(
    token: str,
    allocations: dict[str, float],
    trader_positions: dict[str, list]
) -> dict:
    """
    Compute weighted consensus signal for a specific token.

    Strategy #3: Consensus Voting

    Aggregates positions across all traders for a given token, weighted by their
    allocation weights. Returns a consensus signal based on the ratio of long to
    short exposure.

    Args:
        token: Token symbol (e.g., "BTC", "ETH")
        allocations: {trader_address: weight} mapping
        trader_positions: {trader_address: [position_dicts]} mapping where each
            position dict has keys: token_symbol, side, position_value_usd

    Returns:
        Dictionary with keys:
        - signal: "STRONG_LONG" | "STRONG_SHORT" | "MIXED"
        - long_weight: Total weighted long exposure
        - short_weight: Total weighted short exposure
        - participating_traders: Number of traders holding the token

    Signal rules:
        - STRONG_LONG: long_weight > 2 * short_weight AND >= 3 participants
        - STRONG_SHORT: short_weight > 2 * long_weight AND >= 3 participants
        - MIXED: otherwise

    Example:
        >>> weighted_consensus("BTC", allocations, positions)
        {
            "signal": "STRONG_LONG",
            "long_weight": 12000.0,
            "short_weight": 2000.0,
            "participating_traders": 5
        }
    """
    long_weight = 0.0
    short_weight = 0.0
    participants = 0

    for trader_addr, alloc_weight in allocations.items():
        positions = trader_positions.get(trader_addr, [])
        for pos in positions:
            if pos["token_symbol"] == token:
                participants += 1
                value = abs(pos["position_value_usd"])
                weighted_value = value * alloc_weight
                if pos["side"] == "Long":
                    long_weight += weighted_value
                else:
                    short_weight += weighted_value

    total = long_weight + short_weight
    if total == 0:
        return {
            "signal": "MIXED",
            "long_weight": 0,
            "short_weight": 0,
            "participating_traders": 0
        }

    if long_weight > 2 * short_weight and participants >= 3:
        signal = "STRONG_LONG"
    elif short_weight > 2 * long_weight and participants >= 3:
        signal = "STRONG_SHORT"
    else:
        signal = "MIXED"

    return {
        "signal": signal,
        "long_weight": long_weight,
        "short_weight": short_weight,
        "participating_traders": participants
    }


def size_copied_trade(
    trader_addr: str,
    trade_value_usd: float,
    trader_account_value: float,
    my_account_value: float,
    allocations: dict[str, float]
) -> float:
    """
    Calculate position size for a copied trade.

    Strategy #5: Per-Trade Sizing

    Sizes a copied trade proportionally to:
    1. The trader's allocation weight
    2. The trade's size relative to the trader's account
    3. A copy ratio (0.5) to be more conservative
    4. A maximum single position limit (10% of account)

    Args:
        trader_addr: Trader's Hyperliquid address
        trade_value_usd: Size of the trader's position in USD
        trader_account_value: Total account value of the trader in USD
        my_account_value: Total account value of copier in USD
        allocations: {trader_address: weight} mapping

    Returns:
        Target position size in USD (absolute value, not signed)

    Formula:
        target = my_account_value * (trade_value / trader_account) * weight * COPY_RATIO
        target = min(target, MAX_SINGLE_POSITION)

    Example:
        >>> size_copied_trade(
        ...     "0xabc",
        ...     trade_value_usd=5000,
        ...     trader_account_value=100000,
        ...     my_account_value=10000,
        ...     allocations={"0xabc": 0.5}
        ... )
        125.0  # 10000 * 0.05 * 0.5 * 0.5, capped at 1000 (10% max)
    """
    weight = allocations.get(trader_addr, 0.0)
    if weight == 0:
        return 0.0

    if trader_account_value > 0:
        trader_alloc_pct = trade_value_usd / trader_account_value
    else:
        trader_alloc_pct = 0.0

    COPY_RATIO = 0.5
    target = my_account_value * trader_alloc_pct * weight * COPY_RATIO

    MAX_SINGLE_POSITION = my_account_value * 0.10
    target = min(target, MAX_SINGLE_POSITION)

    return target
