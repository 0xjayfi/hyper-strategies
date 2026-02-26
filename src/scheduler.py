"""
Scheduler & Orchestration — Position-Only Pipeline

Coordinates 4 periodic tasks:
1. Position sweep (hourly): snapshot positions for all active traders
2. Position scoring (hourly, after sweep): metrics -> score -> filter -> allocate
3. Leaderboard refresh (daily): fetch top 100 traders (2 pages of 50)
4. Cleanup (daily): expire blacklist entries, enforce data retention
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from .nansen_client import NansenClient
from .datastore import DataStore
from .position_metrics import compute_position_metrics
from .position_scoring import compute_position_score
from .filters import is_position_eligible
from .allocation import compute_allocations, RiskConfig
from .position_monitor import snapshot_positions_for_trader
from .config import (
    POSITION_SNAPSHOT_MINUTES,
    POSITION_SCORING_MINUTES,
)

logger = logging.getLogger(__name__)


async def refresh_leaderboard(nansen_client: NansenClient, datastore: DataStore) -> None:
    """
    Fetch 30-day leaderboard (top 100) and update traders table.

    Paginates over 2 pages of 50 entries each. Breaks early if a page
    returns fewer than 50 entries (last page reached).

    Args:
        nansen_client: Async Nansen API client
        datastore: SQLite datastore
    """
    logger.info("Starting leaderboard refresh (top 100)")

    # Fetch 30-day window — API requires YYYY-MM-DD (no time component)
    date_to = datetime.now(timezone.utc).date()
    date_from = date_to - timedelta(days=30)

    date_from_str = date_from.isoformat()  # "2026-01-14"
    date_to_str = date_to.isoformat()      # "2026-02-13"

    try:
        count = 0
        for page in range(1, 3):  # Pages 1 and 2
            entries = await nansen_client.fetch_leaderboard(
                date_from=date_from_str,
                date_to=date_to_str,
                pagination={"page": page, "per_page": 50}
            )

            for entry in entries:
                # Upsert trader
                datastore.upsert_trader(
                    address=entry.trader_address,
                    label=entry.trader_address_label
                )

                # Insert snapshot
                datastore.insert_leaderboard_snapshot(
                    address=entry.trader_address,
                    date_from=date_from_str,
                    date_to=date_to_str,
                    total_pnl=entry.total_pnl,
                    roi=entry.roi,
                    account_value=entry.account_value
                )
                count += 1

            if len(entries) < 50:
                break  # Last page

        logger.info(f"Leaderboard refresh complete: {count} traders updated")

    except Exception as e:
        logger.error(f"Leaderboard refresh failed: {e}", exc_info=True)
        raise


async def position_sweep(
    nansen_client: NansenClient,
    datastore: DataStore,
) -> None:
    """
    Snapshot current positions for all active traders.

    Called hourly to build the position time series used by the scoring
    pipeline.

    Args:
        nansen_client: Async Nansen API client
        datastore: SQLite datastore
    """
    traders = datastore.get_active_traders()
    logger.info("Position sweep: snapshotting %d traders", len(traders))

    for address in traders:
        await snapshot_positions_for_trader(address, nansen_client, datastore)

    logger.info("Position sweep complete: %d traders snapshotted", len(traders))


async def position_scoring_cycle(
    nansen_client: NansenClient,
    datastore: DataStore,
    risk_config: RiskConfig,
) -> Dict[str, float]:
    """
    Position-only scoring pipeline: metrics -> score -> filter -> allocate.

    For each active trader:
    1. Retrieve 30-day account value series and position snapshots
    2. Compute position-based metrics
    3. Check position-based eligibility
    4. Compute position-based composite score
    5. Store score
    After all traders scored, compute and store allocations.

    Args:
        nansen_client: Async Nansen API client (unused but kept for signature compat)
        datastore: SQLite datastore
        risk_config: Risk configuration for allocation

    Returns:
        New allocations dict {address: weight}
    """
    logger.info("Starting position scoring cycle")

    try:
        # Step 1: Get active traders
        traders = datastore.get_active_traders()
        logger.info(f"Scoring {len(traders)} active traders")

        if not traders:
            logger.warning("No active traders found")
            return {}

        # Step 2: Score each trader
        eligible_traders = []
        scores = {}

        for address in traders:
            # Get 30-day time series data
            account_series = datastore.get_account_value_series(address, days=30)
            position_snapshots = datastore.get_position_snapshot_series(address, days=30)

            # Skip if insufficient data
            if len(account_series) < 2:
                logger.debug(f"Skipping {address}: insufficient account series ({len(account_series)} points)")
                continue

            # Compute position-based metrics
            metrics = compute_position_metrics(account_series, position_snapshots)

            # Check position-based eligibility
            is_eligible, reason = is_position_eligible(address, metrics, datastore)

            # Get label for smart money bonus
            label = datastore.get_trader_label(address)

            # Compute hours since last snapshot with positions
            hours_since = _hours_since_last_snapshot(address, datastore)

            # Compute position-based score
            score_dict = compute_position_score(
                metrics=metrics,
                label=label,
                hours_since_last_snapshot=hours_since,
            )

            # Add fields required by insert_score and compute_allocations
            # Map position score components to the trader_scores schema
            score_for_db = _map_score_to_db_schema(score_dict, is_eligible)

            # Store score
            datastore.insert_score(address, score_for_db)

            # Add to eligible list if passed
            if is_eligible:
                eligible_traders.append(address)
                scores[address] = score_for_db
                logger.debug(f"Trader {address} eligible with score {score_dict['final_score']:.4f}")
            else:
                logger.info(f"Trader {address} filtered: {reason}")

        logger.info(f"Found {len(eligible_traders)} eligible traders out of {len(traders)}")

        # Step 3: Get old allocations for turnover limiting
        old_allocations = datastore.get_latest_allocations()

        # Step 4: Build trader positions dict for risk-cap checks
        trader_positions = {}
        for address in eligible_traders:
            positions = datastore.get_latest_position_snapshot(address)
            trader_positions[address] = positions

        # Step 5: Compute new allocations
        new_allocations = compute_allocations(
            eligible_traders=eligible_traders,
            scores=scores,
            old_allocations=old_allocations,
            trader_positions=trader_positions,
            risk_config=risk_config,
        )

        # Step 6: Store allocations
        datastore.insert_allocations(new_allocations)

        logger.info(f"Position scoring cycle complete: {len(new_allocations)} allocations generated")
        if new_allocations:
            top5 = dict(sorted(new_allocations.items(), key=lambda x: x[1], reverse=True)[:5])
            logger.info(f"Allocation summary: {top5}")

        return new_allocations

    except Exception as e:
        logger.error(f"Position scoring cycle failed: {e}", exc_info=True)
        raise


def _hours_since_last_snapshot(address: str, datastore: DataStore) -> float:
    """Compute hours since the trader's most recent position snapshot."""
    latest = datastore.get_latest_position_snapshot(address)
    if not latest:
        return 9999.0

    # All rows in a snapshot share the same captured_at
    captured_at_str = latest[0].get("captured_at")
    if not captured_at_str:
        return 9999.0

    try:
        captured_at = datetime.fromisoformat(captured_at_str)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - captured_at).total_seconds() / 3600
    except (ValueError, TypeError):
        return 9999.0


def _map_score_to_db_schema(score_dict: dict, is_eligible: bool) -> dict:
    """Map position-based score components to the trader_scores DB schema.

    The trader_scores table expects trade-based column names. We map the
    6 position-based components into the closest corresponding columns,
    setting unused columns to 0.0.

    This also adds the ``roi_tier_multiplier`` (always 1.0 for position-based
    scoring, since we don't have per-trade ROI tiers) and ``passes_anti_luck``
    fields needed by compute_allocations and insert_score.
    """
    return {
        # Map position components to DB columns
        "normalized_roi": score_dict.get("account_growth_score", 0.0),
        "normalized_sharpe": score_dict.get("drawdown_score", 0.0),
        "normalized_win_rate": score_dict.get("leverage_score", 0.0),
        "consistency_score": score_dict.get("consistency_score", 0.0),
        "smart_money_bonus": score_dict.get("smart_money_bonus", 1.0),
        "risk_management_score": score_dict.get("liquidation_distance_score", 0.0),
        "style_multiplier": score_dict.get("diversity_score", 0.0),
        "recency_decay": score_dict.get("recency_decay", 1.0),
        "raw_composite_score": score_dict.get("raw_composite_score", 0.0),
        "final_score": score_dict.get("final_score", 0.0),
        # Position-based scoring doesn't use ROI tiers — neutral 1.0
        "roi_tier_multiplier": 1.0,
        "passes_anti_luck": 1 if is_eligible else 0,
    }


async def run_scheduler(
    nansen_client: NansenClient,
    datastore: DataStore,
    risk_config: RiskConfig,
) -> None:
    """
    Main scheduler loop running all periodic tasks.

    Tasks:
    1. Position sweep: every POSITION_SNAPSHOT_MINUTES (default 60 min)
    2. Position scoring: every POSITION_SCORING_MINUTES (after sweep)
    3. Leaderboard refresh: daily
    4. Cleanup: daily (expire blacklist, enforce retention)

    Args:
        nansen_client: Async Nansen API client
        datastore: SQLite datastore
        risk_config: Risk configuration for allocation
    """
    logger.info("Starting scheduler")

    # Track last run times
    last_leaderboard_refresh = None
    last_position_sweep = None
    last_scoring = None
    last_cleanup = None

    # --- Startup: run leaderboard refresh once ---
    try:
        logger.info("Running initial leaderboard refresh")
        await refresh_leaderboard(nansen_client, datastore)
        last_leaderboard_refresh = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial leaderboard refresh failed: {e}")

    # --- Startup: run initial position sweep + scoring ---
    try:
        logger.info("Running initial position sweep")
        await position_sweep(nansen_client, datastore)
        last_position_sweep = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial position sweep failed: {e}")

    try:
        logger.info("Running initial position scoring cycle")
        await position_scoring_cycle(nansen_client, datastore, risk_config)
        last_scoring = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial position scoring cycle failed: {e}")

    # --- Startup: run initial cleanup ---
    try:
        logger.info("Running initial cleanup tasks")
        datastore.cleanup_expired_blacklist()
        datastore.enforce_retention(days=90)
        last_cleanup = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial cleanup failed: {e}")

    # --- Main loop ---
    logger.info("Entering main scheduler loop")

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute

            now = datetime.now(timezone.utc)

            # Hourly position sweep + scoring
            sweep_interval = timedelta(minutes=POSITION_SNAPSHOT_MINUTES)
            if last_position_sweep is None or (now - last_position_sweep) >= sweep_interval:
                logger.info(f"Triggering position sweep ({POSITION_SNAPSHOT_MINUTES}min interval)")
                try:
                    await position_sweep(nansen_client, datastore)
                    last_position_sweep = now
                except Exception as e:
                    logger.error(f"Position sweep failed: {e}")

                # Scoring runs after sweep
                scoring_interval = timedelta(minutes=POSITION_SCORING_MINUTES)
                if last_scoring is None or (now - last_scoring) >= scoring_interval:
                    logger.info(f"Triggering position scoring ({POSITION_SCORING_MINUTES}min interval)")
                    try:
                        await position_scoring_cycle(nansen_client, datastore, risk_config)
                        last_scoring = now
                    except Exception as e:
                        logger.error(f"Position scoring cycle failed: {e}")

            # Daily leaderboard refresh
            if last_leaderboard_refresh is None or (now - last_leaderboard_refresh) >= timedelta(days=1):
                logger.info("Triggering daily leaderboard refresh")
                try:
                    await refresh_leaderboard(nansen_client, datastore)
                    last_leaderboard_refresh = now
                except Exception as e:
                    logger.error(f"Leaderboard refresh failed: {e}")

            # Daily cleanup tasks
            if last_cleanup is None or (now - last_cleanup) >= timedelta(days=1):
                logger.info("Triggering daily cleanup tasks")
                try:
                    datastore.cleanup_expired_blacklist()
                    datastore.enforce_retention(days=90)
                    last_cleanup = now
                except Exception as e:
                    logger.error(f"Cleanup tasks failed: {e}")

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}", exc_info=True)
            # Continue running even if one iteration fails
            await asyncio.sleep(60)
