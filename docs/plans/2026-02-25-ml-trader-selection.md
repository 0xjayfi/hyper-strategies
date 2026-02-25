# ML Trader Selection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Train an XGBoost model to predict trader forward 7-day PnL, replacing the hand-tuned composite score for trader selection.

**Architecture:** Backfill labeled training data from 3 months of trade history using a sliding window, train an XGBoost regressor, integrate via shadow mode alongside existing scoring, then toggle to live mode. New `src/snap/ml/` package with feature extraction, dataset construction, training, and prediction modules.

**Tech Stack:** XGBoost, scikit-learn, numpy, pandas (already transitive dep), SQLite for feature snapshots.

**Design Doc:** `docs/plans/2026-02-25-ml-trader-selection-design.md`

---

## Task 1: Add Dependencies & Create ML Package Skeleton

**Files:**
- Modify: `pyproject.toml:6-12`
- Create: `src/snap/ml/__init__.py`

**Step 1: Add ML dependencies to pyproject.toml**

In `pyproject.toml`, add xgboost, scikit-learn, and numpy to the dependencies list (lines 6-12):

```python
dependencies = [
    "httpx>=0.27",
    "pydantic>=2.0",
    "python-dotenv>=1.0",
    "rich>=13.0",
    "textual>=0.85",
    "xgboost>=2.0",
    "scikit-learn>=1.4",
    "numpy>=1.26",
]
```

**Step 2: Create ml package**

Create `src/snap/ml/__init__.py` with empty content (just a docstring):

```python
"""ML-based trader selection for Snap."""
```

**Step 3: Install updated dependencies**

Run: `pip install -e ".[dev]"`
Expected: Successful install with xgboost, scikit-learn, numpy

**Step 4: Verify imports work**

Run: `python -c "import xgboost; import sklearn; import numpy; print('OK')"`
Expected: `OK`

**Step 5: Commit**

```bash
git add pyproject.toml src/snap/ml/__init__.py
git commit -m "feat(ml): add xgboost/sklearn deps and ml package skeleton"
```

---

## Task 2: Add ML Config Constants

**Files:**
- Modify: `src/snap/config.py` (add after line 151, end of file)
- Test: `tests/test_config_ml.py`

**Step 1: Write the failing test**

Create `tests/test_config_ml.py`:

```python
"""Tests for ML configuration constants."""

from snap import config


def test_ml_defaults_exist():
    assert hasattr(config, "ML_TRADER_SELECTION")
    assert config.ML_TRADER_SELECTION is False


def test_ml_forward_window():
    assert config.ML_FORWARD_WINDOW_DAYS == 7


def test_ml_retrain_cadence():
    assert config.ML_RETRAIN_CADENCE_DAYS == 7


def test_ml_snapshot_hour():
    assert config.ML_SNAPSHOT_HOUR_UTC == 1


def test_ml_model_dir():
    assert config.ML_MODEL_DIR == "models/"


def test_ml_min_train_samples():
    assert config.ML_MIN_TRAIN_SAMPLES == 5000


def test_ml_backfill_window_stride_days():
    assert config.ML_BACKFILL_STRIDE_DAYS == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_ml.py -v`
Expected: FAIL — `AttributeError: module 'snap.config' has no attribute 'ML_TRADER_SELECTION'`

**Step 3: Add ML constants to config.py**

Append to end of `src/snap/config.py`:

```python

# ===========================================================================
# ML Trader Selection (Phase 10)
# ===========================================================================
ML_TRADER_SELECTION: bool = os.environ.get(
    "SNAP_ML_TRADER_SELECTION", "false"
).lower() in ("true", "1", "yes")
ML_MODEL_DIR: str = os.environ.get("SNAP_ML_MODEL_DIR", "models/")
ML_FORWARD_WINDOW_DAYS: int = int(os.environ.get("SNAP_ML_FORWARD_DAYS", "7"))
ML_RETRAIN_CADENCE_DAYS: int = int(os.environ.get("SNAP_ML_RETRAIN_DAYS", "7"))
ML_SNAPSHOT_HOUR_UTC: int = int(os.environ.get("SNAP_ML_SNAPSHOT_HOUR", "1"))
ML_MIN_TRAIN_SAMPLES: int = int(os.environ.get("SNAP_ML_MIN_SAMPLES", "5000"))
ML_BACKFILL_STRIDE_DAYS: int = int(os.environ.get("SNAP_ML_STRIDE_DAYS", "3"))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_ml.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add src/snap/config.py tests/test_config_ml.py
git commit -m "feat(ml): add ML configuration constants"
```

---

## Task 3: Add ML Database Tables

**Files:**
- Modify: `src/snap/database.py` (add table definitions after line 218, add to `_STRATEGY_STATEMENTS`)
- Test: `tests/test_database_ml.py`

**Step 1: Write the failing test**

Create `tests/test_database_ml.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_database_ml.py -v`
Expected: FAIL — table `ml_feature_snapshots` does not exist

**Step 3: Add table definitions to database.py**

Add the following SQL strings in `src/snap/database.py` after the `_CREATE_SYSTEM_STATE` definition (around line 218), and append them to `_STRATEGY_STATEMENTS` and `_ALL_STATEMENTS`:

```python
_CREATE_ML_FEATURE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS ml_feature_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    address                 TEXT    NOT NULL,
    snapshot_date           TEXT    NOT NULL,
    roi_7d                  REAL,
    roi_30d                 REAL,
    roi_90d                 REAL,
    pnl_7d                  REAL,
    pnl_30d                REAL,
    pnl_90d                REAL,
    win_rate                REAL,
    profit_factor           REAL,
    pseudo_sharpe           REAL,
    trade_count             INTEGER,
    avg_hold_hours          REAL,
    trades_per_day          REAL,
    consistency_score       REAL,
    smart_money_bonus       REAL,
    risk_mgmt_score         REAL,
    position_concentration  REAL,
    num_open_positions      INTEGER,
    avg_leverage            REAL,
    pnl_volatility_7d      REAL,
    market_correlation      REAL,
    days_since_last_trade   REAL,
    max_drawdown_30d        REAL,
    forward_pnl_7d          REAL,
    created_at              TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

_CREATE_ML_MODELS = """
CREATE TABLE IF NOT EXISTS ml_models (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    version                 INTEGER NOT NULL,
    trained_at              TEXT    NOT NULL,
    train_rmse              REAL,
    val_rmse                REAL,
    test_rmse               REAL,
    top15_backtest_pnl      REAL,
    feature_importances     TEXT,
    model_path              TEXT,
    is_active               INTEGER DEFAULT 0
);
"""
```

Then add both to the appropriate statement lists (find where `_STRATEGY_STATEMENTS` is assembled and append):

```python
# Add to _STRATEGY_STATEMENTS list:
_CREATE_ML_FEATURE_SNAPSHOTS,
_CREATE_ML_MODELS,
```

And to `_ALL_STATEMENTS` as well.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_database_ml.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add src/snap/database.py tests/test_database_ml.py
git commit -m "feat(ml): add ml_feature_snapshots and ml_models tables"
```

---

## Task 4: Feature Extraction Module

**Files:**
- Create: `src/snap/ml/features.py`
- Test: `tests/test_ml_features.py`

This module extracts features for a trader at a given point in time from trade history. It reuses computation logic from `scoring.py` (functions at lines 187-610) but operates on arbitrary time windows rather than the "current" state.

**Step 1: Write the failing tests**

Create `tests/test_ml_features.py`:

```python
"""Tests for ML feature extraction."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from snap.database import init_db
from snap.ml.features import (
    FEATURE_COLUMNS,
    compute_pnl_volatility,
    compute_position_concentration,
    compute_max_drawdown,
    extract_trader_features,
    extract_all_trader_features,
)


def _insert_trades(conn, address, trades):
    """Helper: insert trade rows into trade_history."""
    for t in trades:
        conn.execute(
            """INSERT INTO trade_history
               (address, token_symbol, action, side, size, price, value_usd,
                closed_pnl, fee_usd, timestamp, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                address,
                t.get("token", "BTC"),
                t.get("action", "Close"),
                t.get("side", "Long"),
                t.get("size", 1.0),
                t.get("price", 50000.0),
                t.get("value_usd", 50000.0),
                t.get("closed_pnl", 100.0),
                t.get("fee_usd", 5.0),
                t["timestamp"],
                "2026-02-25T00:00:00Z",
            ),
        )
    conn.commit()


def _insert_trader(conn, address, account_value=100000.0, label=""):
    conn.execute(
        "INSERT OR REPLACE INTO traders (address, account_value, label) VALUES (?, ?, ?)",
        (address, account_value, label),
    )
    conn.commit()


def _insert_positions(conn, address, snapshot_batch, positions):
    """Helper: insert position snapshot rows."""
    for p in positions:
        conn.execute(
            """INSERT INTO position_snapshots
               (snapshot_batch, address, token_symbol, side, size, entry_price,
                mark_price, position_value_usd, leverage_value, leverage_type,
                liquidation_price, unrealized_pnl, margin_used, account_value, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_batch,
                address,
                p.get("token", "BTC"),
                p.get("side", "Long"),
                p.get("size", 1.0),
                p.get("entry_price", 50000.0),
                p.get("mark_price", 51000.0),
                p.get("position_value_usd", 50000.0),
                p.get("leverage", 5.0),
                "cross",
                0.0,
                p.get("unrealized_pnl", 1000.0),
                10000.0,
                100000.0,
                p.get("captured_at", "2026-02-20T00:00:00Z"),
            ),
        )
    conn.commit()


class TestFeatureColumns:
    def test_feature_columns_is_list(self):
        assert isinstance(FEATURE_COLUMNS, list)
        assert len(FEATURE_COLUMNS) >= 20

    def test_includes_existing_scoring_features(self):
        for col in ["roi_7d", "roi_30d", "win_rate", "profit_factor", "pseudo_sharpe"]:
            assert col in FEATURE_COLUMNS

    def test_includes_new_features(self):
        for col in ["position_concentration", "avg_leverage", "pnl_volatility_7d", "max_drawdown_30d"]:
            assert col in FEATURE_COLUMNS


class TestPnlVolatility:
    def test_empty_returns_zero(self):
        assert compute_pnl_volatility([]) == 0.0

    def test_single_trade_returns_zero(self):
        assert compute_pnl_volatility([100.0]) == 0.0

    def test_varied_pnl(self):
        pnls = [100.0, -50.0, 200.0, -100.0, 50.0]
        vol = compute_pnl_volatility(pnls)
        assert vol > 0.0


class TestPositionConcentration:
    def test_empty_returns_zero(self):
        assert compute_position_concentration([]) == 0.0

    def test_single_position(self):
        assert compute_position_concentration([50000.0]) == 1.0

    def test_equal_positions(self):
        result = compute_position_concentration([25000.0, 25000.0])
        assert abs(result - 0.5) < 0.01

    def test_concentrated(self):
        result = compute_position_concentration([90000.0, 5000.0, 5000.0])
        assert result == 0.9


class TestMaxDrawdown:
    def test_empty(self):
        assert compute_max_drawdown([]) == 0.0

    def test_no_drawdown(self):
        assert compute_max_drawdown([100.0, 200.0, 300.0]) == 0.0

    def test_simple_drawdown(self):
        # cumulative: 100, 50, 150 -> peak 100, trough 50 -> dd = 50%
        dd = compute_max_drawdown([100.0, -50.0, 100.0])
        assert abs(dd - 0.5) < 0.01


class TestExtractTraderFeatures:
    def test_returns_dict_with_all_columns(self):
        conn = init_db(":memory:")
        addr = "0xtest1"
        _insert_trader(conn, addr)
        base = datetime(2026, 1, 15)
        trades = []
        for i in range(50):
            ts = base - timedelta(days=i % 30, hours=i)
            pnl = 100.0 if i % 3 != 0 else -50.0
            trades.append({
                "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000"),
                "closed_pnl": pnl,
                "action": "Close",
                "side": "Long",
                "token": "BTC" if i % 2 == 0 else "ETH",
                "price": 50000.0,
                "value_usd": 50000.0,
            })
        _insert_trades(conn, addr, trades)
        as_of = datetime(2026, 1, 15)
        features = extract_trader_features(conn, addr, as_of)
        assert features is not None
        for col in FEATURE_COLUMNS:
            assert col in features, f"Missing feature: {col}"
        conn.close()

    def test_returns_none_for_trader_with_no_trades(self):
        conn = init_db(":memory:")
        _insert_trader(conn, "0xempty")
        features = extract_trader_features(conn, "0xempty", datetime(2026, 1, 15))
        assert features is None
        conn.close()


class TestExtractAllTraderFeatures:
    def test_extracts_multiple_traders(self):
        conn = init_db(":memory:")
        base = datetime(2026, 1, 15)
        for addr_idx in range(3):
            addr = f"0xtrader{addr_idx}"
            _insert_trader(conn, addr)
            trades = []
            for i in range(30):
                ts = base - timedelta(days=i % 20, hours=i)
                trades.append({
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.000000"),
                    "closed_pnl": 50.0,
                    "token": "BTC",
                })
            _insert_trades(conn, addr, trades)

        results = extract_all_trader_features(conn, as_of=base)
        assert len(results) == 3
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_features.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snap.ml.features'`

**Step 3: Implement features.py**

Create `src/snap/ml/features.py`. This module:
- Defines `FEATURE_COLUMNS` — the canonical list of feature names
- `compute_pnl_volatility(pnls)` — stddev of per-trade PnL
- `compute_position_concentration(position_values)` — max position / total
- `compute_max_drawdown(pnls)` — max peak-to-trough drawdown on cumulative PnL
- `extract_trader_features(conn, address, as_of)` — pull trades from DB for the lookback window, compute all features, return dict
- `extract_all_trader_features(conn, as_of)` — extract for all traders with sufficient trade history

Key implementation notes:
- Reuse `scoring.py` functions: import `compute_trade_metrics` (line 187), `compute_avg_hold_hours` (line 307), `compute_consistency_score` (line 458), `compute_smart_money_bonus` (line 496), `compute_risk_mgmt_score` (line 513), `compute_recency_decay` (line 538)
- Query `trade_history` table for trades within the lookback window: `WHERE address = ? AND timestamp <= ? AND timestamp >= ?`
- Query `position_snapshots` for the nearest snapshot to `as_of` for position-based features (concentration, avg leverage, num positions)
- Query `traders` table for account_value and label
- Lookback: 90 days for ROI/PnL features, 30 days for trade metrics
- New features computed directly: `pnl_volatility_7d` (stddev of daily PnL over last 7d), `position_concentration`, `avg_leverage`, `num_open_positions`, `days_since_last_trade`, `max_drawdown_30d`, `market_correlation` (correlation of trader's daily PnL with BTC daily returns — set to 0.0 initially if insufficient data)

```python
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
    # All from the same batch (latest available)
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ml_features.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/snap/ml/features.py tests/test_ml_features.py
git commit -m "feat(ml): add feature extraction module"
```

---

## Task 5: Dataset Construction Module

**Files:**
- Create: `src/snap/ml/dataset.py`
- Test: `tests/test_ml_dataset.py`

This module builds the labeled training dataset using the sliding window approach over historical trade data.

**Step 1: Write the failing tests**

Create `tests/test_ml_dataset.py`:

```python
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
    def test_returns_dates(self):
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_dataset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snap.ml.dataset'`

**Step 3: Implement dataset.py**

Create `src/snap/ml/dataset.py`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ml_dataset.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/snap/ml/dataset.py tests/test_ml_dataset.py
git commit -m "feat(ml): add sliding window dataset construction"
```

---

## Task 6: Training Pipeline

**Files:**
- Create: `src/snap/ml/train.py`
- Test: `tests/test_ml_train.py`

**Step 1: Write the failing tests**

Create `tests/test_ml_train.py`:

```python
"""Tests for ML training pipeline."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from snap.ml.features import FEATURE_COLUMNS
from snap.ml.train import (
    train_model,
    evaluate_model,
    save_model,
    load_model,
    ModelResult,
)


def _make_synthetic_df(n_samples=200, n_windows=10):
    """Create a synthetic dataset for training tests."""
    rng = np.random.RandomState(42)
    rows = []
    base_date = datetime(2026, 1, 1)
    for w in range(n_windows):
        wdate = base_date + timedelta(days=w * 3)
        for i in range(n_samples // n_windows):
            feat = {col: rng.randn() for col in FEATURE_COLUMNS}
            # target loosely correlated with roi_30d and win_rate
            target = feat["roi_30d"] * 0.5 + feat["win_rate"] * 0.3 + rng.randn() * 0.1
            feat["address"] = f"0x{w:04d}{i:04d}"
            feat["window_date"] = wdate
            feat["forward_pnl_7d"] = target
            rows.append(feat)
    return pd.DataFrame(rows)


class TestTrainModel:
    def test_returns_model_result(self):
        df = _make_synthetic_df()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        assert isinstance(result, ModelResult)
        assert result.model is not None
        assert result.train_rmse >= 0
        assert result.val_rmse >= 0

    def test_feature_importances_populated(self):
        df = _make_synthetic_df()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        assert len(result.feature_importances) == len(FEATURE_COLUMNS)
        assert all(v >= 0 for v in result.feature_importances.values())


class TestEvaluateModel:
    def test_top15_pnl(self):
        df = _make_synthetic_df(n_samples=100, n_windows=5)
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        # Evaluate on the test split
        from snap.ml.dataset import split_dataset_chronological
        _, _, test = split_dataset_chronological(df, val_frac=0.2, test_frac=0.15)
        if len(test) > 0:
            metrics = evaluate_model(result.model, test)
            assert "rmse" in metrics
            assert "top15_actual_pnl" in metrics
            assert "spearman_corr" in metrics


class TestSaveLoadModel:
    def test_roundtrip(self, tmp_path):
        df = _make_synthetic_df()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        model_path = str(tmp_path / "model.json")
        meta_path = save_model(result, model_path)
        loaded = load_model(model_path)
        assert loaded is not None
        # Verify metadata saved
        assert Path(meta_path).exists()
        meta = json.loads(Path(meta_path).read_text())
        assert "train_rmse" in meta
        assert "feature_importances" in meta
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_train.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snap.ml.train'`

**Step 3: Implement train.py**

Create `src/snap/ml/train.py`:

```python
"""XGBoost training pipeline for trader selection model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.metrics import mean_squared_error

from snap.ml.dataset import split_dataset_chronological
from snap.ml.features import FEATURE_COLUMNS


@dataclass
class ModelResult:
    """Result of a training run."""

    model: xgb.XGBRegressor
    train_rmse: float
    val_rmse: float
    test_rmse: float
    feature_importances: dict[str, float] = field(default_factory=dict)
    top15_backtest_pnl: float = 0.0


def train_model(
    df,
    val_frac: float = 0.2,
    test_frac: float = 0.15,
    params: dict | None = None,
) -> ModelResult:
    """Train XGBoost regressor on labeled dataset.

    Uses chronological split and early stopping on validation set.
    """
    train_df, val_df, test_df = split_dataset_chronological(df, val_frac, test_frac)

    X_train = train_df[FEATURE_COLUMNS].values
    y_train = train_df["forward_pnl_7d"].values
    X_val = val_df[FEATURE_COLUMNS].values if len(val_df) > 0 else X_train[:1]
    y_val = val_df["forward_pnl_7d"].values if len(val_df) > 0 else y_train[:1]
    X_test = test_df[FEATURE_COLUMNS].values if len(test_df) > 0 else None
    y_test = test_df["forward_pnl_7d"].values if len(test_df) > 0 else None

    default_params = {
        "max_depth": 5,
        "n_estimators": 500,
        "learning_rate": 0.05,
        "min_child_weight": 10,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "reg:squarederror",
        "random_state": 42,
        "n_jobs": -1,
    }
    if params:
        default_params.update(params)

    model = xgb.XGBRegressor(**default_params)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Metrics
    train_pred = model.predict(X_train)
    train_rmse = float(np.sqrt(mean_squared_error(y_train, train_pred)))
    val_pred = model.predict(X_val)
    val_rmse = float(np.sqrt(mean_squared_error(y_val, val_pred)))

    test_rmse = 0.0
    top15_pnl = 0.0
    if X_test is not None and len(X_test) > 0:
        test_pred = model.predict(X_test)
        test_rmse = float(np.sqrt(mean_squared_error(y_test, test_pred)))
        metrics = evaluate_model(model, test_df)
        top15_pnl = metrics.get("top15_actual_pnl", 0.0)

    # Feature importances
    importances = dict(zip(FEATURE_COLUMNS, model.feature_importances_.tolist()))

    return ModelResult(
        model=model,
        train_rmse=train_rmse,
        val_rmse=val_rmse,
        test_rmse=test_rmse,
        feature_importances=importances,
        top15_backtest_pnl=top15_pnl,
    )


def evaluate_model(model: xgb.XGBRegressor, test_df) -> dict:
    """Evaluate model on a test set.

    Returns dict with rmse, top15_actual_pnl, spearman_corr.
    """
    X = test_df[FEATURE_COLUMNS].values
    y = test_df["forward_pnl_7d"].values
    pred = model.predict(X)

    rmse = float(np.sqrt(mean_squared_error(y, pred)))

    # Top-15 actual PnL: if we picked top 15 by prediction, what was actual PnL?
    test_copy = test_df.copy()
    test_copy["predicted"] = pred
    # Per window, pick top 15 by prediction, sum actual PnL
    top15_pnl = 0.0
    n_windows = 0
    for _, group in test_copy.groupby("window_date"):
        top15 = group.nlargest(min(15, len(group)), "predicted")
        top15_pnl += top15["forward_pnl_7d"].sum()
        n_windows += 1
    avg_top15_pnl = top15_pnl / n_windows if n_windows > 0 else 0.0

    # Spearman rank correlation
    if len(y) > 2:
        corr, _ = spearmanr(y, pred)
        corr = float(corr) if not np.isnan(corr) else 0.0
    else:
        corr = 0.0

    return {
        "rmse": rmse,
        "top15_actual_pnl": avg_top15_pnl,
        "spearman_corr": corr,
    }


def save_model(result: ModelResult, model_path: str) -> str:
    """Save trained model and metadata.

    Returns path to the metadata JSON file.
    """
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result.model.save_model(str(path))

    meta = {
        "trained_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "train_rmse": result.train_rmse,
        "val_rmse": result.val_rmse,
        "test_rmse": result.test_rmse,
        "top15_backtest_pnl": result.top15_backtest_pnl,
        "feature_importances": result.feature_importances,
    }
    meta_path = str(path.with_suffix(".meta.json"))
    Path(meta_path).write_text(json.dumps(meta, indent=2))
    return meta_path


def load_model(model_path: str) -> xgb.XGBRegressor | None:
    """Load a saved XGBoost model."""
    path = Path(model_path)
    if not path.exists():
        return None
    model = xgb.XGBRegressor()
    model.load_model(str(path))
    return model
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ml_train.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/snap/ml/train.py tests/test_ml_train.py
git commit -m "feat(ml): add XGBoost training pipeline"
```

---

## Task 7: Prediction & Scoring Integration Module

**Files:**
- Create: `src/snap/ml/predict.py`
- Test: `tests/test_ml_predict.py`

**Step 1: Write the failing tests**

Create `tests/test_ml_predict.py`:

```python
"""Tests for ML prediction and scoring integration."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from snap.database import init_db
from snap.ml.features import FEATURE_COLUMNS
from snap.ml.predict import (
    predict_trader_scores,
    rank_traders_by_prediction,
)
from snap.ml.train import train_model, save_model


def _make_synthetic_df(n=200, n_windows=10):
    rng = np.random.RandomState(42)
    rows = []
    base = datetime(2026, 1, 1)
    for w in range(n_windows):
        wdate = base + timedelta(days=w * 3)
        for i in range(n // n_windows):
            feat = {c: rng.randn() for c in FEATURE_COLUMNS}
            feat["forward_pnl_7d"] = feat["roi_30d"] * 0.5 + rng.randn() * 0.1
            feat["address"] = f"0x{w:04d}{i:04d}"
            feat["window_date"] = wdate
            rows.append(feat)
    return pd.DataFrame(rows)


@pytest.fixture()
def trained_model(tmp_path):
    df = _make_synthetic_df()
    result = train_model(df)
    model_path = str(tmp_path / "model.json")
    save_model(result, model_path)
    return model_path


class TestPredictTraderScores:
    def test_returns_predictions(self, trained_model):
        features_list = []
        rng = np.random.RandomState(99)
        for i in range(5):
            feat = {c: rng.randn() for c in FEATURE_COLUMNS}
            feat["address"] = f"0xpred{i}"
            features_list.append(feat)
        predictions = predict_trader_scores(trained_model, features_list)
        assert len(predictions) == 5
        assert all("address" in p for p in predictions)
        assert all("ml_predicted_pnl" in p for p in predictions)

    def test_empty_features_returns_empty(self, trained_model):
        predictions = predict_trader_scores(trained_model, [])
        assert len(predictions) == 0


class TestRankTraders:
    def test_returns_top_n(self, trained_model):
        features_list = []
        rng = np.random.RandomState(99)
        for i in range(20):
            feat = {c: rng.randn() for c in FEATURE_COLUMNS}
            feat["address"] = f"0xrank{i}"
            features_list.append(feat)
        ranked = rank_traders_by_prediction(trained_model, features_list, top_n=15)
        assert len(ranked) == 15
        # Verify descending order
        pnls = [r["ml_predicted_pnl"] for r in ranked]
        assert pnls == sorted(pnls, reverse=True)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_predict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snap.ml.predict'`

**Step 3: Implement predict.py**

Create `src/snap/ml/predict.py`:

```python
"""Prediction module — score traders using trained XGBoost model."""

from __future__ import annotations

import numpy as np

from snap.ml.features import FEATURE_COLUMNS
from snap.ml.train import load_model


def predict_trader_scores(
    model_path: str,
    features_list: list[dict],
) -> list[dict]:
    """Score traders using a trained model.

    Args:
        model_path: Path to saved XGBoost model file.
        features_list: List of feature dicts (each must have 'address' + FEATURE_COLUMNS).

    Returns:
        List of dicts with 'address' and 'ml_predicted_pnl'.
    """
    if not features_list:
        return []

    model = load_model(model_path)
    if model is None:
        return []

    addresses = [f["address"] for f in features_list]
    X = np.array([[f.get(col, 0.0) or 0.0 for col in FEATURE_COLUMNS] for f in features_list])
    predictions = model.predict(X)

    return [
        {"address": addr, "ml_predicted_pnl": float(pred)}
        for addr, pred in zip(addresses, predictions)
    ]


def rank_traders_by_prediction(
    model_path: str,
    features_list: list[dict],
    top_n: int = 15,
) -> list[dict]:
    """Score all traders and return the top N by predicted PnL.

    Args:
        model_path: Path to saved XGBoost model.
        features_list: Feature dicts for all candidate traders.
        top_n: Number of top traders to return.

    Returns:
        Top N traders sorted by predicted PnL descending.
    """
    scored = predict_trader_scores(model_path, features_list)
    scored.sort(key=lambda x: x["ml_predicted_pnl"], reverse=True)
    return scored[:top_n]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ml_predict.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/snap/ml/predict.py tests/test_ml_predict.py
git commit -m "feat(ml): add prediction and trader ranking module"
```

---

## Task 8: CLI Training Script

**Files:**
- Create: `scripts/train_model.py`
- Test: manual run

This is the end-to-end CLI script that builds the dataset from the market DB, trains the model, evaluates it, and saves the artifact.

**Step 1: Create the training script**

Create `scripts/train_model.py`:

```python
#!/usr/bin/env python3
"""End-to-end ML model training script.

Usage:
    python scripts/train_model.py --data-db data/market_190226 --output models/xgb_trader_v1.json
    python scripts/train_model.py --data-db data/market_190226 --output models/xgb_trader_v1.json --stride 3 --forward 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snap.database import get_connection
from snap.ml.dataset import build_dataset
from snap.ml.train import train_model, save_model, evaluate_model
from snap.ml.features import FEATURE_COLUMNS


def main():
    parser = argparse.ArgumentParser(description="Train ML trader selection model")
    parser.add_argument("--data-db", required=True, help="Path to market data DB")
    parser.add_argument("--output", default="models/xgb_trader_v1.json", help="Output model path")
    parser.add_argument("--start", default=None, help="Dataset start date (YYYY-MM-DD), default: earliest data")
    parser.add_argument("--end", default=None, help="Dataset end date (YYYY-MM-DD), default: latest data")
    parser.add_argument("--stride", type=int, default=3, help="Window stride in days (default: 3)")
    parser.add_argument("--forward", type=int, default=7, help="Forward PnL window in days (default: 7)")
    parser.add_argument("--val-frac", type=float, default=0.2, help="Validation fraction (default: 0.2)")
    parser.add_argument("--test-frac", type=float, default=0.15, help="Test fraction (default: 0.15)")
    args = parser.parse_args()

    print(f"Loading data from {args.data_db}...")
    conn = get_connection(args.data_db)

    # Determine date range from data
    row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM trade_history").fetchone()
    if row[0] is None:
        print("ERROR: No trade history found in database.")
        sys.exit(1)

    data_start = datetime.fromisoformat(row[0][:19])
    data_end = datetime.fromisoformat(row[1][:19])
    print(f"Trade history range: {data_start.date()} to {data_end.date()}")

    start = datetime.fromisoformat(args.start) if args.start else data_start
    end = datetime.fromisoformat(args.end) if args.end else data_end
    print(f"Using window range: {start.date()} to {end.date()}")

    # Build dataset
    print(f"Building dataset (stride={args.stride}d, forward={args.forward}d)...")
    df = build_dataset(
        conn,
        start=start,
        end=end,
        stride_days=args.stride,
        forward_days=args.forward,
    )
    print(f"Dataset: {len(df)} samples, {df['address'].nunique()} unique traders, "
          f"{df['window_date'].nunique()} windows")

    if len(df) < 100:
        print("WARNING: Very small dataset. Results may be unreliable.")

    # Train
    print("Training XGBoost model...")
    result = train_model(df, val_frac=args.val_frac, test_frac=args.test_frac)

    print(f"\n=== Training Results ===")
    print(f"  Train RMSE:         {result.train_rmse:.6f}")
    print(f"  Validation RMSE:    {result.val_rmse:.6f}")
    print(f"  Test RMSE:          {result.test_rmse:.6f}")
    print(f"  Top-15 backtest PnL: {result.top15_backtest_pnl:+.4f}")

    print(f"\n=== Feature Importances (top 10) ===")
    sorted_imp = sorted(result.feature_importances.items(), key=lambda x: x[1], reverse=True)
    for name, imp in sorted_imp[:10]:
        bar = "#" * int(imp * 100)
        print(f"  {name:25s} {imp:.4f} {bar}")

    # Save
    meta_path = save_model(result, args.output)
    print(f"\nModel saved to: {args.output}")
    print(f"Metadata saved to: {meta_path}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
```

**Step 2: Verify it runs (dry run)**

Run: `python scripts/train_model.py --data-db data/market_190226 --output models/xgb_trader_test.json`
Expected: Loads data, builds dataset, trains model, prints metrics, saves model file.

**Step 3: Commit**

```bash
git add scripts/train_model.py
git commit -m "feat(ml): add CLI training script"
```

---

## Task 9: Daily Feature Snapshot Job

**Files:**
- Create: `src/snap/ml/daily_snapshot.py`
- Test: `tests/test_ml_snapshot.py`

**Step 1: Write the failing tests**

Create `tests/test_ml_snapshot.py`:

```python
"""Tests for daily ML feature snapshot job."""

from datetime import datetime, timedelta

import pytest

from snap.database import init_db
from snap.ml.daily_snapshot import (
    snapshot_trader_features,
    backfill_forward_pnl,
)


def _seed_db(conn, num_traders=3, days=30):
    base = datetime(2026, 2, 15)
    for t in range(num_traders):
        addr = f"0xsnap{t:04d}"
        conn.execute(
            "INSERT OR REPLACE INTO traders (address, account_value, label) VALUES (?, ?, ?)",
            (addr, 100000.0, ""),
        )
        for d in range(days):
            for h in range(3):
                ts = (base - timedelta(days=d, hours=h * 8)).strftime("%Y-%m-%dT%H:%M:%S.000000")
                conn.execute(
                    """INSERT INTO trade_history
                       (address, token_symbol, action, side, size, price,
                        value_usd, closed_pnl, fee_usd, timestamp, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (addr, "BTC", "Close", "Long", 0.1, 50000.0,
                     5000.0, 100.0, 2.0, ts, "2026-02-25T00:00:00Z"),
                )
    conn.commit()


class TestSnapshotTraderFeatures:
    def test_inserts_snapshots(self):
        conn = init_db(":memory:")
        _seed_db(conn)
        count = snapshot_trader_features(conn, as_of=datetime(2026, 2, 15))
        assert count >= 1
        rows = conn.execute("SELECT COUNT(*) FROM ml_feature_snapshots").fetchone()[0]
        assert rows == count
        conn.close()

    def test_snapshot_has_null_forward_pnl(self):
        conn = init_db(":memory:")
        _seed_db(conn)
        snapshot_trader_features(conn, as_of=datetime(2026, 2, 15))
        row = conn.execute(
            "SELECT forward_pnl_7d FROM ml_feature_snapshots LIMIT 1"
        ).fetchone()
        assert row[0] is None
        conn.close()


class TestBackfillForwardPnl:
    def test_fills_forward_pnl(self):
        conn = init_db(":memory:")
        _seed_db(conn, days=30)
        # Snapshot at day 10 (should have 7 days of forward data)
        as_of = datetime(2026, 2, 5)
        snapshot_trader_features(conn, as_of=as_of)
        filled = backfill_forward_pnl(conn, as_of=datetime(2026, 2, 15))
        assert filled >= 1
        row = conn.execute(
            "SELECT forward_pnl_7d FROM ml_feature_snapshots WHERE forward_pnl_7d IS NOT NULL LIMIT 1"
        ).fetchone()
        assert row is not None
        conn.close()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ml_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement daily_snapshot.py**

Create `src/snap/ml/daily_snapshot.py`:

```python
"""Daily feature snapshot job for ongoing ML data collection."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from snap.ml.features import FEATURE_COLUMNS, extract_all_trader_features
from snap.ml.dataset import compute_forward_pnl


def snapshot_trader_features(
    conn: sqlite3.Connection,
    as_of: datetime | None = None,
) -> int:
    """Snapshot current features for all traders into ml_feature_snapshots.

    Inserts one row per trader with forward_pnl_7d = NULL (to be backfilled later).
    Returns count of rows inserted.
    """
    if as_of is None:
        as_of = datetime.utcnow()

    snapshot_date = as_of.strftime("%Y-%m-%d")
    features_list = extract_all_trader_features(conn, as_of)

    count = 0
    for feat in features_list:
        addr = feat.pop("address", None)
        if addr is None:
            continue
        cols = ["address", "snapshot_date"] + FEATURE_COLUMNS
        vals = [addr, snapshot_date] + [feat.get(c, None) for c in FEATURE_COLUMNS]
        placeholders = ", ".join(["?"] * len(vals))
        col_str = ", ".join(cols)
        conn.execute(
            f"INSERT INTO ml_feature_snapshots ({col_str}) VALUES ({placeholders})",
            vals,
        )
        count += 1

    conn.commit()
    return count


def backfill_forward_pnl(
    conn: sqlite3.Connection,
    as_of: datetime | None = None,
    forward_days: int = 7,
) -> int:
    """Backfill forward_pnl_7d for snapshots that are old enough.

    Finds snapshots where forward_pnl_7d IS NULL and snapshot_date is at
    least forward_days ago, then computes and fills in the actual PnL.
    Returns count of rows updated.
    """
    if as_of is None:
        as_of = datetime.utcnow()

    cutoff = (as_of - timedelta(days=forward_days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT id, address, snapshot_date FROM ml_feature_snapshots
           WHERE forward_pnl_7d IS NULL AND snapshot_date <= ?""",
        (cutoff,),
    ).fetchall()

    count = 0
    for row_id, address, snap_date in rows:
        snap_dt = datetime.fromisoformat(snap_date)
        pnl = compute_forward_pnl(conn, address, snap_dt, forward_days)
        if pnl is not None:
            # Normalize by account value
            acct_row = conn.execute(
                "SELECT account_value FROM traders WHERE address = ?", (address,)
            ).fetchone()
            acct_val = float(acct_row[0]) if acct_row and acct_row[0] else 100_000.0
            normalized = pnl / acct_val if acct_val > 0 else 0.0
            conn.execute(
                "UPDATE ml_feature_snapshots SET forward_pnl_7d = ? WHERE id = ?",
                (normalized, row_id),
            )
            count += 1

    conn.commit()
    return count
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ml_snapshot.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/snap/ml/daily_snapshot.py tests/test_ml_snapshot.py
git commit -m "feat(ml): add daily feature snapshot and backfill job"
```

---

## Task 10: Wire Shadow Mode into Scoring Pipeline

**Files:**
- Modify: `src/snap/scoring.py` (around line 1602, in `refresh_trader_universe`)
- Create: `tests/test_ml_integration.py`

This task adds the shadow mode: after the existing scoring runs, if a model exists, also compute ML predictions and log them alongside the composite score. No behavior change — purely additive logging.

**Step 1: Write the failing test**

Create `tests/test_ml_integration.py`:

```python
"""Tests for ML shadow mode integration with scoring pipeline."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from snap.ml.predict import predict_trader_scores
from snap.ml.features import FEATURE_COLUMNS


def test_shadow_score_logged_when_model_exists(tmp_path, strategy_db_conn):
    """Verify that ML shadow scores can be computed for scored traders."""
    # This tests the predict_trader_scores function with mock features
    # that simulate what would come from the trader_scores table
    import numpy as np
    from snap.ml.train import train_model, save_model

    # Create a tiny model
    import pandas as pd
    from datetime import datetime, timedelta
    rng = np.random.RandomState(42)
    rows = []
    for w in range(5):
        wdate = datetime(2026, 1, 1) + timedelta(days=w * 3)
        for i in range(20):
            feat = {c: rng.randn() for c in FEATURE_COLUMNS}
            feat["forward_pnl_7d"] = feat["roi_30d"] * 0.5
            feat["address"] = f"0x{w}{i}"
            feat["window_date"] = wdate
            rows.append(feat)
    df = pd.DataFrame(rows)
    result = train_model(df)
    model_path = str(tmp_path / "shadow.json")
    save_model(result, model_path)

    # Simulate features from scored traders
    features = [
        {**{c: rng.randn() for c in FEATURE_COLUMNS}, "address": f"0xtrader{i}"}
        for i in range(15)
    ]

    predictions = predict_trader_scores(model_path, features)
    assert len(predictions) == 15
    assert all("ml_predicted_pnl" in p for p in predictions)


def test_shadow_mode_no_model_returns_empty():
    """When no model file exists, shadow scoring returns empty."""
    predictions = predict_trader_scores("/nonexistent/model.json", [{"address": "0x1"}])
    assert len(predictions) == 0
```

**Step 2: Run test to verify it fails/passes**

Run: `pytest tests/test_ml_integration.py -v`
Expected: PASS (this tests existing predict module integration)

**Step 3: Add shadow mode hook to scoring.py**

At the end of `refresh_trader_universe()` in `src/snap/scoring.py` (around line 1602+), after the existing scoring completes, add a shadow mode block. Find the return statement and add before it:

```python
    # --- ML Shadow Mode ---
    # If a trained model exists, compute ML predictions alongside composite scores
    # and log them. This does NOT affect trader selection.
    try:
        from snap.config import ML_TRADER_SELECTION, ML_MODEL_DIR
        from pathlib import Path
        import glob as _glob
        model_files = sorted(_glob.glob(str(Path(ML_MODEL_DIR) / "xgb_trader_*.json")))
        if model_files:
            active_model = model_files[-1]  # latest
            from snap.ml.features import FEATURE_COLUMNS, extract_all_trader_features
            from snap.ml.predict import predict_trader_scores
            from snap.database import get_connection
            import logging
            _ml_logger = logging.getLogger(__name__)
            _ml_logger.info("ML shadow mode: scoring with model %s", active_model)
            data_conn = get_connection(db_path)
            from datetime import datetime
            all_features = extract_all_trader_features(data_conn, datetime.utcnow())
            if all_features:
                predictions = predict_trader_scores(active_model, all_features)
                predictions.sort(key=lambda x: x["ml_predicted_pnl"], reverse=True)
                _ml_logger.info(
                    "ML shadow top-5: %s",
                    [(p["address"][:10], f"{p['ml_predicted_pnl']:+.4f}") for p in predictions[:5]],
                )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("ML shadow mode failed: %s", e)
```

**Step 4: Run full test suite to verify no regressions**

Run: `pytest -x -q`
Expected: All existing tests still pass

**Step 5: Commit**

```bash
git add src/snap/scoring.py tests/test_ml_integration.py
git commit -m "feat(ml): add shadow mode scoring hook in refresh_trader_universe"
```

---

## Task 11: Add ML Snapshot Cadence to Scheduler

**Files:**
- Modify: `src/snap/scheduler.py`
- Test: `tests/test_scheduler_ml.py`

Add a daily cadence to the scheduler that runs the feature snapshot job.

**Step 1: Write the failing test**

Create `tests/test_scheduler_ml.py`:

```python
"""Tests for ML snapshot scheduling."""

from datetime import datetime, timedelta

import pytest

from snap.scheduler import SystemScheduler


class TestMLSnapshotCadence:
    def test_should_snapshot_after_24h(self):
        """Scheduler should trigger ML snapshot after 24 hours."""
        # This tests that the scheduler has the concept of an ML snapshot cadence.
        scheduler = SystemScheduler.__new__(SystemScheduler)
        # Check the attribute exists
        assert hasattr(SystemScheduler, '_should_snapshot_ml') or hasattr(SystemScheduler, '_run_ml_snapshot')
```

Note: The exact test will depend on how the scheduler exposes its cadence check. The key behavior is:
- `_should_snapshot_ml()` returns True when 24h have elapsed since last snapshot
- `_run_ml_snapshot()` calls `snapshot_trader_features()` and `backfill_forward_pnl()`

**Step 2: Implement in scheduler.py**

Add to `SchedulerState` enum:
```python
SNAPSHOTTING_ML = "SNAPSHOTTING_ML"
```

Add to `__init__`:
```python
self._last_ml_snapshot: float = 0.0
```

Add methods:
```python
def _should_snapshot_ml(self, now: datetime) -> bool:
    from snap.config import ML_SNAPSHOT_HOUR_UTC
    elapsed = time.time() - self._last_ml_snapshot
    return elapsed >= 86400 and now.hour == ML_SNAPSHOT_HOUR_UTC

async def _run_ml_snapshot(self) -> None:
    self._set_state(SchedulerState.SNAPSHOTTING_ML)
    try:
        from snap.ml.daily_snapshot import snapshot_trader_features, backfill_forward_pnl
        from snap.database import get_connection
        from datetime import datetime
        conn = get_connection(self._db_path)
        count = snapshot_trader_features(conn, datetime.utcnow())
        filled = backfill_forward_pnl(conn, datetime.utcnow())
        self._logger.info("ML snapshot: %d features captured, %d forward PnL backfilled", count, filled)
        conn.close()
        self._last_ml_snapshot = time.time()
    except Exception as e:
        self._logger.warning("ML snapshot failed: %s", e)
    finally:
        self._set_state(SchedulerState.IDLE)
```

Add to the `run()` priority chain (lowest priority, after monitor):
```python
elif self._should_snapshot_ml(now):
    await self._run_ml_snapshot()
```

**Step 3: Run tests**

Run: `pytest tests/test_scheduler_ml.py tests/test_scheduler.py -v`
Expected: All pass

**Step 4: Commit**

```bash
git add src/snap/scheduler.py tests/test_scheduler_ml.py
git commit -m "feat(ml): add daily ML feature snapshot cadence to scheduler"
```

---

## Task 12: Run First Training & Validate

This is a manual validation task — run the full pipeline on the real data.

**Step 1: Run the training script**

```bash
mkdir -p models
python scripts/train_model.py \
    --data-db data/market_190226 \
    --output models/xgb_trader_v1.json \
    --stride 3 \
    --forward 7
```

**Step 2: Review the output**

Check:
- Dataset size (target: 25K–50K samples, minimum 5K)
- Train vs val RMSE (val should not be much worse than train — check for overfitting)
- Top-15 backtest PnL (positive = model picks profitable traders)
- Spearman correlation (> 0.1 is a meaningful signal)
- Feature importance (which features matter most?)

**Step 3: Compare against baseline**

Manually inspect: do the model's top-15 overlap with the current composite-score top-15? If they're very different, investigate why.

**Step 4: Commit the first model**

```bash
git add models/xgb_trader_v1.json models/xgb_trader_v1.meta.json
git commit -m "feat(ml): first trained model v1"
```

---

## Summary of Deliverables

| Task | Files | Tests | Description |
|------|-------|-------|-------------|
| 1 | pyproject.toml, ml/__init__.py | - | Dependencies + package skeleton |
| 2 | config.py | test_config_ml.py (7) | ML configuration constants |
| 3 | database.py | test_database_ml.py (6) | ML database tables |
| 4 | ml/features.py | test_ml_features.py (~15) | Feature extraction |
| 5 | ml/dataset.py | test_ml_dataset.py (~8) | Sliding window dataset |
| 6 | ml/train.py | test_ml_train.py (~5) | XGBoost training pipeline |
| 7 | ml/predict.py | test_ml_predict.py (~4) | Prediction module |
| 8 | scripts/train_model.py | manual | CLI training script |
| 9 | ml/daily_snapshot.py | test_ml_snapshot.py (~3) | Live data collection |
| 10 | scoring.py | test_ml_integration.py (2) | Shadow mode hook |
| 11 | scheduler.py | test_scheduler_ml.py (1) | Snapshot cadence |
| 12 | models/*.json | manual | First training run |

**Total estimated tests: ~50 new tests across 8 test files.**
