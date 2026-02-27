"""Prediction module — score traders using trained XGBoost model."""

from __future__ import annotations

import glob as _glob
import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from snap.ml.features import (
    FEATURE_COLUMNS,
    add_derived_features,
    get_per_sample_feature_cols,
    aggregate_per_trader,
    get_aggregated_feature_cols,
)
from snap.ml.train import load_model


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


def _load_feature_caps(model_path: str) -> dict:
    """Load feature caps from the model's metadata sidecar file."""
    meta_path = model_path.replace(".json", ".meta.json")
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        return meta.get("feature_caps", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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

    caps = _load_feature_caps(model_path)

    addresses = [f["address"] for f in features_list]
    X = np.array([[f.get(col, 0.0) or 0.0 for col in FEATURE_COLUMNS] for f in features_list])

    # Apply same inf/NaN handling as training to avoid train/serve skew
    for i, col in enumerate(FEATURE_COLUMNS):
        cap = caps.get(col)
        if cap is not None:
            X[:, i] = np.where(np.isposinf(X[:, i]), cap, X[:, i])
            X[:, i] = np.where(np.isneginf(X[:, i]), -cap, X[:, i])
        else:
            X[:, i] = np.where(np.isinf(X[:, i]), 0.0, X[:, i])
    X = np.nan_to_num(X, nan=0.0)

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

    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = add_derived_features(df, training=False)

    per_sample_cols = pipeline.per_sample_cols
    agg_df = aggregate_per_trader(df, per_sample_cols, target_col=None, min_windows=pipeline.min_windows)

    if agg_df.empty:
        return []

    addresses = agg_df["address"].tolist()
    X = agg_df[pipeline.agg_feat_cols].values.astype(np.float32)

    base_preds = np.column_stack([m.predict(X) for m in pipeline.base_models])

    X_meta = np.hstack([X, base_preds])
    X_meta_s = pipeline.scaler.transform(X_meta)
    final_preds = pipeline.meta_learner.predict(X_meta_s)

    return [
        {"address": addr, "ml_predicted_pnl": float(pred)}
        for addr, pred in zip(addresses, final_preds)
    ]
