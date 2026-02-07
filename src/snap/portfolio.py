"""Target portfolio computation, risk overlay, and rebalance diff logic.

Implements Algorithms 4.2, 4.3, and 4.4 from the specification:

1. ``calculate_copy_size`` — Per-trader copy sizing with COPY_RATIO.
2. ``compute_target_portfolio`` — Score-weighted aggregation across tracked
   traders' positions into target allocations per (token, side).
3. ``apply_risk_overlay`` — 6-step sequential cap system (per-position,
   per-token, directional, total exposure, position count, leverage).
4. ``compute_rebalance_diff`` — Diff between target allocations and current
   positions, producing a list of rebalance actions (OPEN / CLOSE / ADJUST).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal

from snap.config import (
    COPY_RATIO,
    MAX_EXPOSURE_PER_TOKEN_PCT,
    MAX_LEVERAGE,
    MAX_LONG_EXPOSURE_PCT,
    MAX_SHORT_EXPOSURE_PCT,
    MAX_SINGLE_POSITION_HARD_CAP,
    MAX_SINGLE_POSITION_PCT,
    MAX_TOTAL_EXPOSURE_PCT,
    MAX_TOTAL_POSITIONS,
    REBALANCE_BAND,
)
from snap.database import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TargetAllocation:
    """A single target allocation for a (token, side) pair."""

    token_symbol: str
    side: str  # "Long" or "Short"
    raw_weight: float = 0.0  # before risk overlay (score-weighted USD)
    capped_weight: float = 0.0  # after risk overlay
    target_usd: float = 0.0  # capped_weight (final USD target)
    target_size: float = 0.0  # target_usd / mark_price
    mark_price: float = 0.0  # latest mark price from snapshots


@dataclass
class RebalanceAction:
    """A single action to take during rebalance."""

    token_symbol: str
    side: str
    action: Literal["OPEN", "CLOSE", "INCREASE", "DECREASE"]
    delta_usd: float  # positive = add exposure, negative = reduce
    current_usd: float = 0.0
    target_usd: float = 0.0
    mark_price: float = 0.0


@dataclass
class TraderSnapshot:
    """Lightweight container for a trader's position snapshot data."""

    address: str
    composite_score: float
    account_value: float
    positions: list[dict] = field(default_factory=list)
    # Each position dict has: token_symbol, side, position_value_usd, mark_price


# ---------------------------------------------------------------------------
# 1. Copy Sizing (Agent 1)
# ---------------------------------------------------------------------------


def calculate_copy_size(
    position_value_usd: float,
    trader_account_value: float,
    my_account_value: float,
    copy_ratio: float = COPY_RATIO,
) -> float:
    """Calculate the raw USD copy size for a single trader's position.

    Formula::

        trader_alloc_pct = position_value_usd / trader_account_value
        raw_copy_usd = my_account_value * trader_alloc_pct * copy_ratio

    Parameters
    ----------
    position_value_usd:
        The trader's position value in USD.
    trader_account_value:
        The trader's total account value in USD.
    my_account_value:
        Our account value in USD.
    copy_ratio:
        Fraction of the trader's allocation to copy (default 0.5).

    Returns
    -------
    float
        Raw copy size in USD before any risk caps.
    """
    if trader_account_value <= 0:
        return 0.0
    trader_alloc_pct = position_value_usd / trader_account_value
    return my_account_value * trader_alloc_pct * copy_ratio


# ---------------------------------------------------------------------------
# 2. Target Portfolio Computation (Algorithm 4.2)
# ---------------------------------------------------------------------------


def compute_target_portfolio(
    trader_snapshots: list[TraderSnapshot],
    my_account_value: float,
) -> list[TargetAllocation]:
    """Aggregate tracked traders' positions into score-weighted targets.

    For each unique (token, side) pair across all traders, computes a
    score-weighted target USD amount.  Higher-scoring traders have more
    influence on the index, analogous to a quality-factor-weighted index.

    Parameters
    ----------
    trader_snapshots:
        List of ``TraderSnapshot`` objects, each with composite_score,
        account_value, and positions.
    my_account_value:
        Our account value in USD.

    Returns
    -------
    list[TargetAllocation]
        Raw (pre-risk-overlay) target allocations per (token, side).
    """
    if not trader_snapshots:
        return []

    total_score = sum(t.composite_score for t in trader_snapshots)
    if total_score <= 0:
        return []

    # Accumulate weighted USD per (token, side)
    # Also track the latest mark_price per token
    agg: dict[tuple[str, str], float] = {}
    mark_prices: dict[str, float] = {}

    for trader in trader_snapshots:
        if trader.composite_score <= 0:
            continue
        score_weight = trader.composite_score / total_score

        for pos in trader.positions:
            token = pos["token_symbol"]
            side = pos["side"]
            position_value_usd = pos["position_value_usd"]

            raw_copy = calculate_copy_size(
                position_value_usd=position_value_usd,
                trader_account_value=trader.account_value,
                my_account_value=my_account_value,
            )

            key = (token, side)
            agg[key] = agg.get(key, 0.0) + raw_copy * score_weight

            if pos.get("mark_price") and pos["mark_price"] > 0:
                mark_prices[token] = pos["mark_price"]

    targets: list[TargetAllocation] = []
    for (token, side), weighted_usd in agg.items():
        mp = mark_prices.get(token, 0.0)
        targets.append(
            TargetAllocation(
                token_symbol=token,
                side=side,
                raw_weight=weighted_usd,
                capped_weight=weighted_usd,
                target_usd=weighted_usd,
                target_size=weighted_usd / mp if mp > 0 else 0.0,
                mark_price=mp,
            )
        )

    return targets


# ---------------------------------------------------------------------------
# 3. Risk Overlay (Algorithm 4.3)
# ---------------------------------------------------------------------------


def apply_risk_overlay(
    targets: list[TargetAllocation],
    account_value: float,
) -> list[TargetAllocation]:
    """Apply the 6-step sequential risk overlay to target allocations.

    Steps applied in order:

    1. **Per-position cap**: ``min(account_value * 0.10, 50_000)``
    2. **Per-token cap**: ``0.15 * account_value``
    3. **Directional caps**: long and short each capped at ``0.60 * account_value``
    4. **Total exposure cap**: ``0.50 * account_value``
    5. **Position count**: keep top ``MAX_TOTAL_POSITIONS`` (5) by target_usd
    6. **Leverage cap**: ``MAX_LEVERAGE`` (5x) — metadata only, applied at execution

    Parameters
    ----------
    targets:
        List of ``TargetAllocation`` objects (mutated in place).
    account_value:
        Our account value in USD.

    Returns
    -------
    list[TargetAllocation]
        The same list, with ``capped_weight``, ``target_usd``, and
        ``target_size`` adjusted to respect all constraints.
    """
    if not targets:
        return targets

    # Step 1: Per-position cap
    max_single = min(account_value * MAX_SINGLE_POSITION_PCT, MAX_SINGLE_POSITION_HARD_CAP)
    for t in targets:
        t.target_usd = min(t.target_usd, max_single)

    # Step 2: Per-token cap
    max_per_token = MAX_EXPOSURE_PER_TOKEN_PCT * account_value
    for t in targets:
        t.target_usd = min(t.target_usd, max_per_token)

    # Step 3: Directional caps
    max_long = MAX_LONG_EXPOSURE_PCT * account_value
    max_short = MAX_SHORT_EXPOSURE_PCT * account_value

    total_long = sum(t.target_usd for t in targets if t.side == "Long")
    total_short = sum(t.target_usd for t in targets if t.side == "Short")

    if total_long > max_long:
        scale = max_long / total_long
        for t in targets:
            if t.side == "Long":
                t.target_usd *= scale

    if total_short > max_short:
        scale = max_short / total_short
        for t in targets:
            if t.side == "Short":
                t.target_usd *= scale

    # Step 4: Total exposure cap
    max_total = MAX_TOTAL_EXPOSURE_PCT * account_value
    total_exposure = sum(t.target_usd for t in targets)
    if total_exposure > max_total:
        scale = max_total / total_exposure
        for t in targets:
            t.target_usd *= scale

    # Step 5: Position count — keep top MAX_TOTAL_POSITIONS by target_usd
    targets.sort(key=lambda t: t.target_usd, reverse=True)
    for t in targets[MAX_TOTAL_POSITIONS:]:
        t.target_usd = 0.0

    # Update capped_weight and target_size
    for t in targets:
        t.capped_weight = t.target_usd
        t.target_size = t.target_usd / t.mark_price if t.mark_price > 0 else 0.0

    return targets


# ---------------------------------------------------------------------------
# 4. Rebalance Diff (Algorithm 4.4 steps 1-2)
# ---------------------------------------------------------------------------


def compute_rebalance_diff(
    targets: list[TargetAllocation],
    current_positions: list[dict],
    rebalance_band: float = REBALANCE_BAND,
) -> list[RebalanceAction]:
    """Compute the diff between target allocations and current positions.

    Handles four cases per the specification:

    - **CASE A (OPEN)**: No current position, target > 0.
    - **CASE B (ADJUST)**: Current position same side, target > 0.
      Applies rebalance band: skip if ``|delta| / current < band``.
    - **CASE C (CLOSE + OPEN)**: Current position opposite side → close then open.
    - **CASE D (CLOSE)**: Current position exists but no target.

    Actions are returned in execution priority order:
    1. CLOSE actions first (reduce exposure before adding)
    2. DECREASE actions
    3. INCREASE actions
    4. OPEN actions last

    Parameters
    ----------
    targets:
        Target allocations (after risk overlay). Only entries with
        ``target_usd > 0`` are considered active targets.
    current_positions:
        List of dicts from the ``our_positions`` table, each with at least:
        ``token_symbol``, ``side``, ``position_usd``, ``entry_price``.
    rebalance_band:
        Fractional tolerance before rebalancing (default 0.10 = 10%).

    Returns
    -------
    list[RebalanceAction]
        Ordered list of actions to execute.
    """
    actions: list[RebalanceAction] = []

    # Index current positions by token_symbol
    current_by_token: dict[str, dict] = {}
    for pos in current_positions:
        current_by_token[pos["token_symbol"]] = pos

    # Index active targets by token_symbol
    target_by_token: dict[str, TargetAllocation] = {}
    for t in targets:
        if t.target_usd > 0:
            target_by_token[t.token_symbol] = t

    # Tokens in both targets and current positions, or only in one
    all_tokens = set(current_by_token.keys()) | set(target_by_token.keys())

    for token in all_tokens:
        current = current_by_token.get(token)
        target = target_by_token.get(token)

        if current is None and target is not None:
            # CASE A: No current position, target > 0 → OPEN
            actions.append(
                RebalanceAction(
                    token_symbol=token,
                    side=target.side,
                    action="OPEN",
                    delta_usd=target.target_usd,
                    current_usd=0.0,
                    target_usd=target.target_usd,
                    mark_price=target.mark_price,
                )
            )
        elif current is not None and target is None:
            # CASE D: Current position, no target → CLOSE
            actions.append(
                RebalanceAction(
                    token_symbol=token,
                    side=current["side"],
                    action="CLOSE",
                    delta_usd=-current["position_usd"],
                    current_usd=current["position_usd"],
                    target_usd=0.0,
                    mark_price=current.get("current_price", 0.0),
                )
            )
        elif current is not None and target is not None:
            if current["side"] == target.side:
                # CASE B: Same side → ADJUST (INCREASE or DECREASE)
                delta_usd = target.target_usd - current["position_usd"]

                # Apply rebalance band
                if current["position_usd"] > 0:
                    pct_change = abs(delta_usd) / current["position_usd"]
                    if pct_change < rebalance_band:
                        continue  # Within tolerance, skip

                action_type: Literal["INCREASE", "DECREASE"]
                if delta_usd > 0:
                    action_type = "INCREASE"
                else:
                    action_type = "DECREASE"

                actions.append(
                    RebalanceAction(
                        token_symbol=token,
                        side=target.side,
                        action=action_type,
                        delta_usd=delta_usd,
                        current_usd=current["position_usd"],
                        target_usd=target.target_usd,
                        mark_price=target.mark_price,
                    )
                )
            else:
                # CASE C: Opposite side → CLOSE existing + OPEN new
                actions.append(
                    RebalanceAction(
                        token_symbol=token,
                        side=current["side"],
                        action="CLOSE",
                        delta_usd=-current["position_usd"],
                        current_usd=current["position_usd"],
                        target_usd=0.0,
                        mark_price=current.get("current_price", 0.0),
                    )
                )
                actions.append(
                    RebalanceAction(
                        token_symbol=token,
                        side=target.side,
                        action="OPEN",
                        delta_usd=target.target_usd,
                        current_usd=0.0,
                        target_usd=target.target_usd,
                        mark_price=target.mark_price,
                    )
                )

    # Sort by execution priority: CLOSE > DECREASE > INCREASE > OPEN
    _PRIORITY = {"CLOSE": 0, "DECREASE": 1, "INCREASE": 2, "OPEN": 3}
    actions.sort(key=lambda a: _PRIORITY.get(a.action, 99))

    return actions


# ---------------------------------------------------------------------------
# 5. Database Helpers
# ---------------------------------------------------------------------------


def get_tracked_traders(db_path: str, top_n: int) -> list[dict]:
    """Fetch top N eligible traders by composite score from the database.

    Returns
    -------
    list[dict]
        Each dict has: ``address``, ``composite_score``.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT address, composite_score
               FROM trader_scores
               WHERE is_eligible = 1
               ORDER BY composite_score DESC
               LIMIT ?""",
            (top_n,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_current_positions(db_path: str) -> list[dict]:
    """Fetch all rows from our_positions table.

    Returns
    -------
    list[dict]
        Each dict has all columns from ``our_positions``.
    """
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM our_positions").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def store_target_allocations(
    db_path: str,
    rebalance_id: str,
    targets: list[TargetAllocation],
) -> int:
    """Persist target allocations to the database.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database.
    rebalance_id:
        UUID string for this rebalance cycle.
    targets:
        List of ``TargetAllocation`` objects to store.

    Returns
    -------
    int
        Number of rows inserted.
    """
    conn = get_connection(db_path)
    count = 0
    try:
        with conn:
            for t in targets:
                if t.target_usd <= 0:
                    continue
                conn.execute(
                    """INSERT INTO target_allocations
                       (rebalance_id, token_symbol, side,
                        raw_weight, capped_weight, target_usd, target_size)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        rebalance_id,
                        t.token_symbol,
                        t.side,
                        t.raw_weight,
                        t.capped_weight,
                        t.target_usd,
                        t.target_size,
                    ),
                )
                count += 1
    finally:
        conn.close()

    logger.info(
        "Stored %d target allocations for rebalance_id=%s",
        count,
        rebalance_id,
    )
    return count
