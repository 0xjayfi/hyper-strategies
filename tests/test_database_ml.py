"""Tests for ML database tables."""

import sqlite3

from snap.database import init_strategy_db


def test_ml_feature_snapshots_table_exists(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_strategy_db(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ml_feature_snapshots'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_ml_models_table_exists(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_strategy_db(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ml_models'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_ml_feature_snapshots_columns(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_strategy_db(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ml_feature_snapshots)")]
    assert "address" in cols
    assert "snapshot_date" in cols
    assert "roi_7d" in cols
    assert "forward_pnl_7d" in cols
    assert "position_concentration" in cols
    assert "avg_leverage" in cols
    assert "pnl_volatility_7d" in cols
    assert "max_drawdown_30d" in cols
    conn.close()


def test_ml_models_columns(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_strategy_db(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ml_models)")]
    assert "version" in cols
    assert "trained_at" in cols
    assert "val_rmse" in cols
    assert "top15_backtest_pnl" in cols
    assert "model_path" in cols
    assert "is_active" in cols
    conn.close()


def test_insert_feature_snapshot(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_strategy_db(db_path)
    conn.execute(
        """INSERT INTO ml_feature_snapshots
           (address, snapshot_date, roi_7d, roi_30d, win_rate, trade_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("0xabc", "2026-02-25", 0.05, 0.12, 0.85, 500),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ml_feature_snapshots WHERE address='0xabc'").fetchone()
    assert row is not None
    conn.close()


def test_insert_ml_model(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = init_strategy_db(db_path)
    conn.execute(
        """INSERT INTO ml_models
           (version, trained_at, train_rmse, val_rmse, test_rmse, model_path, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (1, "2026-02-25T00:00:00Z", 0.05, 0.06, 0.07, "models/v1.json", 1),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM ml_models WHERE version=1").fetchone()
    assert row is not None
    conn.close()
