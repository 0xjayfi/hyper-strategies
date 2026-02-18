#!/usr/bin/env python3
"""Run a single paper-trade rebalance cycle against the eligible traders.

Steps:
  1. Load top 15 eligible traders from the DB (scored by daily flow)
  2. Fetch each trader's current Hyperliquid positions via Nansen API
  3. Build TraderSnapshots, compute target portfolio, apply risk overlay
  4. Diff against our current positions (empty on first run)
  5. Execute via PaperTradeClient, print summary

Usage:
    python scripts/run_rebalance.py [--db-path data/snap_diagnostic.db] [--account-value 10000]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid

sys.path.insert(0, "src")

from snap.config import ACCOUNT_VALUE, NANSEN_API_KEY, TOP_N_TRADERS
from snap.database import get_connection, init_db
from snap.execution import PaperTradeClient, execute_rebalance
from snap.ingestion import ingest_positions
from snap.nansen_client import NansenClient
from snap.portfolio import (
    TraderSnapshot,
    apply_risk_overlay,
    compute_rebalance_diff,
    compute_target_portfolio,
    get_current_positions,
    get_tracked_traders,
    net_opposing_targets,
    store_target_allocations,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("rebalance")


async def main(db_path: str, account_value: float) -> None:
    if not NANSEN_API_KEY:
        logger.error("NANSEN_API_KEY not set. Export it or add to .env")
        sys.exit(1)

    # Ensure all tables exist
    conn = init_db(db_path)
    conn.close()

    # ── Step 1: Load eligible traders ────────────────────────────────────
    tracked = get_tracked_traders(db_path, TOP_N_TRADERS)
    if not tracked:
        logger.error("No eligible traders in DB. Run daily flow first.")
        sys.exit(1)

    addresses = [t["address"] for t in tracked]
    score_map = {t["address"]: t["composite_score"] for t in tracked}

    print(f"\n{'='*90}")
    print(f"  REBALANCE CYCLE  |  {len(tracked)} tracked traders  |  "
          f"account=${account_value:,.0f}  |  DB: {db_path}")
    print(f"{'='*90}")
    print(f"\nTracked traders (by score):")
    for i, t in enumerate(tracked, 1):
        print(f"  {i:>2}. {t['address'][:14]}...  score={t['composite_score']:.4f}")

    # ── Step 2: Fetch current positions via Nansen ───────────────────────
    rebalance_id = str(uuid.uuid4())
    snapshot_batch = rebalance_id

    print(f"\nFetching positions for {len(addresses)} traders...")
    async with NansenClient(api_key=NANSEN_API_KEY) as client:
        snap_count = await ingest_positions(
            client, db_path, addresses, snapshot_batch
        )
    print(f"  -> {snap_count} position snapshots stored (batch={snapshot_batch[:8]}...)")

    # ── Step 3: Build TraderSnapshots from DB ────────────────────────────
    conn = get_connection(db_path)
    try:
        # Get account values from traders table
        acct_rows = conn.execute(
            "SELECT address, account_value FROM traders WHERE address IN ({})".format(
                ",".join("?" for _ in addresses)
            ),
            addresses,
        ).fetchall()
        acct_map = {r["address"]: r["account_value"] or 0.0 for r in acct_rows}

        # Get snapshots from this batch
        snap_rows = conn.execute(
            """SELECT address, token_symbol, side, position_value_usd, mark_price
               FROM position_snapshots
               WHERE snapshot_batch = ?""",
            (snapshot_batch,),
        ).fetchall()
    finally:
        conn.close()

    # Group positions by trader address
    positions_by_addr: dict[str, list[dict]] = {}
    for row in snap_rows:
        addr = row["address"]
        positions_by_addr.setdefault(addr, []).append({
            "token_symbol": row["token_symbol"],
            "side": row["side"],
            "position_value_usd": row["position_value_usd"] or 0.0,
            "mark_price": row["mark_price"] or 0.0,
        })

    trader_snapshots: list[TraderSnapshot] = []
    for addr in addresses:
        positions = positions_by_addr.get(addr, [])
        trader_snapshots.append(TraderSnapshot(
            address=addr,
            composite_score=score_map.get(addr, 0.0),
            account_value=acct_map.get(addr, 0.0),
            positions=positions,
        ))

    # Print position summary
    traders_with_pos = sum(1 for ts in trader_snapshots if ts.positions)
    total_positions = sum(len(ts.positions) for ts in trader_snapshots)
    print(f"\n  Traders with open positions: {traders_with_pos}/{len(trader_snapshots)}")
    print(f"  Total positions across traders: {total_positions}")

    if total_positions == 0:
        print("\n  No positions found across tracked traders. Nothing to rebalance.")
        return

    # Show what traders hold
    print(f"\n{'─'*90}")
    print(f"  TRADER POSITIONS")
    print(f"{'─'*90}")
    for ts in trader_snapshots:
        if not ts.positions:
            continue
        print(f"\n  {ts.address[:14]}...  score={ts.composite_score:.4f}  "
              f"acct=${ts.account_value:,.0f}  ({len(ts.positions)} positions)")
        for p in ts.positions:
            print(f"    {p['side']:<5} {p['token_symbol']:<8} "
                  f"${p['position_value_usd']:>12,.2f}  "
                  f"mark=${p['mark_price']:>12,.4f}")

    # ── Step 4: Compute target portfolio ─────────────────────────────────
    raw_targets = compute_target_portfolio(trader_snapshots, account_value)
    print(f"\n{'─'*90}")
    print(f"  RAW TARGET PORTFOLIO ({len(raw_targets)} positions)")
    print(f"{'─'*90}")
    for t in sorted(raw_targets, key=lambda x: x.target_usd, reverse=True):
        print(f"  {t.side:<5} {t.token_symbol:<8} "
              f"raw=${t.raw_weight:>10,.2f}  target=${t.target_usd:>10,.2f}  "
              f"mark=${t.mark_price:>12,.4f}")

    # ── Step 4b: Net opposing targets ────────────────────────────────────
    netted_targets = net_opposing_targets(raw_targets)
    if len(netted_targets) != len(raw_targets):
        print(f"\n{'─'*90}")
        print(f"  NETTED TARGETS ({len(raw_targets)} raw -> {len(netted_targets)} netted)")
        print(f"{'─'*90}")
        for t in sorted(netted_targets, key=lambda x: x.target_usd, reverse=True):
            print(f"  {t.side:<5} {t.token_symbol:<8} "
                  f"target=${t.target_usd:>10,.2f}  "
                  f"mark=${t.mark_price:>12,.4f}")

    # ── Step 5: Apply risk overlay ───────────────────────────────────────
    capped_targets = apply_risk_overlay(netted_targets, account_value)
    active_targets = [t for t in capped_targets if t.target_usd > 0]
    print(f"\n{'─'*90}")
    print(f"  RISK-CAPPED TARGET PORTFOLIO ({len(active_targets)} positions)")
    print(f"{'─'*90}")
    total_exposure = 0.0
    for t in active_targets:
        print(f"  {t.side:<5} {t.token_symbol:<8} "
              f"target=${t.target_usd:>10,.2f}  "
              f"({t.target_usd/account_value*100:.1f}% of acct)  "
              f"size={t.target_size:>12,.6f}")
        total_exposure += t.target_usd
    print(f"\n  Total exposure: ${total_exposure:,.2f} "
          f"({total_exposure/account_value*100:.1f}% of ${account_value:,.0f})")

    # Store target allocations
    store_target_allocations(db_path, rebalance_id, capped_targets)

    # ── Step 6: Compute rebalance diff ───────────────────────────────────
    current_positions = get_current_positions(db_path)
    actions = compute_rebalance_diff(capped_targets, current_positions)

    print(f"\n{'─'*90}")
    print(f"  REBALANCE ACTIONS ({len(actions)} orders)")
    print(f"{'─'*90}")
    for a in actions:
        print(f"  {a.action:<8} {a.side:<5} {a.token_symbol:<8} "
              f"delta=${a.delta_usd:>10,.2f}  "
              f"current=${a.current_usd:>10,.2f}  "
              f"target=${a.target_usd:>10,.2f}")

    if not actions:
        print("  No actions needed (within rebalance band or no targets).")
        return

    # ── Step 7: Execute via PaperTradeClient ─────────────────────────────
    # Build mark price map from targets
    mark_prices = {}
    for t in capped_targets:
        if t.mark_price > 0:
            mark_prices[t.token_symbol] = t.mark_price

    paper_client = PaperTradeClient(mark_prices=mark_prices)
    summary = await execute_rebalance(paper_client, rebalance_id, actions, db_path)

    print(f"\n{'='*90}")
    print(f"  EXECUTION SUMMARY (paper trade)")
    print(f"{'='*90}")
    print(f"  Rebalance ID: {rebalance_id}")
    print(f"  Orders sent:   {summary['orders_sent']}")
    print(f"  Orders filled: {summary['orders_filled']}")
    print(f"  Orders failed: {summary['orders_failed']}")
    if summary['orders_filled'] > 0:
        avg_slip = summary['total_slippage_bps'] / summary['orders_filled']
        print(f"  Avg slippage:  {avg_slip:.1f} bps")

    # ── Print final positions ────────────────────────────────────────────
    final_positions = get_current_positions(db_path)
    if final_positions:
        print(f"\n{'─'*90}")
        print(f"  OUR POSITIONS (after rebalance)")
        print(f"{'─'*90}")
        total_pos_usd = 0.0
        for pos in final_positions:
            print(f"  {pos['side']:<5} {pos['token_symbol']:<8} "
                  f"size={pos['size']:>12,.6f}  "
                  f"entry=${pos['entry_price']:>12,.4f}  "
                  f"pos_usd=${pos['position_usd']:>10,.2f}  "
                  f"SL=${pos['stop_loss_price']:>12,.4f}  "
                  f"TS=${pos['trailing_stop_price']:>12,.4f}")
            total_pos_usd += pos["position_usd"]
        print(f"\n  Total position value: ${total_pos_usd:,.2f} "
              f"({total_pos_usd/account_value*100:.1f}% of account)")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run paper-trade rebalance cycle")
    parser.add_argument(
        "--db-path", default="data/snap_diagnostic.db",
        help="SQLite DB path (default: data/snap_diagnostic.db)",
    )
    parser.add_argument(
        "--account-value", type=float, default=None,
        help=f"Account value in USD (default: {ACCOUNT_VALUE})",
    )
    args = parser.parse_args()
    acct = args.account_value if args.account_value is not None else ACCOUNT_VALUE
    asyncio.run(main(args.db_path, acct))
