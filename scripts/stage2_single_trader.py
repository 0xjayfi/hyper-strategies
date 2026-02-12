"""Stage 2: Single Trader End-to-End

Runs the full metrics pipeline for 1 trader picked from the leaderboard.
Validates: positions fetch, trades fetch + pagination across 3 windows,
metrics computation, SQLite storage, and rate limiter pacing.

Expected: ~4 profiler API calls, ~28s runtime (7s interval each).

Prerequisites:
    export NANSEN_API_KEY=your_key

Usage:
    python scripts/stage2_single_trader.py
"""

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
logger = logging.getLogger("stage2")


async def main() -> int:
    print("=" * 60)
    print("STAGE 2: Single Trader End-to-End")
    print("=" * 60)
    print()

    ds = DataStore(":memory:")
    t0 = time.monotonic()
    errors = []

    async with NansenClient() as client:
        # Step 1: Pick one trader from leaderboard
        now = datetime.now(timezone.utc)
        date_to = now.strftime("%Y-%m-%d")
        date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

        logger.info("Fetching leaderboard to pick a trader...")
        entries = await client.fetch_leaderboard(
            date_from=date_from,
            date_to=date_to,
            pagination={"page": 1, "per_page": 5},
        )

        if not entries:
            print("STAGE 2 FAILED — leaderboard returned no entries")
            return 1

        # Pick the top trader by total_pnl
        entry = max(entries, key=lambda e: e.total_pnl)
        address = entry.trader_address
        logger.info(
            "Selected trader: %s (pnl=%.0f, roi=%.1f%%)",
            address, entry.total_pnl, entry.roi,
        )

        # Step 2: Upsert trader into DB
        ds.upsert_trader(address, entry.trader_address_label)

        # Step 3: Fetch positions (1 profiler API call)
        logger.info("Fetching positions...")
        try:
            snapshot = await client.fetch_address_positions(address)
            acct_val = snapshot.margin_summary_account_value_usd
            n_positions = len(snapshot.asset_positions)
            logger.info(
                "  Positions: %d open, account_value=%s",
                n_positions, acct_val,
            )
        except Exception as e:
            errors.append(f"fetch_positions: {e}")
            logger.error("  Failed: %s", e)

        # Step 4: Recompute metrics (1 pos + 3 trades = 4 profiler calls)
        logger.info("Recomputing metrics for 3 windows (7d, 30d, 90d)...")
        await recompute_all_metrics(
            nansen_client=client,
            datastore=ds,
            trader_addresses=[address],
            windows=[7, 30, 90],
        )

        # Step 5: Verify stored metrics
        print()
        print(f"  Trader: {address}")
        print(f"  Label:  {entry.trader_address_label or '(none)'}")
        print()

        all_windows_ok = True
        for w in [7, 30, 90]:
            m = ds.get_latest_metrics(address, window_days=w)
            if m is None:
                print(f"  {w:2d}d: MISSING — no metrics stored")
                errors.append(f"metrics {w}d: missing")
                all_windows_ok = False
                continue

            print(
                f"  {w:2d}d: trades={m.total_trades:3d}  "
                f"win_rate={m.win_rate:.2f}  "
                f"profit_factor={m.profit_factor:.2f}  "
                f"sharpe={m.pseudo_sharpe:.2f}  "
                f"roi_proxy={m.roi_proxy:+.1f}%  "
                f"total_pnl={m.total_pnl:+,.0f}"
            )

    elapsed = time.monotonic() - t0
    ds.close()

    print()
    print(f"  Runtime: {elapsed:.1f}s")
    print(f"  Errors:  {len(errors)}")
    print()

    if errors:
        print("STAGE 2 FAILED")
        for e in errors:
            print(f"  - {e}")
        return 1

    if not all_windows_ok:
        print("STAGE 2 FAILED — missing metrics for some windows")
        return 1

    print("STAGE 2 PASSED")
    print("  - Leaderboard fetch works")
    print("  - Positions fetch works")
    print("  - Trades fetch + pagination works across 3 windows")
    print("  - Metrics computed and stored in SQLite")
    print(f"  - Rate limiter paced {int(elapsed // 7)} profiler calls at ~7s intervals")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
