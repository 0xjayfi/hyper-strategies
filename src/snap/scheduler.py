"""Scheduler and orchestration for the Snap copytrading system.

Implements Phase 6 of the specification:

1. ``SchedulerState`` — Enum for state machine transitions.
2. ``SystemScheduler``  — Async scheduler coordinating all cadences:
   - Daily trader refresh at 00:00 UTC
   - 4h rebalance cycle
   - 5m trade ingestion
   - 60s position monitoring
3. State machine with locking (via ``rebalance_lock`` from monitoring).
4. Graceful shutdown — completes current cycle, cancels pending tasks.
5. Startup recovery — loads last-run timestamps from ``system_state`` table.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from datetime import datetime, timedelta, timezone

from snap.config import (
    MONITOR_INTERVAL_SECONDS,
    POLL_TRADES_MINUTES,
    REBALANCE_INTERVAL_HOURS,
    TOP_N_TRADERS,
)
from snap.database import get_connection
from snap.execution import HyperliquidClient, PaperTradeClient, execute_rebalance
from snap.monitoring import _monitor_once, rebalance_lock
from snap.portfolio import (
    apply_risk_overlay,
    compute_rebalance_diff,
    compute_target_portfolio,
    get_current_positions,
    get_tracked_traders,
    net_opposing_targets,
    store_target_allocations,
    TraderSnapshot,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. State Machine
# ---------------------------------------------------------------------------


class SchedulerState(enum.Enum):
    """State machine for the scheduler."""

    IDLE = "IDLE"
    REFRESHING_TRADERS = "REFRESHING_TRADERS"
    REBALANCING = "REBALANCING"
    INGESTING_TRADES = "INGESTING_TRADES"
    MONITORING = "MONITORING"
    SHUTTING_DOWN = "SHUTTING_DOWN"


# ---------------------------------------------------------------------------
# 2. System State DB helpers
# ---------------------------------------------------------------------------


def get_system_state(db_path: str, key: str) -> str | None:
    """Read a value from the system_state table."""
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM system_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def set_system_state(db_path: str, key: str, value: str) -> None:
    """Upsert a value into the system_state table."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO system_state (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
                (key, value, now, value, now),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. SystemScheduler
# ---------------------------------------------------------------------------


class SystemScheduler:
    """Async scheduler coordinating all system cadences.

    Parameters
    ----------
    client:
        Exchange client (real or paper).
    nansen_client:
        Nansen API client for data ingestion.
    db_path:
        Path to the SQLite database (data DB in dual-DB mode, or the
        single combined DB).
    strategy_db_path:
        Optional path to the strategy database.  When ``None``, defaults
        to *db_path* (single-DB mode).
    """

    def __init__(
        self,
        client: HyperliquidClient,
        nansen_client,
        db_path: str,
        *,
        strategy_db_path: str | None = None,
        scoring_overrides: dict | None = None,
    ) -> None:
        self.client = client
        self.nansen_client = nansen_client
        self.db_path = db_path
        self.strategy_db_path = strategy_db_path or db_path
        self._scoring_overrides = scoring_overrides

        self.state = SchedulerState.IDLE
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

        # Timestamps for cadence tracking
        self._last_trader_refresh: datetime | None = None
        self._last_rebalance: datetime | None = None
        self._last_trade_ingestion: datetime | None = None
        self._last_monitor: datetime | None = None

    def set_scoring_overrides(self, overrides: dict | None) -> None:
        """Update scoring variant overrides (for live variant switching)."""
        self._scoring_overrides = overrides

    # -- State management --------------------------------------------------

    def _set_state(self, new_state: SchedulerState) -> None:
        """Transition to a new state."""
        old = self.state
        self.state = new_state
        logger.info("State transition: %s -> %s", old.value, new_state.value)

    # -- Startup recovery --------------------------------------------------

    def recover_state(self) -> None:
        """Load last-run timestamps from the database.

        Reads ``last_trader_refresh_at``, ``last_rebalance_at``, and
        ``last_trade_ingestion_at`` from ``system_state`` to determine
        which jobs need to run immediately on startup.
        """
        for key, attr in [
            ("last_trader_refresh_at", "_last_trader_refresh"),
            ("last_rebalance_at", "_last_rebalance"),
            ("last_trade_ingestion_at", "_last_trade_ingestion"),
        ]:
            val = get_system_state(self.strategy_db_path, key)
            if val:
                try:
                    dt = datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    setattr(self, attr, dt)
                    logger.info("Recovered %s = %s", key, val)
                except (ValueError, TypeError):
                    logger.warning("Could not parse %s=%r", key, val)

    # -- Job: Daily Trader Refresh -----------------------------------------

    async def _run_trader_refresh(self) -> None:
        """Execute the daily trader universe refresh."""
        self._set_state(SchedulerState.REFRESHING_TRADERS)
        try:
            from snap.scoring import refresh_trader_universe

            eligible = await refresh_trader_universe(
                self.nansen_client,
                self.db_path,
                strategy_db_path=self.strategy_db_path,
                overrides=self._scoring_overrides,
            )
            now = datetime.now(timezone.utc)
            self._last_trader_refresh = now
            set_system_state(
                self.strategy_db_path,
                "last_trader_refresh_at",
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            logger.info("Trader refresh complete: %d eligible", eligible)
        except Exception:
            logger.exception("Trader refresh failed")
        finally:
            self._set_state(SchedulerState.IDLE)

    # -- Job: Rebalance Cycle ----------------------------------------------

    async def _run_rebalance(self) -> None:
        """Execute one rebalance cycle (snapshot -> target -> risk -> execute)."""
        self._set_state(SchedulerState.REBALANCING)
        async with rebalance_lock:
            try:
                rebalance_id = str(uuid.uuid4())

                # 1. Get tracked traders (from strategy DB)
                tracked = get_tracked_traders(self.strategy_db_path, TOP_N_TRADERS)
                if not tracked:
                    logger.warning("No tracked traders, skipping rebalance")
                    return

                # 2. Snapshot positions for each trader (into data DB)
                from snap.ingestion import ingest_positions

                addresses = [t["address"] for t in tracked]
                await ingest_positions(
                    self.nansen_client, self.db_path, addresses, rebalance_id
                )

                # 2b. Update PaperTradeClient mark prices from snapshots (data DB)
                if isinstance(self.client, PaperTradeClient):
                    _conn = get_connection(self.db_path)
                    try:
                        price_rows = _conn.execute(
                            """SELECT DISTINCT token_symbol, mark_price
                               FROM position_snapshots
                               WHERE snapshot_batch = ? AND mark_price > 0""",
                            (rebalance_id,),
                        ).fetchall()
                        for row in price_rows:
                            self.client.set_mark_price(
                                row["token_symbol"], row["mark_price"]
                            )
                        logger.info(
                            "Updated %d mark prices in PaperTradeClient",
                            len(price_rows),
                        )
                    finally:
                        _conn.close()

                # 3. Build trader snapshots for target computation (data DB)
                conn = get_connection(self.db_path)
                try:
                    snapshots = []
                    for t in tracked:
                        addr = t["address"]
                        trader_row = conn.execute(
                            "SELECT account_value FROM traders WHERE address = ?",
                            (addr,),
                        ).fetchone()
                        acct_val = trader_row["account_value"] if trader_row else 0.0

                        pos_rows = conn.execute(
                            """SELECT token_symbol, side, position_value_usd, mark_price
                               FROM position_snapshots
                               WHERE snapshot_batch = ? AND address = ?""",
                            (rebalance_id, addr),
                        ).fetchall()

                        positions = [dict(r) for r in pos_rows]
                        snapshots.append(
                            TraderSnapshot(
                                address=addr,
                                composite_score=t["composite_score"],
                                account_value=acct_val,
                                positions=positions,
                            )
                        )
                finally:
                    conn.close()

                # 4. Get our account value (from strategy DB)
                acct_val_str = get_system_state(self.strategy_db_path, "account_value")
                my_account_value = float(acct_val_str) if acct_val_str else 100_000.0

                # 5. Compute target portfolio (strategy DB)
                targets = compute_target_portfolio(snapshots, my_account_value)
                targets = net_opposing_targets(targets)
                targets = apply_risk_overlay(targets, my_account_value)
                store_target_allocations(self.strategy_db_path, rebalance_id, targets)

                # 6. Compute diff and execute (strategy DB)
                current = get_current_positions(self.strategy_db_path)
                actions = compute_rebalance_diff(targets, current)

                if actions:
                    summary = await execute_rebalance(
                        self.client, rebalance_id, actions, self.strategy_db_path
                    )
                    logger.info("Rebalance %s: %s", rebalance_id, summary)
                else:
                    logger.info("Rebalance %s: no actions needed", rebalance_id)

                now = datetime.now(timezone.utc)
                self._last_rebalance = now
                set_system_state(
                    self.strategy_db_path,
                    "last_rebalance_at",
                    now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
            except Exception:
                logger.exception("Rebalance failed")
            finally:
                self._set_state(SchedulerState.IDLE)

    # -- Job: Trade Ingestion (5m) -----------------------------------------

    async def _run_trade_ingestion(self) -> None:
        """Ingest recent trades for tracked traders."""
        self._set_state(SchedulerState.INGESTING_TRADES)
        try:
            from snap.ingestion import ingest_trades

            tracked = get_tracked_traders(self.strategy_db_path, TOP_N_TRADERS)
            if not tracked:
                return

            addresses = [t["address"] for t in tracked]
            # 6h lookback window
            now = datetime.now(timezone.utc)
            date_from = (now - timedelta(hours=6)).strftime("%Y-%m-%d")
            date_to = now.strftime("%Y-%m-%d")

            count = await ingest_trades(
                self.nansen_client, self.db_path, addresses, date_from, date_to
            )
            self._last_trade_ingestion = now
            set_system_state(
                self.strategy_db_path,
                "last_trade_ingestion_at",
                now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            logger.info("Trade ingestion complete: %d new trades", count)
        except Exception:
            logger.exception("Trade ingestion failed")
        finally:
            self._set_state(SchedulerState.IDLE)

    # -- Job: Monitor Positions (60s) --------------------------------------

    async def _run_monitor(self) -> None:
        """Run one monitoring pass."""
        self._set_state(SchedulerState.MONITORING)
        async with rebalance_lock:
            try:
                summary = await _monitor_once(self.client, self.strategy_db_path)
                self._last_monitor = datetime.now(timezone.utc)
                logger.debug("Monitor: %s", summary)
            except Exception:
                logger.exception("Monitor pass failed")
            finally:
                self._set_state(SchedulerState.IDLE)

    # -- Cadence checks ----------------------------------------------------

    def _should_refresh_traders(self, now: datetime) -> bool:
        """Check if we should run the daily trader refresh."""
        if self._last_trader_refresh is None:
            return True
        elapsed = (now - self._last_trader_refresh).total_seconds()
        return elapsed >= 24 * 3600

    def _should_rebalance(self, now: datetime) -> bool:
        """Check if we should run a rebalance cycle."""
        if self._last_rebalance is None:
            return True
        elapsed = (now - self._last_rebalance).total_seconds()
        return elapsed >= REBALANCE_INTERVAL_HOURS * 3600

    def _should_ingest_trades(self, now: datetime) -> bool:
        """Check if we should ingest trades.

        Disabled: trade history is only used by the daily scoring engine,
        not by the monitor or rebalance loop.  Saves Nansen API quota.
        """
        return False

    def _should_monitor(self, now: datetime) -> bool:
        """Check if we should run a monitoring pass."""
        if self._last_monitor is None:
            return True
        elapsed = (now - self._last_monitor).total_seconds()
        return elapsed >= MONITOR_INTERVAL_SECONDS

    # -- Main loop ---------------------------------------------------------

    async def run(
        self,
        tick_interval_s: float = 1.0,
        max_ticks: int | None = None,
    ) -> None:
        """Main scheduler loop.

        Checks cadences on each tick and dispatches jobs as needed.
        Jobs are run sequentially to avoid resource contention (except
        monitoring which acquires the rebalance_lock independently).

        Parameters
        ----------
        tick_interval_s:
            Seconds between tick checks (default 1.0).
        max_ticks:
            If set, stop after this many ticks (for testing).
        """
        logger.info("Scheduler starting")
        tick = 0

        while not self._stop_event.is_set():
            if max_ticks is not None and tick >= max_ticks:
                break

            now = datetime.now(timezone.utc)

            if self.state == SchedulerState.IDLE:
                # Priority order: trader refresh > rebalance > trades > monitor
                if self._should_refresh_traders(now):
                    await self._run_trader_refresh()
                elif self._should_rebalance(now):
                    await self._run_rebalance()
                elif self._should_ingest_trades(now):
                    await self._run_trade_ingestion()
                elif self._should_monitor(now):
                    await self._run_monitor()

            tick += 1
            if max_ticks is not None and tick >= max_ticks:
                break
            await asyncio.sleep(tick_interval_s)

        logger.info("Scheduler stopped after %d ticks", tick)

    # -- Graceful shutdown -------------------------------------------------

    def request_shutdown(self) -> None:
        """Signal the scheduler to stop after the current cycle completes."""
        logger.info("Shutdown requested")
        self._stop_event.set()
        self.state = SchedulerState.SHUTTING_DOWN

    async def shutdown(self) -> None:
        """Request shutdown and wait for running tasks to complete."""
        self.request_shutdown()
        # Cancel any pending asyncio tasks we spawned
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tasks.clear()
        logger.info("Scheduler shutdown complete")
