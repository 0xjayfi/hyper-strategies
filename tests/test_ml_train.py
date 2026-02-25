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
