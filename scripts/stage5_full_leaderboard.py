"""Stage 5: Full Leaderboard — Real Volume Stress Test

Runs recompute_all_metrics against the full leaderboard to stress-test
rate limiting under sustained load. Tracks 429 errors, runtime, and
per-trader success/failure.

Expected: hundreds of profiler API calls, 1-3+ hours runtime.

Prerequisites:
    export NANSEN_API_KEY=your_key

Usage:
    python scripts/stage5_full_leaderboard.py [--max-traders N]
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from src.datastore import DataStore
from src.metrics import recompute_all_metrics
from src.nansen_client import NansenClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("stage5")


class RateLimitCounter(logging.Handler):
    """Counts rate limit warnings in the log stream."""

    def __init__(self) -> None:
        super().__init__()
        self.count_429 = 0
        self.count_5xx = 0

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "rate limit hit" in msg.lower():
            self.count_429 += 1
        elif "server error" in msg.lower() and "status=" in msg:
            self.count_5xx += 1


async def fetch_full_leaderboard(client: NansenClient) -> list:
    """Fetch all leaderboard pages."""
    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    all_entries = []
    page = 1
    per_page = 100

    while True:
        logger.info("Fetching leaderboard page %d...", page)
        entries = await client.fetch_leaderboard(
            date_from=date_from,
            date_to=date_to,
            pagination={"page": page, "per_page": per_page},
        )
        all_entries.extend(entries)
        logger.info("  Got %d entries (total: %d)", len(entries), len(all_entries))

        if len(entries) < per_page:
            break
        page += 1

    return all_entries


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-traders", type=int, default=0,
        help="Limit to N traders (0 = all)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("STAGE 5: Full Leaderboard — Real Volume Stress Test")
    print("=" * 60)
    print()

    # Attach counter to track 429s
    counter = RateLimitCounter()
    logging.getLogger("src.nansen_client").addHandler(counter)

    ds = DataStore(":memory:")
    t0 = time.monotonic()

    async with NansenClient() as client:
        # Step 1: Fetch full leaderboard
        entries = await fetch_full_leaderboard(client)

        if args.max_traders > 0:
            entries = entries[:args.max_traders]
            logger.info("Limited to %d traders", len(entries))

        addresses = []
        for entry in entries:
            ds.upsert_trader(entry.trader_address, entry.trader_address_label)
            addresses.append(entry.trader_address)

        logger.info("Total traders: %d", len(addresses))
        print(f"  Traders to process: {len(addresses)}")
        print(f"  Estimated profiler calls: ~{len(addresses) * 4}")
        print(f"  Estimated runtime at 7s/call: ~{len(addresses) * 4 * 7 / 60:.0f} min")
        print()

        # Step 2: Recompute metrics for ALL traders
        logger.info("Starting full metrics recompute...")
        t_metrics = time.monotonic()
        await recompute_all_metrics(
            nansen_client=client,
            datastore=ds,
            trader_addresses=addresses,
            windows=[7, 30, 90],
        )
        metrics_elapsed = time.monotonic() - t_metrics

    elapsed = time.monotonic() - t0
    total_429 = counter.count_429
    total_5xx = counter.count_5xx

    # Count how many traders got metrics
    traders_with_metrics = 0
    traders_missing = 0
    for addr in addresses:
        m30 = ds.get_latest_metrics(addr, window_days=30)
        if m30 is not None:
            traders_with_metrics += 1
        else:
            traders_missing += 1

    ds.close()

    # Report
    print()
    print("-" * 60)
    print("RESULTS")
    print("-" * 60)
    print(f"  Total traders:          {len(addresses)}")
    print(f"  Metrics computed:       {traders_with_metrics}")
    print(f"  Metrics missing:        {traders_missing}")
    print(f"  429 rate limit hits:    {total_429}")
    print(f"  5xx server errors:      {total_5xx}")
    print(f"  Metrics phase runtime:  {metrics_elapsed:.0f}s ({metrics_elapsed / 60:.1f} min)")
    print(f"  Total runtime:          {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    if len(addresses) > 0:
        print(f"  Avg per trader:         {metrics_elapsed / len(addresses):.1f}s")
    print()

    # Assess
    success_rate = traders_with_metrics / len(addresses) * 100 if addresses else 0

    if total_429 > 10:
        print(f"WARNING: {total_429} rate limit hits — consider tuning profiler limits")
    if traders_missing > len(addresses) * 0.1:
        print(f"WARNING: {traders_missing} traders missing metrics ({100 - success_rate:.0f}% failure)")

    print()
    if total_429 <= 5 and success_rate >= 95:
        print("STAGE 5 PASSED")
        print(f"  - {success_rate:.0f}% success rate")
        print(f"  - {total_429} retried 429s (acceptable)")
        print(f"  - Rate limiter held under sustained load")
    elif total_429 <= 15 and success_rate >= 90:
        print("STAGE 5 MARGINAL — review rate limit tuning")
    else:
        print("STAGE 5 NEEDS WORK — too many failures or 429s")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
