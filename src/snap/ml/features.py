"""Feature extraction for ML trader selection model."""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timedelta

from snap.scoring import (
    compute_trade_metrics,
    compute_consistency_score,
    compute_smart_money_bonus,
    compute_risk_mgmt_score,
    compute_recency_decay,
)

FEATURE_COLUMNS: list[str] = [
    "roi_7d",
    "roi_30d",
    "roi_90d",
    "pnl_7d",
    "pnl_30d",
    "pnl_90d",
    "win_rate",
    "profit_factor",
    "pseudo_sharpe",
    "trade_count",
    "avg_hold_hours",
    "trades_per_day",
    "consistency_score",
    "smart_money_bonus",
    "risk_mgmt_score",
    "recency_decay",
    "position_concentration",
    "num_open_positions",
    "avg_leverage",
    "pnl_volatility_7d",
    "market_correlation",
    "days_since_last_trade",
    "max_drawdown_30d",
]


def compute_pnl_volatility(pnls: list[float]) -> float:
    """Standard deviation of per-trade PnL values."""
    if len(pnls) < 2:
        return 0.0
    return statistics.stdev(pnls)


def compute_position_concentration(position_values: list[float]) -> float:
    """Fraction of total position value in the largest single position."""
    if not position_values:
        return 0.0
    total = sum(abs(v) for v in position_values)
    if total == 0:
        return 0.0
    return max(abs(v) for v in position_values) / total


def compute_max_drawdown(pnls: list[float]) -> float:
    """Max peak-to-trough drawdown on cumulative PnL series.

    Returns a value in [0, 1] representing the fraction lost from peak.
    """
    if not pnls:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        if peak > 0:
            dd = (peak - cumulative) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _fetch_trades_in_window(
    conn: sqlite3.Connection,
    address: str,
    window_start: str,
    window_end: str,
) -> list[dict]:
    """Fetch trades for a trader within a time window."""
    rows = conn.execute(
        """SELECT token_symbol, action, side, size, price, value_usd,
                  closed_pnl, fee_usd, timestamp
           FROM trade_history
           WHERE address = ? AND timestamp >= ? AND timestamp <= ?
           ORDER BY timestamp ASC""",
        (address, window_start, window_end),
    ).fetchall()
    cols = [
        "token_symbol", "action", "side", "size", "price",
        "value_usd", "closed_pnl", "fee_usd", "timestamp",
    ]
    return [dict(zip(cols, r)) for r in rows]


def _compute_roi_from_trades(trades: list[dict], account_value: float) -> float:
    """Compute ROI from realized PnL in trade list."""
    if not trades or account_value <= 0:
        return 0.0
    total_pnl = sum(float(t.get("closed_pnl", 0) or 0) for t in trades)
    return total_pnl / account_value


def _get_nearest_positions(
    conn: sqlite3.Connection,
    address: str,
    as_of: datetime,
) -> list[dict]:
    """Get position snapshot nearest to as_of date."""
    as_of_str = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        """SELECT token_symbol, side, position_value_usd, leverage_value
           FROM position_snapshots
           WHERE address = ? AND captured_at <= ?
           ORDER BY captured_at DESC
           LIMIT 50""",
        (address, as_of_str),
    ).fetchall()
    if not rows:
        return []
    return [
        {"token": r[0], "side": r[1], "value_usd": float(r[2]), "leverage": float(r[3])}
        for r in rows
    ]


def extract_trader_features(
    conn: sqlite3.Connection,
    address: str,
    as_of: datetime,
    lookback_days: int = 90,
) -> dict | None:
    """Extract all ML features for a trader at a point in time.

    Returns None if the trader has insufficient data (< 10 trades in window).
    """
    window_end = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
    window_start_90 = (as_of - timedelta(days=lookback_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    window_start_30 = (as_of - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_start_7 = (as_of - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fetch trades for different windows
    trades_90 = _fetch_trades_in_window(conn, address, window_start_90, window_end)
    if len(trades_90) < 10:
        return None

    trades_30 = [t for t in trades_90 if t["timestamp"] >= window_start_30]
    trades_7 = [t for t in trades_90 if t["timestamp"] >= window_start_7]

    # Account value and label
    row = conn.execute(
        "SELECT account_value, label FROM traders WHERE address = ?", (address,)
    ).fetchone()
    account_value = float(row[0]) if row and row[0] else 100_000.0
    label = row[1] if row else ""

    # ROI per window
    roi_7d = _compute_roi_from_trades(trades_7, account_value)
    roi_30d = _compute_roi_from_trades(trades_30, account_value)
    roi_90d = _compute_roi_from_trades(trades_90, account_value)

    # PnL per window
    pnl_7d = sum(float(t.get("closed_pnl", 0) or 0) for t in trades_7)
    pnl_30d = sum(float(t.get("closed_pnl", 0) or 0) for t in trades_30)
    pnl_90d = sum(float(t.get("closed_pnl", 0) or 0) for t in trades_90)

    # Trade metrics from scoring.py (uses 90d trades)
    metrics = compute_trade_metrics(trades_90)

    # Scoring features
    consistency = compute_consistency_score(roi_7d, roi_30d, roi_90d)
    smart_money = compute_smart_money_bonus(label)
    avg_leverage = None  # computed from positions below
    risk_mgmt = compute_risk_mgmt_score(avg_leverage)
    recency = compute_recency_decay(metrics.get("most_recent_trade"))

    # Position-based features
    positions = _get_nearest_positions(conn, address, as_of)
    pos_values = [p["value_usd"] for p in positions]
    pos_leverages = [p["leverage"] for p in positions]
    position_concentration = compute_position_concentration(pos_values)
    num_open_positions = len(positions)
    avg_leverage_val = (
        sum(pos_leverages) / len(pos_leverages) if pos_leverages else 0.0
    )

    # Recompute risk_mgmt with actual leverage
    risk_mgmt = compute_risk_mgmt_score(avg_leverage_val if avg_leverage_val > 0 else None)

    # PnL volatility (per-trade PnL stddev over last 7 days)
    pnls_7d = [float(t.get("closed_pnl", 0) or 0) for t in trades_7]
    pnl_vol = compute_pnl_volatility(pnls_7d)

    # Days since last trade
    if trades_90:
        last_ts = trades_90[-1]["timestamp"]
        try:
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            days_since = (as_of - last_dt.replace(tzinfo=None)).total_seconds() / 86400
        except (ValueError, TypeError):
            days_since = 999.0
    else:
        days_since = 999.0

    # Max drawdown over 30d
    pnls_30d = [float(t.get("closed_pnl", 0) or 0) for t in trades_30]
    max_dd = compute_max_drawdown(pnls_30d)

    # Market correlation — placeholder 0.0 (requires BTC price series)
    market_corr = 0.0

    return {
        "roi_7d": roi_7d,
        "roi_30d": roi_30d,
        "roi_90d": roi_90d,
        "pnl_7d": pnl_7d,
        "pnl_30d": pnl_30d,
        "pnl_90d": pnl_90d,
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "pseudo_sharpe": metrics["pseudo_sharpe"],
        "trade_count": metrics["trade_count"],
        "avg_hold_hours": metrics["avg_hold_hours"],
        "trades_per_day": metrics["trades_per_day"],
        "consistency_score": consistency,
        "smart_money_bonus": smart_money,
        "risk_mgmt_score": risk_mgmt,
        "recency_decay": recency,
        "position_concentration": position_concentration,
        "num_open_positions": num_open_positions,
        "avg_leverage": avg_leverage_val,
        "pnl_volatility_7d": pnl_vol,
        "market_correlation": market_corr,
        "days_since_last_trade": days_since,
        "max_drawdown_30d": max_dd,
    }


def extract_all_trader_features(
    conn: sqlite3.Connection,
    as_of: datetime,
    lookback_days: int = 90,
) -> list[dict]:
    """Extract features for all traders with sufficient history.

    Returns list of dicts, each with 'address' key plus all FEATURE_COLUMNS.
    """
    window_start = (as_of - timedelta(days=lookback_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    window_end = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Find traders with at least 10 trades in window
    addresses = [
        r[0]
        for r in conn.execute(
            """SELECT address FROM trade_history
               WHERE timestamp >= ? AND timestamp <= ?
               GROUP BY address
               HAVING COUNT(*) >= 10""",
            (window_start, window_end),
        ).fetchall()
    ]

    results = []
    for addr in addresses:
        features = extract_trader_features(conn, addr, as_of, lookback_days)
        if features is not None:
            features["address"] = addr
            results.append(features)
    return results
