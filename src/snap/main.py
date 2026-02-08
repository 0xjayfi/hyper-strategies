"""CLI entry point for the Snap copytrading system.

Usage::

    # Paper-trade mode (default)
    python -m snap.main

    # Paper-trade with custom settings
    python -m snap.main --db-path ./data/snap.db --account-value 10000

    # Live mode (sends real orders to Hyperliquid)
    python -m snap.main --live --account-value 5000

Environment variables (override CLI defaults):
    SNAP_PAPER_TRADE   - "true" (default) or "false"
    SNAP_DB_PATH       - SQLite database path (default "snap.db")
    SNAP_ACCOUNT_VALUE - Starting account value in USD
    SNAP_LOG_FILE      - Optional log file path
    SNAP_DASHBOARD_FILE - Optional dashboard JSON output path
    SNAP_HEALTH_FILE   - Health check file path
    NANSEN_API_KEY     - Required for data ingestion
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from snap.config import (
    ACCOUNT_VALUE,
    DASHBOARD_FILE,
    DB_PATH,
    HEALTH_CHECK_FILE,
    LOG_FILE,
    NANSEN_API_KEY,
    PAPER_TRADE,
)
from snap.database import init_db
from snap.execution import PaperTradeClient
from snap.nansen_client import NansenClient
from snap.observability import (
    check_alerts,
    collect_metrics,
    emit_alerts,
    export_dashboard,
    setup_json_logging,
    write_health_check,
)
from snap.scheduler import SystemScheduler, set_system_state

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="snap",
        description="Snap - Hyperliquid copytrading via position snapshot rebalancing",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Enable live trading (sends real orders to Hyperliquid)",
    )
    mode_group.add_argument(
        "--paper",
        action="store_true",
        default=False,
        help="Run in paper-trade mode (default)",
    )
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help=f"SQLite database path (default: {DB_PATH})",
    )
    parser.add_argument(
        "--account-value",
        type=float,
        default=ACCOUNT_VALUE,
        help=f"Starting account value in USD (default: {ACCOUNT_VALUE})",
    )
    parser.add_argument(
        "--log-file",
        default=LOG_FILE,
        help="Optional log file path",
    )
    parser.add_argument(
        "--dashboard-file",
        default=DASHBOARD_FILE,
        help="Optional dashboard JSON output path",
    )
    parser.add_argument(
        "--health-file",
        default=HEALTH_CHECK_FILE,
        help=f"Health check file path (default: {HEALTH_CHECK_FILE})",
    )
    args = parser.parse_args(argv)

    # If neither flag given, use config default
    if not args.live and not args.paper:
        if PAPER_TRADE:
            args.paper = True
        else:
            args.live = True

    return args


async def run(args: argparse.Namespace) -> None:
    """Main async entry point.

    Sets up all components and runs the scheduler until interrupted.
    """
    paper_mode = not args.live

    # 1. Initialize logging
    setup_json_logging(log_file=args.log_file)

    logger.info(
        "Starting Snap system: mode=%s db=%s account_value=%.0f",
        "PAPER" if paper_mode else "LIVE",
        args.db_path,
        args.account_value,
    )

    if args.live:
        logger.warning("LIVE MODE ENABLED - real orders will be sent to Hyperliquid")

    # 2. Validate API key
    if not NANSEN_API_KEY:
        logger.error("NANSEN_API_KEY not set. Export it or add to .env file.")
        sys.exit(1)

    # 3. Initialize database
    conn = init_db(args.db_path)
    conn.close()

    # 4. Set initial account value
    set_system_state(args.db_path, "account_value", str(args.account_value))

    # 5. Create exchange client
    if paper_mode:
        # Paper client starts with empty mark prices; scheduler will fetch them
        client = PaperTradeClient(mark_prices={})
        logger.info("Using PaperTradeClient (simulated fills)")
    else:
        # Placeholder for real Hyperliquid client
        # In production, replace with a real HyperliquidClient implementation
        logger.error(
            "Live HyperliquidClient not yet implemented. "
            "Use --paper mode or implement a live client."
        )
        sys.exit(1)

    # 6. Create Nansen client
    nansen_client = NansenClient(api_key=NANSEN_API_KEY)

    # 7. Create and configure scheduler
    scheduler = SystemScheduler(
        client=client,
        nansen_client=nansen_client,
        db_path=args.db_path,
    )
    scheduler.recover_state()

    # 8. Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_requested = False

    def _signal_handler() -> None:
        nonlocal shutdown_requested
        if not shutdown_requested:
            shutdown_requested = True
            logger.info("Received shutdown signal, stopping gracefully...")
            scheduler.request_shutdown()
        else:
            logger.warning("Second signal received, forcing exit")
            sys.exit(1)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # 9. Write initial health check
    write_health_check(args.db_path, health_file=args.health_file)

    # 10. Run scheduler
    try:
        await scheduler.run()
    except asyncio.CancelledError:
        logger.info("Scheduler cancelled")
    finally:
        # Final health check and dashboard export
        try:
            write_health_check(args.db_path, health_file=args.health_file)
            if args.dashboard_file:
                export_dashboard(args.db_path, output_path=args.dashboard_file)

            metrics = collect_metrics(args.db_path)
            alerts = check_alerts(metrics)
            if alerts:
                emit_alerts(alerts)
        except Exception:
            logger.exception("Error during shutdown cleanup")

        await nansen_client.close()
        logger.info("Snap system shut down")


def main(argv: list[str] | None = None) -> None:
    """Synchronous entry point."""
    args = parse_args(argv)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
