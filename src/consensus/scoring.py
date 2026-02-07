"""Trader scoring, style classification, and watchlist construction."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from consensus.models import TradeRecord, TraderStyle


def calculate_avg_hold_time(trades: list[TradeRecord]) -> float:
    """Estimate average hold time in hours from open/close trade pairs.

    Groups trades by (trader, token, side) and computes the time between
    the first Open and the last Close for each group.  Returns the average
    across all completed round-trips, or 0 if none found.
    """
    # Build open/close timestamps per (trader, token, side)
    opens: dict[tuple[str, str, str], datetime] = {}
    hold_times: list[float] = []

    for t in sorted(trades, key=lambda x: x.timestamp):
        key = (t.trader_address, t.token_symbol, t.side)
        if t.action == "Open":
            opens[key] = t.timestamp
        elif t.action == "Close" and key in opens:
            dt = (t.timestamp - opens.pop(key)).total_seconds() / 3600
            if dt > 0:
                hold_times.append(dt)

    return sum(hold_times) / len(hold_times) if hold_times else 0.0


def classify_trader_style(trades: list[TradeRecord], days_active: int) -> TraderStyle:
    """Classify a trader as HFT, SWING, or POSITION based on trade frequency and hold time."""
    trades_per_day = len(trades) / max(days_active, 1)
    avg_hold_time_hours = calculate_avg_hold_time(trades)

    if trades_per_day > 5 and avg_hold_time_hours < 4:
        return TraderStyle.HFT
    elif trades_per_day >= 0.3 and avg_hold_time_hours < 336:  # < 2 weeks
        return TraderStyle.SWING
    else:
        return TraderStyle.POSITION


def compute_trader_score(
    trader: dict,
    trades: list[TradeRecord],
    now: datetime | None = None,
) -> float:
    """Compute composite TRADER_SCORE.

    Formula:
        (0.25 * normalized_roi + 0.20 * normalized_sharpe +
         0.15 * normalized_win_rate + 0.20 * consistency +
         0.10 * smart_money_bonus + 0.10 * risk_score)
        * style_multiplier * recency_decay

    Args:
        trader: Dict with keys roi_7d, roi_30d, roi_90d, label (optional).
        trades: List of TradeRecord for the scoring window.
        now: Current time (defaults to utcnow).
    """
    if now is None:
        now = datetime.now(UTC)

    if not trades:
        return 0.0

    # --- Normalized ROI (0-1, capped at 100%) ---
    normalized_roi = min(1.0, max(0.0, trader.get("roi_90d", 0) / 100))

    # --- Pseudo-Sharpe ---
    close_trades = [t for t in trades if t.action == "Close" and t.value_usd > 0]
    returns = [t.closed_pnl / t.value_usd for t in close_trades]
    if returns:
        avg_ret = sum(returns) / len(returns)
        std_ret = (sum((r - avg_ret) ** 2 for r in returns) / max(len(returns) - 1, 1)) ** 0.5
        normalized_sharpe = min(1.0, max(0.0, (avg_ret / std_ret) if std_ret > 0 else 0.0))
    else:
        avg_ret = 0.0
        normalized_sharpe = 0.0

    # --- Win rate ---
    winners = sum(1 for r in returns if r > 0)
    normalized_win_rate = winners / len(returns) if returns else 0.0

    # --- Consistency (7d vs 30d vs 90d all positive) ---
    roi_7d = trader.get("roi_7d", 0)
    roi_30d = trader.get("roi_30d", 0)
    roi_90d = trader.get("roi_90d", 0)
    positives = sum(1 for r in [roi_7d, roi_30d, roi_90d] if r > 0)
    if positives == 3:
        consistency = 0.85
    elif positives == 2:
        consistency = 0.50
    else:
        consistency = 0.20

    # --- Smart money bonus ---
    label = trader.get("label", "")
    if "Fund" in label:
        sm_bonus = 1.0
    elif "Smart" in label:
        sm_bonus = 0.8
    elif label:
        sm_bonus = 0.5
    else:
        sm_bonus = 0.0

    # --- Risk management score (lower avg leverage = better) ---
    total_value = sum(t.value_usd for t in trades)
    total_size = sum(abs(t.size) for t in trades)
    avg_leverage = total_value / max(total_size, 1)
    risk_score = min(1.0, max(0.0, 1.0 - (avg_leverage / 20)))

    # --- Style multiplier ---
    style = classify_trader_style(trades, 90)
    style_mult = {"SWING": 1.0, "POSITION": 0.8, "HFT": 0.0}[style.value]

    # --- Recency decay ---
    last_trade_time = max(t.timestamp for t in trades)
    # Handle timezone-aware vs naive datetimes
    if last_trade_time.tzinfo is None:
        days_since_last = (now.replace(tzinfo=None) - last_trade_time).days
    else:
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        days_since_last = (now - last_trade_time).days
    recency_decay = math.exp(-days_since_last / 30)

    raw_score = (
        0.25 * normalized_roi
        + 0.20 * normalized_sharpe
        + 0.15 * normalized_win_rate
        + 0.20 * consistency
        + 0.10 * sm_bonus
        + 0.10 * risk_score
    )

    return raw_score * style_mult * recency_decay
