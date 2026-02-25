"""Tests for ML configuration constants."""

from snap import config


def test_ml_defaults_exist():
    assert hasattr(config, "ML_TRADER_SELECTION")
    assert config.ML_TRADER_SELECTION is False


def test_ml_forward_window():
    assert config.ML_FORWARD_WINDOW_DAYS == 7


def test_ml_retrain_cadence():
    assert config.ML_RETRAIN_CADENCE_DAYS == 7


def test_ml_snapshot_hour():
    assert config.ML_SNAPSHOT_HOUR_UTC == 1


def test_ml_model_dir():
    assert config.ML_MODEL_DIR == "models/"


def test_ml_min_train_samples():
    assert config.ML_MIN_TRAIN_SAMPLES == 5000


def test_ml_backfill_window_stride_days():
    assert config.ML_BACKFILL_STRIDE_DAYS == 3
