"""Prediction module — score traders using trained XGBoost model."""

from __future__ import annotations

import json

import numpy as np

from snap.ml.features import FEATURE_COLUMNS
from snap.ml.train import load_model


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
