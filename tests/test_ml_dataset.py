"""Tests for ML dataset construction."""

from datetime import datetime, timedelta

import pytest

from snap.database import init_db
from snap.ml.dataset import (
    compute_forward_pnl,
    generate_window_dates,
    build_dataset,
    split_dataset_chronological,
)


def _seed_db(conn, num_traders=5, days=90):
    """Seed a DB with synthetic trade history for testing."""
    base = datetime(2026, 2, 15)
    for t_idx in range(num_traders):
        addr = f"0xtrader{t_idx:04d}"
        conn.execute(
            "INSERT OR REPLACE INTO traders (address, account_value, label) VALUES (?, ?, ?)",
            (addr, 100000.0, ""),
        )
        for d in range(days):
            for h in range(3):  # 3 trades per day
                ts = (base - timedelta(days=d, hours=h * 8)).strftime(
                    "%Y-%m-%dT%H:%M:%S.000000"
                )
                pnl = 100.0 if (d + h + t_idx) % 3 != 0 else -50.0
                conn.execute(
                    """INSERT INTO trade_history
                       (address, token_symbol, action, side, size, price,
                        value_usd, closed_pnl, fee_usd, timestamp, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (addr, "BTC", "Close", "Long", 0.1, 50000.0,
                     5000.0, pnl, 2.0, ts, "2026-02-25T00:00:00Z"),
                )
    conn.commit()


class TestGenerateWindowDates:
    def test_default_stride_is_7(self):
        """Default stride_days should be 7, not 3."""
        dates = generate_window_dates(
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 22),
        )
        # Jan 1, 8, 15 = 3 windows with default stride=7
        assert len(dates) == 3

    def test_returns_dates_stride_3(self):
        dates = generate_window_dates(
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 15),
            stride_days=3,
        )
        assert len(dates) == 5  # Jan 1, 4, 7, 10, 13

    def test_stride_1(self):
        dates = generate_window_dates(
            start=datetime(2026, 1, 1),
            end=datetime(2026, 1, 4),
            stride_days=1,
        )
        assert len(dates) == 3  # Jan 1, 2, 3

    def test_empty_if_start_after_end(self):
        dates = generate_window_dates(
            start=datetime(2026, 2, 1),
            end=datetime(2026, 1, 1),
            stride_days=3,
        )
        assert len(dates) == 0

    def test_stride_7_produces_fewer_windows_than_stride_3(self):
        """Stride=7 should produce significantly fewer windows than stride=3."""
        start = datetime(2026, 1, 1)
        end = datetime(2026, 4, 1)  # 90-day range
        dates_stride_3 = generate_window_dates(start, end, stride_days=3)
        dates_stride_7 = generate_window_dates(start, end, stride_days=7)
        assert len(dates_stride_7) < len(dates_stride_3)
        # Stride-7 should produce roughly 3/7 as many windows as stride-3
        ratio = len(dates_stride_7) / len(dates_stride_3)
        assert 0.3 < ratio < 0.6


class TestComputeForwardPnl:
    def test_sums_pnl_in_forward_window(self):
        conn = init_db(":memory:")
        _seed_db(conn, num_traders=1, days=30)
        addr = "0xtrader0000"
        as_of = datetime(2026, 1, 25)
        pnl = compute_forward_pnl(conn, addr, as_of, forward_days=7)
        assert isinstance(pnl, float)
        conn.close()

    def test_returns_none_if_no_forward_trades(self):
        conn = init_db(":memory:")
        _seed_db(conn, num_traders=1, days=30)
        # as_of is in the future — no trades after it
        pnl = compute_forward_pnl(
            conn, "0xtrader0000", datetime(2026, 3, 1), forward_days=7
        )
        assert pnl is None
        conn.close()


class TestBuildDataset:
    def test_returns_nonempty_dataframe(self):
        conn = init_db(":memory:")
        _seed_db(conn, num_traders=3, days=60)
        df = build_dataset(
            conn,
            start=datetime(2025, 12, 20),
            end=datetime(2026, 2, 1),
            stride_days=7,
            forward_days=7,
        )
        assert len(df) > 0
        assert "forward_pnl_7d" in df.columns
        assert "address" in df.columns
        assert "window_date" in df.columns
        conn.close()

    def test_no_null_targets(self):
        conn = init_db(":memory:")
        _seed_db(conn, num_traders=3, days=60)
        df = build_dataset(
            conn,
            start=datetime(2025, 12, 20),
            end=datetime(2026, 1, 30),
            stride_days=7,
            forward_days=7,
        )
        assert df["forward_pnl_7d"].isna().sum() == 0
        conn.close()


class TestSplitDataset:
    def test_chronological_split(self):
        conn = init_db(":memory:")
        _seed_db(conn, num_traders=3, days=90)
        df = build_dataset(
            conn,
            start=datetime(2025, 12, 1),
            end=datetime(2026, 2, 1),
            stride_days=7,
            forward_days=7,
        )
        train, val, test = split_dataset_chronological(
            df, val_frac=0.2, test_frac=0.15
        )
        # No overlap
        if len(train) > 0 and len(val) > 0:
            assert train["window_date"].max() <= val["window_date"].min()
        if len(val) > 0 and len(test) > 0:
            assert val["window_date"].max() <= test["window_date"].min()
        conn.close()
