"""Anti-Luck Filters & Blacklist Gates (Phase 5)

Provides multi-timeframe profitability gates, win-rate bounds, profit-factor
checks, trade-count minimums, and blacklist eligibility verification.  These
filters run *before* a trader enters the allocation set.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.models import TradeMetrics
from src.datastore import DataStore
from src import config

logger = logging.getLogger(__name__)

LIQUIDATION_COOLDOWN_DAYS = config.LIQUIDATION_COOLDOWN_DAYS


# ---------------------------------------------------------------------------
# Anti-luck filter
# ---------------------------------------------------------------------------


def apply_anti_luck_filter(
    m7: TradeMetrics,
    m30: TradeMetrics,
    m90: TradeMetrics,
) -> tuple[bool, str]:
    """Check multi-timeframe profitability, win-rate, profit-factor, and trade count.

    Returns
    -------
    tuple[bool, str]
        ``(passes, reason_if_failed)``.  When the trader passes all gates
        the reason is ``"passed"``.
    """
    # Multi-timeframe profitability gates (from config)
    g7 = config.ANTI_LUCK_7D
    g30 = config.ANTI_LUCK_30D
    g90 = config.ANTI_LUCK_90D
    wr_lo, wr_hi = config.WIN_RATE_BOUNDS
    min_pf = config.MIN_PROFIT_FACTOR
    trend_pf = config.TREND_TRADER_PF
    min_trades = config.MIN_TRADES_30D

    if not (m7.total_pnl > g7["min_pnl"] and m7.roi_proxy > g7["min_roi"]):
        return False, f"7d gate: pnl={m7.total_pnl:.0f}, roi={m7.roi_proxy:.1f}%"
    if not (m30.total_pnl > g30["min_pnl"] and m30.roi_proxy > g30["min_roi"]):
        return False, f"30d gate: pnl={m30.total_pnl:.0f}, roi={m30.roi_proxy:.1f}%"
    if not (m90.total_pnl > g90["min_pnl"] and m90.roi_proxy > g90["min_roi"]):
        return False, f"90d gate: pnl={m90.total_pnl:.0f}, roi={m90.roi_proxy:.1f}%"

    # Win rate bounds
    if m30.win_rate > wr_hi:
        return False, f"Win rate too high: {m30.win_rate:.2f} (possible manipulation)"
    if m30.win_rate < wr_lo:
        # Allow trend trader exception: low win rate but high profit factor
        if m30.profit_factor < trend_pf:
            return False, (
                f"Win rate {m30.win_rate:.2f} with PF {m30.profit_factor:.1f} "
                f"(not trend trader)"
            )
        # Trend trader passes

    # Profit factor gate
    if m30.profit_factor < min_pf:
        # Trend trader variant: win<40% but PF>trend_pf is OK (already handled above)
        if not (m30.win_rate < 0.40 and m30.profit_factor > trend_pf):
            return False, f"Profit factor {m30.profit_factor:.2f} < {min_pf}"

    # Minimum trade count for statistical significance
    if m30.total_trades < min_trades:
        return False, f"Insufficient trades: {m30.total_trades} < {min_trades}"

    return True, "passed"


# ---------------------------------------------------------------------------
# Blacklist check
# ---------------------------------------------------------------------------


def is_trader_eligible(address: str, datastore: DataStore) -> tuple[bool, str]:
    """Check whether a trader is currently blacklisted.

    Returns
    -------
    tuple[bool, str]
        ``(eligible, reason)``.
    """
    if datastore.is_blacklisted(address):
        entry = datastore.get_blacklist_entry(address)
        if entry:
            return False, (
                f"Blacklisted until {entry['expires_at']} ({entry['reason']})"
            )
        return False, "Blacklisted (details unavailable)"
    return True, "eligible"


def blacklist_trader(address: str, reason: str, datastore: DataStore) -> None:
    """Add a trader to the blacklist with the configured cooldown period."""
    expires = (datetime.utcnow() + timedelta(days=LIQUIDATION_COOLDOWN_DAYS)).isoformat()
    datastore.add_to_blacklist(address, reason, expires)
    logger.info("Blacklisted %s for %d days: %s", address, LIQUIDATION_COOLDOWN_DAYS, reason)


# ---------------------------------------------------------------------------
# Combined eligibility gate
# ---------------------------------------------------------------------------


def is_fully_eligible(
    address: str,
    m7: TradeMetrics,
    m30: TradeMetrics,
    m90: TradeMetrics,
    datastore: DataStore,
) -> tuple[bool, str]:
    """Run both blacklist check and anti-luck filter.

    Returns
    -------
    tuple[bool, str]
        ``(eligible, reason)``.
    """
    ok, reason = is_trader_eligible(address, datastore)
    if not ok:
        return False, reason

    ok, reason = apply_anti_luck_filter(m7, m30, m90)
    if not ok:
        return False, reason

    return True, "eligible"
