"""Backtesting engine for the Snap copytrading system.

Simulates the full trading loop over historical data with a lightweight
execution simulator.  Computes performance metrics (Sharpe, Sortino,
max-drawdown, etc.) and can emit a Markdown report.

This module is self-contained and does NOT depend on the live Execution Engine
(Phase 4).
"""

from __future__ import annotations

import logging
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Literal

from snap.config import (
    MAX_POSITION_DURATION_HOURS,
    SLIPPAGE_BPS,
    STOP_LOSS_PERCENT,
    TRAILING_STOP_PERCENT,
)
from snap.portfolio import RebalanceAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Execution Simulator
# ---------------------------------------------------------------------------


@dataclass
class SimulatedFill:
    """Result of a simulated order execution."""

    token_symbol: str
    side: str
    size: float
    fill_price: float
    slippage_bps: float
    fee_usd: float
    is_filled: bool  # False for missed fills


class ExecutionSimulator:
    """Simulates order fills with slippage, partial fills, and misses.

    Parameters
    ----------
    slippage_bps:
        Per-token slippage in basis points.  Falls back to ``SLIPPAGE_BPS``
        from config when *None*.
    miss_rate:
        Probability that a LIMIT order is missed entirely (default 5 %).
    partial_rate:
        Probability that an order is only partially filled (default 10 %).
    rng_seed:
        Seed for the internal ``random.Random`` instance so that results are
        reproducible.
    """

    _FEE_RATE: float = 0.0005  # 0.05 % taker fee

    def __init__(
        self,
        slippage_bps: dict[str, int] | None = None,
        miss_rate: float = 0.05,
        partial_rate: float = 0.10,
        rng_seed: int | None = None,
    ) -> None:
        self.slippage_bps = slippage_bps if slippage_bps is not None else dict(SLIPPAGE_BPS)
        self.miss_rate = miss_rate
        self.partial_rate = partial_rate
        self.rng = random.Random(rng_seed)

    # ------------------------------------------------------------------

    def _get_base_bps(self, token: str) -> int:
        return self.slippage_bps.get(token, self.slippage_bps.get("DEFAULT", 15))

    # ------------------------------------------------------------------

    def simulate_fill(self, action: RebalanceAction) -> SimulatedFill:
        """Simulate execution of a single ``RebalanceAction``.

        Rules
        -----
        * **MARKET orders** (CLOSE actions) always fill --- miss rate does not
          apply.
        * **LIMIT orders** (OPEN / INCREASE / DECREASE) may miss with
          probability ``miss_rate``.
        * Partial fills happen with probability ``partial_rate``; the filled
          portion is uniformly drawn from [50 %, 90 %] of the intended size.
        * Slippage is base_bps + uniform noise in [-50 %, +50 %] of base_bps.
        * Fee is ``0.05 %`` of the filled notional value.
        """

        mark = action.mark_price
        token = action.token_symbol
        is_close = action.action == "CLOSE"

        # --- Miss check (LIMIT orders only) ---
        if not is_close and self.rng.random() < self.miss_rate:
            return SimulatedFill(
                token_symbol=token,
                side=action.side,
                size=0.0,
                fill_price=mark,
                slippage_bps=0.0,
                fee_usd=0.0,
                is_filled=False,
            )

        # --- Slippage ---
        base_bps = self._get_base_bps(token)
        noise = self.rng.uniform(-0.5, 0.5) * base_bps
        actual_bps = base_bps + noise

        # Direction: opening Long or closing Short => buy => adverse slip up
        #            opening Short or closing Long => sell => adverse slip down
        if is_close:
            # Closing: reverse slippage direction relative to the position side
            if action.side == "Long":
                # Selling to close long: slip down (worse for seller)
                fill_price = mark * (1 - actual_bps / 10_000)
            else:
                # Buying to close short: slip up (worse for buyer)
                fill_price = mark * (1 + actual_bps / 10_000)
        else:
            # Opening / adjusting
            if action.side == "Long":
                fill_price = mark * (1 + actual_bps / 10_000)
            else:
                fill_price = mark * (1 - actual_bps / 10_000)

        # --- Intended size ---
        intended_size = abs(action.delta_usd) / mark if mark > 0 else 0.0

        # --- Partial fill ---
        if self.rng.random() < self.partial_rate:
            fill_fraction = self.rng.uniform(0.5, 0.9)
            filled_size = intended_size * fill_fraction
        else:
            filled_size = intended_size

        # --- Fee ---
        fill_value = filled_size * fill_price
        fee = fill_value * self._FEE_RATE

        return SimulatedFill(
            token_symbol=token,
            side=action.side,
            size=filled_size,
            fill_price=fill_price,
            slippage_bps=actual_bps,
            fee_usd=fee,
            is_filled=True,
        )


# ---------------------------------------------------------------------------
# 2. Performance Metrics
# ---------------------------------------------------------------------------


@dataclass
class BacktestMetrics:
    """Aggregate metrics produced by the backtesting engine."""

    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    avg_hold_hours: float = 0.0
    total_positions: int = 0
    total_fees_usd: float = 0.0
    total_slippage_cost_usd: float = 0.0
    stop_loss_exits: int = 0
    trailing_stop_exits: int = 0
    time_stop_exits: int = 0
    rebalance_exits: int = 0


def compute_backtest_metrics(
    equity_curve: list[float],
    closed_positions: list[dict],
    days: int,
) -> BacktestMetrics:
    """Compute aggregate performance metrics from a backtest run.

    Parameters
    ----------
    equity_curve:
        Daily equity values (length >= 1).  An empty list produces zero
        metrics.
    closed_positions:
        Each dict must have: ``pnl``, ``hold_hours``, ``exit_reason``,
        ``fees``, ``slippage_cost``.
    days:
        Calendar days the backtest spans.

    Returns
    -------
    BacktestMetrics
    """

    if not equity_curve or len(equity_curve) < 1:
        return BacktestMetrics()

    # --- Total & annualized return ---
    if equity_curve[0] == 0:
        total_return = 0.0
    else:
        total_return = (equity_curve[-1] / equity_curve[0] - 1) * 100

    if days > 0 and total_return > -100:
        annualized = ((1 + total_return / 100) ** (365 / days) - 1) * 100
    else:
        annualized = 0.0

    # --- Max drawdown & duration ---
    max_dd_pct = 0.0
    max_dd_duration = 0.0
    peak = equity_curve[0]
    dd_start_idx = 0
    current_dd_days = 0

    for i, equity in enumerate(equity_curve):
        if equity >= peak:
            peak = equity
            dd_start_idx = i
            current_dd_days = 0
        else:
            dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd_pct:
                max_dd_pct = dd
            current_dd_days = i - dd_start_idx
            if current_dd_days > max_dd_duration:
                max_dd_duration = current_dd_days

    # --- Daily returns ---
    daily_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0:
            daily_returns.append(equity_curve[i] / equity_curve[i - 1] - 1)
        else:
            daily_returns.append(0.0)

    # --- Sharpe ratio ---
    sharpe = 0.0
    if len(daily_returns) >= 2:
        mean_r = statistics.mean(daily_returns)
        std_r = statistics.stdev(daily_returns)
        if std_r > 0:
            sharpe = mean_r / std_r * math.sqrt(365)

    # --- Sortino ratio ---
    sortino = 0.0
    if len(daily_returns) >= 2:
        mean_r = statistics.mean(daily_returns)
        negative_returns = [r for r in daily_returns if r < 0]
        if len(negative_returns) >= 2:
            downside_std = statistics.stdev(negative_returns)
            if downside_std > 0:
                sortino = mean_r / downside_std * math.sqrt(365)
        # If no negative returns or only one, sortino stays 0

    # --- Position-level stats ---
    total_positions = len(closed_positions)
    winners = sum(1 for p in closed_positions if p["pnl"] > 0)
    win_rate = winners / total_positions if total_positions > 0 else 0.0

    hold_hours = [p["hold_hours"] for p in closed_positions]
    avg_hold = statistics.mean(hold_hours) if hold_hours else 0.0

    total_fees = sum(p.get("fees", 0.0) for p in closed_positions)
    total_slippage = sum(p.get("slippage_cost", 0.0) for p in closed_positions)

    stop_loss_exits = sum(1 for p in closed_positions if p.get("exit_reason") == "stop_loss")
    trailing_stop_exits = sum(
        1 for p in closed_positions if p.get("exit_reason") == "trailing_stop"
    )
    time_stop_exits = sum(1 for p in closed_positions if p.get("exit_reason") == "time_stop")
    rebalance_exits = sum(1 for p in closed_positions if p.get("exit_reason") == "rebalance")

    return BacktestMetrics(
        total_return_pct=total_return,
        annualized_return_pct=annualized,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_days=max_dd_duration,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        win_rate=win_rate,
        avg_hold_hours=avg_hold,
        total_positions=total_positions,
        total_fees_usd=total_fees,
        total_slippage_cost_usd=total_slippage,
        stop_loss_exits=stop_loss_exits,
        trailing_stop_exits=trailing_stop_exits,
        time_stop_exits=time_stop_exits,
        rebalance_exits=rebalance_exits,
    )


# ---------------------------------------------------------------------------
# 3. Simulation Helpers  (Stop-loss / Trailing / Time)
# ---------------------------------------------------------------------------


@dataclass
class SimPosition:
    """A position held during backtest simulation."""

    token_symbol: str
    side: str  # "Long" or "Short"
    size: float
    entry_price: float
    position_usd: float
    stop_loss_price: float
    trailing_stop_price: float
    trailing_high: float  # for Longs: highest price seen; for Shorts: lowest
    opened_at: int  # simulation step (hour index)
    max_close_step: int  # opened_at + MAX_POSITION_DURATION_HOURS


def make_sim_position(
    token_symbol: str,
    side: str,
    size: float,
    entry_price: float,
    opened_at: int,
) -> SimPosition:
    """Factory that computes derived stop prices from entry price.

    Parameters
    ----------
    token_symbol:
        Token symbol (e.g. ``"BTC"``).
    side:
        ``"Long"`` or ``"Short"``.
    size:
        Position size in token units.
    entry_price:
        Average entry price.
    opened_at:
        Simulation step (hour index) when the position was opened.

    Returns
    -------
    SimPosition
    """
    position_usd = abs(size * entry_price)

    if side == "Long":
        stop_loss = entry_price * (1 - STOP_LOSS_PERCENT / 100)
        trailing_stop = entry_price * (1 - TRAILING_STOP_PERCENT / 100)
        trailing_high = entry_price
    else:
        stop_loss = entry_price * (1 + STOP_LOSS_PERCENT / 100)
        trailing_stop = entry_price * (1 + TRAILING_STOP_PERCENT / 100)
        trailing_high = entry_price  # actually "trailing low" for shorts

    return SimPosition(
        token_symbol=token_symbol,
        side=side,
        size=size,
        entry_price=entry_price,
        position_usd=position_usd,
        stop_loss_price=stop_loss,
        trailing_stop_price=trailing_stop,
        trailing_high=trailing_high,
        opened_at=opened_at,
        max_close_step=opened_at + MAX_POSITION_DURATION_HOURS,
    )


def check_stop_loss(position: SimPosition, current_price: float) -> bool:
    """Check whether a fixed stop-loss has been triggered.

    Long:  triggered when ``current_price <= stop_loss_price``.
    Short: triggered when ``current_price >= stop_loss_price``.
    """
    if position.side == "Long":
        return current_price <= position.stop_loss_price
    else:
        return current_price >= position.stop_loss_price


def check_trailing_stop(
    position: SimPosition, current_price: float
) -> tuple[bool, SimPosition]:
    """Update trailing high/low and check whether the trailing stop triggers.

    For Longs the ``trailing_high`` ratchets upward and the trailing stop
    price is ``trailing_high * (1 - TRAILING_STOP_PERCENT / 100)``.

    For Shorts the ``trailing_high`` (really trailing_low) ratchets downward
    and the trailing stop price is ``trailing_high * (1 + TRAILING_STOP_PERCENT / 100)``.

    Returns
    -------
    tuple[bool, SimPosition]
        ``(triggered, updated_position)``
    """
    if position.side == "Long":
        if current_price > position.trailing_high:
            position.trailing_high = current_price
        position.trailing_stop_price = position.trailing_high * (
            1 - TRAILING_STOP_PERCENT / 100
        )
        triggered = current_price <= position.trailing_stop_price
    else:
        if current_price < position.trailing_high:
            position.trailing_high = current_price
        position.trailing_stop_price = position.trailing_high * (
            1 + TRAILING_STOP_PERCENT / 100
        )
        triggered = current_price >= position.trailing_stop_price

    return triggered, position


def check_time_stop(position: SimPosition, current_step: int) -> bool:
    """Return *True* if ``current_step >= max_close_step``."""
    return current_step >= position.max_close_step


# ---------------------------------------------------------------------------
# 4. Report Generation
# ---------------------------------------------------------------------------


def generate_backtest_report(
    metrics: BacktestMetrics,
    output_path: str | None = None,
) -> str:
    """Generate a Markdown-formatted backtest report.

    Parameters
    ----------
    metrics:
        Computed backtest metrics.
    output_path:
        If provided, write the report to this file path.

    Returns
    -------
    str
        The Markdown report string.
    """
    lines = [
        "# Backtest Report",
        "",
        "## Returns",
        f"- **Total Return:** {metrics.total_return_pct:.2f}%",
        f"- **Annualized Return:** {metrics.annualized_return_pct:.2f}%",
        "",
        "## Risk",
        f"- **Max Drawdown:** {metrics.max_drawdown_pct:.2f}%",
        f"- **Max Drawdown Duration:** {metrics.max_drawdown_duration_days:.1f} days",
        f"- **Sharpe Ratio:** {metrics.sharpe_ratio:.3f}",
        f"- **Sortino Ratio:** {metrics.sortino_ratio:.3f}",
        "",
        "## Positions",
        f"- **Total Positions:** {metrics.total_positions}",
        f"- **Win Rate:** {metrics.win_rate:.2%}",
        f"- **Avg Hold Time:** {metrics.avg_hold_hours:.1f} hours",
        "",
        "## Costs",
        f"- **Total Fees:** ${metrics.total_fees_usd:,.2f}",
        f"- **Total Slippage Cost:** ${metrics.total_slippage_cost_usd:,.2f}",
        "",
        "## Exit Reasons",
        f"- **Stop-Loss:** {metrics.stop_loss_exits}",
        f"- **Trailing Stop:** {metrics.trailing_stop_exits}",
        f"- **Time Stop:** {metrics.time_stop_exits}",
        f"- **Rebalance:** {metrics.rebalance_exits}",
        "",
    ]

    report = "\n".join(lines)

    if output_path is not None:
        with open(output_path, "w") as fh:
            fh.write(report)
        logger.info("Backtest report written to %s", output_path)

    return report
