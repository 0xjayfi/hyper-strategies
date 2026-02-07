"""
Metrics Engine (Phase 3)

Computes trade-derived metrics for each trader over rolling windows:
- Win rate, profit factor, Sharpe-like ratios
- ROI proxy (realized PnL / account value)
- Max drawdown proxy (worst single-trade loss)
"""

import logging
from datetime import datetime, timedelta

import numpy as np

from src.models import Trade, TradeMetrics
from src.nansen_client import NansenClient
from src.datastore import DataStore

logger = logging.getLogger(__name__)


def compute_trade_metrics(trades: list[Trade], account_value: float, window_days: int) -> TradeMetrics:
    """
    Compute derived metrics from a list of trades within a rolling window.

    Args:
        trades: List of Trade objects for the trader in the window
        account_value: Current account value in USD (from position snapshot)
        window_days: Size of the rolling window in days (e.g., 7, 30, 90)

    Returns:
        TradeMetrics object with computed statistics
    """
    # Filter to closing trades with realized PnL
    close_trades = [t for t in trades if t.action in ("Close", "Reduce") and t.closed_pnl != 0]

    total_trades = len(close_trades)
    if total_trades == 0:
        return TradeMetrics.empty(window_days)

    winning = [t for t in close_trades if t.closed_pnl > 0]
    losing = [t for t in close_trades if t.closed_pnl < 0]

    win_rate = len(winning) / total_trades

    gross_profit = sum(t.closed_pnl for t in winning)
    gross_loss = abs(sum(t.closed_pnl for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Per-trade returns as fraction of trade value
    returns = []
    for t in close_trades:
        if t.value_usd > 0:
            returns.append(t.closed_pnl / t.value_usd)

    avg_return = float(np.mean(returns)) if returns else 0.0
    std_return = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    pseudo_sharpe = float(avg_return / std_return) if std_return > 0 else 0.0

    total_pnl = sum(t.closed_pnl for t in close_trades)

    # ROI proxy: total realized PnL / account value at start of window
    roi_proxy = (total_pnl / account_value * 100) if account_value > 0 else 0.0

    # Drawdown proxy: worst single-trade loss as % of account
    worst_loss = min((t.closed_pnl for t in close_trades), default=0)
    max_drawdown_proxy = abs(worst_loss) / account_value if account_value > 0 else 0.0

    return TradeMetrics(
        window_days=window_days,
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_return=avg_return,
        std_return=std_return,
        pseudo_sharpe=pseudo_sharpe,
        total_pnl=total_pnl,
        roi_proxy=roi_proxy,
        max_drawdown_proxy=max_drawdown_proxy,
    )


async def recompute_all_metrics(
    nansen_client: NansenClient,
    datastore: DataStore,
    trader_addresses: list[str],
    windows: list[int] | None = None,
) -> None:
    """
    Batch computation of metrics for all traders across multiple rolling windows.

    For each trader:
    1. Fetches current account value from position snapshot (once per trader)
    2. For each window: fetches trades, computes metrics, stores to database

    Args:
        nansen_client: Async Nansen API client
        datastore: Sync SQLite datastore
        trader_addresses: List of trader wallet addresses to compute metrics for
        windows: List of window sizes in days (default: [7, 30, 90])
    """
    if windows is None:
        windows = [7, 30, 90]

    logger.info(f"Recomputing metrics for {len(trader_addresses)} traders across windows: {windows}")

    for address in trader_addresses:
        logger.info(f"Processing trader: {address}")

        # Fetch account value once per trader
        try:
            position_snapshot = await nansen_client.fetch_address_positions(address)
            account_value_str = position_snapshot.margin_summary_account_value_usd
            account_value = float(account_value_str) if account_value_str else 0.0
        except Exception as e:
            logger.error(f"Failed to fetch positions for {address}: {e}")
            account_value = 0.0

        # Compute metrics for each window
        for window_days in windows:
            logger.debug(f"  Window: {window_days} days")

            date_to = datetime.utcnow().strftime("%Y-%m-%d")
            date_from = (datetime.utcnow() - timedelta(days=window_days)).strftime("%Y-%m-%d")

            try:
                # Fetch trades for this window
                trades = await nansen_client.fetch_address_trades(
                    address=address,
                    date_from=date_from,
                    date_to=date_to,
                )

                # Compute metrics
                metrics = compute_trade_metrics(trades, account_value, window_days)

                # Store to database
                datastore.insert_trade_metrics(address, metrics)

                logger.debug(
                    f"    Stored metrics: {metrics.total_trades} trades, "
                    f"ROI proxy: {metrics.roi_proxy:.2f}%, "
                    f"Sharpe: {metrics.pseudo_sharpe:.2f}"
                )

            except Exception as e:
                logger.error(f"Failed to compute metrics for {address} (window={window_days}): {e}")
                continue

    logger.info("Metrics recomputation complete")
