#!/usr/bin/env python3
"""Score a single trader end-to-end with self-healing rate limit handling.

This script:
1. Clears any stale rate limiter state
2. Fetches leaderboard data (tightened filters) to get ROI/PnL
3. Fetches trades + positions for 1 trader
4. Runs the full scoring pipeline
5. On ANY 429, automatically waits and retries (while loop until solved)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "src")

from datetime import datetime, timedelta, timezone

from snap.config import NANSEN_API_KEY
from snap.nansen_client import NansenClient, NansenRateLimitError
from snap.scoring import (
    _fetch_avg_leverage,
    passes_consistency_gate,
    passes_tier1,
    score_trader,
)

STATE_FILE = "/tmp/snap_nansen_rate_state.json"


def wait_for_clean_window():
    """Block until Nansen's 60s rate window is clear based on persisted state."""
    if not os.path.exists(STATE_FILE):
        print("[WINDOW] No state file — window assumed clear.")
        return

    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print("[WINDOW] Corrupt state file — clearing and proceeding.")
        os.remove(STATE_FILE)
        return

    now = time.time()
    timestamps = [t for t in data.get("timestamps", []) if t > now - 60]
    cooldown = data.get("cooldown_until", 0)

    if cooldown > now:
        wait = cooldown - now
        print(f"[WINDOW] Active cooldown — waiting {wait:.0f}s...")
        time.sleep(wait + 2)
    elif timestamps:
        oldest = min(timestamps)
        wait = 60 - (now - oldest)
        if wait > 0:
            print(f"[WINDOW] {len(timestamps)} recent requests — waiting {wait:.0f}s for window to clear...")
            time.sleep(wait + 2)
        else:
            print(f"[WINDOW] Window clear ({len(timestamps)} stale timestamps).")
    else:
        print("[WINDOW] Window clear.")


async def safe_api_call(label: str, coro_fn, *args, max_retries=10, **kwargs):
    """Call an async API function with automatic 429 retry loop.

    Returns the result on success. Retries on NansenRateLimitError.
    """
    for attempt in range(1, max_retries + 1):
        try:
            result = await coro_fn(*args, **kwargs)
            return result
        except NansenRateLimitError as e:
            print(f"[429] {label} — attempt {attempt}/{max_retries}: {e}")
            # Read retry_after from state file if available
            wait = 60
            if os.path.exists(STATE_FILE):
                try:
                    with open(STATE_FILE) as f:
                        data = json.load(f)
                    cd = data.get("cooldown_until", 0)
                    remaining = cd - time.time()
                    if remaining > 0:
                        wait = remaining + 2
                except Exception:
                    pass
            print(f"[429] Waiting {wait:.0f}s before retry...")
            await asyncio.sleep(wait)

    raise RuntimeError(f"Failed after {max_retries} retries: {label}")


async def main():
    if not NANSEN_API_KEY:
        print("ERROR: NANSEN_API_KEY not set")
        sys.exit(1)

    # Step 0: Wait for clean window
    print("=" * 60)
    print("  SINGLE TRADER SCORING TEST")
    print("=" * 60)
    wait_for_clean_window()

    async with NansenClient(api_key=NANSEN_API_KEY) as client:
        today = datetime.now(timezone.utc).date()

        # Step 1: Fetch leaderboard (tightened filters) for 30d only first
        # to pick a good candidate trader
        print("\n[1/5] Fetching 30d leaderboard (min_pnl=$10,000)...")
        entries_30d = await safe_api_call(
            "leaderboard_30d",
            client.get_leaderboard,
            date_from=(today - timedelta(days=30)).isoformat(),
            date_to=today.isoformat(),
            min_account_value=50_000,
            min_total_pnl=10_000,
        )
        print(f"       Got {len(entries_30d)} traders from 30d leaderboard")

        if not entries_30d:
            print("ERROR: No traders returned")
            return

        # Pick the top trader by ROI
        entries_30d.sort(key=lambda e: e.get("roi", 0), reverse=True)
        target = entries_30d[0]
        addr = target["trader_address"]
        print(f"\n       Target: {addr}")
        print(f"       Label:  {target.get('trader_address_label', '')}")
        print(f"       ROI:    {target.get('roi', 0):.2f}%")
        print(f"       PnL:    ${target.get('total_pnl', 0):,.0f}")
        print(f"       Acct:   ${target.get('account_value', 0):,.0f}")

        # Step 2: Fetch 7d and 90d leaderboard data for this trader
        merged = {
            "roi_7d": None, "roi_30d": target.get("roi", 0),
            "roi_90d": None,
            "pnl_7d": None, "pnl_30d": target.get("total_pnl", 0),
            "pnl_90d": None,
            "account_value": target.get("account_value", 0),
            "label": target.get("trader_address_label", ""),
        }

        for label, days, min_pnl in [("7d", 7, 0), ("90d", 90, 50_000)]:
            print(f"\n[2/5] Fetching {label} leaderboard (min_pnl=${min_pnl:,.0f})...")
            entries = await safe_api_call(
                f"leaderboard_{label}",
                client.get_leaderboard,
                date_from=(today - timedelta(days=days)).isoformat(),
                date_to=today.isoformat(),
                min_account_value=50_000,
                min_total_pnl=min_pnl,
            )
            print(f"       Got {len(entries)} traders")
            for e in entries:
                if e.get("trader_address") == addr:
                    merged[f"roi_{label}"] = e.get("roi", 0)
                    merged[f"pnl_{label}"] = e.get("total_pnl", 0)
                    print(f"       Found target: ROI={e.get('roi', 0):.2f}% PnL=${e.get('total_pnl', 0):,.0f}")
                    break
            else:
                print(f"       Target not found in {label} leaderboard (OK for provisional)")

        # Step 3: Check filters
        print("\n[3/5] Pre-scoring filters:")
        t1 = passes_tier1(merged["roi_30d"], merged["account_value"])
        cg, prov = passes_consistency_gate(
            merged["roi_7d"], merged["roi_30d"], merged["roi_90d"],
            merged["pnl_7d"], merged["pnl_30d"], merged["pnl_90d"],
        )
        print(f"       Tier-1:       {'PASS' if t1 else 'FAIL'}")
        print(f"       Consistency:  {'PASS' if cg else 'FAIL'} (provisional={prov})")
        for k, v in merged.items():
            if isinstance(v, (int, float)) and v is not None:
                print(f"       {k}: {v:,.2f}" if isinstance(v, float) else f"       {k}: {v}")

        # Step 4: Fetch trades + positions
        print(f"\n[4/5] Fetching 90d trade history...")
        trades = await safe_api_call(
            "perp_trades",
            client.get_perp_trades,
            address=addr,
            date_from=(today - timedelta(days=90)).isoformat(),
            date_to=today.isoformat(),
        )
        print(f"       Got {len(trades)} trades")

        print(f"       Fetching positions for avg leverage...")
        avg_lev = await safe_api_call(
            "avg_leverage",
            _fetch_avg_leverage,
            client, addr,
        )
        print(f"       Avg leverage: {avg_lev}")

        # Step 5: Score
        print(f"\n[5/5] Running scoring pipeline...")
        result = score_trader(
            roi_7d=merged["roi_7d"],
            roi_30d=merged["roi_30d"],
            roi_90d=merged["roi_90d"],
            pnl_7d=merged["pnl_7d"],
            pnl_30d=merged["pnl_30d"],
            pnl_90d=merged["pnl_90d"],
            account_value=merged["account_value"],
            label=merged["label"],
            trades=trades,
            avg_leverage=avg_lev,
        )

        print(f"\n{'=' * 60}")
        print(f"  SCORING RESULT: {addr}")
        print(f"{'=' * 60}")
        print(f"  {'Metric':<25} {'Value':>12}")
        print(f"  {'-'*25} {'-'*12}")
        for k, v in result.items():
            if isinstance(v, float):
                print(f"  {k:<25} {v:>12.4f}")
            else:
                print(f"  {k:<25} {str(v):>12}")
        print(f"{'=' * 60}")
        eligible = "YES" if result["is_eligible"] else "NO"
        print(f"  ELIGIBLE: {eligible}  |  COMPOSITE SCORE: {result['composite_score']:.4f}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
