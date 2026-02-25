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
