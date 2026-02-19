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
    DATA_DB_PATH,
    DB_PATH,
    HEALTH_CHECK_FILE,
    LOG_FILE,
    NANSEN_API_KEY,
    PAPER_TRADE,
    STRATEGY_DB_PATH,
)
from snap.database import init_data_db, init_db, init_strategy_db
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
from snap.scheduler import SystemScheduler, get_system_state, set_system_state
from snap.tui import console, print_portfolio, print_scores, render_status_bar

logger = logging.getLogger(__name__)

_COMMANDS_HELP = (
    "[r] Refresh traders  [b] Rebalance  [m] Monitor  "
    "[s] Scores  [p] Portfolio  [q] Quit"
)


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
        "--data-db",
        default=DATA_DB_PATH or None,
        help="Data DB path (defaults to --db-path)",
    )
    parser.add_argument(
        "--strategy-db",
        default=STRATEGY_DB_PATH or None,
        help="Strategy DB path (defaults to --db-path)",
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
    parser.add_argument(
        "--classic",
        action="store_true",
        default=False,
        help="Use the classic Rich-based TUI instead of the new Textual interface",
    )
    args = parser.parse_args(argv)

    # If neither flag given, use config default
    if not args.live and not args.paper:
        if PAPER_TRADE:
            args.paper = True
        else:
            args.live = True

    # Resolve data/strategy DB paths (default to --db-path)
    args.data_db = args.data_db or args.db_path
    args.strategy_db = args.strategy_db or args.db_path

    return args


def _print_status(scheduler: SystemScheduler, args: argparse.Namespace) -> None:
    """Print the status bar with current scheduler state."""
    mode = "PAPER" if not args.live else "LIVE"
    acct_str = get_system_state(args.strategy_db, "account_value")
    acct_val = float(acct_str) if acct_str else args.account_value
    last_refresh = get_system_state(args.strategy_db, "last_trader_refresh_at")
    last_rebalance = get_system_state(args.strategy_db, "last_rebalance_at")

    panel = render_status_bar(
        state=scheduler.state.value,
        mode=mode,
        account_value=acct_val,
        last_refresh=last_refresh,
        last_rebalance=last_rebalance,
    )
    console.print(panel)


async def _input_loop(
    scheduler: SystemScheduler,
    args: argparse.Namespace,
) -> None:
    """Non-blocking stdin reader for interactive commands."""
    loop = asyncio.get_running_loop()

    while not scheduler._stop_event.is_set():
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
        except EOFError:
            break

        if not line:
            break

        key = line.strip().lower()
        if not key:
            continue

        if key == "q":
            console.print("[dim]Shutting down...[/]")
            scheduler.request_shutdown()
            break
        elif key == "r":
            console.print("[dim]Running trader refresh...[/]")
            await scheduler._run_trader_refresh()
            _print_status(scheduler, args)
        elif key == "b":
            console.print("[dim]Running rebalance...[/]")
            await scheduler._run_rebalance()
            _print_status(scheduler, args)
        elif key == "m":
            console.print("[dim]Running monitor pass...[/]")
            await scheduler._run_monitor()
            _print_status(scheduler, args)
        elif key == "s":
            print_scores(args.strategy_db)
        elif key == "p":
            print_portfolio(args.strategy_db)
        else:
            console.print(f"[dim]Unknown command: {key!r}[/]")
            console.print(f"[dim]{_COMMANDS_HELP}[/]")


async def run(args: argparse.Namespace) -> None:
    """Main async entry point.

    Sets up all components and runs the scheduler + input loop concurrently.
    """
    paper_mode = not args.live

    # 1. Initialize logging
    setup_json_logging(log_file=args.log_file)

    logger.info(
        "Starting Snap system: mode=%s data_db=%s strategy_db=%s account_value=%.0f",
        "PAPER" if paper_mode else "LIVE",
        args.data_db,
        args.strategy_db,
        args.account_value,
    )

    if args.live:
        logger.warning("LIVE MODE ENABLED - real orders will be sent to Hyperliquid")

    # 2. Validate API key
    if not NANSEN_API_KEY:
        logger.error("NANSEN_API_KEY not set. Export it or add to .env file.")
        sys.exit(1)

    # 3. Initialize database(s)
    if args.data_db != args.strategy_db:
        conn = init_data_db(args.data_db)
        conn.close()
        conn = init_strategy_db(args.strategy_db)
        conn.close()
    else:
        conn = init_db(args.db_path)
        conn.close()

    # 4. Set initial account value (strategy DB)
    set_system_state(args.strategy_db, "account_value", str(args.account_value))

    # 5. Create exchange client
    if paper_mode:
        client = PaperTradeClient(mark_prices={}, live_prices=True)
        logger.info("Using PaperTradeClient (simulated fills)")
    else:
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
        db_path=args.data_db,
        strategy_db_path=args.strategy_db,
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
    write_health_check(args.strategy_db, health_file=args.health_file)

    # 10. Print startup banner
    _print_status(scheduler, args)
    print_portfolio(args.strategy_db)
    console.print(f"\n[bold]{_COMMANDS_HELP}[/]\n")

    # 11. Run scheduler + input loop concurrently
    try:
        await asyncio.gather(
            scheduler.run(),
            _input_loop(scheduler, args),
        )
    except asyncio.CancelledError:
        logger.info("Scheduler cancelled")
    finally:
        # Final health check and dashboard export
        try:
            write_health_check(args.strategy_db, health_file=args.health_file)
            if args.dashboard_file:
                export_dashboard(
                    args.strategy_db,
                    output_path=args.dashboard_file,
                    data_db_path=args.data_db,
                )

            metrics = collect_metrics(args.strategy_db, data_db_path=args.data_db)
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
    if args.classic:
        asyncio.run(run(args))
    else:
        from snap.tui_app import SnapApp

        app = SnapApp(db_path=args.strategy_db, data_db_path=args.data_db)
        app.run()


if __name__ == "__main__":
    main()
