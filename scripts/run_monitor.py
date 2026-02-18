#!/usr/bin/env python3
"""Run the position monitoring loop on existing paper positions.

Checks stop-loss, trailing-stop, and time-stop every 60s.
Uses PaperTradeClient with live mark prices from Nansen.

Usage:
    python scripts/run_monitor.py --db-path data/snap_daily_v5.db
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

sys.path.insert(0, "src")

from snap.config import MONITOR_INTERVAL_SECONDS
from snap.execution import PaperTradeClient
from snap.monitoring import monitor_positions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("monitor")


async def main(db_path: str, interval: int) -> None:
    # Build mark prices from current positions in DB
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT token_symbol, entry_price FROM our_positions"
    ).fetchall()
    conn.close()

    if not rows:
        logger.error("No open positions in DB. Run rebalance first.")
        sys.exit(1)

    mark_prices = {r["token_symbol"]: r["entry_price"] for r in rows}
    logger.info("Monitoring %d open positions: %s", len(rows), list(mark_prices.keys()))

    client = PaperTradeClient(mark_prices=mark_prices, live_prices=True)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    logger.info("Starting monitor loop (interval=%ds). Ctrl+C to stop.", interval)
    await monitor_positions(
        client=client,
        db_path=db_path,
        interval_s=interval,
        stop_event=stop_event,
    )
    logger.info("Monitor stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run position monitoring loop")
    parser.add_argument(
        "--db-path", default="data/snap_daily_v5.db", help="SQLite DB path"
    )
    parser.add_argument(
        "--interval", type=int, default=MONITOR_INTERVAL_SECONDS,
        help=f"Seconds between checks (default: {MONITOR_INTERVAL_SECONDS})",
    )
    args = parser.parse_args()
    asyncio.run(main(args.db_path, args.interval))
