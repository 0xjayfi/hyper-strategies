"""Integration smoke test for the multi-angle content pipeline.

Seeds DB with synthetic snapshot data for 2 consecutive days, runs
detection, and verifies at least one angle fires with valid payload.

Does NOT call Typefully or Claude Code.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

# Ensure the repo root is on sys.path so src imports work
sys.path.insert(0, ".")

from src.content.dispatcher import detect_and_select
from src.datastore import DataStore


def main() -> None:
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    print(f"=== Multi-Angle Content Pipeline — Integration Smoke Test ===")
    print(f"Today:     {today}")
    print(f"Yesterday: {yesterday}")
    print()

    # ------------------------------------------------------------------
    # 1. Create an in-memory DataStore
    # ------------------------------------------------------------------
    ds = DataStore(db_path=":memory:")

    # ------------------------------------------------------------------
    # 2. Seed score_snapshots for yesterday and today
    #    Create several traders with varying scores/ranks.
    #    We engineer a significant rank change (trader C jumps from rank 8
    #    to rank 1) so wallet_spotlight and leaderboard_shakeup can fire.
    # ------------------------------------------------------------------
    print("Seeding score_snapshots...")

    traders = [
        ("0xAAA", "Trader A"),
        ("0xBBB", "Trader B"),
        ("0xCCC", "Trader C"),
        ("0xDDD", "Trader D"),
        ("0xEEE", "Trader E"),
        ("0xFFF", "Trader F"),
        ("0xGGG", "Trader G"),
        ("0xHHH", "Trader H"),
        ("0xIII", "Trader I"),
        ("0xJJJ", "Trader J"),
    ]

    for addr, label in traders:
        ds.upsert_trader(addr, label=label)

    # Yesterday: stable ordering 1-10
    for i, (addr, _) in enumerate(traders, start=1):
        ds.insert_score_snapshot(
            snapshot_date=yesterday,
            trader_id=addr,
            rank=i,
            composite_score=round(1.0 - i * 0.08, 4),
            growth_score=0.5,
            drawdown_score=0.5,
            leverage_score=0.5,
            liq_distance_score=0.5,
            diversity_score=0.5,
            consistency_score=0.5,
            smart_money=(i <= 3),  # top 3 are smart money
        )

    # Today: big shuffle — trader C (0xCCC) jumps to rank 1, others shift
    today_order = [
        ("0xCCC", 1, 0.95),  # was rank 3 -> rank 1 (rank_delta=2, score_delta=+0.19)
        ("0xAAA", 2, 0.88),  # was rank 1 -> rank 2
        ("0xEEE", 3, 0.82),  # was rank 5 -> rank 3 (entered top 3)
        ("0xBBB", 4, 0.78),  # was rank 2 -> rank 4
        ("0xDDD", 5, 0.72),  # was rank 4 -> rank 5
        ("0xJJJ", 6, 0.65),  # was rank 10 -> rank 6 (big jump)
        ("0xFFF", 7, 0.60),  # was rank 6 -> rank 7
        ("0xGGG", 8, 0.55),  # was rank 7 -> rank 8
        ("0xHHH", 9, 0.50),  # was rank 8 -> rank 9
        ("0xIII", 10, 0.45), # was rank 9 -> rank 10
    ]

    for addr, rank, score in today_order:
        ds.insert_score_snapshot(
            snapshot_date=today,
            trader_id=addr,
            rank=rank,
            composite_score=score,
            growth_score=0.5 + (0.2 if addr == "0xCCC" else 0.0),
            drawdown_score=0.5,
            leverage_score=0.5,
            liq_distance_score=0.5,
            diversity_score=0.5,
            consistency_score=0.5 + (0.15 if addr == "0xCCC" else 0.0),
            smart_money=(rank <= 3),
        )

    # ------------------------------------------------------------------
    # 3. Seed consensus_snapshots for yesterday and today
    #    Create token data with a direction flip on BTC.
    # ------------------------------------------------------------------
    print("Seeding consensus_snapshots...")

    # Yesterday: BTC bullish, ETH bullish
    ds.insert_consensus_snapshot(yesterday, "BTC", "bullish", 72.0, 500_000.0, 200_000.0)
    ds.insert_consensus_snapshot(yesterday, "ETH", "bullish", 65.0, 300_000.0, 150_000.0)

    # Today: BTC flipped to bearish (direction flip), ETH stayed bullish
    ds.insert_consensus_snapshot(today, "BTC", "bearish", 68.0, 200_000.0, 500_000.0)
    ds.insert_consensus_snapshot(today, "ETH", "bullish", 70.0, 350_000.0, 130_000.0)

    # ------------------------------------------------------------------
    # 4. Seed allocation_snapshots for yesterday and today
    #    Add a new trader entry (0xKKK enters today).
    # ------------------------------------------------------------------
    print("Seeding allocation_snapshots...")

    ds.upsert_trader("0xKKK", label="New Trader K")

    ds.insert_allocation_snapshot(yesterday, "0xAAA", 0.40)
    ds.insert_allocation_snapshot(yesterday, "0xBBB", 0.35)
    ds.insert_allocation_snapshot(yesterday, "0xCCC", 0.25)

    ds.insert_allocation_snapshot(today, "0xAAA", 0.30)
    ds.insert_allocation_snapshot(today, "0xBBB", 0.30)
    ds.insert_allocation_snapshot(today, "0xCCC", 0.20)
    ds.insert_allocation_snapshot(today, "0xKKK", 0.20)  # new entry

    # ------------------------------------------------------------------
    # 5. Seed index_portfolio_snapshots for yesterday and today
    #    Flip a token's side (BTC goes from Long to Short).
    # ------------------------------------------------------------------
    print("Seeding index_portfolio_snapshots...")

    ds.insert_index_portfolio_snapshot(yesterday, "BTC", "Long", 0.40, 100_000.0)
    ds.insert_index_portfolio_snapshot(yesterday, "ETH", "Long", 0.35, 87_500.0)
    ds.insert_index_portfolio_snapshot(yesterday, "SOL", "Short", 0.25, 62_500.0)

    ds.insert_index_portfolio_snapshot(today, "BTC", "Short", 0.40, 100_000.0)  # side flip
    ds.insert_index_portfolio_snapshot(today, "ETH", "Long", 0.35, 87_500.0)
    ds.insert_index_portfolio_snapshot(today, "SOL", "Short", 0.25, 62_500.0)
    ds.insert_index_portfolio_snapshot(today, "AVAX", "Long", 0.10, 25_000.0)  # new entry

    # ------------------------------------------------------------------
    # 6. Run detect_and_select
    # ------------------------------------------------------------------
    print()
    print("Running detect_and_select(datastore)...")
    selections = detect_and_select(ds)

    # ------------------------------------------------------------------
    # 7. Verify results
    # ------------------------------------------------------------------
    print()
    print(f"Selections returned: {len(selections)}")
    assert len(selections) > 0, "FAIL: No angles were selected!"

    all_passed = True
    for sel in selections:
        angle_type = sel["angle_type"]
        payload_path = sel["payload_path"]

        print(f"\n--- Angle: {angle_type} ---")
        print(f"  raw_score:      {sel['raw_score']:.4f}")
        print(f"  effective_score: {sel['effective_score']:.4f}")
        print(f"  auto_publish:   {sel['auto_publish']}")
        print(f"  payload_path:   {payload_path}")

        # Read and validate the payload
        with open(payload_path) as f:
            payload = json.load(f)

        if not payload.get("post_worthy"):
            print(f"  FAIL: payload missing post_worthy=True")
            all_passed = False
        else:
            print(f"  post_worthy:    True")

        # Verify JSON round-trip
        try:
            json.dumps(payload, default=str)
            print(f"  json serializable: True")
        except (TypeError, ValueError) as e:
            print(f"  FAIL: payload not JSON-serializable: {e}")
            all_passed = False

    # ------------------------------------------------------------------
    # 8. Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    if all_passed:
        print("PASS: All selected angles have valid, post-worthy payloads.")
    else:
        print("FAIL: One or more angles had invalid payloads.")
        sys.exit(1)

    print(f"Total angles selected: {len(selections)}")
    for sel in selections:
        print(f"  - {sel['angle_type']} (score={sel['effective_score']:.4f})")
    print("=" * 60)

    ds.close()


if __name__ == "__main__":
    main()
