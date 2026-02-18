#!/usr/bin/env python3
"""Grid search over 5 filter variations using cached trade data.

Re-scores all traders in the diagnostic DB with different filter/weight
configurations.  No API calls — pure offline re-scoring.

Usage:
    python scripts/grid_search_filters.py --db-path data/snap_diagnostic.db
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, "src")

from snap.scoring import (
    compute_quality_thresholds,
    compute_thresholds,
    compute_trade_metrics,
    passes_tier1,
    score_trader,
)
from snap.variants import VARIANT_LABELS, VARIANTS


# =========================================================================
# Data Loading
# =========================================================================


def load_traders(db_path: str) -> dict[str, dict]:
    """Load merged trader data from the traders + trader_scores tables."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT ts.address, ts.roi_7d, ts.roi_30d, ts.roi_90d,
                  ts.pnl_7d, ts.pnl_30d, ts.pnl_90d,
                  t.label, t.account_value
           FROM trader_scores ts
           JOIN traders t ON ts.address = t.address"""
    ).fetchall()
    traders = {}
    for r in rows:
        addr = r["address"]
        traders[addr] = {
            "address": addr,
            "roi_7d": r["roi_7d"],
            "roi_30d": r["roi_30d"],
            "roi_90d": r["roi_90d"],
            "pnl_7d": r["pnl_7d"],
            "pnl_30d": r["pnl_30d"],
            "pnl_90d": r["pnl_90d"],
            "label": r["label"] or "",
            "account_value": r["account_value"],
        }
    conn.close()
    return traders


def load_trades(db_path: str) -> dict[str, list[dict]]:
    """Load all cached trades grouped by address."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT address, token_symbol, action, side, size, price,
                  value_usd, closed_pnl, fee_usd, timestamp
           FROM trade_history
           ORDER BY address, timestamp"""
    ).fetchall()
    trades_by_addr: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        trades_by_addr[r["address"]].append(dict(r))
    conn.close()
    return dict(trades_by_addr)


# =========================================================================
# Scoring Pipeline (per variant)
# =========================================================================


def run_variant(
    name: str,
    params: dict,
    traders: dict[str, dict],
    trades_by_addr: dict[str, list[dict]],
) -> dict:
    """Run the full scoring pipeline for one variant configuration."""
    percentile = params["FILTER_PERCENTILE"]

    # Build overrides dict for score_trader
    overrides = {
        "WIN_RATE_MIN": params["WIN_RATE_MIN"],
        "WIN_RATE_MAX": params["WIN_RATE_MAX"],
        "TREND_TRADER_MIN_PF": params["TREND_TRADER_MIN_PF"],
        "TREND_TRADER_MAX_WR": params["TREND_TRADER_MAX_WR"],
        "hft_tpd": params["hft_tpd"],
        "hft_ahh": params["hft_ahh"],
        "position_mult": params["position_mult"],
        "weights": params["weights"],
    }

    # Step 1: Compute tier-1 thresholds from the full population
    thresholds = compute_thresholds(traders, percentile=percentile)

    # Step 2: Identify tier-1 passers and compute their trade metrics
    tier1_metrics: list[dict] = []
    tier1_addrs: set[str] = set()

    for addr, t in traders.items():
        if passes_tier1(t["roi_30d"], t["account_value"], thresholds=thresholds):
            tier1_addrs.add(addr)
            trades = trades_by_addr.get(addr, [])
            m = compute_trade_metrics(trades)
            tier1_metrics.append(m)

    # Step 3: Compute quality thresholds from tier-1 passers' trade metrics
    quality_thresholds = compute_quality_thresholds(tier1_metrics, percentile=percentile)

    # Step 4: Score every trader
    results: list[dict] = []
    for addr, t in traders.items():
        trades = trades_by_addr.get(addr, [])
        score = score_trader(
            roi_7d=t["roi_7d"],
            roi_30d=t["roi_30d"],
            roi_90d=t["roi_90d"],
            pnl_7d=t["pnl_7d"],
            pnl_30d=t["pnl_30d"],
            pnl_90d=t["pnl_90d"],
            account_value=t["account_value"],
            label=t["label"],
            trades=trades,
            avg_leverage=None,  # not cached in trade_history
            thresholds=thresholds,
            quality_thresholds=quality_thresholds,
            overrides=overrides,
        )
        score["address"] = addr
        results.append(score)

    # Collect eligible
    eligible = [r for r in results if r["is_eligible"]]
    eligible.sort(key=lambda r: r["composite_score"], reverse=True)

    unique_addrs = {r["address"] for r in eligible}

    # Compute distributions
    scores = [r["composite_score"] for r in eligible]
    rois = [r["roi_30d"] for r in eligible if r["roi_30d"] is not None]
    win_rates = [r["win_rate"] for r in eligible]

    styles = defaultdict(int)
    for r in eligible:
        styles[r["style"]] += 1

    return {
        "name": name,
        "eligible_count": len(eligible),
        "unique_count": len(unique_addrs),
        "score_min": min(scores) if scores else 0,
        "score_med": statistics.median(scores) if scores else 0,
        "score_max": max(scores) if scores else 0,
        "roi_min": min(rois) if rois else 0,
        "roi_med": statistics.median(rois) if rois else 0,
        "roi_max": max(rois) if rois else 0,
        "wr_min": min(win_rates) if win_rates else 0,
        "wr_med": statistics.median(win_rates) if win_rates else 0,
        "wr_max": max(win_rates) if win_rates else 0,
        "styles": dict(styles),
        "top15": eligible[:15],
        "thresholds": thresholds,
        "quality_thresholds": quality_thresholds,
        "tier1_count": len(tier1_addrs),
    }


# =========================================================================
# Report Formatting
# =========================================================================


def print_variant_report(result: dict) -> None:
    """Print detailed report for one variant."""
    print(f"\nVariant: {result['name']}")
    print(f"  Tier-1 passers: {result['tier1_count']}")
    print(
        f"  Eligible: {result['eligible_count']}  |  "
        f"Unique addresses: {result['unique_count']}"
    )
    print(
        f"  Score: min={result['score_min']:.3f}  "
        f"med={result['score_med']:.3f}  "
        f"max={result['score_max']:.3f}"
    )
    print(
        f"  ROI 30d: min={result['roi_min']:.2f}%  "
        f"med={result['roi_med']:.2f}%  "
        f"max={result['roi_max']:.2f}%"
    )
    print(
        f"  Win Rate: min={result['wr_min']:.1%}  "
        f"med={result['wr_med']:.1%}  "
        f"max={result['wr_max']:.1%}"
    )

    style_str = ", ".join(
        f"{k}={v}" for k, v in sorted(result["styles"].items())
    )
    print(f"  Styles: {style_str}")

    # Thresholds
    t = result["thresholds"]
    qt = result["quality_thresholds"]
    print(
        f"  Thresholds: roi_30d>={t['roi_30d']:.4f}% "
        f"acct>=${t['account_value']:.0f}"
    )
    print(
        f"  Quality: min_trades>={qt['min_trade_count']:.0f} "
        f"min_pf>={qt['min_profit_factor']:.2f} "
        f"wr=[{qt['win_rate_min']:.2f}, {qt['win_rate_max']:.2f}]"
    )

    top = result["top15"]
    if top:
        print(f"  Top {min(len(top), 15)}:")
        for i, r in enumerate(top[:15], 1):
            addr_short = r["address"][:8] + "..."
            roi_str = f"{r['roi_30d']:.2f}%" if r["roi_30d"] is not None else "N/A"
            print(
                f"    {i:2d}. {addr_short} "
                f"score={r['composite_score']:.3f} "
                f"roi={roi_str} "
                f"wr={r['win_rate']:.1%} "
                f"style={r['style']}"
            )


def print_comparison_table(all_results: list[dict]) -> None:
    """Print side-by-side comparison table."""
    print("\n" + "=" * 80)
    print("COMPARISON SUMMARY")
    print("=" * 80)
    header = (
        f"{'Variant':<20} {'Eligible':>8} {'Unique':>7} "
        f"{'Med Score':>10} {'Med ROI':>9} {'Med WR':>8} "
        f"{'Tier1':>6}"
    )
    print(header)
    print("-" * 80)
    for r in all_results:
        roi_str = f"{r['roi_med']:.2f}%"
        wr_str = f"{r['wr_med']:.1%}"
        print(
            f"{r['name']:<20} {r['eligible_count']:>8} {r['unique_count']:>7} "
            f"{r['score_med']:>10.3f} {roi_str:>9} {wr_str:>8} "
            f"{r['tier1_count']:>6}"
        )
    print()


# =========================================================================
# Main
# =========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Grid search filter variations")
    parser.add_argument(
        "--db-path",
        default="data/snap_diagnostic.db",
        help="Path to the diagnostic SQLite database",
    )
    args = parser.parse_args()

    display_names = {k: f"{k} ({VARIANT_LABELS[k]})" for k in VARIANTS}

    print("Loading data from", args.db_path, "...")
    traders = load_traders(args.db_path)
    trades_by_addr = load_trades(args.db_path)
    print(
        f"Loaded {len(traders)} traders, "
        f"{sum(len(v) for v in trades_by_addr.values())} trade records "
        f"across {len(trades_by_addr)} addresses"
    )

    print("\n" + "=" * 80)
    print("FILTER GRID SEARCH RESULTS")
    print("=" * 80)

    all_results: list[dict] = []
    for key, params in VARIANTS.items():
        result = run_variant(display_names[key], params, traders, trades_by_addr)
        all_results.append(result)
        print_variant_report(result)

    print_comparison_table(all_results)


if __name__ == "__main__":
    main()
