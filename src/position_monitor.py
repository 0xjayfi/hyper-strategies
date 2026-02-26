"""
Position Monitor & Liquidation Detection (Phase 7)

Monitors trader positions every 15 minutes to detect liquidations.
If a position disappears without a Close/Reduce trade, the trader is blacklisted.
"""

import logging
from datetime import datetime, timedelta, timezone

from src.models import AssetPosition, PositionSnapshot
from src.nansen_client import NansenClient
from src.datastore import DataStore

logger = logging.getLogger(__name__)


async def snapshot_positions_for_trader(
    address: str,
    nansen_client: NansenClient,
    datastore: DataStore,
) -> None:
    """
    Fetch current positions from Nansen API and store them in the datastore.

    Args:
        address: Trader address to snapshot
        nansen_client: Async Nansen API client
        datastore: Sync datastore for persistence
    """
    try:
        snapshot = await nansen_client.fetch_address_positions(address)

        positions_list = []
        account_value = (
            float(snapshot.margin_summary_account_value_usd)
            if snapshot.margin_summary_account_value_usd
            else None
        )

        for ap in snapshot.asset_positions:
            position_dict = {
                "token_symbol": ap.position.token_symbol,
                "side": "Long" if float(ap.position.size) > 0 else "Short",
                "position_value_usd": float(ap.position.position_value_usd),
                "entry_price": float(ap.position.entry_price_usd),
                "leverage_value": ap.position.leverage_value,
                "leverage_type": ap.position.leverage_type,
                "liquidation_price": (
                    float(ap.position.liquidation_price_usd)
                    if ap.position.liquidation_price_usd
                    else None
                ),
                "unrealized_pnl": (
                    float(ap.position.unrealized_pnl_usd)
                    if ap.position.unrealized_pnl_usd
                    else None
                ),
                "account_value": account_value,
            }
            positions_list.append(position_dict)

        datastore.insert_position_snapshot(address, positions_list)
        logger.debug(
            "Snapshotted %d positions for %s",
            len(positions_list),
            address,
        )

    except Exception as e:
        logger.warning(
            "Failed to snapshot positions for %s: %s",
            address,
            e,
        )


async def detect_liquidations(
    tracked_traders: list[str],
    datastore: DataStore,
    nansen_client: NansenClient,
) -> list[str]:
    """
    Compare current positions against last snapshot.
    If a position disappeared without a Close/Reduce trade, treat as liquidation.

    Args:
        tracked_traders: List of trader addresses to check
        datastore: Datastore for querying previous snapshots and blacklisting
        nansen_client: Async Nansen API client

    Returns:
        List of addresses that were likely liquidated
    """
    liquidated = []

    for address in tracked_traders:
        try:
            prev_positions = datastore.get_latest_position_snapshot(address)
            if not prev_positions:
                continue

            current = await nansen_client.fetch_address_positions(address)
            current_tokens = {
                ap.position.token_symbol for ap in current.asset_positions
            }

            # Fetch recent trades to check for Close actions
            recent_trades = await nansen_client.fetch_address_trades(
                address,
                date_from=(datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d"),
                date_to=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            recent_close_tokens = {
                t.token_symbol
                for t in recent_trades
                if t.closed_pnl != 0
            }

            for prev_pos in prev_positions:
                if prev_pos["token_symbol"] not in current_tokens:
                    if prev_pos["token_symbol"] not in recent_close_tokens:
                        liquidated.append(address)
                        datastore.add_to_blacklist(address, "liquidation")
                        logger.warning(
                            "Probable liquidation detected for %s on %s",
                            address,
                            prev_pos["token_symbol"],
                        )
                        break

        except Exception as e:
            logger.warning(
                "Failed to check liquidation for %s: %s",
                address,
                e,
            )
            continue

    return liquidated


async def monitor_positions(
    nansen_client: NansenClient,
    datastore: DataStore,
) -> list[str]:
    """
    Main entry point called every 15 minutes to monitor positions and detect liquidations.

    Args:
        nansen_client: Async Nansen API client
        datastore: Datastore for persistence and queries

    Returns:
        List of addresses that were liquidated during this monitoring cycle
    """
    traders = datastore.get_active_traders()
    logger.info("Starting position monitoring for %d traders", len(traders))

    # Snapshot current positions for all traders
    for address in traders:
        await snapshot_positions_for_trader(address, nansen_client, datastore)

    # Detect liquidations by comparing snapshots
    liquidated = await detect_liquidations(traders, datastore, nansen_client)

    logger.info(
        "Position monitoring complete: %d traders checked, %d liquidations detected",
        len(traders),
        len(liquidated),
    )

    return liquidated
