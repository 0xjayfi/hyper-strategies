"""Tests for ML shadow mode integration with scoring pipeline."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
import numpy as np

from snap.ml.predict import predict_trader_scores
from snap.ml.features import FEATURE_COLUMNS


def test_shadow_score_logged_when_model_exists(tmp_path):
    """Verify that ML shadow scores can be computed for scored traders."""
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


def test_shadow_mode_with_18_feature_set(tmp_path):
    """Verify shadow mode works correctly with the reduced 18-feature set."""
    from snap.ml.train import train_model, save_model

    import pandas as pd
    from datetime import datetime, timedelta

    assert len(FEATURE_COLUMNS) == 18, "FEATURE_COLUMNS should have exactly 18 features"

    rng = np.random.RandomState(99)
    rows = []
    for w in range(5):
        wdate = datetime(2026, 1, 1) + timedelta(days=w * 3)
        for i in range(20):
            feat = {c: rng.randn() for c in FEATURE_COLUMNS}
            feat["forward_pnl_7d"] = feat["roi_30d"] * 0.3 + rng.randn() * 0.1
            feat["address"] = f"0xfeat{w}_{i}"
            feat["window_date"] = wdate
            rows.append(feat)

    df = pd.DataFrame(rows)
    result = train_model(df)
    model_path = str(tmp_path / "model_18feat.json")
    save_model(result, model_path)

    # Predict with 18-feature inputs
    test_features = [
        {**{c: rng.randn() for c in FEATURE_COLUMNS}, "address": f"0xtest{i}"}
        for i in range(10)
    ]
    predictions = predict_trader_scores(model_path, test_features)
    assert len(predictions) == 10
    assert all("ml_predicted_pnl" in p for p in predictions)
    # All predictions should be finite numbers
    assert all(np.isfinite(p["ml_predicted_pnl"]) for p in predictions)


def test_shadow_mode_old_23_feature_model_backward_compat(tmp_path):
    """Test backward compat when model was trained on old 23-feature set.

    When the model expects 23 features but we only supply 18, XGBoost raises
    a ValueError on predict(). predict_trader_scores does not currently catch
    this, so we verify the error is raised and document the expected behavior.

    In production, the model should be retrained on the 18-feature set before
    enabling shadow mode. This test ensures we know what happens if an old
    model is accidentally used.
    """
    import xgboost as xgb

    # Simulate a model trained on the old 23-feature set
    old_feature_columns = FEATURE_COLUMNS + [
        "market_correlation",
        "position_concentration",
        "num_open_positions",
        "avg_leverage",
        "risk_mgmt_score",
    ]
    assert len(old_feature_columns) == 23

    rng = np.random.RandomState(42)
    n_samples = 100
    X_old = rng.randn(n_samples, 23)
    y_old = rng.randn(n_samples)

    old_model = xgb.XGBRegressor(n_estimators=10, random_state=42)
    old_model.fit(X_old, y_old)

    model_path = str(tmp_path / "old_23feat.json")
    old_model.save_model(model_path)

    # Try to predict with 18-feature inputs (current FEATURE_COLUMNS)
    test_features = [
        {**{c: rng.randn() for c in FEATURE_COLUMNS}, "address": f"0xold{i}"}
        for i in range(5)
    ]

    # XGBoost raises ValueError when feature count mismatches.
    # This documents the current behavior -- old models must be retrained.
    with pytest.raises(ValueError):
        predict_trader_scores(model_path, test_features)


def test_shadow_mode_auto_detects_v3(tmp_path):
    """Shadow mode should use stacked pipeline when stacked_pipeline.pkl exists."""
    from snap.ml.predict import load_stacked_pipeline

    # Import the helper from test_ml_predict
    import sys, importlib
    sys.path.insert(0, str(Path(__file__).parent))
    from test_ml_predict import _create_synthetic_stacked_model

    # Create a v3 model dir with pipeline
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    _create_synthetic_stacked_model(model_dir)

    # Verify auto-detection
    pipeline = load_stacked_pipeline(str(model_dir))
    assert pipeline is not None
    assert len(pipeline.base_models) == 8
