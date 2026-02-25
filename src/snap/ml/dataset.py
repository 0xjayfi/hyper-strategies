"""Dataset construction for ML trader selection via sliding window."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from snap.ml.features import FEATURE_COLUMNS, extract_all_trader_features


def generate_window_dates(
    start: datetime,
    end: datetime,
    stride_days: int = 3,
) -> list[datetime]:
    """Generate evaluation dates from start to end at stride intervals.

    The end date is exclusive — last window must leave room for forward PnL.
    """
    dates = []
    current = start
    while current < end:
        dates.append(current)
        current += timedelta(days=stride_days)
    return dates


def compute_forward_pnl(
    conn: sqlite3.Connection,
    address: str,
    as_of: datetime,
    forward_days: int = 7,
) -> float | None:
    """Compute a trader's total realized PnL in the forward window.

    Returns None if the trader has no trades in the forward window.
    """
    start = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (as_of + timedelta(days=forward_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = conn.execute(
        """SELECT SUM(closed_pnl), COUNT(*)
           FROM trade_history
           WHERE address = ? AND timestamp > ? AND timestamp <= ?""",
        (address, start, end),
    ).fetchone()
    if row is None or row[1] == 0:
        return None
    return float(row[0]) if row[0] is not None else None


def build_dataset(
    conn: sqlite3.Connection,
    start: datetime,
    end: datetime,
    stride_days: int = 3,
    forward_days: int = 7,
    lookback_days: int = 90,
) -> pd.DataFrame:
    """Build labeled dataset using sliding window over trade history.

    For each window date, extract features for all traders and compute
    their forward PnL. Rows with no forward PnL are dropped.

    Returns DataFrame with columns: address, window_date, FEATURE_COLUMNS, forward_pnl_7d
    """
    # End date for windows must allow forward_days of future data
    window_end = end - timedelta(days=forward_days)
    window_dates = generate_window_dates(start, window_end, stride_days)

    all_rows: list[dict] = []
    for wdate in window_dates:
        features_list = extract_all_trader_features(conn, wdate, lookback_days)
        for feat in features_list:
            addr = feat.pop("address")
            fwd_pnl = compute_forward_pnl(conn, addr, wdate, forward_days)
            if fwd_pnl is None:
                continue
            # Normalize by account value
            acct_row = conn.execute(
                "SELECT account_value FROM traders WHERE address = ?", (addr,)
            ).fetchone()
            acct_val = float(acct_row[0]) if acct_row and acct_row[0] else 100_000.0
            normalized_pnl = fwd_pnl / acct_val if acct_val > 0 else 0.0

            row = {"address": addr, "window_date": wdate, **feat, "forward_pnl_7d": normalized_pnl}
            all_rows.append(row)

    if not all_rows:
        return pd.DataFrame(columns=["address", "window_date"] + FEATURE_COLUMNS + ["forward_pnl_7d"])

    return pd.DataFrame(all_rows)


def split_dataset_chronological(
    df: pd.DataFrame,
    val_frac: float = 0.2,
    test_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split dataset by time — train, validation, test.

    Ensures no future data leaks into training.
    """
    sorted_dates = sorted(df["window_date"].unique())
    n = len(sorted_dates)
    if n < 3:
        return df, pd.DataFrame(), pd.DataFrame()

    test_start_idx = max(1, int(n * (1 - test_frac)))
    val_start_idx = max(1, int(n * (1 - test_frac - val_frac)))

    test_start_date = sorted_dates[test_start_idx]
    val_start_date = sorted_dates[val_start_idx]

    train = df[df["window_date"] < val_start_date].copy()
    val = df[(df["window_date"] >= val_start_date) & (df["window_date"] < test_start_date)].copy()
    test = df[df["window_date"] >= test_start_date].copy()

    return train, val, test
