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
    # Replace inf values with NaN, then fill NaN with 0 — profit_factor
    # can be inf when a trader has no losing trades.
    clean_df = df.copy()
    clean_df[FEATURE_COLUMNS] = clean_df[FEATURE_COLUMNS].replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)

    train_df, val_df, test_df = split_dataset_chronological(clean_df, val_frac, test_frac)

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
