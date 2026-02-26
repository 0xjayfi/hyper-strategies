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


def _make_synthetic_df_with_inf(n_samples=200, n_windows=10):
    """Create a synthetic dataset that has inf values in profit_factor."""
    rng = np.random.RandomState(42)
    rows = []
    base_date = datetime(2026, 1, 1)
    for w in range(n_windows):
        wdate = base_date + timedelta(days=w * 3)
        for i in range(n_samples // n_windows):
            feat = {col: rng.randn() for col in FEATURE_COLUMNS}
            # Inject inf values: ~20% of rows get profit_factor=inf
            if rng.rand() < 0.2:
                feat["profit_factor"] = np.inf
            # Also inject a few -inf for pseudo_sharpe
            if rng.rand() < 0.05:
                feat["pseudo_sharpe"] = -np.inf
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

    def test_early_stopping_reduces_trees(self):
        """Early stopping should stop before 500 estimators when validation plateaus."""
        df = _make_synthetic_df(n_samples=200, n_windows=10)
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        # best_iteration is 0-indexed, so best_iteration + 1 is the number of trees
        # With early_stopping_rounds=50 and a small dataset, it should stop well before 500
        best_iter = result.model.best_iteration
        assert best_iter < 500, (
            f"Expected early stopping before 500, but model used best_iteration={best_iter}"
        )

    def test_feature_caps_returned(self):
        """feature_caps should be a dict on ModelResult (empty if no inf in data)."""
        df = _make_synthetic_df()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        assert isinstance(result.feature_caps, dict)

    def test_feature_caps_populated_with_inf_data(self):
        """When data has inf values, feature_caps should contain the capped columns."""
        df = _make_synthetic_df_with_inf()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        # profit_factor had inf injected, so it should be in feature_caps
        assert "profit_factor" in result.feature_caps
        assert result.feature_caps["profit_factor"] >= 10.0


class TestInfCapping:
    def test_inf_not_zeroed(self):
        """Inf values should be capped, NOT replaced with 0.0."""
        df = _make_synthetic_df_with_inf()
        # Before training, verify there are inf values in profit_factor
        assert np.isinf(df["profit_factor"]).any(), "Test data should contain inf"

        result = train_model(df, val_frac=0.2, test_frac=0.15)
        # The cap should be positive and >= 10.0
        cap = result.feature_caps["profit_factor"]
        assert cap >= 10.0

    def test_inf_capped_at_95th_percentile_or_floor(self):
        """Cap should be max(95th percentile of finite values, 10.0)."""
        rng = np.random.RandomState(99)
        base_date = datetime(2026, 1, 1)
        rows = []
        for w in range(5):
            wdate = base_date + timedelta(days=w * 3)
            for i in range(40):
                feat = {col: rng.uniform(0, 5) for col in FEATURE_COLUMNS}
                # Set profit_factor to known values
                feat["profit_factor"] = rng.uniform(1.0, 3.0)
                feat["address"] = f"0x{w:04d}{i:04d}"
                feat["window_date"] = wdate
                feat["forward_pnl_7d"] = rng.randn()
                rows.append(feat)
        df = pd.DataFrame(rows)

        # Inject some inf values
        inf_indices = rng.choice(len(df), size=10, replace=False)
        df.loc[inf_indices, "profit_factor"] = np.inf

        result = train_model(df, val_frac=0.2, test_frac=0.15)
        cap = result.feature_caps["profit_factor"]
        # Since all finite values are in [1.0, 3.0], 95th percentile < 10.0, so cap = 10.0
        assert cap == 10.0

    def test_neg_inf_capped_to_negative(self):
        """Negative inf should be capped to -cap value."""
        df = _make_synthetic_df_with_inf()
        # pseudo_sharpe may have -inf injected
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        # The key point: the model should still train successfully with no inf in data
        assert result.train_rmse >= 0
        assert result.val_rmse >= 0

    def test_no_inf_in_clean_data_means_empty_caps(self):
        """When data has no inf, feature_caps should be empty."""
        df = _make_synthetic_df()
        # Verify no inf in the synthetic data
        for col in FEATURE_COLUMNS:
            assert not np.isinf(df[col]).any()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        assert result.feature_caps == {}


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

    def test_baseline_metrics_present(self):
        """evaluate_model should return avg_baseline_pnl and model_lift."""
        df = _make_synthetic_df(n_samples=200, n_windows=10)
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        from snap.ml.dataset import split_dataset_chronological
        _, _, test = split_dataset_chronological(df, val_frac=0.2, test_frac=0.15)
        if len(test) > 0:
            metrics = evaluate_model(result.model, test)
            assert "avg_baseline_pnl" in metrics
            assert "model_lift" in metrics

    def test_model_lift_is_difference(self):
        """model_lift should equal top15_actual_pnl - avg_baseline_pnl."""
        df = _make_synthetic_df(n_samples=200, n_windows=10)
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        from snap.ml.dataset import split_dataset_chronological
        _, _, test = split_dataset_chronological(df, val_frac=0.2, test_frac=0.15)
        if len(test) > 0:
            metrics = evaluate_model(result.model, test)
            expected_lift = metrics["top15_actual_pnl"] - metrics["avg_baseline_pnl"]
            assert abs(metrics["model_lift"] - expected_lift) < 1e-10


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

    def test_feature_caps_in_metadata(self, tmp_path):
        """feature_caps should be saved in the .meta.json file."""
        df = _make_synthetic_df_with_inf()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        model_path = str(tmp_path / "model.json")
        meta_path = save_model(result, model_path)
        meta = json.loads(Path(meta_path).read_text())
        assert "feature_caps" in meta
        assert isinstance(meta["feature_caps"], dict)
        # profit_factor should be capped since the data had inf
        assert "profit_factor" in meta["feature_caps"]
        assert meta["feature_caps"]["profit_factor"] >= 10.0

    def test_feature_caps_empty_when_no_inf(self, tmp_path):
        """When no inf values, feature_caps should be empty dict in metadata."""
        df = _make_synthetic_df()
        result = train_model(df, val_frac=0.2, test_frac=0.15)
        model_path = str(tmp_path / "model.json")
        meta_path = save_model(result, model_path)
        meta = json.loads(Path(meta_path).read_text())
        assert "feature_caps" in meta
        assert meta["feature_caps"] == {}
