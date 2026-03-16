"""Dispatcher — central orchestrator for the multi-angle content pipeline.

Provides two CLI commands:
- ``--snapshot``: Take daily snapshots (scores, consensus, allocations, portfolio)
- ``--detect``:   Run angle detection, rank, select, write output payloads

Usage::

    python -m src.content.dispatcher --snapshot
    python -m src.content.dispatcher --detect
    python -m src.content.dispatcher --snapshot --detect
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from src.config import (
    CONTENT_FRESHNESS_BOOST_PER_DAY,
    CONTENT_MAX_FRESHNESS_BOOST,
    CONTENT_SECOND_POST_MIN_SCORE,
)
from src.content.angles import ALL_ANGLES
from src.datastore import DataStore
from src.scheduler import save_daily_score_snapshot
from src.strategy_interface import build_index_portfolio, weighted_consensus

logger = logging.getLogger(__name__)

# Directory where payload / selection files are written
_DATA_DIR = "data"


# ------------------------------------------------------------------
# Snapshot command
# ------------------------------------------------------------------


def take_consensus_snapshot(datastore: DataStore, nansen_client=None) -> None:
    """Compute consensus from current allocations + positions and snapshot it.

    For each token held by allocated traders, computes weighted long/short
    exposure and derives a consensus direction and confidence percentage.
    """
    today = datetime.now(timezone.utc).date()

    allocations = datastore.get_latest_allocations()
    if not allocations:
        logger.info("Consensus snapshot: no allocations, skipping")
        return

    # Gather latest positions per allocated trader
    trader_positions: dict[str, list] = {}
    for address in allocations:
        positions = datastore.get_latest_position_snapshot(address)
        if positions:
            trader_positions[address] = [
                {
                    "token_symbol": p["token_symbol"],
                    "side": p["side"],
                    "position_value_usd": abs(float(p["position_value_usd"])),
                }
                for p in positions
            ]

    # Collect all unique tokens across all positions
    all_tokens: set[str] = set()
    for positions in trader_positions.values():
        for p in positions:
            all_tokens.add(p["token_symbol"])

    if not all_tokens:
        logger.info("Consensus snapshot: no positions found, skipping")
        return

    count = 0
    for token in sorted(all_tokens):
        result = weighted_consensus(token, allocations, trader_positions)
        long_usd = result["long_weight"]
        short_usd = result["short_weight"]
        total = long_usd + short_usd

        if total == 0:
            continue

        confidence_pct = (max(long_usd, short_usd) / total) * 100
        direction = "LONG" if long_usd >= short_usd else "SHORT"

        datastore.insert_consensus_snapshot(
            snapshot_date=today,
            token=token,
            direction=direction,
            confidence_pct=round(confidence_pct, 1),
            sm_long_usd=round(long_usd, 2),
            sm_short_usd=round(short_usd, 2),
        )
        count += 1

    logger.info("Consensus snapshot: %d tokens snapshotted", count)


def take_index_portfolio_snapshot(datastore: DataStore) -> None:
    """Compute index portfolio from allocations + positions and snapshot it.

    Uses build_index_portfolio() to aggregate weighted positions across
    all allocated traders, then stores each (token, side) entry.
    """
    today = datetime.now(timezone.utc).date()

    allocations = datastore.get_latest_allocations()
    if not allocations:
        logger.info("Index portfolio snapshot: no allocations, skipping")
        return

    # Gather latest positions per allocated trader
    trader_positions: dict[str, list] = {}
    for address in allocations:
        positions = datastore.get_latest_position_snapshot(address)
        if positions:
            trader_positions[address] = [
                {
                    "token_symbol": p["token_symbol"],
                    "side": p["side"],
                    "position_value_usd": abs(float(p["position_value_usd"])),
                }
                for p in positions
            ]

    if not trader_positions:
        logger.info("Index portfolio snapshot: no positions found, skipping")
        return

    # Use a notional $100k account for weight normalization (absolute value
    # doesn't matter since we normalize to relative weights below)
    portfolio = build_index_portfolio(allocations, trader_positions, 100_000.0)

    if not portfolio:
        logger.info("Index portfolio snapshot: empty portfolio, skipping")
        return

    total_usd = sum(portfolio.values())

    count = 0
    for (token, side), target_usd in portfolio.items():
        weight = (target_usd / total_usd) if total_usd > 0 else 0.0
        datastore.insert_index_portfolio_snapshot(
            snapshot_date=today,
            token=token,
            side=side,
            target_weight=round(weight, 4),
            target_usd=round(target_usd, 2),
        )
        count += 1

    logger.info("Index portfolio snapshot: %d entries snapshotted", count)


def take_daily_snapshots(datastore: DataStore, nansen_client=None) -> None:
    """Take all daily snapshots needed before detection.

    Steps:
      a) Score snapshot — saves today's ranked scores
      b) Consensus snapshot — Nansen market overview (placeholder)
      c) Allocation snapshot — copies current allocations into snapshot table
      d) Index portfolio snapshot — (placeholder)
    """
    today = datetime.now(timezone.utc).date()

    # (a) Score snapshot
    logger.info("Taking daily score snapshot for %s", today)
    save_daily_score_snapshot(datastore, snapshot_date=today)

    # (b) Consensus snapshot
    take_consensus_snapshot(datastore, nansen_client)

    # (c) Allocation snapshot
    logger.info("Taking allocation snapshot for %s", today)
    allocations = datastore.get_latest_allocations()
    if allocations:
        for address, weight in allocations.items():
            datastore.insert_allocation_snapshot(today, address, weight)
        logger.info(
            "Allocation snapshot: %d traders snapshotted", len(allocations)
        )
    else:
        logger.info("Allocation snapshot: no allocations to snapshot")

    # (d) Index portfolio snapshot
    take_index_portfolio_snapshot(datastore)


# ------------------------------------------------------------------
# Detection command
# ------------------------------------------------------------------


def detect_and_select(datastore: DataStore, nansen_client=None) -> list[dict]:
    """Run angle detection, rank by effective score, select up to 2, write outputs.

    Returns the list of selection dicts (also written to
    ``data/content_selections.json``).  Returns an empty list when no
    angle qualifies.
    """
    today = datetime.now(timezone.utc).date()

    # Remove any stale selections file from a previous run
    selections_path = os.path.join(_DATA_DIR, "content_selections.json")
    if os.path.exists(selections_path):
        os.remove(selections_path)
        logger.info("Removed stale %s", selections_path)

    # ----- score each angle -----
    scored: list[dict] = []
    for angle in ALL_ANGLES:
        try:
            raw_score = angle.detect(datastore, nansen_client)
        except Exception:
            logger.exception("detect() failed for %s", angle.angle_type)
            raw_score = 0.0

        if raw_score <= 0:
            logger.debug(
                "Angle %s: raw_score=0, skipping", angle.angle_type
            )
            continue

        # Cooldown + freshness boost
        last_date_str = datastore.get_last_post_date(angle.angle_type)

        if last_date_str is not None:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_since_last = (today - last_date).days

            if days_since_last < angle.cooldown_days:
                logger.info(
                    "Angle %s blocked by cooldown (%d < %d)",
                    angle.angle_type,
                    days_since_last,
                    angle.cooldown_days,
                )
                effective_score = 0.0
            else:
                boost = min(
                    CONTENT_MAX_FRESHNESS_BOOST,
                    1.0
                    + (days_since_last - angle.cooldown_days)
                    * CONTENT_FRESHNESS_BOOST_PER_DAY,
                )
                effective_score = raw_score * boost
        else:
            # Never posted before — maximum freshness boost
            effective_score = raw_score * CONTENT_MAX_FRESHNESS_BOOST

        scored.append(
            {
                "angle": angle,
                "raw_score": raw_score,
                "effective_score": effective_score,
            }
        )

    # ----- rank & select -----
    scored.sort(key=lambda s: s["effective_score"], reverse=True)

    selected: list[dict] = []

    if scored and scored[0]["effective_score"] > 0:
        selected.append(scored[0])

    if (
        len(scored) >= 2
        and scored[1]["effective_score"] >= CONTENT_SECOND_POST_MIN_SCORE
    ):
        selected.append(scored[1])

    if not selected:
        logger.info("No angles selected — no content_selections.json written")
        return []

    # ----- build payloads & write files -----
    os.makedirs(_DATA_DIR, exist_ok=True)
    selections_output: list[dict] = []

    for entry in selected:
        angle = entry["angle"]
        try:
            payload = angle.build_payload(datastore, nansen_client)
        except Exception:
            logger.exception(
                "build_payload() failed for %s", angle.angle_type
            )
            continue

        payload_path = os.path.join(
            _DATA_DIR, f"content_payload_{angle.angle_type}.json"
        )
        with open(payload_path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info("Wrote payload: %s", payload_path)

        selections_output.append(
            {
                "angle_type": angle.angle_type,
                "raw_score": entry["raw_score"],
                "effective_score": entry["effective_score"],
                "auto_publish": angle.auto_publish,
                "payload_path": payload_path,
            }
        )

    if not selections_output:
        logger.info(
            "All selected angles failed build_payload — no selections written"
        )
        return []

    with open(selections_path, "w") as f:
        json.dump(selections_output, f, indent=2)
    logger.info("Wrote selections: %s", selections_path)

    return selections_output


# ------------------------------------------------------------------
# CLI entry-point
# ------------------------------------------------------------------

def _run_cli(snapshot: bool = False, detect: bool = False) -> None:
    """CLI entry-point logic, extracted for testability."""
    from src.nansen_client import NansenClient

    nansen_client = NansenClient()  # Reads NANSEN_API_KEY from env
    datastore = DataStore()
    try:
        if snapshot:
            take_daily_snapshots(datastore, nansen_client=nansen_client)
        if detect:
            detect_and_select(datastore, nansen_client=nansen_client)
    finally:
        datastore.close()


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Multi-angle content pipeline dispatcher"
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Take daily snapshots (scores, consensus, allocations, portfolio)",
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="Run angle detection, rank, select, write outputs",
    )
    args = parser.parse_args()

    _run_cli(snapshot=args.snapshot, detect=args.detect)
