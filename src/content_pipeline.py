"""Content Pipeline — Score mover detection and payload generation.

Compares daily score snapshots to detect interesting rank/score changes,
then generates a JSON payload for the writer agent team.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.datastore import DataStore
from src.config import (
    CONTENT_MIN_RANK_CHANGE,
    CONTENT_MIN_SCORE_DELTA,
    CONTENT_TOP_N,
)
from src.nansen_client import NansenClient

logger = logging.getLogger(__name__)


def detect_score_movers(
    datastore: DataStore,
    today: date | None = None,
    yesterday: date | None = None,
    min_rank_change: int | None = None,
    min_score_delta: float | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """Detect wallets with significant rank or score changes between two days.

    Returns a list of mover dicts sorted by combined change magnitude (largest first).
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if yesterday is None:
        yesterday = today - timedelta(days=1)
    if min_rank_change is None:
        min_rank_change = CONTENT_MIN_RANK_CHANGE
    if min_score_delta is None:
        min_score_delta = CONTENT_MIN_SCORE_DELTA
    if top_n is None:
        top_n = CONTENT_TOP_N

    today_rows = datastore.get_score_snapshots_for_date(today)
    yesterday_rows = datastore.get_score_snapshots_for_date(yesterday)

    if not today_rows or not yesterday_rows:
        logger.info("Missing snapshot data for comparison (today=%s, yesterday=%s)", today, yesterday)
        return []

    yesterday_map = {r["trader_id"]: r for r in yesterday_rows}

    movers = []
    for row in today_rows:
        addr = row["trader_id"]
        if addr not in yesterday_map:
            if row["rank"] <= top_n:
                movers.append({
                    "address": addr,
                    "old_rank": None,
                    "new_rank": row["rank"],
                    "rank_delta": None,
                    "old_score": None,
                    "new_score": row["composite_score"],
                    "score_delta": None,
                    "new_entrant": True,
                    "today": row,
                    "yesterday": None,
                })
            continue

        prev = yesterday_map[addr]
        rank_delta = prev["rank"] - row["rank"]
        score_delta = row["composite_score"] - prev["composite_score"]

        is_rank_mover = abs(rank_delta) >= min_rank_change
        is_score_mover = abs(score_delta) >= min_score_delta

        entered_top_n = row["rank"] <= top_n and prev["rank"] > top_n
        exited_top_n = row["rank"] > top_n and prev["rank"] <= top_n

        if is_rank_mover or is_score_mover or entered_top_n or exited_top_n:
            movers.append({
                "address": addr,
                "old_rank": prev["rank"],
                "new_rank": row["rank"],
                "rank_delta": rank_delta,
                "old_score": prev["composite_score"],
                "new_score": row["composite_score"],
                "score_delta": score_delta,
                "new_entrant": False,
                "today": row,
                "yesterday": prev,
            })

    def sort_key(m):
        rd = abs(m["rank_delta"] or 0)
        sd = abs(m["score_delta"] or 0)
        return rd + sd * 10

    movers.sort(key=sort_key, reverse=True)
    return movers


def _compute_top_dimension_movers(today_row: dict, yesterday_row: dict | None) -> list[dict]:
    """Find the 2-3 dimensions that changed most between days."""
    if yesterday_row is None:
        return []

    dimensions = [
        ("growth", "growth_score"),
        ("drawdown", "drawdown_score"),
        ("leverage", "leverage_score"),
        ("liq_distance", "liq_distance_score"),
        ("diversity", "diversity_score"),
        ("consistency", "consistency_score"),
    ]

    deltas = []
    for name, col in dimensions:
        old_val = yesterday_row.get(col, 0.0) or 0.0
        new_val = today_row.get(col, 0.0) or 0.0
        delta = new_val - old_val
        if abs(delta) > 0.001:
            deltas.append({"dimension": name, "delta": round(delta, 4)})

    deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return deltas[:3]


async def _fetch_current_positions(address: str) -> list[dict]:
    """Fetch live positions for a wallet via the Nansen API.

    Returns a simplified list of position dicts for the content payload.
    """
    try:
        async with NansenClient() as client:
            snapshot = await client.fetch_address_positions(address)
    except Exception:
        logger.exception("Failed to fetch positions for %s", address)
        return []

    positions = []
    for ap in snapshot.asset_positions:
        p = ap.position
        size = float(p.size)
        positions.append({
            "token": p.token_symbol,
            "side": "Long" if size > 0 else "Short",
            "position_value_usd": round(float(p.position_value_usd), 2),
            "entry_price": round(float(p.entry_price_usd), 2),
            "leverage": p.leverage_value,
            "liquidation_price": round(float(p.liquidation_price_usd), 2) if p.liquidation_price_usd else None,
            "unrealized_pnl_usd": round(float(p.unrealized_pnl_usd), 2) if p.unrealized_pnl_usd else None,
        })

    # Sort by position value descending
    positions.sort(key=lambda x: abs(x["position_value_usd"]), reverse=True)
    return positions


def generate_content_payload(
    datastore: DataStore,
    today: date | None = None,
    yesterday: date | None = None,
) -> dict:
    """Generate the content payload JSON for the writer agent team.

    Returns a dict with `post_worthy: True/False` and the full signal data.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if yesterday is None:
        yesterday = today - timedelta(days=1)

    movers = detect_score_movers(datastore, today=today, yesterday=yesterday)

    if not movers:
        return {"post_worthy": False, "snapshot_date": today.isoformat()}

    top_mover = movers[0]
    top_dimension_movers = _compute_top_dimension_movers(
        top_mover["today"], top_mover.get("yesterday"),
    )

    today_rows = datastore.get_score_snapshots_for_date(today)
    top_5 = [
        {
            "address": r["trader_id"],
            "label": datastore.get_trader_label(r["trader_id"]),
            "score": r["composite_score"],
            "rank": r["rank"],
            "smart_money": bool(r.get("smart_money")),
        }
        for r in today_rows[:5]
    ]

    current_dims = {}
    previous_dims = {}
    for name, col in [
        ("growth", "growth_score"), ("drawdown", "drawdown_score"),
        ("leverage", "leverage_score"), ("liq_distance", "liq_distance_score"),
        ("diversity", "diversity_score"), ("consistency", "consistency_score"),
    ]:
        current_dims[name] = top_mover["today"].get(col, 0.0) or 0.0
        if top_mover.get("yesterday"):
            previous_dims[name] = top_mover["yesterday"].get(col, 0.0) or 0.0

    label = datastore.get_trader_label(top_mover["address"])

    # Fetch live positions from Nansen API
    current_positions = asyncio.run(
        _fetch_current_positions(top_mover["address"])
    )
    logger.info(
        "Fetched %d live positions for %s", len(current_positions), top_mover["address"]
    )

    return {
        "post_worthy": True,
        "snapshot_date": today.isoformat(),
        "wallet": {
            "address": top_mover["address"],
            "label": label,
            "smart_money": bool(top_mover["today"].get("smart_money")),
        },
        "change": {
            "old_rank": top_mover["old_rank"],
            "new_rank": top_mover["new_rank"],
            "rank_delta": top_mover["rank_delta"],
            "old_score": top_mover["old_score"],
            "new_score": top_mover["new_score"],
            "score_delta": top_mover["score_delta"],
            "new_entrant": top_mover["new_entrant"],
        },
        "current_dimensions": current_dims,
        "previous_dimensions": previous_dims,
        "top_movers": top_dimension_movers,
        "current_positions": current_positions,
        "context": {
            "top_5_wallets": top_5,
        },
    }


def run_content_pipeline(db_path: str = "data/pnl_weighted.db") -> bool:
    """Main entry point. Detect movers, write payload to data/content_payload.json.

    Returns True if a post-worthy payload was generated.
    """
    datastore = DataStore(db_path)
    try:
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        payload = generate_content_payload(datastore, today=today, yesterday=yesterday)

        output_dir = Path("data")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "content_payload.json"

        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2)

        logger.info("Content payload written to %s (post_worthy=%s)", output_path, payload["post_worthy"])
        return payload["post_worthy"]

    finally:
        datastore.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    result = run_content_pipeline()
    sys.exit(0 if result else 1)
