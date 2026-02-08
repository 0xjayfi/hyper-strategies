"""Backtest and paper trading module for the Hyperliquid copy-trading system.

Implements Phase 9: replay historical trader activity through the signal
pipeline, simulate execution with slippage, track positions with stop logic,
and compute performance metrics.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from src.config import settings
from src.executor import compute_stop_price, compute_trailing_stop_initial
from src.models import ExecutionResult, OurPosition, Signal
from src.nansen_client import NansenClient, map_leaderboard_entry, map_trade
from src.position_monitor import (
    compute_unrealized_pct,
    trailing_stop_triggered,
    update_trailing_stop,
)
from src.sizing import compute_copy_size
from src.trader_scorer import (
    assign_tiers,
    classify_trader_style,
    compute_trader_score,
    passes_selection_filter,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# 9.2 -- Slippage simulation
# ---------------------------------------------------------------------------


def simulate_slippage(token: str, side: str, size_usd: float) -> float:
    """Return estimated slippage in percent.

    Args:
        token: Token symbol (e.g. ``"BTC"``, ``"ETH"``).
        side: ``"Long"`` or ``"Short"`` (unused in this model but kept for
              future asymmetric slippage modelling).
        size_usd: Notional order size in USD.

    Returns:
        Estimated slippage as a percentage (e.g. 0.05 means 0.05 %).
    """
    base_slippage = {"BTC": 0.02, "ETH": 0.03, "SOL": 0.08, "_default": 0.15}
    slippage = base_slippage.get(token, base_slippage["_default"])
    size_factor = 1 + (size_usd / 100_000) * 0.5
    return slippage * size_factor


# ---------------------------------------------------------------------------
# 9.3 -- PaperExecutor
# ---------------------------------------------------------------------------


class PaperExecutor:
    """Simulates execution without placing real orders.

    Used as a drop-in replacement for :class:`HyperLiquidExecutor` when
    ``PAPER_MODE=True``.
    """

    def __init__(self, price_feed: dict[str, float] | None = None) -> None:
        self.prices: dict[str, float] = price_feed or {}

    async def execute_signal(self, signal: Signal) -> ExecutionResult:
        """Simulate order execution with slippage.

        If the price feed contains an entry for the signal's token, use it;
        otherwise fall back to the implied price from copy_size_usd.
        """
        base_price = self.prices.get(signal.token_symbol)
        if base_price is None or base_price <= 0:
            # Derive an implied price: treat value_usd / (copy_size_usd / value_usd)
            # as a best-effort proxy.  When we have no price at all, use 1.0 so
            # the fill_size calculation does not divide by zero.
            base_price = 1.0

        slippage_pct = simulate_slippage(
            signal.token_symbol, signal.side, signal.copy_size_usd,
        )
        if signal.side == "Long":
            fill_price = base_price * (1 + slippage_pct / 100)
        else:
            fill_price = base_price * (1 - slippage_pct / 100)

        fill_size = signal.copy_size_usd / fill_price if fill_price > 0 else 0.0

        return ExecutionResult(
            success=True,
            order_id=f"paper-{signal.id}",
            fill_price=fill_price,
            fill_size=fill_size,
        )

    async def get_mark_price(self, token: str) -> float:
        """Return the current simulated mark price for *token*."""
        return self.prices.get(token, 0.0)

    async def close_position_on_exchange(
        self, token: str, side: str, size: float,
    ) -> ExecutionResult:
        """Simulate closing a position."""
        price = self.prices.get(token, 0.0)
        slippage_pct = simulate_slippage(token, side, size * price if price > 0 else 0)
        if side == "Long":
            fill_price = price * (1 - slippage_pct / 100)
        else:
            fill_price = price * (1 + slippage_pct / 100)

        return ExecutionResult(
            success=True,
            order_id=f"paper-close-{token}",
            fill_price=fill_price,
            fill_size=size,
        )

    async def cancel_stop_orders(self, token: str) -> None:
        """No-op for paper trading."""

    async def place_stop_order(
        self, token: str, side: str, size: float, trigger_price: float,
    ) -> None:
        """No-op for paper trading."""


# ---------------------------------------------------------------------------
# Internal dataclass for tracking closed trades
# ---------------------------------------------------------------------------


@dataclass
class ClosedTrade:
    """Record of a completed round-trip trade used for metrics calculation."""

    token: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl_usd: float
    pnl_pct: float
    opened_at: str
    closed_at: str
    close_reason: str
    source_trader: str


# ---------------------------------------------------------------------------
# 9.4 -- Backtest metrics
# ---------------------------------------------------------------------------


@dataclass
class BacktestMetrics:
    """Aggregate performance statistics for a backtest run."""

    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    avg_trade_duration_hours: float
    total_trades: int
    winning_trades: int
    losing_trades: int


def compute_metrics(
    closed_trades: list[ClosedTrade],
    equity_curve: list[tuple[str, float]],
    initial_capital: float,
) -> BacktestMetrics:
    """Derive performance metrics from a completed backtest.

    Args:
        closed_trades: List of closed trade records.
        equity_curve: List of ``(timestamp_iso, equity)`` tuples.
        initial_capital: Starting capital in USD.

    Returns:
        A populated :class:`BacktestMetrics` instance.
    """
    total_trades = len(closed_trades)

    if total_trades == 0:
        return BacktestMetrics(
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_trade_duration_hours=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
        )

    # Win / loss decomposition
    winning = [t for t in closed_trades if t.pnl_usd > 0]
    losing = [t for t in closed_trades if t.pnl_usd <= 0]
    winning_trades = len(winning)
    losing_trades = len(losing)

    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    gross_profit = sum(t.pnl_usd for t in winning)
    gross_loss = abs(sum(t.pnl_usd for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Total return
    final_equity = equity_curve[-1][1] if equity_curve else initial_capital
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100

    # Max drawdown
    peak = initial_capital
    max_dd = 0.0
    for _, equity in equity_curve:
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    max_drawdown_pct = max_dd

    # Sharpe ratio (annualised, using per-trade returns as proxy for periods)
    returns = [t.pnl_pct / 100 for t in closed_trades]
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        std_r = math.sqrt(var_r)
        sharpe_ratio = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0
    elif len(returns) == 1:
        sharpe_ratio = 0.0
    else:
        sharpe_ratio = 0.0

    # Average trade duration
    durations: list[float] = []
    for t in closed_trades:
        try:
            opened = datetime.fromisoformat(t.opened_at)
            closed = datetime.fromisoformat(t.closed_at)
            if opened.tzinfo is None:
                opened = opened.replace(tzinfo=timezone.utc)
            if closed.tzinfo is None:
                closed = closed.replace(tzinfo=timezone.utc)
            durations.append((closed - opened).total_seconds() / 3600)
        except (ValueError, TypeError):
            pass

    avg_duration = sum(durations) / len(durations) if durations else 0.0

    return BacktestMetrics(
        total_return_pct=round(total_return_pct, 4),
        max_drawdown_pct=round(max_drawdown_pct, 4),
        sharpe_ratio=round(sharpe_ratio, 4),
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4),
        avg_trade_duration_hours=round(avg_duration, 2),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
    )


def print_report(metrics: BacktestMetrics) -> None:
    """Print a human-readable performance report to stdout."""
    width = 50
    print()
    print("=" * width)
    print("  BACKTEST PERFORMANCE REPORT")
    print("=" * width)
    print(f"  Total Return:           {metrics.total_return_pct:>+10.2f} %")
    print(f"  Max Drawdown:           {metrics.max_drawdown_pct:>10.2f} %")
    print(f"  Sharpe Ratio:           {metrics.sharpe_ratio:>10.2f}")
    print(f"  Win Rate:               {metrics.win_rate * 100:>10.2f} %")
    print(f"  Profit Factor:          {metrics.profit_factor:>10.2f}")
    print(f"  Avg Trade Duration:     {metrics.avg_trade_duration_hours:>10.2f} h")
    print("-" * width)
    print(f"  Total Trades:           {metrics.total_trades:>10d}")
    print(f"  Winning Trades:         {metrics.winning_trades:>10d}")
    print(f"  Losing Trades:          {metrics.losing_trades:>10d}")
    print("=" * width)
    print()


# ---------------------------------------------------------------------------
# 9.1 -- Backtester
# ---------------------------------------------------------------------------


class Backtester:
    """Replay historical trades through the copy-trading pipeline.

    The backtester is fully self-contained -- it does not require the database
    layer or a running system.  Scoring, filtering, sizing, and stop logic are
    all driven by the same pure-function helpers used in production.

    Usage::

        bt = Backtester("2024-06-01", "2024-09-01", initial_capital=100_000)
        nansen = NansenClient(api_key="...")
        await bt.run(nansen)
        metrics = bt.compute_results()
        print_report(metrics)
    """

    def __init__(
        self,
        start_date: str,
        end_date: str,
        initial_capital: float = 100_000,
    ) -> None:
        self.start_date = start_date
        self.end_date = end_date
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.positions: list[OurPosition] = []
        self.closed_trades: list[ClosedTrade] = []
        self.equity_curve: list[tuple[str, float]] = []
        self.peak_equity: float = initial_capital

        # Internal counters
        self._next_pos_id: int = 1
        self._last_prices: dict[str, float] = {}

    # -- helpers --------------------------------------------------------------

    def _record_equity(self, timestamp: str) -> None:
        """Snapshot current equity (capital + mark-to-market open positions)."""
        mtm = 0.0
        for pos in self.positions:
            mark = self._last_prices.get(pos.token_symbol, pos.entry_price)
            pnl_pct = compute_unrealized_pct(pos, mark)
            mtm += pos.value_usd * (1 + pnl_pct / 100)
        equity = self.capital + mtm
        self.equity_curve.append((timestamp, equity))
        if equity > self.peak_equity:
            self.peak_equity = equity

    def _close_position(
        self,
        pos: OurPosition,
        exit_price: float,
        close_ts: str,
        reason: str,
    ) -> None:
        """Close a position, record the trade, and return capital."""
        pnl_pct = compute_unrealized_pct(pos, exit_price)
        pnl_usd = pos.value_usd * pnl_pct / 100

        self.closed_trades.append(
            ClosedTrade(
                token=pos.token_symbol,
                side=pos.side,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                size=pos.size,
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                opened_at=pos.opened_at,
                closed_at=close_ts,
                close_reason=reason,
                source_trader=pos.source_trader or "",
            )
        )

        # Return capital: original capital allocated + PnL
        self.capital += pos.value_usd + pnl_usd

        # Remove from open positions
        self.positions = [p for p in self.positions if p.id != pos.id]

        log.info(
            "bt_position_closed",
            token=pos.token_symbol,
            side=pos.side,
            pnl_usd=round(pnl_usd, 2),
            pnl_pct=round(pnl_pct, 2),
            reason=reason,
        )

    def _check_stops(self, current_ts: str) -> None:
        """Check all open positions for stop triggers at the current timestamp.

        Uses ``self._last_prices`` as the proxy for mark prices.
        """
        positions_to_close: list[tuple[OurPosition, str]] = []

        for pos in list(self.positions):
            mark = self._last_prices.get(pos.token_symbol)
            if mark is None:
                continue

            # --- Trailing stop update ---
            trail_updates = update_trailing_stop(pos, mark)
            if trail_updates is not None:
                for k, v in trail_updates.items():
                    if hasattr(pos, k):
                        object.__setattr__(pos, k, v)

            # --- Hard stop ---
            if pos.stop_price is not None:
                if pos.side == "Long" and mark <= pos.stop_price:
                    positions_to_close.append((pos, "hard_stop"))
                    continue
                if pos.side == "Short" and mark >= pos.stop_price:
                    positions_to_close.append((pos, "hard_stop"))
                    continue

            # --- Trailing stop trigger ---
            if trailing_stop_triggered(pos, mark):
                positions_to_close.append((pos, "trailing_stop"))
                continue

            # --- Time stop ---
            try:
                opened_dt = datetime.fromisoformat(pos.opened_at)
                current_dt = datetime.fromisoformat(current_ts)
                if opened_dt.tzinfo is None:
                    opened_dt = opened_dt.replace(tzinfo=timezone.utc)
                if current_dt.tzinfo is None:
                    current_dt = current_dt.replace(tzinfo=timezone.utc)
                hours_open = (current_dt - opened_dt).total_seconds() / 3600
                if hours_open >= settings.MAX_POSITION_DURATION_HOURS:
                    positions_to_close.append((pos, "time_stop"))
                    continue
            except (ValueError, TypeError):
                pass

        for pos, reason in positions_to_close:
            exit_price = self._last_prices.get(pos.token_symbol, pos.entry_price)
            self._close_position(pos, exit_price, current_ts, reason)

    def _should_copy_trade(
        self,
        trade: dict,
        trader_info: dict,
    ) -> bool:
        """Apply lightweight filters that mirror the live evaluation pipeline.

        Returns True if the trade passes all gate checks.
        """
        action = trade.get("action", "")
        if action not in ("Open", "Add"):
            return False

        token = trade.get("token_symbol", "")
        value_usd = float(trade.get("value_usd", 0))

        # Minimum trade value
        min_value = settings.MIN_TRADE_VALUE_USD.get(
            token, settings.MIN_TRADE_VALUE_USD["_default"]
        )
        if value_usd < min_value:
            return False

        # Position weight
        account_value = trader_info.get("account_value", 0)
        if account_value > 0:
            position_weight = value_usd / account_value
        else:
            position_weight = 0.0

        if position_weight < settings.MIN_POSITION_WEIGHT:
            return False

        # Max positions limit
        if len(self.positions) >= settings.MAX_TOTAL_POSITIONS:
            return False

        # Max total exposure
        total_exposure = sum(p.value_usd for p in self.positions)
        current_equity = self.capital + total_exposure
        if total_exposure >= current_equity * settings.MAX_TOTAL_OPEN_POSITIONS_USD_RATIO:
            return False

        # Per-token exposure
        token_exposure = sum(
            p.value_usd for p in self.positions if p.token_symbol == token
        )
        if token_exposure >= current_equity * settings.MAX_EXPOSURE_PER_TOKEN:
            return False

        return True

    # -- main run method ------------------------------------------------------

    async def run(self, nansen: NansenClient) -> BacktestMetrics:
        """Execute the full backtest.

        Steps:
            1. Fetch the leaderboard for the period.
            2. Score and select traders (reuse scoring logic).
            3. Fetch all trades for tracked traders in the date range.
            4. Sort all trades by timestamp.
            5. Replay through the signal pipeline.
            6. Simulate execution with slippage model.
            7. Simulate stops using trade-price proxies.

        Args:
            nansen: An initialised :class:`NansenClient`.

        Returns:
            :class:`BacktestMetrics` for the run.
        """
        log.info(
            "backtest_start",
            start_date=self.start_date,
            end_date=self.end_date,
            initial_capital=self.initial_capital,
        )

        # ----- 1. Fetch leaderboard -----
        now_utc = datetime.now(timezone.utc)
        date_from_90d = datetime.fromisoformat(self.start_date)
        if date_from_90d.tzinfo is None:
            date_from_90d = date_from_90d.replace(tzinfo=timezone.utc)

        raw_boards: dict[str, list[dict]] = {}
        windows = {
            "7d": self.start_date,
            "30d": self.start_date,
            "90d": self.start_date,
        }
        for label, dt_from in windows.items():
            raw_boards[label] = await nansen.get_perp_leaderboard(
                dt_from, self.end_date,
            )
            log.info(
                "bt_leaderboard_fetched", window=label, count=len(raw_boards[label]),
            )

        # ----- 2. Score and select traders -----
        traders: dict[str, dict] = {}
        for window_label, raw_entries in raw_boards.items():
            for raw in raw_entries:
                entry = map_leaderboard_entry(raw)
                addr = entry["address"]
                if addr not in traders:
                    traders[addr] = {
                        "address": addr,
                        "label": entry["label"],
                        "account_value": entry["account_value"],
                        "roi_7d": 0.0,
                        "roi_30d": 0.0,
                        "roi_90d": 0.0,
                    }
                if entry["label"]:
                    traders[addr]["label"] = entry["label"]
                if entry["account_value"]:
                    traders[addr]["account_value"] = entry["account_value"]
                roi_key = f"roi_{window_label}"
                traders[addr][roi_key] = entry["roi"]

        log.info("bt_traders_merged", unique_addresses=len(traders))

        scored_traders: list[dict] = []
        for addr, trader in traders.items():
            try:
                raw_trades = await nansen.get_address_perp_trades(
                    addr, self.start_date, self.end_date,
                )
                mapped_trades = [map_trade(rt) for rt in raw_trades]
                close_trades = [t for t in mapped_trades if t.action == "Close"]
                nof_trades = len(close_trades)

                total_closes_raw = sum(
                    1 for rt in raw_trades if rt.get("action") == "Close"
                )
                winning = sum(
                    1
                    for rt in raw_trades
                    if rt.get("action") == "Close"
                    and rt.get("closed_pnl") is not None
                    and float(rt.get("closed_pnl", 0)) > 0
                )
                win_rate = winning / total_closes_raw if total_closes_raw > 0 else 0.0

                days_active = max(
                    1,
                    (
                        datetime.fromisoformat(self.end_date).replace(tzinfo=timezone.utc)
                        - datetime.fromisoformat(self.start_date).replace(tzinfo=timezone.utc)
                    ).days,
                )
                style = classify_trader_style(mapped_trades, days_active)

                if not passes_selection_filter(
                    nof_trades=nof_trades,
                    style=style,
                    account_value=trader["account_value"],
                    roi_30d=trader["roi_30d"],
                    win_rate=win_rate,
                    blacklisted_until=None,
                ):
                    continue

                score = compute_trader_score(
                    trader=trader,
                    trades_90d=raw_trades,
                    roi_7d=trader["roi_7d"],
                    roi_30d=trader["roi_30d"],
                    roi_90d=trader["roi_90d"],
                )

                scored_traders.append({
                    "address": addr,
                    "label": trader["label"],
                    "score": score,
                    "style": style,
                    "roi_7d": trader["roi_7d"],
                    "roi_30d": trader["roi_30d"],
                    "account_value": trader["account_value"],
                    "nof_trades": nof_trades,
                })
            except Exception:
                log.exception("bt_scoring_failed", address=addr)
                continue

        scored_traders = assign_tiers(scored_traders)
        primary_traders = {
            t["address"]: t for t in scored_traders if t.get("tier") == "primary"
        }
        log.info("bt_traders_selected", primary=len(primary_traders))

        if not primary_traders:
            log.warning("bt_no_primary_traders_found")
            self._record_equity(self.end_date)
            return self.compute_results()

        # ----- 3. Fetch all trades for tracked traders -----
        all_trades: list[tuple[dict, dict]] = []
        for addr, trader_info in primary_traders.items():
            try:
                raw_trades = await nansen.get_address_perp_trades(
                    addr, self.start_date, self.end_date,
                )
                for rt in raw_trades:
                    rt["_trader_address"] = addr
                    all_trades.append((rt, trader_info))
            except Exception:
                log.exception("bt_trade_fetch_failed", address=addr)
                continue

        log.info("bt_total_trades_fetched", count=len(all_trades))

        # ----- 4. Sort by timestamp -----
        def _trade_ts(item: tuple[dict, dict]) -> str:
            return item[0].get("timestamp", "")

        all_trades.sort(key=_trade_ts)

        # ----- 5-7. Replay -----
        for trade_dict, trader_info in all_trades:
            ts = trade_dict.get("timestamp", "")
            token = trade_dict.get("token_symbol", "")
            price = float(trade_dict.get("price", 0))

            if not ts or price <= 0:
                continue

            # Update the last-known price for this token
            self._last_prices[token] = price

            # Check stops on existing positions before processing new trades
            self._check_stops(ts)

            # Record equity at each trade timestamp
            self._record_equity(ts)

            # Filter
            if not self._should_copy_trade(trade_dict, trader_info):
                continue

            side = trade_dict.get("side", "")
            value_usd = float(trade_dict.get("value_usd", 0))
            account_value = trader_info.get("account_value", 0)
            trader_address = trade_dict.get("_trader_address", "")
            roi_7d = trader_info.get("roi_7d", 0.0)

            # Position weight for sizing
            position_weight = value_usd / account_value if account_value > 0 else 0.0

            # Compute copy size
            current_equity = self.capital + sum(p.value_usd for p in self.positions)
            leverage = None  # not available in historical trades
            copy_size = compute_copy_size(
                trader_position_value=value_usd,
                trader_account_value=account_value,
                our_account_value=current_equity,
                trader_roi_7d=roi_7d,
                leverage=leverage,
            )
            if copy_size <= 0:
                continue

            # Check we have enough free capital
            if copy_size > self.capital:
                copy_size = self.capital
            if copy_size < 100:
                continue

            # Apply simulated slippage
            slippage_pct = simulate_slippage(token, side, copy_size)
            if side == "Long":
                fill_price = price * (1 + slippage_pct / 100)
            else:
                fill_price = price * (1 - slippage_pct / 100)

            if fill_price <= 0:
                continue

            fill_size = copy_size / fill_price

            # Compute stops
            stop_price = compute_stop_price(fill_price, side)
            trailing_stop = compute_trailing_stop_initial(fill_price, side)

            # Open position
            pos = OurPosition(
                id=self._next_pos_id,
                token_symbol=token,
                side=side,
                entry_price=fill_price,
                size=fill_size,
                value_usd=copy_size,
                stop_price=stop_price,
                trailing_stop_price=trailing_stop,
                highest_price=fill_price if side == "Long" else None,
                lowest_price=fill_price if side == "Short" else None,
                opened_at=ts,
                source_trader=trader_address,
                source_signal_id=str(uuid.uuid4()),
                status="open",
            )
            self._next_pos_id += 1

            # Deduct capital
            self.capital -= copy_size

            self.positions.append(pos)
            log.info(
                "bt_position_opened",
                token=token,
                side=side,
                entry_price=round(fill_price, 4),
                copy_size=round(copy_size, 2),
                fill_size=round(fill_size, 6),
                stop_price=round(stop_price, 4),
                trailing_stop=round(trailing_stop, 4),
            )

        # ----- End of replay: close any remaining open positions at last known price -----
        end_ts = self.end_date
        for pos in list(self.positions):
            exit_price = self._last_prices.get(pos.token_symbol, pos.entry_price)
            self._close_position(pos, exit_price, end_ts, "backtest_end")

        self._record_equity(end_ts)

        metrics = self.compute_results()
        log.info(
            "backtest_complete",
            total_return_pct=metrics.total_return_pct,
            max_drawdown_pct=metrics.max_drawdown_pct,
            sharpe_ratio=metrics.sharpe_ratio,
            total_trades=metrics.total_trades,
        )
        return metrics

    def compute_results(self) -> BacktestMetrics:
        """Compute metrics from the collected closed trades and equity curve."""
        return compute_metrics(
            self.closed_trades,
            self.equity_curve,
            self.initial_capital,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    """Run a sample backtest when the module is executed directly."""
    import sys

    api_key = settings.NANSEN_API_KEY
    if not api_key:
        print(
            "ERROR: NANSEN_API_KEY not set. Export it or add it to .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    start_date = "2024-06-01"
    end_date = "2024-09-01"
    initial_capital = 100_000.0

    # Allow overriding via CLI args:  python -m src.backtest 2024-01-01 2024-06-01 200000
    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    if len(sys.argv) >= 4:
        initial_capital = float(sys.argv[3])

    print(f"Running backtest: {start_date} -> {end_date} | Capital: ${initial_capital:,.0f}")

    nansen = NansenClient(api_key=api_key)
    try:
        bt = Backtester(start_date, end_date, initial_capital)
        metrics = await bt.run(nansen)
        print_report(metrics)
    finally:
        await nansen.close()


if __name__ == "__main__":
    asyncio.run(_main())
