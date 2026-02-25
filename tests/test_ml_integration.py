"""Tests for ML shadow mode integration with scoring pipeline."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from snap.ml.predict import predict_trader_scores
from snap.ml.features import FEATURE_COLUMNS


def test_shadow_score_logged_when_model_exists(tmp_path):
    """Verify that ML shadow scores can be computed for scored traders."""
    import numpy as np
    from snap.ml.train import train_model, save_model

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
