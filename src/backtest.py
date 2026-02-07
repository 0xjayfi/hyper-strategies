"""Backtesting Framework (Phase 10)

Simulates the PnL-Weighted Dynamic Allocation strategy on historical trade data.
Rebalances at regular intervals, computes metrics/scores/allocations for each period,
and tracks portfolio value changes based on weighted trader PnL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from src.models import Trade, TradeMetrics
from src.metrics import compute_trade_metrics
from src.scoring import compute_trader_score
from src.filters import apply_anti_luck_filter
from src.allocation import compute_allocations, RiskConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BacktestResult dataclass
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """Backtesting results with timeline and summary statistics."""

    timeline: list[dict]  # [{date, portfolio_value, turnover, num_traders, allocations}]
    total_return: float
    max_drawdown: float
    avg_turnover: float
    sharpe: float


# ---------------------------------------------------------------------------
# Helper: date_range
# ---------------------------------------------------------------------------


def date_range(start_date: str, end_date: str, step_days: int) -> list[str]:
    """Generate list of YYYY-MM-DD strings from start to end.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        step_days: Number of days between each date

    Returns:
        List of date strings in YYYY-MM-DD format
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=step_days)

    return dates


# ---------------------------------------------------------------------------
# Helper: compute_max_drawdown
# ---------------------------------------------------------------------------


def compute_max_drawdown(timeline: list[dict]) -> float:
    """Max peak-to-trough decline from timeline entries with 'portfolio_value'.

    Args:
        timeline: List of dicts with 'portfolio_value' key

    Returns:
        Maximum drawdown as a decimal (e.g., 0.20 for 20% drawdown)
    """
    if not timeline:
        return 0.0

    values = [entry["portfolio_value"] for entry in timeline]
    peak = values[0]
    max_dd = 0.0

    for value in values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, drawdown)

    return max_dd


# ---------------------------------------------------------------------------
# Helper: compute_portfolio_sharpe
# ---------------------------------------------------------------------------


def compute_portfolio_sharpe(timeline: list[dict]) -> float:
    """Annualized Sharpe from daily portfolio value changes.

    Args:
        timeline: List of dicts with 'portfolio_value' key

    Returns:
        Annualized Sharpe ratio (assuming 0% risk-free rate)
    """
    if len(timeline) < 2:
        return 0.0

    values = [entry["portfolio_value"] for entry in timeline]
    returns = []

    for i in range(1, len(values)):
        if values[i - 1] > 0:
            daily_return = (values[i] - values[i - 1]) / values[i - 1]
            returns.append(daily_return)

    if not returns:
        return 0.0

    avg_return = float(np.mean(returns))
    std_return = float(np.std(returns, ddof=1))

    if std_return == 0:
        return 0.0

    # Annualize: multiply mean by sqrt(365), std by sqrt(365)
    sharpe = (avg_return / std_return) * np.sqrt(365)

    return float(sharpe)


# ---------------------------------------------------------------------------
# Helper: filter_trades_by_window
# ---------------------------------------------------------------------------


def filter_trades_by_window(
    trades: list[Trade], end_date: str, window_days: int
) -> list[Trade]:
    """Filter trades to those within [end_date - window_days, end_date].

    Args:
        trades: List of Trade objects
        end_date: End date in YYYY-MM-DD format
        window_days: Number of days in the lookback window

    Returns:
        Filtered list of trades within the window
    """
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=window_days)

    filtered = []
    for t in trades:
        # Parse ISO timestamp (e.g., "2026-01-15T12:00:00")
        try:
            trade_dt = datetime.fromisoformat(t.timestamp.replace("Z", "+00:00"))
            # Remove timezone info for comparison if present
            if trade_dt.tzinfo is not None:
                trade_dt = trade_dt.replace(tzinfo=None)

            if start_dt <= trade_dt <= end_dt:
                filtered.append(t)
        except Exception as e:
            logger.warning(f"Failed to parse trade timestamp {t.timestamp}: {e}")
            continue

    return filtered


# ---------------------------------------------------------------------------
# Helper: filter_trades_by_period
# ---------------------------------------------------------------------------


def filter_trades_by_period(
    trades: list[Trade], start_date: str, end_date: str
) -> list[Trade]:
    """Filter trades to those within [start_date, end_date].

    Args:
        trades: List of Trade objects
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Filtered list of trades within the period
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    filtered = []
    for t in trades:
        try:
            trade_dt = datetime.fromisoformat(t.timestamp.replace("Z", "+00:00"))
            if trade_dt.tzinfo is not None:
                trade_dt = trade_dt.replace(tzinfo=None)

            if start_dt <= trade_dt <= end_dt:
                filtered.append(t)
        except Exception as e:
            logger.warning(f"Failed to parse trade timestamp {t.timestamp}: {e}")
            continue

    return filtered


# ---------------------------------------------------------------------------
# Helper: compute_period_pnl
# ---------------------------------------------------------------------------


def compute_period_pnl(trades: list[Trade]) -> float:
    """Sum closed_pnl from all trades in the period.

    Args:
        trades: List of Trade objects

    Returns:
        Total PnL for the period
    """
    total = 0.0
    for t in trades:
        if t.action in ("Close", "Reduce"):
            total += t.closed_pnl
    return total


# ---------------------------------------------------------------------------
# Helper: compute_turnover
# ---------------------------------------------------------------------------


def compute_turnover(
    new_allocations: dict[str, float], old_allocations: dict[str, float]
) -> float:
    """Compute total turnover between two allocation sets.

    Turnover = sum of absolute weight changes.

    Args:
        new_allocations: {address: weight} for new period
        old_allocations: {address: weight} for previous period

    Returns:
        Total turnover as a decimal (0.0 to 2.0)
    """
    all_addrs = set(new_allocations.keys()) | set(old_allocations.keys())
    total_turnover = 0.0

    for addr in all_addrs:
        new_w = new_allocations.get(addr, 0.0)
        old_w = old_allocations.get(addr, 0.0)
        total_turnover += abs(new_w - old_w)

    return total_turnover


# ---------------------------------------------------------------------------
# Main function: backtest_allocations
# ---------------------------------------------------------------------------


def backtest_allocations(
    historical_trades: dict[str, list[Trade]],  # {address: [Trade, ...]}
    account_values: dict[str, float],  # {address: account_value_usd}
    start_date: str,
    end_date: str,
    rebalance_frequency_days: int = 1,
    starting_capital: float = 100_000,
    softmax_temperature: float = 2.0,
) -> BacktestResult:
    """Backtest the PnL-Weighted Dynamic Allocation strategy.

    Args:
        historical_trades: Historical trades for each trader {address: [Trade, ...]}
        account_values: Account value for each trader {address: account_value_usd}
        start_date: Backtest start date in YYYY-MM-DD format
        end_date: Backtest end date in YYYY-MM-DD format
        rebalance_frequency_days: Days between rebalances (default: 1)
        starting_capital: Initial portfolio capital in USD (default: 100,000)
        softmax_temperature: Temperature for softmax allocation (default: 2.0)

    Returns:
        BacktestResult with timeline and summary metrics
    """
    logger.info(
        f"Starting backtest from {start_date} to {end_date}, "
        f"rebalance every {rebalance_frequency_days} days"
    )

    timeline = []
    portfolio_value = starting_capital
    current_allocations = {}

    # Generate rebalance dates
    rebalance_dates = date_range(start_date, end_date, rebalance_frequency_days)

    for i, rebalance_date in enumerate(rebalance_dates):
        logger.debug(f"Rebalancing on {rebalance_date}")

        # Compute metrics for each trader
        trader_metrics = {}
        trader_scores = {}
        eligible_traders = []

        for address, trades in historical_trades.items():
            account_value = account_values.get(address, 0.0)

            # Filter trades for each window ending at rebalance_date
            trades_7d = filter_trades_by_window(trades, rebalance_date, 7)
            trades_30d = filter_trades_by_window(trades, rebalance_date, 30)
            trades_90d = filter_trades_by_window(trades, rebalance_date, 90)

            # Compute metrics
            m7 = compute_trade_metrics(trades_7d, account_value, 7)
            m30 = compute_trade_metrics(trades_30d, account_value, 30)
            m90 = compute_trade_metrics(trades_90d, account_value, 90)

            trader_metrics[address] = {"m7": m7, "m30": m30, "m90": m90}

            # Apply anti-luck filter
            passes, reason = apply_anti_luck_filter(m7, m30, m90)
            if not passes:
                logger.debug(f"  {address}: filtered out ({reason})")
                continue

            # Compute score (use defaults for backtest: no label, no positions, no recency)
            score = compute_trader_score(
                metrics_7d=m7,
                metrics_30d=m30,
                metrics_90d=m90,
                label=None,
                positions=[],
                hours_since_last_trade=0,
            )
            trader_scores[address] = score
            eligible_traders.append(address)

        logger.debug(f"  Eligible traders: {len(eligible_traders)}")

        # Compute allocations
        risk_config = RiskConfig(max_total_open_usd=starting_capital * 0.5)
        new_allocations = compute_allocations(
            eligible_traders=eligible_traders,
            scores=trader_scores,
            old_allocations=current_allocations,
            trader_positions={},  # Empty for backtest
            risk_config=risk_config,
            softmax_temperature=softmax_temperature,
        )

        # Compute turnover
        turnover = compute_turnover(new_allocations, current_allocations)

        # Simulate period PnL
        period_pnl = 0.0
        if i < len(rebalance_dates) - 1:
            # Not the last rebalance date
            next_date = rebalance_dates[i + 1]

            for address, weight in new_allocations.items():
                # Get trades in this rebalance period
                period_trades = filter_trades_by_period(
                    historical_trades.get(address, []), rebalance_date, next_date
                )
                trader_pnl = compute_period_pnl(period_trades)
                weighted_pnl = trader_pnl * weight
                period_pnl += weighted_pnl

        # Update portfolio value
        portfolio_value += period_pnl

        # Record timeline entry
        timeline.append(
            {
                "date": rebalance_date,
                "portfolio_value": portfolio_value,
                "turnover": turnover,
                "num_traders": len(new_allocations),
                "allocations": dict(new_allocations),
            }
        )

        # Update current allocations
        current_allocations = new_allocations

        logger.debug(
            f"  Portfolio value: ${portfolio_value:,.2f}, "
            f"Period PnL: ${period_pnl:,.2f}, "
            f"Turnover: {turnover:.2%}"
        )

    # Compute summary statistics
    total_return = (portfolio_value - starting_capital) / starting_capital
    max_drawdown = compute_max_drawdown(timeline)
    avg_turnover = float(np.mean([t["turnover"] for t in timeline])) if timeline else 0.0
    sharpe = compute_portfolio_sharpe(timeline)

    logger.info(
        f"Backtest complete: "
        f"Total return: {total_return:.2%}, "
        f"Max drawdown: {max_drawdown:.2%}, "
        f"Sharpe: {sharpe:.2f}, "
        f"Avg turnover: {avg_turnover:.2%}"
    )

    return BacktestResult(
        timeline=timeline,
        total_return=total_return,
        max_drawdown=max_drawdown,
        avg_turnover=avg_turnover,
        sharpe=sharpe,
    )
