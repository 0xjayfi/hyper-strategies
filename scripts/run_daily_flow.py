#!/usr/bin/env python3
"""Run the daily data flow: fetch leaderboard, score traders, print results.

Usage:
    python scripts/run_daily_flow.py [--db-path snap_daily.db]
    python scripts/run_daily_flow.py --variant V5 --db-path data/snap_v5.db
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from datetime import datetime

# Ensure the src package is importable
sys.path.insert(0, "src")

from snap.config import NANSEN_API_KEY
from snap.database import get_connection, init_db
from snap.nansen_client import NansenClient
from snap.scoring import refresh_trader_universe
from snap.variants import VARIANT_LABELS, VARIANTS


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("daily_flow")


async def main(db_path: str, variant: str | None = None) -> None:
    if not NANSEN_API_KEY:
        logger.error("NANSEN_API_KEY not set. Export it or add to .env")
        sys.exit(1)

    # 1. Init database
    logger.info("Initializing database at %s", db_path)
    conn = init_db(db_path)
    conn.close()

    # 2. Resolve variant overrides
    overrides = None
    if variant:
        variant_key = variant.upper()
        if variant_key not in VARIANTS:
            logger.error(
                "Unknown variant %r. Available: %s",
                variant,
                ", ".join(VARIANTS.keys()),
            )
            sys.exit(1)
        overrides = VARIANTS[variant_key]
        logger.info(
            "Using variant %s (%s)", variant_key, VARIANT_LABELS[variant_key]
        )

    # 3. Run the full trader universe refresh
    async with NansenClient(api_key=NANSEN_API_KEY) as client:
        logger.info("Starting trader universe refresh...")
        eligible_count = await refresh_trader_universe(
            client, db_path, overrides=overrides
        )
        logger.info("Refresh complete. %d eligible traders found.", eligible_count)

    # 3. Query and print results
    conn = get_connection(db_path)
    try:
        # All scored traders, ordered by composite score
        rows = conn.execute(
            """SELECT
                ts.address,
                t.label,
                t.account_value,
                ts.roi_7d,
                ts.roi_30d,
                ts.roi_90d,
                ts.pnl_7d,
                ts.pnl_30d,
                ts.pnl_90d,
                ts.win_rate,
                ts.profit_factor,
                ts.pseudo_sharpe,
                ts.trade_count,
                ts.style,
                ts.composite_score,
                ts.passes_tier1,
                ts.passes_consistency,
                ts.passes_quality,
                ts.is_eligible,
                ts.fail_reason
            FROM trader_scores ts
            JOIN traders t ON t.address = ts.address
            ORDER BY ts.composite_score DESC"""
        ).fetchall()

        if not rows:
            logger.warning("No traders found in database.")
            return

        # Print summary header
        print("\n" + "=" * 120)
        print(f"  DAILY TRADER EXTRACTION  |  Total scored: {len(rows)}  |  "
              f"Eligible: {sum(1 for r in rows if r['is_eligible'])}  |  "
              f"DB: {db_path}")
        print("=" * 120)

        # Print eligible traders
        eligible_rows = [r for r in rows if r["is_eligible"]]
        if eligible_rows:
            print(f"\n{'='*120}")
            print(f"  ELIGIBLE TRADERS (Top {len(eligible_rows)} by composite score)")
            print(f"{'='*120}")
            print(f"{'#':>3}  {'Address':<44} {'Label':<16} {'Acct Val':>10} "
                  f"{'ROI 30d':>8} {'WR':>6} {'PF':>6} {'Sharpe':>7} "
                  f"{'Style':<9} {'Score':>7}")
            print("-" * 120)

            for i, row in enumerate(eligible_rows, 1):
                addr = row["address"]
                label = (row["label"] or "")[:15]
                acct = row["account_value"] or 0
                roi_30d = row["roi_30d"] or 0
                wr = row["win_rate"] or 0
                pf = row["profit_factor"] or 0
                sharpe = row["pseudo_sharpe"] or 0
                style = row["style"] or ""
                score = row["composite_score"] or 0

                print(f"{i:>3}  {addr:<44} {label:<16} {acct:>10,.0f} "
                      f"{roi_30d:>7.1f}% {wr:>5.1%} {pf:>6.2f} {sharpe:>7.2f} "
                      f"{style:<9} {score:>7.4f}")

        # Print ineligible traders (condensed)
        ineligible_rows = [r for r in rows if not r["is_eligible"]]
        if ineligible_rows:
            print(f"\n{'='*140}")
            print(f"  INELIGIBLE TRADERS ({len(ineligible_rows)} total, top 20 shown)")
            print(f"{'='*140}")
            print(f"{'#':>3}  {'Address':<44} {'Label':<16} {'Acct Val':>10} "
                  f"{'ROI 30d':>8} {'Trades':>7} {'Style':<9} {'Score':>7}  "
                  f"{'Fail Reason':<30}")
            print("-" * 140)

            for i, row in enumerate(ineligible_rows[:20], 1):
                addr = row["address"]
                label = (row["label"] or "")[:15]
                acct = row["account_value"] or 0
                roi_30d = row["roi_30d"] or 0
                tc = row["trade_count"] or 0
                style = row["style"] or ""
                score = row["composite_score"] or 0
                fail = row["fail_reason"] or ""

                print(f"{i:>3}  {addr:<44} {label:<16} {acct:>10,.0f} "
                      f"{roi_30d:>7.1f}% {tc:>7} {style:<9} {score:>7.4f}  "
                      f"{fail:<30}")

            if len(ineligible_rows) > 20:
                print(f"     ... and {len(ineligible_rows) - 20} more")

            # Print fail reason summary
            reason_counts: dict[str, int] = {}
            for row in ineligible_rows:
                fr = row["fail_reason"] or ""
                for reason in fr.split(","):
                    reason = reason.strip()
                    if reason:
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
            if reason_counts:
                sorted_reasons = sorted(
                    reason_counts.items(), key=lambda x: x[1], reverse=True
                )
                print(f"\n  Fail reason summary: "
                      + ", ".join(f"{r}={c}" for r, c in sorted_reasons))

        # Export eligible addresses for easy copy
        if eligible_rows:
            print(f"\n{'='*120}")
            print("  ELIGIBLE WALLET ADDRESSES (copy-paste ready)")
            print(f"{'='*120}")
            for row in eligible_rows:
                print(row["address"])

        # Save all results to CSV
        date_str = datetime.now().strftime("%Y%m%d")
        csv_path = f"data/traders_{date_str}.csv"
        fieldnames = [
            "address", "label", "account_value", "roi_7d", "roi_30d",
            "roi_90d", "pnl_7d", "pnl_30d", "pnl_90d", "win_rate",
            "profit_factor", "pseudo_sharpe", "trade_count", "style",
            "composite_score", "passes_tier1", "passes_consistency",
            "passes_quality", "is_eligible", "fail_reason",
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row[k] for k in fieldnames})
        logger.info("Saved %d traders to %s", len(rows), csv_path)

        # Save eligible-only CSV
        if eligible_rows:
            elig_path = f"data/eligible_{date_str}.csv"
            with open(elig_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in eligible_rows:
                    writer.writerow({k: row[k] for k in fieldnames})
            logger.info("Saved %d eligible traders to %s", len(eligible_rows), elig_path)

        print()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run daily trader extraction flow")
    parser.add_argument("--db-path", default="snap_daily.db", help="SQLite DB path")
    parser.add_argument(
        "--variant",
        choices=list(VARIANTS.keys()),
        default=None,
        help="Filter variant to use (V1-V5). Default: production config.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.db_path, variant=args.variant))
