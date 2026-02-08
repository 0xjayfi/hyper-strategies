"""Main orchestrator for the Hyperliquid copy-trading system.

Launches all concurrent subsystems:
  - Leaderboard refresh (daily trader scoring)
  - Trade ingestion polling (new trade detection + evaluation)
  - Deferred signal processor (delayed signal re-evaluation)
  - Position monitor (trailing stops, profit-taking, liquidation detection)

Handles graceful shutdown on SIGINT / SIGTERM.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Any

import structlog
from structlog.types import Processor

from src.config import settings
from src import db
from src.nansen_client import NansenClient
from src.trader_scorer import refresh_trader_scores
from src.trade_ingestion import poll_trader_trades, process_deferred_signals
from src.executor import HyperLiquidExecutor
from src.position_monitor import monitor_loop


# ---------------------------------------------------------------------------
# 8.3 — Structured logging configuration
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    """Configure structlog with JSON (production) or console (development) rendering.

    Uses PAPER_MODE as a proxy for environment: paper mode enables coloured
    console output for local development; non-paper mode emits JSON lines
    suitable for log aggregation in production.

    The LOG_FORMAT environment variable can override this heuristic:
      LOG_FORMAT=json  -> always JSON
      LOG_FORMAT=console -> always console
    """
    log_format = os.environ.get("LOG_FORMAT", "").lower()

    if log_format == "json":
        use_json = True
    elif log_format == "console":
        use_json = False
    else:
        # Default: JSON for production (PAPER_MODE=False), console for dev
        use_json = not settings.PAPER_MODE

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if use_json:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Also configure the stdlib logging integration so that any stdlib loggers
    # (e.g. from httpx, asyncio) are rendered through the same pipeline.
    import logging

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# 8.1 — Loop wrappers
# ---------------------------------------------------------------------------

log = structlog.get_logger()


async def leaderboard_refresh_loop(nansen: NansenClient) -> None:
    """Run the daily trader scoring pipeline in an infinite loop.

    Calls ``refresh_trader_scores`` once, then sleeps for
    ``POLLING_INTERVAL_LEADERBOARD_SEC`` (default 86 400 s = 24 h).
    Exceptions are caught and logged so the loop never dies.
    """
    log.info(
        "leaderboard_refresh_loop_started",
        interval_sec=settings.POLLING_INTERVAL_LEADERBOARD_SEC,
    )

    while True:
        try:
            log.info("leaderboard_refresh_start")
            await refresh_trader_scores(nansen)
            log.info("leaderboard_refresh_complete")
        except Exception:
            log.exception("leaderboard_refresh_error")

        await asyncio.sleep(settings.POLLING_INTERVAL_LEADERBOARD_SEC)


async def trade_ingestion_loop(
    nansen: NansenClient,
    execute_callback: Any,
) -> None:
    """Wrapper around the trade polling loop.

    ``poll_trader_trades`` already runs forever internally, but we wrap it
    in a try/except so that an unhandled exception at the top level is
    logged and retried after a brief back-off rather than crashing the
    entire application.
    """
    log.info("trade_ingestion_loop_started")

    while True:
        try:
            await poll_trader_trades(nansen, execute_callback)
        except Exception:
            log.exception("trade_ingestion_loop_error")
            await asyncio.sleep(10)


async def deferred_signal_loop(
    nansen: NansenClient,
    execute_callback: Any,
) -> None:
    """Wrapper around the deferred signal processor.

    ``process_deferred_signals`` already runs forever internally, but we
    wrap it for top-level resilience.
    """
    log.info("deferred_signal_loop_started")

    while True:
        try:
            await process_deferred_signals(nansen, execute_callback)
        except Exception:
            log.exception("deferred_signal_loop_error")
            await asyncio.sleep(10)


async def position_monitor_wrapper(
    executor: HyperLiquidExecutor,
    nansen: NansenClient,
) -> None:
    """Wrapper around the position monitor loop.

    ``monitor_loop`` already runs forever internally, but we wrap it
    for top-level resilience.
    """
    log.info("position_monitor_loop_started")

    while True:
        try:
            await monitor_loop(executor, nansen)
        except Exception:
            log.exception("position_monitor_loop_error")
            await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# 8.2 — Graceful shutdown
# ---------------------------------------------------------------------------


def _create_shutdown_handler(
    loop: asyncio.AbstractEventLoop,
    nansen: NansenClient,
) -> Any:
    """Return a signal callback that triggers graceful shutdown.

    The callback:
      1. Logs the received signal.
      2. Cancels every running asyncio task (except the current one).
      3. Schedules the Nansen client cleanup.
    """
    shutdown_triggered = False

    def _handler(sig: signal.Signals) -> None:
        nonlocal shutdown_triggered
        if shutdown_triggered:
            log.warning("shutdown_forced", signal=sig.name)
            return
        shutdown_triggered = True

        log.info("shutdown_signal_received", signal=sig.name)

        # Cancel all tasks except the current one so gather() raises
        # CancelledError and the finally block in main() can run cleanup.
        tasks = [
            t for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.done()
        ]
        log.info("cancelling_tasks", count=len(tasks))
        for task in tasks:
            task.cancel()

    return _handler


# ---------------------------------------------------------------------------
# 8.1 — Main entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Initialise all subsystems and launch concurrent processing loops.

    Lifecycle:
        1. Configure structured logging.
        2. Initialise the SQLite database (create tables if needed).
        3. Create the Nansen API client.
        4. Create the HyperLiquid executor (paper or live).
        5. Register SIGINT/SIGTERM handlers for graceful shutdown.
        6. Launch all loops via ``asyncio.gather``.
        7. On shutdown, clean up resources in the finally block.
    """
    # 1. Logging
    configure_logging()

    log.info(
        "application_starting",
        paper_mode=settings.PAPER_MODE,
        polling_leaderboard_sec=settings.POLLING_INTERVAL_LEADERBOARD_SEC,
        polling_trades_sec=settings.POLLING_INTERVAL_ADDRESS_TRADES_SEC,
    )

    # 2. Database
    await db.init()
    log.info("database_initialised")

    # 3. Nansen client
    nansen = NansenClient(api_key=settings.NANSEN_API_KEY)
    log.info("nansen_client_created")

    # 4. HyperLiquid executor
    if settings.PAPER_MODE:
        hl_client = None
        log.info("paper_mode_enabled", note="SDK client set to None")
    else:
        # In live mode, initialise the real Hyperliquid SDK client:
        #
        #   from hyperliquid.utils import constants
        #   import eth_account
        #   account = eth_account.Account.from_key(os.environ["HL_PRIVATE_KEY"])
        #   hl_client = hyperliquid.Exchange(
        #       account, constants.MAINNET_API_URL, account_address=account.address,
        #   )
        #
        # Until the SDK is installed, fall back to None (will error on
        # first real order attempt, which is the desired fail-safe).
        hl_client = None
        log.warning(
            "live_mode_no_sdk",
            note="Hyperliquid SDK not configured; set PAPER_MODE=True or install SDK",
        )

    executor = HyperLiquidExecutor(sdk_client=hl_client)
    log.info("executor_created", paper_mode=settings.PAPER_MODE)

    # The execute callback wired into ingestion and deferred processor
    execute_callback = executor.execute_signal

    # 5. Graceful shutdown handlers
    loop = asyncio.get_running_loop()

    try:
        handler = _create_shutdown_handler(loop, nansen)
        loop.add_signal_handler(signal.SIGINT, handler, signal.SIGINT)
        loop.add_signal_handler(signal.SIGTERM, handler, signal.SIGTERM)
        log.info("signal_handlers_registered", signals=["SIGINT", "SIGTERM"])
    except NotImplementedError:
        # Windows does not support add_signal_handler; fall back to
        # signal.signal for a best-effort approach.
        log.warning("signal_handlers_not_supported", note="using fallback for non-Unix")

    # 6. Launch concurrent loops
    try:
        log.info("launching_subsystems")
        await asyncio.gather(
            leaderboard_refresh_loop(nansen),
            trade_ingestion_loop(nansen, execute_callback),
            deferred_signal_loop(nansen, execute_callback),
            position_monitor_wrapper(executor, nansen),
        )
    except asyncio.CancelledError:
        log.info("tasks_cancelled_during_shutdown")
    finally:
        # 7. Cleanup
        log.info("shutdown_cleanup_start")

        try:
            await nansen.close()
            log.info("nansen_client_closed")
        except Exception:
            log.exception("nansen_client_close_error")

        log.info("application_stopped")


if __name__ == "__main__":
    asyncio.run(main())
