"""
Phase 8: Scheduler & Orchestration

Coordinates periodic tasks:
- Leaderboard refresh (daily)
- Full recompute cycle (every 6 hours)
- Position monitoring (every 15 minutes)
- Cleanup tasks (daily)
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from .nansen_client import NansenClient
from .datastore import DataStore
from .metrics import recompute_all_metrics
from .scoring import compute_trader_score
from .filters import is_fully_eligible
from .allocation import compute_allocations, RiskConfig
from .position_monitor import monitor_positions
from .config import (
    METRICS_RECOMPUTE_HOURS,
    POSITION_MONITOR_MINUTES,
    LEADERBOARD_REFRESH_CRON,
)

logger = logging.getLogger(__name__)


async def refresh_leaderboard(nansen_client: NansenClient, datastore: DataStore) -> None:
    """
    Fetch 30-day leaderboard and update traders table.

    Args:
        nansen_client: Async Nansen API client
        datastore: SQLite datastore
    """
    logger.info("Starting leaderboard refresh")

    # Fetch 30-day window
    date_to = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    date_from = date_to - timedelta(days=30)

    try:
        entries = await nansen_client.fetch_leaderboard(
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat()
        )

        count = 0
        for entry in entries:
            # Upsert trader
            datastore.upsert_trader(
                address=entry.trader_address,
                label=entry.trader_address_label
            )

            # Insert snapshot
            datastore.insert_leaderboard_snapshot(
                address=entry.trader_address,
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                total_pnl=entry.total_pnl,
                roi=entry.roi,
                account_value=entry.account_value
            )
            count += 1

        logger.info(f"Leaderboard refresh complete: {count} traders updated")

    except Exception as e:
        logger.error(f"Leaderboard refresh failed: {e}", exc_info=True)
        raise


async def full_recompute_cycle(
    nansen_client: NansenClient,
    datastore: DataStore,
    risk_config: RiskConfig
) -> Dict[str, float]:
    """
    Main orchestration: recompute metrics, scores, and allocations.

    Args:
        nansen_client: Async Nansen API client
        datastore: SQLite datastore
        risk_config: Risk configuration for allocation

    Returns:
        New allocations dict {address: weight}
    """
    logger.info("Starting full recompute cycle")

    try:
        # Step 1: Get active traders
        traders = datastore.get_active_traders()
        logger.info(f"Processing {len(traders)} active traders")

        if not traders:
            logger.warning("No active traders found")
            return {}

        # Step 2: Recompute metrics for all traders
        logger.info("Recomputing trade metrics for all windows")
        await recompute_all_metrics(
            nansen_client=nansen_client,
            datastore=datastore,
            trader_addresses=traders,
            windows=[7, 30, 90]
        )

        # Step 3: Score each trader and collect eligible ones
        eligible_traders = []
        scores = {}

        for address in traders:
            # Get metrics for all windows
            m7 = datastore.get_latest_metrics(address, window_days=7)
            m30 = datastore.get_latest_metrics(address, window_days=30)
            m90 = datastore.get_latest_metrics(address, window_days=90)

            # Skip if any window missing
            if not m7 or not m30 or not m90:
                logger.debug(f"Skipping {address}: missing metrics")
                continue

            # Check eligibility
            is_eligible, reason = is_fully_eligible(address, m7, m30, m90, datastore)

            # Get additional data for scoring
            label = datastore.get_trader_label(address)
            positions = datastore.get_latest_position_snapshot(address)
            last_trade_time_str = datastore.get_last_trade_time(address)

            # Compute hours since last trade
            if last_trade_time_str:
                try:
                    last_trade_time = datetime.fromisoformat(last_trade_time_str)
                    hours_since = (datetime.now(timezone.utc) - last_trade_time).total_seconds() / 3600
                except (ValueError, TypeError):
                    logger.warning(f"Invalid last_trade_time for {address}: {last_trade_time_str}")
                    hours_since = 9999  # Default to very old
            else:
                hours_since = 9999  # No trades on record

            # Compute score
            score_dict = compute_trader_score(
                metrics_7d=m7,
                metrics_30d=m30,
                metrics_90d=m90,
                label=label,
                positions=positions,
                hours_since_last_trade=hours_since
            )

            # Override passes_anti_luck based on eligibility
            score_dict["passes_anti_luck"] = 1 if is_eligible else 0

            # Store score
            datastore.insert_score(address, score_dict)

            # Add to eligible list if passed
            if is_eligible:
                eligible_traders.append(address)
                scores[address] = score_dict["final_score"]
                logger.debug(f"Trader {address} eligible with score {score_dict['final_score']:.4f}")
            else:
                logger.debug(f"Trader {address} filtered: {reason}")

        logger.info(f"Found {len(eligible_traders)} eligible traders out of {len(traders)}")

        # Step 4: Get old allocations
        old_allocations = datastore.get_latest_allocations()

        # Step 5: Build trader positions dict
        trader_positions = {}
        for address in eligible_traders:
            positions = datastore.get_latest_position_snapshot(address)
            trader_positions[address] = positions

        # Step 6: Compute new allocations
        new_allocations = compute_allocations(
            eligible_traders=eligible_traders,
            scores=scores,
            old_allocations=old_allocations,
            trader_positions=trader_positions,
            risk_config=risk_config
        )

        # Step 7: Store allocations
        datastore.insert_allocations(new_allocations)

        logger.info(f"Recompute cycle complete: {len(new_allocations)} allocations generated")
        logger.info(f"Allocation summary: {dict(sorted(new_allocations.items(), key=lambda x: x[1], reverse=True)[:5])}")

        return new_allocations

    except Exception as e:
        logger.error(f"Full recompute cycle failed: {e}", exc_info=True)
        raise


async def run_scheduler(
    nansen_client: NansenClient,
    datastore: DataStore,
    risk_config: RiskConfig
) -> None:
    """
    Main scheduler loop running all periodic tasks.

    Tasks:
    - Leaderboard refresh: daily
    - Full recompute cycle: every METRICS_RECOMPUTE_HOURS (default 6h)
    - Position monitoring: every POSITION_MONITOR_MINUTES (default 15min)
    - Cleanup tasks: daily

    Args:
        nansen_client: Async Nansen API client
        datastore: SQLite datastore
        risk_config: Risk configuration for allocation
    """
    logger.info("Starting scheduler")

    # Track last run times
    last_leaderboard_refresh = None
    last_recompute = None
    last_position_monitor = None
    last_cleanup = None

    # Run initial tasks
    try:
        logger.info("Running initial leaderboard refresh")
        await refresh_leaderboard(nansen_client, datastore)
        last_leaderboard_refresh = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial leaderboard refresh failed: {e}")

    try:
        logger.info("Running initial recompute cycle")
        await full_recompute_cycle(nansen_client, datastore, risk_config)
        last_recompute = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial recompute cycle failed: {e}")

    try:
        logger.info("Running initial position monitor")
        liquidated = await monitor_positions(nansen_client, datastore)
        if liquidated:
            logger.warning(f"Detected {len(liquidated)} liquidated traders: {liquidated}")
        last_position_monitor = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial position monitor failed: {e}")

    try:
        logger.info("Running initial cleanup tasks")
        datastore.cleanup_expired_blacklist()
        datastore.enforce_retention(days=90)
        last_cleanup = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Initial cleanup failed: {e}")

    # Main loop
    logger.info("Entering main scheduler loop")

    while True:
        try:
            await asyncio.sleep(60)  # Check every minute

            now = datetime.now(timezone.utc)

            # Daily leaderboard refresh
            if last_leaderboard_refresh is None or (now - last_leaderboard_refresh) >= timedelta(days=1):
                logger.info("Triggering daily leaderboard refresh")
                try:
                    await refresh_leaderboard(nansen_client, datastore)
                    last_leaderboard_refresh = now
                except Exception as e:
                    logger.error(f"Leaderboard refresh failed: {e}")

            # Periodic recompute cycle
            recompute_interval = timedelta(hours=METRICS_RECOMPUTE_HOURS)
            if last_recompute is None or (now - last_recompute) >= recompute_interval:
                logger.info(f"Triggering recompute cycle ({METRICS_RECOMPUTE_HOURS}h interval)")
                try:
                    await full_recompute_cycle(nansen_client, datastore, risk_config)
                    last_recompute = now
                except Exception as e:
                    logger.error(f"Recompute cycle failed: {e}")

            # Position monitoring
            monitor_interval = timedelta(minutes=POSITION_MONITOR_MINUTES)
            if last_position_monitor is None or (now - last_position_monitor) >= monitor_interval:
                logger.debug(f"Triggering position monitor ({POSITION_MONITOR_MINUTES}min interval)")
                try:
                    liquidated = await monitor_positions(nansen_client, datastore)
                    if liquidated:
                        logger.warning(f"Detected {len(liquidated)} liquidated traders: {liquidated}")
                        # Trigger immediate recompute if liquidations detected
                        logger.info("Liquidations detected, triggering immediate recompute")
                        await full_recompute_cycle(nansen_client, datastore, risk_config)
                        last_recompute = now
                    last_position_monitor = now
                except Exception as e:
                    logger.error(f"Position monitor failed: {e}")

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
