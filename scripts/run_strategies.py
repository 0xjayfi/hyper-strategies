#!/usr/bin/env python3
"""Run multiple scoring strategies against cached trader data and compare results.

Requires data to be already collected (via run_daily_flow.py --collect-only).
Runs each variant's scoring against the same cached data — no API calls.

Usage:
    # Run all variants (V1-V5) and compare
    python scripts/run_strategies.py --db-path data/snap.db

    # Run specific variants only
    python scripts/run_strategies.py --db-path data/snap.db --variants V1 V3 V5
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime

sys.path.insert(0, "src")

from snap.database import get_connection, init_db
from snap.scoring import score_from_cache
from snap.variants import VARIANT_DESCRIPTIONS, VARIANT_LABELS, VARIANTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("strategies")


def _check_data_exists(db_path: str) -> int:
    """Return count of traders in the DB, or 0 if empty."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM traders").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def _run_variant(db_path: str, variant_key: str, overrides: dict) -> list[dict]:
    """Score with a given variant, return eligible traders."""
    # Clear old scores
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM trader_scores")
    finally:
        conn.close()

    return score_from_cache(db_path, overrides=overrides)


def main(db_path: str, variant_keys: list[str]) -> None:
    # Init database
    conn = init_db(db_path)
    conn.close()

    # Verify data exists
    trader_count = _check_data_exists(db_path)
    if trader_count == 0:
        logger.error(
            "No traders in database at %s. Run data collection first:\n"
            "  python scripts/run_daily_flow.py --collect-only --db-path %s",
            db_path,
            db_path,
        )
        sys.exit(1)
    logger.info("Found %d traders in %s", trader_count, db_path)

    # Run each variant
    results: dict[str, list[dict]] = {}
    for vk in variant_keys:
        if vk not in VARIANTS:
            logger.warning("Unknown variant %r, skipping", vk)
            continue
        logger.info("Running variant %s (%s)...", vk, VARIANT_LABELS[vk])
        eligible = _run_variant(db_path, vk, VARIANTS[vk])
        results[vk] = eligible
        logger.info("  %s: %d eligible traders", vk, len(eligible))

    # Print comparison table
    print("\n" + "=" * 120)
    print(f"  STRATEGY COMPARISON  |  DB: {db_path}  |  "
          f"Traders in cache: {trader_count}")
    print("=" * 120)

    # Summary table
    print(f"\n{'Variant':<6} {'Label':<20} {'Eligible':>8} {'Top Score':>10} "
          f"{'Avg Score':>10} {'Avg WR':>8} {'Avg PF':>8} {'Avg Sharpe':>11}")
    print("-" * 90)

    for vk in variant_keys:
        if vk not in results:
            continue
        eligible = results[vk]
        label = VARIANT_LABELS.get(vk, "")
        count = len(eligible)
        if count > 0:
            top_score = eligible[0]["composite_score"]
            avg_score = sum(e["composite_score"] for e in eligible) / count
            avg_wr = sum(e.get("win_rate", 0) or 0 for e in eligible) / count
            avg_pf = sum(e.get("profit_factor", 0) or 0 for e in eligible) / count
            avg_sh = sum(e.get("pseudo_sharpe", 0) or 0 for e in eligible) / count
        else:
            top_score = avg_score = avg_wr = avg_pf = avg_sh = 0.0

        print(f"{vk:<6} {label:<20} {count:>8} {top_score:>10.4f} "
              f"{avg_score:>10.4f} {avg_wr:>7.1%} {avg_pf:>8.2f} {avg_sh:>11.2f}")

    # Per-variant eligible trader details
    for vk in variant_keys:
        if vk not in results or not results[vk]:
            continue
        eligible = results[vk]
        print(f"\n{'='*120}")
        print(f"  {vk} - {VARIANT_LABELS.get(vk, '')} ({len(eligible)} eligible)")
        print(f"  {VARIANT_DESCRIPTIONS.get(vk, '')}")
        print(f"{'='*120}")
        print(f"{'#':>3}  {'Address':<44} {'WR':>6} {'PF':>6} {'Sharpe':>7} "
              f"{'Style':<9} {'Score':>7}")
        print("-" * 90)
        for i, t in enumerate(eligible[:15], 1):
            wr = t.get("win_rate", 0) or 0
            pf = t.get("profit_factor", 0) or 0
            sh = t.get("pseudo_sharpe", 0) or 0
            style = t.get("style", "") or ""
            score = t["composite_score"]
            print(f"{i:>3}  {t['address']:<44} {wr:>5.1%} {pf:>6.2f} {sh:>7.2f} "
                  f"{style:<9} {score:>7.4f}")
        if len(eligible) > 15:
            print(f"     ... and {len(eligible) - 15} more")

    # Overlap analysis — which traders appear eligible across multiple variants
    if len(results) >= 2:
        print(f"\n{'='*120}")
        print("  OVERLAP ANALYSIS")
        print(f"{'='*120}")

        all_addresses: dict[str, list[str]] = {}
        for vk, eligible in results.items():
            for t in eligible:
                addr = t["address"]
                if addr not in all_addresses:
                    all_addresses[addr] = []
                all_addresses[addr].append(vk)

        # Addresses eligible in ALL tested variants
        tested = [vk for vk in variant_keys if vk in results]
        universal = [
            addr for addr, vks in all_addresses.items() if len(vks) == len(tested)
        ]
        print(f"\n  Eligible in ALL {len(tested)} variants: {len(universal)} traders")
        for addr in universal[:10]:
            print(f"    {addr}")

        # Addresses eligible in only one variant
        unique = {
            vk: [addr for addr, vks in all_addresses.items() if vks == [vk]]
            for vk in tested
        }
        for vk in tested:
            if unique[vk]:
                print(f"\n  Unique to {vk}: {len(unique[vk])} traders")
                for addr in unique[vk][:5]:
                    print(f"    {addr}")

    # Export comparison CSV
    date_str = datetime.now().strftime("%Y%m%d")
    csv_path = f"data/strategy_comparison_{date_str}.csv"
    fieldnames = [
        "variant", "address", "composite_score", "win_rate", "profit_factor",
        "pseudo_sharpe", "trade_count", "style",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for vk in variant_keys:
            if vk not in results:
                continue
            for t in results[vk]:
                writer.writerow({
                    "variant": vk,
                    "address": t["address"],
                    "composite_score": t["composite_score"],
                    "win_rate": t.get("win_rate"),
                    "profit_factor": t.get("profit_factor"),
                    "pseudo_sharpe": t.get("pseudo_sharpe"),
                    "trade_count": t.get("trade_count"),
                    "style": t.get("style"),
                })
    logger.info("Saved comparison to %s", csv_path)

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare scoring strategies against cached trader data"
    )
    parser.add_argument("--db-path", default="snap_daily.db", help="SQLite DB path")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=list(VARIANTS.keys()),
        help="Variants to test (default: all). E.g. --variants V1 V3 V5",
    )
    args = parser.parse_args()
    main(args.db_path, args.variants)
