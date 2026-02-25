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
