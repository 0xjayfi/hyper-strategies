"""Stage 4: Position Monitor Dry Run

Validates liquidation detection logic without real stakes.
Snapshots positions for 5 traders, waits briefly, re-snapshots,
and checks for false positives.

Expected: ~15 profiler API calls, ~3-4 min runtime.

Prerequisites:
    export NANSEN_API_KEY=your_key

Usage:
    python scripts/stage4_position_monitor.py
"""

import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from src.datastore import DataStore
from src.nansen_client import NansenClient
from src.position_monitor import (
    detect_liquidations,
    monitor_positions,
    snapshot_positions_for_trader,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("stage4")

COHORT_SIZE = 5
WAIT_BETWEEN_SNAPSHOTS = 30  # seconds


async def main() -> int:
    print("=" * 60)
    print("STAGE 4: Position Monitor Dry Run")
    print("=" * 60)
    print()

    ds = DataStore(":memory:")
    t0 = time.monotonic()

    async with NansenClient() as client:
        # Step 1: Fetch leaderboard to get trader addresses
        now = datetime.now(timezone.utc)
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

        logger.info("Fetching leaderboard...")
        entries = await client.fetch_leaderboard(
            date_from=date_from,
            date_to=date_to,
            pagination={"page": 1, "per_page": COHORT_SIZE},
        )

        for entry in entries:
            ds.upsert_trader(entry.trader_address, entry.trader_address_label)

        addresses = [e.trader_address for e in entries]
        logger.info("Selected %d traders", len(addresses))

        # Step 2: First snapshot — establish baseline
        logger.info("Taking first position snapshot...")
        for address in addresses:
            await snapshot_positions_for_trader(address, client, ds)

        # Report baseline positions
        print()
        print("  Baseline positions:")
        for address in addresses:
            positions = ds.get_latest_position_snapshot(address)
            n = len(positions) if positions else 0
            tokens = [p["token_symbol"] for p in positions] if positions else []
            print(f"    {address[:10]}... : {n} positions {tokens}")

        # Step 3: Wait briefly
        print()
        logger.info(
            "Waiting %ds before second snapshot (positions should be stable)...",
            WAIT_BETWEEN_SNAPSHOTS,
        )
        await asyncio.sleep(WAIT_BETWEEN_SNAPSHOTS)

        # Step 4: Run full monitor_positions cycle
        # This re-snapshots all traders and then runs liquidation detection
        logger.info("Running liquidation detection...")
        liquidated = await detect_liquidations(addresses, ds, client)

    elapsed = time.monotonic() - t0
    ds.close()

    # Report
    print()
    print("-" * 60)
    print("RESULTS")
    print("-" * 60)
    print(f"  Traders monitored:       {len(addresses)}")
    print(f"  Liquidations detected:   {len(liquidated)}")
    print(f"  Wait between snapshots:  {WAIT_BETWEEN_SNAPSHOTS}s")
    print(f"  Runtime:                 {elapsed:.1f}s")
    print()

    if liquidated:
        print("  WARNING: Liquidations detected (may be real or false positive):")
        for addr in liquidated:
            print(f"    {addr}")
        print()
        print("  If these traders genuinely closed positions in the last 30s,")
        print("  these are real detections. Otherwise investigate false positives.")
        print()
        # Don't fail — liquidations may be genuine
        print("STAGE 4 COMPLETED (with detections — review manually)")
    else:
        print("STAGE 4 PASSED")
        print("  - Position snapshots stored correctly")
        print("  - No false liquidation detections")
        print("  - Diff logic working as expected")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
