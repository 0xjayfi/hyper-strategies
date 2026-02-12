"""Stage 6: Scheduler — Single Full Cycle

Runs one complete scheduler iteration: leaderboard refresh, full recompute
(metrics + scoring + filtering + allocation), and position monitoring.
Uses a persistent SQLite DB so you can inspect results after.

Expected: full leaderboard volume, 3-4+ hours runtime.

Prerequisites:
    export NANSEN_API_KEY=your_key

Usage:
    python scripts/stage6_scheduler_cycle.py [--max-traders N] [--db PATH]
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from src.allocation import RiskConfig, compute_allocations
from src.datastore import DataStore
from src.filters import is_fully_eligible
from src.metrics import recompute_all_metrics
from src.nansen_client import NansenClient
from src.position_monitor import monitor_positions
from src.scoring import compute_trader_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("stage6")


class RateLimitCounter(logging.Handler):
    """Counts rate limit warnings."""

    def __init__(self) -> None:
        super().__init__()
        self.count_429 = 0

    def emit(self, record: logging.LogRecord) -> None:
        if "rate limit hit" in record.getMessage().lower():
            self.count_429 += 1


async def refresh_leaderboard(
    client: NansenClient, ds: DataStore, max_traders: int,
) -> list[str]:
    """Fetch leaderboard and ingest into DB. Returns list of addresses."""
    now = datetime.now(timezone.utc)
    date_to = now.strftime("%Y-%m-%d")
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    all_entries = []
    page = 1
    per_page = 100

    while True:
        logger.info("Leaderboard page %d...", page)
        entries = await client.fetch_leaderboard(
            date_from=date_from,
            date_to=date_to,
            pagination={"page": page, "per_page": per_page},
        )
        all_entries.extend(entries)
        if len(entries) < per_page:
            break
        page += 1

    if max_traders > 0:
        all_entries = all_entries[:max_traders]

    for entry in all_entries:
        ds.upsert_trader(entry.trader_address, entry.trader_address_label)
        ds.insert_leaderboard_snapshot(
            address=entry.trader_address,
            date_from=date_from,
            date_to=date_to,
            total_pnl=entry.total_pnl,
            roi=entry.roi,
            account_value=entry.account_value,
        )

    return [e.trader_address for e in all_entries]


def score_and_allocate(
    ds: DataStore, addresses: list[str],
) -> tuple[list[str], dict[str, float]]:
    """Score traders, apply filters, compute allocations. Returns (eligible, allocations)."""
    eligible_traders = []
    scores = {}

    for address in addresses:
        m7 = ds.get_latest_metrics(address, window_days=7)
        m30 = ds.get_latest_metrics(address, window_days=30)
        m90 = ds.get_latest_metrics(address, window_days=90)

        if not m7 or not m30 or not m90:
            continue

        is_eligible, reason = is_fully_eligible(address, m7, m30, m90, ds)

        label = ds.get_trader_label(address)
        positions = ds.get_latest_position_snapshot(address)
        last_trade_time_str = ds.get_last_trade_time(address)

        if last_trade_time_str:
            try:
                last_trade_time = datetime.fromisoformat(last_trade_time_str)
                hours_since = (
                    datetime.now(timezone.utc) - last_trade_time
                ).total_seconds() / 3600
            except (ValueError, TypeError):
                hours_since = 9999
        else:
            hours_since = 9999

        score_dict = compute_trader_score(
            metrics_7d=m7,
            metrics_30d=m30,
            metrics_90d=m90,
            label=label,
            positions=positions,
            hours_since_last_trade=hours_since,
        )
        score_dict["passes_anti_luck"] = 1 if is_eligible else 0
        ds.insert_score(address, score_dict)

        if is_eligible:
            eligible_traders.append(address)
            scores[address] = score_dict

    if not eligible_traders:
        return eligible_traders, {}

    trader_positions = {}
    for address in eligible_traders:
        trader_positions[address] = ds.get_latest_position_snapshot(address)

    risk_config = RiskConfig(max_total_open_usd=50_000.0)
    old_allocations = ds.get_latest_allocations()

    allocations = compute_allocations(
        eligible_traders=eligible_traders,
        scores=scores,
        old_allocations=old_allocations,
        trader_positions=trader_positions,
        risk_config=risk_config,
    )

    ds.insert_allocations(allocations)
    return eligible_traders, allocations


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-traders", type=int, default=0,
        help="Limit to N traders (0 = all). Use 20-50 for a faster test run.",
    )
    parser.add_argument(
        "--db", type=str, default="data/stage6_test.db",
        help="SQLite DB path (persistent so you can inspect after).",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("STAGE 6: Scheduler — Single Full Cycle")
    print("=" * 60)
    print()

    counter = RateLimitCounter()
    logging.getLogger("src.nansen_client").addHandler(counter)

    ds = DataStore(args.db)
    t0 = time.monotonic()
    phase_times = {}

    async with NansenClient() as client:
        # Phase A: Leaderboard refresh
        logger.info("=== Phase A: Leaderboard Refresh ===")
        ta = time.monotonic()
        addresses = await refresh_leaderboard(client, ds, args.max_traders)
        phase_times["leaderboard"] = time.monotonic() - ta
        logger.info("Ingested %d traders", len(addresses))

        # Phase B: Metrics recompute
        logger.info("=== Phase B: Metrics Recompute ===")
        tb = time.monotonic()
        await recompute_all_metrics(
            nansen_client=client,
            datastore=ds,
            trader_addresses=addresses,
            windows=[7, 30, 90],
        )
        phase_times["metrics"] = time.monotonic() - tb

        # Phase C: Scoring + Allocation (offline)
        logger.info("=== Phase C: Scoring + Allocation ===")
        tc = time.monotonic()
        eligible, allocations = score_and_allocate(ds, addresses)
        phase_times["scoring"] = time.monotonic() - tc

        # Phase D: Position monitoring
        logger.info("=== Phase D: Position Monitoring ===")
        td = time.monotonic()
        liquidated = await monitor_positions(client, ds)
        phase_times["monitoring"] = time.monotonic() - td

    elapsed = time.monotonic() - t0

    # Count metrics coverage
    with_metrics = sum(
        1 for a in addresses if ds.get_latest_metrics(a, 30) is not None
    )

    # Report
    print()
    print("=" * 60)
    print("STAGE 6 RESULTS")
    print("=" * 60)
    print()
    print("  Pipeline summary:")
    print(f"    Traders ingested:     {len(addresses)}")
    print(f"    Metrics computed:     {with_metrics}/{len(addresses)}")
    print(f"    Eligible traders:     {len(eligible)}")
    print(f"    Allocations:          {len(allocations)}")
    print(f"    Liquidations:         {len(liquidated)}")
    print(f"    429 rate limits:      {counter.count_429}")
    print()

    print("  Phase timing:")
    for phase, dur in phase_times.items():
        print(f"    {phase:20s} {dur:8.1f}s  ({dur / 60:.1f} min)")
    print(f"    {'TOTAL':20s} {elapsed:8.1f}s  ({elapsed / 60:.1f} min)")
    print()

    if allocations:
        print("  Top allocations:")
        for addr, w in sorted(
            allocations.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            print(f"    {addr[:10]}... = {w:.4f} ({w * 100:.1f}%)")
        print(f"    Weight sum = {sum(allocations.values()):.4f}")
    else:
        print("  No allocations generated")
    print()

    print(f"  Database saved to: {args.db}")
    print("  Inspect with: sqlite3 {args.db} '.tables'")
    print()

    if liquidated:
        print(f"  Liquidated traders: {liquidated}")
        print()

    ds.close()

    # Assessment
    success_rate = with_metrics / len(addresses) * 100 if addresses else 0
    print("STAGE 6 PASSED" if success_rate >= 90 else "STAGE 6 NEEDS WORK")
    print(f"  - Full orchestration cycle completed")
    print(f"  - {success_rate:.0f}% metrics success rate")
    print(f"  - {counter.count_429} rate limit hits")
    if allocations:
        print(f"  - {len(allocations)} allocations generated")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
