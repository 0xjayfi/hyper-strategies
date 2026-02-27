# v3 Stacked Pipeline Inference Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable `predict.py` to serve v3 stacked pipeline predictions (8 XGBoost base models + Ridge meta-learner) using multi-window snapshots from the database.

**Architecture:** Move shared feature engineering functions from `scripts/train_model_v3.py` into `src/snap/ml/features.py`. Add `load_stacked_pipeline()` and `predict_stacked_scores()` to `predict.py`. Update shadow mode hook in `scoring.py` to auto-detect v3 models.

**Tech Stack:** XGBoost, scikit-learn (Ridge, StandardScaler), pandas, numpy, sqlite3

---

### Task 1: Move shared feature engineering into `features.py`

**Files:**
- Modify: `src/snap/ml/features.py`
- Reference: `scripts/train_model_v3.py:44-51,72-151`

**Step 1: Add `EXTRA_RAW_FEATURES` constant to `features.py`**

Add after the `FEATURE_COLUMNS` list (after line 35):

```python
EXTRA_RAW_FEATURES: list[str] = [
    "roi_momentum_7_30",
    "roi_momentum_30_90",
    "pnl_momentum_7_30",
    "wr_x_pf",
    "sharpe_x_wr",
    "roi7_x_rec",
]
```

**Step 2: Add `add_derived_features()` function**

Add at the end of `features.py`. This is the function from `train_model_v3.py:72-107` with a `training` flag to skip target-only transforms at inference time:

```python
def add_derived_features(df: pd.DataFrame, training: bool = True) -> pd.DataFrame:
    """Add cross-sectional normalization, rank, and momentum features.

    Args:
        df: DataFrame with FEATURE_COLUMNS columns and a grouping column
            (``window_date`` for training, ``snapshot_date`` for inference).
        training: If True, winsorize and demean the target column
            ``forward_pnl_7d``. Set to False at inference time when no
            target column exists.

    Returns:
        DataFrame with additional derived columns.
    """
    date_col = "window_date" if "window_date" in df.columns else "snapshot_date"

    for col in FEATURE_COLUMNS:
        fm = np.isfinite(df[col])
        if (~fm).any() and fm.any():
            cap = max(float(df.loc[fm, col].quantile(0.95)), 10.0)
            df.loc[~fm, col] = cap
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].fillna(0.0)

    if training:
        lo = float(df["forward_pnl_7d"].quantile(0.05))
        hi = float(df["forward_pnl_7d"].quantile(0.95))
        df["forward_pnl_7d"] = df["forward_pnl_7d"].clip(lo, hi)
        wm = df.groupby(date_col)["forward_pnl_7d"].transform("mean")
        df["target_dm"] = df["forward_pnl_7d"] - wm

    for col in FEATURE_COLUMNS:
        m = df.groupby(date_col)[col].transform("mean")
        s = df.groupby(date_col)[col].transform("std")
        df[f"{col}_dm"] = np.where(s > 0, (df[col] - m) / s, 0.0)
        df[f"{col}_rank"] = df.groupby(date_col)[col].rank(pct=True)

    df["roi_momentum_7_30"] = df["roi_7d"] - df["roi_30d"]
    df["roi_momentum_30_90"] = df["roi_30d"] - df["roi_90d"]
    df["pnl_momentum_7_30"] = df["pnl_7d"] - df["pnl_30d"]
    df["wr_x_pf"] = df["win_rate"] * np.clip(df["profit_factor"], 0, 50)
    df["sharpe_x_wr"] = df["pseudo_sharpe"] * df["win_rate"]
    df["roi7_x_rec"] = df["roi_7d"] * df["recency_decay"]

    for col in EXTRA_RAW_FEATURES:
        m = df.groupby(date_col)[col].transform("mean")
        s = df.groupby(date_col)[col].transform("std")
        df[f"{col}_dm"] = np.where(s > 0, (df[col] - m) / s, 0.0)
        df[f"{col}_rank"] = df.groupby(date_col)[col].rank(pct=True)

    return df
```

**Step 3: Add `get_per_sample_feature_cols()` function**

```python
def get_per_sample_feature_cols() -> list[str]:
    """Return the 48 per-sample feature column names (dm + rank variants)."""
    cols = []
    for c in FEATURE_COLUMNS:
        cols.append(f"{c}_dm")
        cols.append(f"{c}_rank")
    for c in EXTRA_RAW_FEATURES:
        cols.append(f"{c}_dm")
        cols.append(f"{c}_rank")
    return cols
```

**Step 4: Add `aggregate_per_trader()` function**

```python
def aggregate_per_trader(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str | None = "target_dm",
    min_windows: int = 16,
) -> pd.DataFrame:
    """Aggregate per-sample features to per-trader: mean + trend.

    Args:
        df: DataFrame with per-sample features grouped by address.
        feature_cols: List of per-sample feature column names.
        target_col: Target column to aggregate. None at inference time.
        min_windows: Minimum observation windows per trader.

    Returns:
        DataFrame with one row per trader containing aggregated features.
    """
    date_col = "window_date" if "window_date" in df.columns else "snapshot_date"
    results = []
    for addr, group in df.groupby("address"):
        if len(group) < min_windows:
            continue
        group = group.sort_values(date_col)
        n = len(group)
        row: dict = {"address": addr, "n_windows": n}
        for col in feature_cols:
            vals = group[col].values
            row[f"{col}_mean"] = float(vals.mean())
            k = max(1, n // 3)
            row[f"{col}_trend"] = float(vals[-k:].mean() - vals[:k].mean())
        if target_col is not None and target_col in df.columns:
            row[target_col] = float(group[target_col].values.mean())
        results.append(row)
    return pd.DataFrame(results)
```

**Step 5: Add `get_aggregated_feature_cols()` function**

```python
def get_aggregated_feature_cols(per_sample_cols: list[str]) -> list[str]:
    """Return the 97 aggregated feature column names (mean + trend + n_windows)."""
    cols = []
    for c in per_sample_cols:
        cols.append(f"{c}_mean")
        cols.append(f"{c}_trend")
    cols.append("n_windows")
    return cols
```

**Step 6: Add the `import numpy as np` and `import pandas as pd` to features.py**

At the top of `features.py`, add after existing imports:

```python
import numpy as np
import pandas as pd
```

**Step 7: Run existing tests to verify no breakage**

Run: `pytest tests/test_ml_features.py tests/test_ml_predict.py tests/test_ml_integration.py -v`
Expected: All existing tests PASS (new functions are additive, nothing changed).

**Step 8: Commit**

```bash
git add src/snap/ml/features.py
git commit -m "feat(ml): move shared feature engineering into features.py for train/serve parity"
```

---

### Task 2: Update training scripts to import from `features.py`

**Files:**
- Modify: `scripts/train_model_v3.py`
- Modify: `scripts/train_model_v2.py`

**Step 1: Update `train_model_v3.py` imports and remove duplicated functions**

Replace the local `EXTRA_RAW_FEATURES`, `add_derived_features`, `get_per_sample_feature_cols`, `aggregate_per_trader`, and `get_aggregated_feature_cols` definitions (lines 44-150) with imports from `features.py`:

```python
from snap.ml.features import (
    FEATURE_COLUMNS,
    EXTRA_RAW_FEATURES,
    add_derived_features,
    get_per_sample_feature_cols,
    aggregate_per_trader,
    get_aggregated_feature_cols,
)
```

Remove the duplicate `from snap.ml.features import FEATURE_COLUMNS` on line 42.

In `train_stacked_model()`, update the call to `add_derived_features(df)` — it now defaults to `training=True` so no change needed for the call itself.

**Step 2: Update `train_model_v2.py` similarly**

Replace its local copies of `EXTRA_RAW_FEATURES`, `add_derived_features`, `get_per_sample_feature_cols`, `aggregate_per_trader`, `get_aggregated_feature_cols` with imports from `features.py`.

**Step 3: Verify training scripts still work**

Run: `python scripts/train_model_v3.py --help`
Expected: Help text prints without import errors.

Run: `python scripts/train_model_v2.py --help`
Expected: Help text prints without import errors.

**Step 4: Commit**

```bash
git add scripts/train_model_v3.py scripts/train_model_v2.py
git commit -m "refactor(ml): import shared feature functions from features.py in training scripts"
```

---

### Task 3: Write tests for stacked pipeline loading and prediction

**Files:**
- Create: (extend) `tests/test_ml_predict.py`

**Step 1: Write test for `load_stacked_pipeline`**

Add to `tests/test_ml_predict.py`:

```python
import pickle
from unittest.mock import MagicMock
from snap.ml.predict import load_stacked_pipeline


def _create_synthetic_stacked_model(model_dir):
    """Create a minimal synthetic v3 stacked model for testing."""
    import xgboost as xgb
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from snap.ml.features import get_per_sample_feature_cols, get_aggregated_feature_cols

    per_sample_cols = get_per_sample_feature_cols()
    agg_feat_cols = get_aggregated_feature_cols(per_sample_cols)
    n_features = len(agg_feat_cols)
    n_base = 8

    rng = np.random.RandomState(42)
    X = rng.randn(50, n_features).astype(np.float32)
    y = rng.randn(50).astype(np.float32)

    base_models = []
    for i in range(n_base):
        m = xgb.XGBRegressor(n_estimators=5, max_depth=1, random_state=i)
        m.fit(X, y)
        m.save_model(str(model_dir / f"base_model_{i}.json"))
        base_models.append(m)

    # Build meta features: agg features + base predictions
    base_preds = np.column_stack([m.predict(X) for m in base_models])
    X_meta = np.hstack([X, base_preds])
    scaler = StandardScaler()
    X_meta_s = scaler.fit_transform(X_meta)
    meta = Ridge(alpha=60.0)
    meta.fit(X_meta_s, y)

    pipeline = {
        "meta_learner": meta,
        "scaler": scaler,
        "agg_feat_cols": agg_feat_cols,
        "per_sample_cols": per_sample_cols,
        "min_windows": 3,  # low for testing
    }
    with open(model_dir / "stacked_pipeline.pkl", "wb") as f:
        pickle.dump(pipeline, f)

    # Meta JSON
    import json
    meta_json = {
        "model_version": "v3_stacked",
        "feature_caps": {"profit_factor": 50.0},
    }
    (model_dir / "model_v3.meta.json").write_text(json.dumps(meta_json))

    return pipeline


class TestLoadStackedPipeline:
    def test_loads_all_components(self, tmp_path):
        _create_synthetic_stacked_model(tmp_path)
        pipeline = load_stacked_pipeline(str(tmp_path))
        assert pipeline is not None
        assert len(pipeline.base_models) == 8
        assert pipeline.meta_learner is not None
        assert pipeline.scaler is not None
        assert pipeline.min_windows == 3
        assert len(pipeline.agg_feat_cols) == 97
        assert len(pipeline.per_sample_cols) == 48

    def test_returns_none_when_no_pipeline_pkl(self, tmp_path):
        pipeline = load_stacked_pipeline(str(tmp_path))
        assert pipeline is None

    def test_feature_caps_loaded(self, tmp_path):
        _create_synthetic_stacked_model(tmp_path)
        pipeline = load_stacked_pipeline(str(tmp_path))
        assert pipeline.feature_caps == {"profit_factor": 50.0}
```

**Step 2: Write test for `predict_stacked_scores`**

```python
from snap.ml.predict import predict_stacked_scores
from snap.database import init_db
from snap.ml.features import FEATURE_COLUMNS


def _populate_snapshots(conn, n_traders=10, n_days=20):
    """Insert synthetic snapshots into ml_feature_snapshots."""
    from datetime import datetime, timedelta
    rng = np.random.RandomState(42)
    base_date = datetime(2026, 2, 1)
    for d in range(n_days):
        snap_date = (base_date + timedelta(days=d)).strftime("%Y-%m-%d")
        for t in range(n_traders):
            addr = f"0xtrader{t:04d}"
            vals = {c: float(rng.randn()) for c in FEATURE_COLUMNS}
            cols = ["address", "snapshot_date"] + FEATURE_COLUMNS
            data = [addr, snap_date] + [vals[c] for c in FEATURE_COLUMNS]
            placeholders = ", ".join(["?"] * len(data))
            col_str = ", ".join(cols)
            conn.execute(
                f"INSERT INTO ml_feature_snapshots ({col_str}) VALUES ({placeholders})",
                data,
            )
    conn.commit()


class TestPredictStackedScores:
    def test_returns_predictions_for_eligible_traders(self, tmp_path):
        # Set up model
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        pipeline_info = _create_synthetic_stacked_model(model_dir)

        # Set up DB with snapshots
        db_path = str(tmp_path / "test.db")
        conn = init_db(db_path)
        _populate_snapshots(conn, n_traders=5, n_days=20)

        from datetime import datetime
        as_of = datetime(2026, 2, 20)
        results = predict_stacked_scores(str(model_dir), db_path, as_of)

        assert len(results) > 0
        assert all("address" in r for r in results)
        assert all("ml_predicted_pnl" in r for r in results)
        assert all(np.isfinite(r["ml_predicted_pnl"]) for r in results)

    def test_returns_empty_when_no_snapshots(self, tmp_path):
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        _create_synthetic_stacked_model(model_dir)

        db_path = str(tmp_path / "empty.db")
        conn = init_db(db_path)

        from datetime import datetime
        results = predict_stacked_scores(str(model_dir), db_path, datetime(2026, 2, 20))
        assert results == []

    def test_returns_empty_when_insufficient_windows(self, tmp_path):
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        _create_synthetic_stacked_model(model_dir)  # min_windows=3

        db_path = str(tmp_path / "few.db")
        conn = init_db(db_path)
        _populate_snapshots(conn, n_traders=5, n_days=2)  # only 2 snapshots < 3

        from datetime import datetime
        results = predict_stacked_scores(str(model_dir), db_path, datetime(2026, 2, 3))
        assert results == []
```

**Step 3: Run tests to verify they fail**

Run: `pytest tests/test_ml_predict.py::TestLoadStackedPipeline -v`
Expected: FAIL — `load_stacked_pipeline` does not exist yet.

Run: `pytest tests/test_ml_predict.py::TestPredictStackedScores -v`
Expected: FAIL — `predict_stacked_scores` does not exist yet.

**Step 4: Commit the tests**

```bash
git add tests/test_ml_predict.py
git commit -m "test(ml): add failing tests for v3 stacked pipeline loading and prediction"
```

---

### Task 4: Implement stacked pipeline loading and prediction in `predict.py`

**Files:**
- Modify: `src/snap/ml/predict.py`

**Step 1: Add imports and `StackedPipeline` dataclass**

Add at the top of `predict.py`:

```python
import glob as _glob
import pickle
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import xgboost as xgb

from snap.ml.features import (
    FEATURE_COLUMNS,
    add_derived_features,
    get_per_sample_feature_cols,
    aggregate_per_trader,
    get_aggregated_feature_cols,
)
```

Add the dataclass:

```python
@dataclass
class StackedPipeline:
    """Loaded v3 stacked model artifacts."""
    base_models: list
    meta_learner: object
    scaler: object
    agg_feat_cols: list[str]
    per_sample_cols: list[str]
    min_windows: int
    feature_caps: dict[str, float] = field(default_factory=dict)
```

**Step 2: Implement `load_stacked_pipeline()`**

```python
def load_stacked_pipeline(model_dir: str) -> StackedPipeline | None:
    """Load a v3 stacked model pipeline from a directory.

    Expects: base_model_*.json files, stacked_pipeline.pkl, model_v*.meta.json.
    Returns None if the directory does not contain a stacked pipeline.
    """
    dirpath = Path(model_dir)
    pkl_path = dirpath / "stacked_pipeline.pkl"
    if not pkl_path.exists():
        return None

    with open(pkl_path, "rb") as f:
        pipeline = pickle.load(f)

    base_files = sorted(_glob.glob(str(dirpath / "base_model_*.json")))
    base_models = []
    for bf in base_files:
        m = xgb.XGBRegressor()
        m.load_model(bf)
        base_models.append(m)

    # Load feature caps from meta JSON
    feature_caps: dict[str, float] = {}
    meta_files = sorted(_glob.glob(str(dirpath / "model_v*.meta.json")))
    if meta_files:
        try:
            with open(meta_files[-1]) as f:
                meta = json.load(f)
            feature_caps = meta.get("feature_caps", {})
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    return StackedPipeline(
        base_models=base_models,
        meta_learner=pipeline["meta_learner"],
        scaler=pipeline["scaler"],
        agg_feat_cols=pipeline["agg_feat_cols"],
        per_sample_cols=pipeline["per_sample_cols"],
        min_windows=pipeline["min_windows"],
        feature_caps=feature_caps,
    )
```

**Step 3: Implement `predict_stacked_scores()`**

```python
def predict_stacked_scores(
    model_dir: str,
    db_path: str,
    as_of: datetime,
    lookback_days: int = 90,
) -> list[dict]:
    """Score traders using the v3 stacked pipeline with multi-window snapshots.

    Queries ml_feature_snapshots from the strategy DB, applies the full
    feature engineering pipeline (cross-sectional normalization, aggregation),
    then runs through the stacked model (8 base XGBoost + Ridge meta).

    Args:
        model_dir: Path to directory containing stacked model artifacts.
        db_path: Path to strategy DB containing ml_feature_snapshots table.
        as_of: Reference datetime for the prediction window.
        lookback_days: How many days of snapshots to use.

    Returns:
        List of dicts with 'address' and 'ml_predicted_pnl'.
    """
    pipeline = load_stacked_pipeline(model_dir)
    if pipeline is None:
        return []

    from snap.database import get_connection
    conn = get_connection(db_path)

    start_date = (as_of - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_date = as_of.strftime("%Y-%m-%d")

    rows = conn.execute(
        f"""SELECT address, snapshot_date, {', '.join(FEATURE_COLUMNS)}
            FROM ml_feature_snapshots
            WHERE snapshot_date >= ? AND snapshot_date <= ?""",
        (start_date, end_date),
    ).fetchall()
    conn.close()

    if not rows:
        return []

    cols = ["address", "snapshot_date"] + list(FEATURE_COLUMNS)
    df = pd.DataFrame([dict(zip(cols, r)) for r in rows])

    # Cast feature columns to float
    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Apply feature engineering (no target transforms)
    df = add_derived_features(df, training=False)

    # Aggregate per-trader
    per_sample_cols = pipeline.per_sample_cols
    agg_df = aggregate_per_trader(df, per_sample_cols, target_col=None, min_windows=pipeline.min_windows)

    if agg_df.empty:
        return []

    addresses = agg_df["address"].tolist()
    X = agg_df[pipeline.agg_feat_cols].values.astype(np.float32)

    # Run base models
    base_preds = np.column_stack([m.predict(X) for m in pipeline.base_models])

    # Stack: aggregated features + base predictions
    X_meta = np.hstack([X, base_preds])
    X_meta_s = pipeline.scaler.transform(X_meta)
    final_preds = pipeline.meta_learner.predict(X_meta_s)

    return [
        {"address": addr, "ml_predicted_pnl": float(pred)}
        for addr, pred in zip(addresses, final_preds)
    ]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ml_predict.py -v`
Expected: ALL tests pass, including new `TestLoadStackedPipeline` and `TestPredictStackedScores`.

**Step 5: Run full test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: All ~306+ tests pass.

**Step 6: Commit**

```bash
git add src/snap/ml/predict.py
git commit -m "feat(ml): implement v3 stacked pipeline loading and prediction in predict.py"
```

---

### Task 5: Update shadow mode hook to auto-detect v3

**Files:**
- Modify: `src/snap/scoring.py` (lines 1732-1760)

**Step 1: Write test for shadow mode v3 auto-detection**

Add to `tests/test_ml_integration.py`:

```python
def test_shadow_mode_auto_detects_v3(tmp_path):
    """Shadow mode should use stacked pipeline when stacked_pipeline.pkl exists."""
    from snap.ml.predict import load_stacked_pipeline
    from pathlib import Path

    # Create a v3 model dir with pipeline
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    # Reuse the synthetic model helper from test_ml_predict
    from tests.test_ml_predict import _create_synthetic_stacked_model
    _create_synthetic_stacked_model(model_dir)

    # Verify auto-detection
    pipeline = load_stacked_pipeline(str(model_dir))
    assert pipeline is not None
    assert len(pipeline.base_models) == 8
```

**Step 2: Update the shadow mode block in `scoring.py`**

Replace lines 1732-1760 in `scoring.py` with:

```python
    # --- ML Shadow Mode ---
    # If a trained model exists, compute ML predictions alongside composite scores
    # and log them. This does NOT affect trader selection.
    try:
        from snap.config import ML_MODEL_DIR
        from pathlib import Path
        import logging
        _ml_logger = logging.getLogger(__name__)

        model_dir = str(Path(ML_MODEL_DIR))

        # Auto-detect v3 stacked pipeline vs v1 single model
        if (Path(model_dir) / "stacked_pipeline.pkl").exists():
            from snap.ml.predict import predict_stacked_scores
            from datetime import datetime
            _ml_logger.info("ML shadow mode: using v3 stacked pipeline from %s", model_dir)
            predictions = predict_stacked_scores(model_dir, db_path, datetime.utcnow())
        else:
            import glob as _glob
            model_files = sorted(_glob.glob(str(Path(model_dir) / "xgb_trader_*.json")))
            if model_files:
                active_model = model_files[-1]
                from snap.ml.features import extract_all_trader_features
                from snap.ml.predict import predict_trader_scores
                from snap.database import get_connection
                from datetime import datetime
                _ml_logger.info("ML shadow mode: using v1 model %s", active_model)
                data_conn = get_connection(db_path)
                all_features = extract_all_trader_features(data_conn, datetime.utcnow())
                predictions = predict_trader_scores(active_model, all_features) if all_features else []
            else:
                predictions = []

        if predictions:
            predictions.sort(key=lambda x: x["ml_predicted_pnl"], reverse=True)
            _ml_logger.info(
                "ML shadow top-5: %s",
                [(p["address"][:10], f"{p['ml_predicted_pnl']:+.4f}") for p in predictions[:5]],
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("ML shadow mode failed: %s", e)
```

**Step 3: Run integration tests**

Run: `pytest tests/test_ml_integration.py -v`
Expected: All tests pass.

**Step 4: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/snap/scoring.py tests/test_ml_integration.py
git commit -m "feat(ml): update shadow mode hook to auto-detect v3 stacked pipeline"
```

---

### Task 6: Final verification and cleanup

**Step 1: Run complete test suite**

Run: `pytest tests/ -v`
Expected: All tests pass (306+ original + new tests).

**Step 2: Verify v3 model directory works with the prediction module**

Quick manual check (Python REPL or short script):

```python
from snap.ml.predict import load_stacked_pipeline
p = load_stacked_pipeline("models/v3")
print(f"Base models: {len(p.base_models)}")
print(f"Feature cols: {len(p.agg_feat_cols)}")
print(f"min_windows: {p.min_windows}")
```

Expected: `Base models: 8`, `Feature cols: 97`, `min_windows: 16`.

**Step 3: Commit any final adjustments and verify git status**

```bash
git status
git log --oneline -5
```
