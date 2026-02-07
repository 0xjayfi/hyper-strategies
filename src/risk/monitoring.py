import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from src.risk.constants import (
    EMERGENCY_CLOSE_BUFFER_PCT,
    REDUCE_BUFFER_PCT,
    REDUCE_POSITION_PCT,
)
from src.risk.types import (
    MonitorResult,
    OrderType,
    PositionSnapshot,
    RiskAction,
    RiskAlert,
    Side,
)

logger = logging.getLogger(__name__)


def check_liquidation_buffer(position: PositionSnapshot) -> MonitorResult:
    """
    Verbatim Agent 1 liquidation buffer monitoring.

    Long:  buffer_pct = (mark_price - liquidation_price) / mark_price * 100
    Short: buffer_pct = (liquidation_price - mark_price) / mark_price * 100

    Actions:
      buffer < 10% -> emergency close (market order)
      buffer < 20% -> reduce position by 50% (market order)
      buffer >= 20% -> no action
    """
    if position.mark_price <= 0:
        raise ValueError("mark_price must be > 0")
    if position.liquidation_price <= 0:
        raise ValueError("liquidation_price must be > 0")

    if position.side == Side.LONG:
        buffer_pct = (position.mark_price - position.liquidation_price) / position.mark_price * 100
    else:
        buffer_pct = (position.liquidation_price - position.mark_price) / position.mark_price * 100

    if buffer_pct < EMERGENCY_CLOSE_BUFFER_PCT:
        return MonitorResult(
            action=RiskAction.EMERGENCY_CLOSE,
            buffer_pct=buffer_pct,
            reduce_pct=100.0,
            order_type=OrderType.MARKET,
        )
    elif buffer_pct < REDUCE_BUFFER_PCT:
        return MonitorResult(
            action=RiskAction.REDUCE,
            buffer_pct=buffer_pct,
            reduce_pct=REDUCE_POSITION_PCT,
            order_type=OrderType.MARKET,
        )
    else:
        return MonitorResult(
            action=RiskAction.NONE,
            buffer_pct=buffer_pct,
            reduce_pct=None,
            order_type=OrderType.MARKET,
        )


def _build_alert(position: PositionSnapshot, result: MonitorResult) -> RiskAlert:
    """Build a RiskAlert from a position and its monitor result."""
    return RiskAlert(
        timestamp=datetime.now(timezone.utc).isoformat(),
        token=position.token,
        side=position.side,
        action=result.action,
        buffer_pct=result.buffer_pct,
        position_value_usd=position.position_value_usd,
        mark_price=position.mark_price,
        liquidation_price=position.liquidation_price,
    )


class MonitoringLoop:
    """
    Async monitoring loop that periodically checks liquidation buffers
    for all open positions.

    Args:
        fetch_positions: Async callable that returns a list of PositionSnapshot.
        on_alert: Async callable invoked when a risk action is triggered.
        on_action: Async callable invoked to execute a risk action (reduce/close).
        poll_interval_s: Seconds between polling cycles (default 15).
        cooldown_s: Seconds to skip a position after a reduce action (default 60).
    """

    def __init__(
        self,
        fetch_positions: Callable[[], "asyncio.coroutines"],
        on_alert: Optional[Callable[[RiskAlert], "asyncio.coroutines"]] = None,
        on_action: Optional[Callable[[PositionSnapshot, MonitorResult], "asyncio.coroutines"]] = None,
        poll_interval_s: float = 15.0,
        cooldown_s: float = 60.0,
    ) -> None:
        self.fetch_positions = fetch_positions
        self.on_alert = on_alert
        self.on_action = on_action
        self.poll_interval_s = poll_interval_s
        self.cooldown_s = cooldown_s
        self._cooldowns: dict[str, float] = {}  # token -> timestamp when cooldown expires
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def _cooldown_key(self, position: PositionSnapshot) -> str:
        """Unique key for cooldown tracking: token + side."""
        return f"{position.token}:{position.side.value}"

    def _is_on_cooldown(self, position: PositionSnapshot) -> bool:
        """Check if position is within cooldown window."""
        key = self._cooldown_key(position)
        if key not in self._cooldowns:
            return False
        return time.monotonic() < self._cooldowns[key]

    def _set_cooldown(self, position: PositionSnapshot) -> None:
        """Set cooldown for a position after a reduce action."""
        key = self._cooldown_key(position)
        self._cooldowns[key] = time.monotonic() + self.cooldown_s

    async def _check_single(self, position: PositionSnapshot) -> None:
        """Check one position and handle any required actions."""
        if self._is_on_cooldown(position):
            logger.debug("Skipping %s:%s (cooldown)", position.token, position.side.value)
            return

        result = check_liquidation_buffer(position)

        if result.action == RiskAction.NONE:
            return

        # Emit alert
        alert = _build_alert(position, result)
        if result.action == RiskAction.EMERGENCY_CLOSE:
            logger.critical(
                "EMERGENCY CLOSE %s %s — buffer %.1f%%",
                position.token, position.side.value, result.buffer_pct,
            )
        else:
            logger.warning(
                "REDUCE 50%% %s %s — buffer %.1f%%",
                position.token, position.side.value, result.buffer_pct,
            )

        if self.on_alert is not None:
            await self.on_alert(alert)

        # Execute action
        if self.on_action is not None:
            await self.on_action(position, result)

        # Set cooldown after reduce (not emergency close — position will be gone)
        if result.action == RiskAction.REDUCE:
            self._set_cooldown(position)

    async def _poll_once(self) -> list[RiskAlert]:
        """Run one polling cycle. Returns alerts emitted."""
        alerts: list[RiskAlert] = []
        positions = await self.fetch_positions()

        for position in positions:
            if self._is_on_cooldown(position):
                logger.debug("Skipping %s:%s (cooldown)", position.token, position.side.value)
                continue

            result = check_liquidation_buffer(position)

            if result.action == RiskAction.NONE:
                continue

            alert = _build_alert(position, result)
            alerts.append(alert)

            if result.action == RiskAction.EMERGENCY_CLOSE:
                logger.critical(
                    "EMERGENCY CLOSE %s %s — buffer %.1f%%",
                    position.token, position.side.value, result.buffer_pct,
                )
            else:
                logger.warning(
                    "REDUCE 50%% %s %s — buffer %.1f%%",
                    position.token, position.side.value, result.buffer_pct,
                )

            if self.on_alert is not None:
                await self.on_alert(alert)

            if self.on_action is not None:
                await self.on_action(position, result)

            if result.action == RiskAction.REDUCE:
                self._set_cooldown(position)

        return alerts

    async def run(self) -> None:
        """Start the monitoring loop. Runs until stop() is called."""
        self._running = True
        logger.info("MonitoringLoop started (interval=%.1fs)", self.poll_interval_s)
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Error during monitoring poll")
            await asyncio.sleep(self.poll_interval_s)

    def start(self) -> asyncio.Task:
        """Start the loop as a background asyncio task."""
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MonitoringLoop stopped")
