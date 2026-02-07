import logging
import time
from typing import Optional

from src.risk.nansen_client import NansenClient
from src.risk.hyperliquid_client import HyperliquidClient
from src.risk.types import PositionSnapshot

logger = logging.getLogger(__name__)

# If Nansen fails for this many seconds, switch to HL fallback
NANSEN_FALLBACK_THRESHOLD_S = 30.0


class PositionFetcher:
    """
    Fetches position snapshots for monitoring, using Nansen as primary
    and Hyperliquid public API as fallback for mark prices.

    This class is the `fetch_positions` callable wired into MonitoringLoop.
    """

    def __init__(
        self,
        address: str,
        nansen_client: NansenClient,
        hl_client: HyperliquidClient,
    ) -> None:
        self.address = address
        self.nansen = nansen_client
        self.hl = hl_client
        self._nansen_fail_since: Optional[float] = None

    async def fetch_positions(self) -> list[PositionSnapshot]:
        """
        Fetch current positions as PositionSnapshot list.

        Primary: Nansen Address Perp Positions API
        Fallback: If Nansen fails for >30s, use Hyperliquid for mark prices.
        """
        nansen_positions = None
        try:
            nansen_positions = await self.nansen.fetch_address_perp_positions(
                self.address
            )
            self._nansen_fail_since = None  # Reset on success
        except Exception as e:
            now = time.monotonic()
            if self._nansen_fail_since is None:
                self._nansen_fail_since = now
            elapsed = now - self._nansen_fail_since
            logger.warning(
                "Nansen fetch failed (%.1fs since first failure): %s", elapsed, e
            )

        if nansen_positions is None:
            logger.warning("No Nansen data available, returning empty positions")
            return []

        # Check if we need HL fallback for mark prices
        use_hl_fallback = (
            self._nansen_fail_since is not None
            and (time.monotonic() - self._nansen_fail_since) > NANSEN_FALLBACK_THRESHOLD_S
        )

        hl_prices: dict[str, float] = {}
        if use_hl_fallback:
            try:
                hl_prices = await self.hl.fetch_all_mids()
                logger.info("Using Hyperliquid fallback for mark prices")
            except Exception as e:
                logger.error("Hyperliquid fallback also failed: %s", e)

        snapshots: list[PositionSnapshot] = []
        for npos in nansen_positions:
            mark_override = hl_prices.get(npos.token) if use_hl_fallback else None
            snapshots.append(
                NansenClient.to_position_snapshot(npos, mark_override)
            )

        return snapshots

    async def close(self) -> None:
        """Close underlying HTTP clients."""
        await self.nansen.close()
        await self.hl.close()
