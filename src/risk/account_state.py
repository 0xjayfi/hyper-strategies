import asyncio
import logging
import time
from typing import Optional

from src.risk.nansen_client import NansenClient, NansenPerpPosition
from src.risk.types import AccountState

logger = logging.getLogger(__name__)

# Default refresh interval
DEFAULT_REFRESH_INTERVAL_S = 60.0


def build_account_state(
    positions: list[NansenPerpPosition],
    account_value_usd: float,
) -> AccountState:
    """
    Build an AccountState from a list of Nansen perp positions.

    Aggregates:
      - total_open_positions_usd: sum of abs(position_value_usd)
      - total_long_exposure_usd: sum of position_value_usd where side == "Long"
      - total_short_exposure_usd: sum of position_value_usd where side == "Short"
      - token_exposure_usd: {token: sum of abs(position_value_usd)} per token
    """
    total_open = 0.0
    total_long = 0.0
    total_short = 0.0
    token_exposure: dict[str, float] = {}

    for pos in positions:
        abs_value = abs(pos.position_value_usd)
        total_open += abs_value

        if pos.side == "Long":
            total_long += abs_value
        else:
            total_short += abs_value

        token_exposure[pos.token] = token_exposure.get(pos.token, 0.0) + abs_value

    return AccountState(
        account_value_usd=account_value_usd,
        total_open_positions_usd=total_open,
        total_long_exposure_usd=total_long,
        total_short_exposure_usd=total_short,
        token_exposure_usd=token_exposure,
    )


class AccountStateManager:
    """
    Manages a periodically-refreshed AccountState from Nansen API data.

    Provides `get_current_state()` for callers (e.g. calculate_position_size)
    to get the latest account snapshot without blocking on an API call.

    Args:
        address: Wallet address to fetch positions for.
        nansen_client: NansenClient instance.
        account_value_usd: Starting account value (updated externally or via refresh_account_value callback).
        refresh_interval_s: How often to refresh (default 60s).
        refresh_account_value: Optional async callable that returns current account_value_usd.
    """

    def __init__(
        self,
        address: str,
        nansen_client: NansenClient,
        account_value_usd: float,
        refresh_interval_s: float = DEFAULT_REFRESH_INTERVAL_S,
        refresh_account_value: Optional[callable] = None,
    ) -> None:
        self.address = address
        self.nansen = nansen_client
        self._account_value_usd = account_value_usd
        self.refresh_interval_s = refresh_interval_s
        self._refresh_account_value = refresh_account_value
        self._state: AccountState = AccountState(account_value_usd=account_value_usd)
        self._last_refresh: float = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None

    @property
    def state(self) -> AccountState:
        """Current cached AccountState."""
        return self._state

    def get_current_state(self) -> AccountState:
        """
        Get the current AccountState for use with calculate_position_size.

        Returns the most recently fetched state. Callers do not need to await;
        the background refresh loop keeps the state fresh.
        """
        return self._state

    async def refresh(self) -> AccountState:
        """
        Fetch fresh positions from Nansen and rebuild the AccountState.

        This is called periodically by the background loop, but can also
        be called manually before sizing a new position.
        """
        # Optionally refresh account value
        if self._refresh_account_value is not None:
            try:
                self._account_value_usd = await self._refresh_account_value()
            except Exception as e:
                logger.warning("Failed to refresh account value: %s", e)

        # Fetch positions
        positions = await self.nansen.fetch_address_perp_positions(self.address)

        # Build new state
        self._state = build_account_state(positions, self._account_value_usd)
        self._last_refresh = time.monotonic()

        logger.info(
            "AccountState refreshed: total_open=$%.0f, long=$%.0f, short=$%.0f, tokens=%d",
            self._state.total_open_positions_usd,
            self._state.total_long_exposure_usd,
            self._state.total_short_exposure_usd,
            len(self._state.token_exposure_usd),
        )

        return self._state

    @property
    def seconds_since_refresh(self) -> float:
        """Seconds since the last successful refresh."""
        if self._last_refresh == 0.0:
            return float("inf")
        return time.monotonic() - self._last_refresh

    async def ensure_fresh(self, max_age_s: Optional[float] = None) -> AccountState:
        """
        Return current state if fresh enough, otherwise refresh first.

        Args:
            max_age_s: Maximum age in seconds. Defaults to refresh_interval_s.
        """
        threshold = max_age_s if max_age_s is not None else self.refresh_interval_s
        if self.seconds_since_refresh > threshold:
            return await self.refresh()
        return self._state

    async def _run_loop(self) -> None:
        """Background refresh loop."""
        self._running = True
        logger.info(
            "AccountStateManager refresh loop started (interval=%.0fs)",
            self.refresh_interval_s,
        )
        while self._running:
            try:
                await self.refresh()
            except Exception:
                logger.exception("Error refreshing AccountState")
            await asyncio.sleep(self.refresh_interval_s)

    def start(self) -> asyncio.Task:
        """Start the background refresh loop."""
        self._task = asyncio.create_task(self._run_loop())
        return self._task

    async def stop(self) -> None:
        """Stop the background refresh loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AccountStateManager stopped")
