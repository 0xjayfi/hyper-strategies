"""Tests for ML prediction and scoring integration."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from snap.database import init_db
from snap.ml.features import FEATURE_COLUMNS
from snap.ml.predict import (
    _load_feature_caps,
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


@pytest.fixture()
def trained_model_with_caps(tmp_path):
    """Train a model and save with feature_caps in meta.json."""
    df = _make_synthetic_df()
    result = train_model(df)
    model_path = str(tmp_path / "model_caps.json")
    meta_path = save_model(result, model_path)
    # Inject feature_caps into the meta file
    with open(meta_path) as f:
        meta = json.load(f)
    meta["feature_caps"] = {"profit_factor": 50.0, "pseudo_sharpe": 20.0}
    with open(meta_path, "w") as f:
        json.dump(meta, f)
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

    def test_inf_values_capped_with_feature_caps(self, trained_model_with_caps):
        """Inf values in features should be replaced using feature_caps from meta.json."""
        feat = {c: 1.0 for c in FEATURE_COLUMNS}
        feat["address"] = "0xinf_test"
        feat["profit_factor"] = float("inf")
        feat["pseudo_sharpe"] = float("-inf")
        predictions = predict_trader_scores(trained_model_with_caps, [feat])
        assert len(predictions) == 1
        # Prediction should be a finite number (not NaN or inf)
        assert np.isfinite(predictions[0]["ml_predicted_pnl"])

    def test_inf_values_fallback_without_caps(self, trained_model):
        """Inf values should fall back to 0.0 when no feature_caps exist in meta."""
        feat = {c: 1.0 for c in FEATURE_COLUMNS}
        feat["address"] = "0xinf_nocap"
        feat["profit_factor"] = float("inf")
        predictions = predict_trader_scores(trained_model, [feat])
        assert len(predictions) == 1
        assert np.isfinite(predictions[0]["ml_predicted_pnl"])

    def test_nan_values_replaced(self, trained_model):
        """NaN values in features should be replaced with 0.0."""
        feat = {c: 1.0 for c in FEATURE_COLUMNS}
        feat["address"] = "0xnan_test"
        feat["roi_7d"] = float("nan")
        feat["win_rate"] = float("nan")
        predictions = predict_trader_scores(trained_model, [feat])
        assert len(predictions) == 1
        assert np.isfinite(predictions[0]["ml_predicted_pnl"])

    def test_mixed_inf_nan_values(self, trained_model_with_caps):
        """Mixed inf and NaN values should all be cleaned."""
        feat = {c: 1.0 for c in FEATURE_COLUMNS}
        feat["address"] = "0xmixed"
        feat["profit_factor"] = float("inf")
        feat["pseudo_sharpe"] = float("-inf")
        feat["roi_7d"] = float("nan")
        feat["win_rate"] = float("nan")
        predictions = predict_trader_scores(trained_model_with_caps, [feat])
        assert len(predictions) == 1
        assert np.isfinite(predictions[0]["ml_predicted_pnl"])


class TestLoadFeatureCaps:
    def test_missing_meta_json_returns_empty(self, tmp_path):
        """Missing meta.json should gracefully return empty dict."""
        model_path = str(tmp_path / "nonexistent.json")
        caps = _load_feature_caps(model_path)
        assert caps == {}

    def test_meta_without_feature_caps_returns_empty(self, tmp_path):
        """Meta.json without feature_caps key should return empty dict."""
        meta_path = tmp_path / "model.meta.json"
        meta_path.write_text(json.dumps({"train_rmse": 0.1}))
        model_path = str(tmp_path / "model.json")
        caps = _load_feature_caps(model_path)
        assert caps == {}

    def test_meta_with_feature_caps_returns_caps(self, tmp_path):
        """Meta.json with feature_caps should return them."""
        meta_path = tmp_path / "model.meta.json"
        expected = {"profit_factor": 50.0, "pseudo_sharpe": 20.0}
        meta_path.write_text(json.dumps({"feature_caps": expected}))
        model_path = str(tmp_path / "model.json")
        caps = _load_feature_caps(model_path)
        assert caps == expected

    def test_corrupted_meta_json_returns_empty(self, tmp_path):
        """Corrupted JSON in meta file should return empty dict."""
        meta_path = tmp_path / "model.meta.json"
        meta_path.write_text("not valid json {{{")
        model_path = str(tmp_path / "model.json")
        caps = _load_feature_caps(model_path)
        assert caps == {}


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
