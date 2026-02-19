#!/usr/bin/env python3
"""Run the daily data flow: fetch leaderboard, score traders, print results.

Supports three modes:
    --collect-only   Fetch data from Nansen API and cache in SQLite (no scoring)
    --score-only     Score traders from cached data only (no API calls)
    (default)        Run both collection and scoring

Usage:
    # Full pipeline (collect + score)
    python scripts/run_daily_flow.py --db-path data/snap.db

    # Collect data only (expensive, do once)
    python scripts/run_daily_flow.py --collect-only --db-path data/snap.db

    # Score from cache with a specific variant (cheap, run many times)
    python scripts/run_daily_flow.py --score-only --variant V2 --db-path data/snap.db
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
from snap.database import get_connection, init_data_db, init_db, init_strategy_db
from snap.nansen_client import NansenClient
from snap.variants import VARIANT_LABELS, VARIANTS


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("daily_flow")


def _print_results(
    db_path: str,
    variant_label: str | None = None,
    *,
    data_db_path: str | None = None,
) -> None:
    """Query and print scored results from the database."""
    conn = get_connection(db_path)
    try:
        if data_db_path and data_db_path != db_path:
            # Two-DB mode: query separately and join in Python
            score_rows = conn.execute(
                """SELECT address, roi_7d, roi_30d, roi_90d,
                          pnl_7d, pnl_30d, pnl_90d,
                          win_rate, profit_factor, pseudo_sharpe, trade_count,
                          style, composite_score,
                          passes_tier1, passes_consistency, passes_quality,
                          is_eligible, fail_reason
                   FROM trader_scores
                   ORDER BY composite_score DESC"""
            ).fetchall()
            data_conn = get_connection(data_db_path)
            try:
                trader_info = {}
                for r in data_conn.execute(
                    "SELECT address, label, account_value FROM traders"
                ).fetchall():
                    trader_info[r["address"]] = {
                        "label": r["label"],
                        "account_value": r["account_value"],
                    }
            finally:
                data_conn.close()
            rows = []
            for r in score_rows:
                info = trader_info.get(r["address"], {"label": "", "account_value": 0.0})
                row = dict(r)
                row["label"] = info["label"]
                row["account_value"] = info["account_value"]
                rows.append(row)
        else:
            rows = [
                dict(r) for r in conn.execute(
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
            ]

        if not rows:
            logger.warning("No traders found in database.")
            return

        # Print summary header
        extra = f"  |  Variant: {variant_label}" if variant_label else ""
        print("\n" + "=" * 120)
        print(f"  DAILY TRADER EXTRACTION  |  Total scored: {len(rows)}  |  "
              f"Eligible: {sum(1 for r in rows if r['is_eligible'])}  |  "
              f"DB: {db_path}{extra}")
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
        suffix = f"_{variant_label}" if variant_label else ""
        csv_path = f"data/traders_{date_str}{suffix}.csv"
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
            elig_path = f"data/eligible_{date_str}{suffix}.csv"
            with open(elig_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in eligible_rows:
                    writer.writerow({k: row[k] for k in fieldnames})
            logger.info("Saved %d eligible traders to %s", len(eligible_rows), elig_path)

        print()
    finally:
        conn.close()


async def run_collect(db_path: str) -> None:
    """Run data collection only (no scoring)."""
    if not NANSEN_API_KEY:
        logger.error("NANSEN_API_KEY not set. Export it or add to .env")
        sys.exit(1)

    from snap.collector import collect_trader_data

    async with NansenClient(api_key=NANSEN_API_KEY) as client:
        logger.info("Starting data collection...")
        summary = await collect_trader_data(client, db_path)
        logger.info("Collection complete: %s", summary)


def run_score(
    db_path: str,
    variant: str | None = None,
    *,
    strategy_db_path: str | None = None,
) -> None:
    """Run scoring only from cached data (no API calls)."""
    from snap.scoring import score_from_cache

    score_db = strategy_db_path or db_path

    overrides = None
    variant_label = None
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
        variant_label = f"{variant_key} ({VARIANT_LABELS[variant_key]})"
        logger.info("Using variant %s", variant_label)

    # Clear old scores before re-scoring (in strategy DB)
    conn = get_connection(score_db)
    try:
        with conn:
            conn.execute("DELETE FROM trader_scores")
        logger.info("Cleared old trader_scores")
    finally:
        conn.close()

    logger.info("Scoring from cached data...")
    eligible = score_from_cache(
        db_path, overrides=overrides, strategy_db_path=strategy_db_path
    )
    logger.info("Scoring complete: %d eligible traders", len(eligible))

    _print_results(
        score_db,
        variant_label=variant_label,
        data_db_path=db_path if strategy_db_path else None,
    )


async def run_full(
    db_path: str,
    variant: str | None = None,
    *,
    strategy_db_path: str | None = None,
) -> None:
    """Run the full pipeline: collect + score."""
    if not NANSEN_API_KEY:
        logger.error("NANSEN_API_KEY not set. Export it or add to .env")
        sys.exit(1)

    from snap.scoring import refresh_trader_universe

    score_db = strategy_db_path or db_path

    overrides = None
    variant_label = None
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
        variant_label = f"{variant_key} ({VARIANT_LABELS[variant_key]})"
        logger.info("Using variant %s", variant_label)

    async with NansenClient(api_key=NANSEN_API_KEY) as client:
        logger.info("Starting trader universe refresh...")
        eligible_count = await refresh_trader_universe(
            client, db_path, strategy_db_path=strategy_db_path, overrides=overrides
        )
        logger.info("Refresh complete. %d eligible traders found.", eligible_count)

    _print_results(
        score_db,
        variant_label=variant_label,
        data_db_path=db_path if strategy_db_path else None,
    )


async def main(args: argparse.Namespace) -> None:
    data_db = args.data_db or args.db_path
    strategy_db = args.strategy_db or args.db_path

    # Init database(s)
    if data_db != strategy_db:
        logger.info("Initializing data DB at %s", data_db)
        conn = init_data_db(data_db)
        conn.close()
        logger.info("Initializing strategy DB at %s", strategy_db)
        conn = init_strategy_db(strategy_db)
        conn.close()
    else:
        logger.info("Initializing database at %s", data_db)
        conn = init_db(data_db)
        conn.close()

    strategy_path = strategy_db if data_db != strategy_db else None

    if args.collect_only:
        await run_collect(data_db)
    elif args.score_only:
        run_score(data_db, variant=args.variant, strategy_db_path=strategy_path)
    else:
        await run_full(data_db, variant=args.variant, strategy_db_path=strategy_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run daily trader extraction flow")
    parser.add_argument("--db-path", default="snap_daily.db", help="SQLite DB path")
    parser.add_argument(
        "--data-db",
        default=None,
        help="Data DB path (defaults to --db-path)",
    )
    parser.add_argument(
        "--strategy-db",
        default=None,
        help="Strategy DB path (defaults to --db-path)",
    )
    parser.add_argument(
        "--variant",
        choices=list(VARIANTS.keys()),
        default=None,
        help="Filter variant to use (V1-V5). Default: production config.",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--collect-only",
        action="store_true",
        default=False,
        help="Only fetch and cache data from Nansen API (no scoring)",
    )
    mode_group.add_argument(
        "--score-only",
        action="store_true",
        default=False,
        help="Only score traders from cached data (no API calls)",
    )

    args = parser.parse_args()
    asyncio.run(main(args))
