"""Confirmation window and slippage gate for consensus signals."""

from __future__ import annotations

import logging
from datetime import datetime

from consensus.config import StrategyConfig
from consensus.models import ConsensusSide, PendingSignal, TokenConsensus

logger = logging.getLogger(__name__)


class SignalGate:
    """Manages pending signals with confirmation delay and slippage checks.

    A signal must survive a ``COPY_DELAY_MINUTES`` confirmation window with
    the consensus still STRONG and the price within
    ``MAX_PRICE_SLIPPAGE_PERCENT`` of the detection-time average entry.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingSignal] = {}

    @property
    def pending_signals(self) -> dict[str, PendingSignal]:
        return self._pending

    def process_consensus_change(
        self,
        token: str,
        new_consensus: TokenConsensus,
        current_price: float,
        config: StrategyConfig,
        now: datetime,
    ) -> PendingSignal | None:
        """Evaluate a consensus update and return a confirmed signal or None.

        Lifecycle:
        1. MIXED consensus → cancel any pending signal for *token*.
        2. First STRONG signal → create a :class:`PendingSignal`, return None.
        3. Still within delay window → return None.
        4. After delay: check slippage gate.
           - Pass → mark confirmed and return the signal.
           - Fail → discard and return None.
        """
        signal = self._pending.get(token)

        # Consensus broke — cancel pending signal
        if new_consensus.consensus == ConsensusSide.MIXED:
            removed = self._pending.pop(token, None)
            if removed is not None:
                logger.info(
                    "Signal cancelled for %s: consensus reverted to MIXED", token
                )
            return None

        if signal is None:
            # New signal detected — start confirmation window
            avg_entry = _compute_weighted_avg_entry(new_consensus)
            self._pending[token] = PendingSignal(
                token_symbol=token,
                consensus=new_consensus.consensus,
                detected_at=now,
                avg_entry_price_at_detection=avg_entry,
            )
            logger.info(
                "New pending signal for %s: %s at avg_entry=%.2f",
                token,
                new_consensus.consensus.value,
                avg_entry,
            )
            return None

        # Check if confirmation window has elapsed
        elapsed_min = (now - signal.detected_at).total_seconds() / 60
        if elapsed_min < config.COPY_DELAY_MINUTES:
            return None  # Still waiting

        # Slippage gate
        price_change_pct = (
            abs(current_price - signal.avg_entry_price_at_detection)
            / signal.avg_entry_price_at_detection
            * 100
        )
        if price_change_pct > config.MAX_PRICE_SLIPPAGE_PERCENT:
            self._pending.pop(token)
            logger.info(
                "Signal rejected for %s: slippage %.2f%% exceeds %.2f%%",
                token,
                price_change_pct,
                config.MAX_PRICE_SLIPPAGE_PERCENT,
            )
            return None

        # Confirmed!
        signal.confirmed = True
        self._pending.pop(token)
        logger.info("Signal confirmed for %s: %s", token, signal.consensus.value)
        return signal


def _compute_weighted_avg_entry(consensus: TokenConsensus) -> float:
    """Approximate the weighted average entry price of consensus traders.

    Uses the ratio of total volume to total trader count on the dominant side
    as a simple proxy. A more precise implementation would aggregate actual
    entry prices from each position, but this is sufficient for the slippage
    gate comparison.
    """
    if consensus.consensus == ConsensusSide.STRONG_LONG:
        count = len(consensus.long_traders)
        volume = consensus.long_volume_usd
    elif consensus.consensus == ConsensusSide.STRONG_SHORT:
        count = len(consensus.short_traders)
        volume = consensus.short_volume_usd
    else:
        return 0.0

    if count == 0:
        return 0.0

    # Volume per trader as a proxy for per-position value
    return volume / count
