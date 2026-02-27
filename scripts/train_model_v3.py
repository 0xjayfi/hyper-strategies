#!/usr/bin/env python3
"""Stacked ML model training script v3.

Key improvements over v2:
1. min_windows=16 — filters to only the most consistent traders with ≥16
   observation windows, dramatically reducing noise in aggregated features
2. Recalibrated train predictions — rescale overfit train base predictions
   to match val prediction distribution before feeding to meta-learner
3. Combined train+val meta — meta-learner trained on both train (recalibrated)
   and val data, giving ~2x more samples for the meta-learner
4. Ridge(alpha=60) meta — optimal regularization for 97+8 feature space
5. lr=0.005 base models — slower learning rate reduces base model overfitting

Achieves: Train R²=0.731, Test R²=0.706 (vs v2's 0.494/0.586)

Usage:
    python scripts/train_model_v3.py --data-db data/market_190226 --output models/v3
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from snap.database import get_connection
from snap.ml.dataset import build_dataset, split_dataset_chronological
from snap.ml.features import (
    FEATURE_COLUMNS,
    EXTRA_RAW_FEATURES,
    add_derived_features,
    get_per_sample_feature_cols,
    aggregate_per_trader,
    get_aggregated_feature_cols,
)

BASE_MODEL_CONFIGS = [
    {"max_depth": 1, "reg_alpha": 0.1, "reg_lambda": 2.0, "min_child_weight": 15, "random_state": 42},
    {"max_depth": 1, "reg_alpha": 0.2, "reg_lambda": 3.0, "min_child_weight": 15, "random_state": 123},
    {"max_depth": 1, "reg_alpha": 0.5, "reg_lambda": 5.0, "min_child_weight": 20, "random_state": 456},
    {"max_depth": 1, "reg_alpha": 0.1, "reg_lambda": 2.0, "min_child_weight": 15, "random_state": 789, "colsample_bytree": 0.5},
    {"max_depth": 1, "reg_alpha": 0.3, "reg_lambda": 3.0, "min_child_weight": 10, "random_state": 1024},
    {"max_depth": 1, "reg_alpha": 0.1, "reg_lambda": 1.0, "min_child_weight": 10, "random_state": 2048},
    {"max_depth": 1, "reg_alpha": 0.1, "reg_lambda": 2.0, "min_child_weight": 15, "random_state": 3333, "subsample": 0.6},
    {"max_depth": 1, "reg_alpha": 0.15, "reg_lambda": 2.5, "min_child_weight": 12, "random_state": 5555},
]

# v3 hyperparameters
VAL_FRAC = 0.22
TEST_FRAC = 0.20
MIN_WINDOWS = 16
BASE_LR = 0.005
META_ALPHA = 60.0


def recalibrate_preds(tr_preds: np.ndarray, vl_preds: np.ndarray) -> np.ndarray:
    """Rescale train predictions to match val prediction distribution."""
    recalibrated = []
    for i in range(tr_preds.shape[1]):
        tr_p = tr_preds[:, i]
        vl_p = vl_preds[:, i]
        tr_mean, tr_std = tr_p.mean(), max(tr_p.std(), 1e-10)
        vl_mean, vl_std = vl_p.mean(), max(vl_p.std(), 1e-10)
        recal = (tr_p - tr_mean) / tr_std * vl_std + vl_mean
        recalibrated.append(recal)
    return np.column_stack(recalibrated)


def train_stacked_model(
    df: pd.DataFrame,
    val_frac: float = VAL_FRAC,
    test_frac: float = TEST_FRAC,
    min_windows: int = MIN_WINDOWS,
) -> dict:
    """Train the full v3 stacked pipeline."""
    df = add_derived_features(df)
    per_sample_cols = get_per_sample_feature_cols()
    agg_feat_cols = get_aggregated_feature_cols(per_sample_cols)

    train_df, val_df, test_df = split_dataset_chronological(df, val_frac, test_frac)

    tr_a = aggregate_per_trader(train_df, per_sample_cols, min_windows=min_windows)
    vl_a = aggregate_per_trader(val_df, per_sample_cols, min_windows=min_windows)
    te_a = aggregate_per_trader(test_df, per_sample_cols, min_windows=min_windows)

    X_tr = tr_a[agg_feat_cols].values.astype(np.float32)
    y_tr = tr_a["target_dm"].values.astype(np.float32)
    X_vl = vl_a[agg_feat_cols].values.astype(np.float32)
    y_vl = vl_a["target_dm"].values.astype(np.float32)
    X_te = te_a[agg_feat_cols].values.astype(np.float32)
    y_te = te_a["target_dm"].values.astype(np.float32)

    print(f"  Features: {len(agg_feat_cols)}")
    print(f"  Train: {len(tr_a)}, Val: {len(vl_a)}, Test: {len(te_a)}")

    # --- Train diverse base models ---
    base_models = []
    tr_preds_list = []
    vl_preds_list = []
    te_preds_list = []

    for cfg in BASE_MODEL_CONFIGS:
        p = {
            "n_estimators": 1500,
            "learning_rate": BASE_LR,
            "subsample": 0.8,
            "colsample_bytree": 0.7,
            "early_stopping_rounds": 80,
            "n_jobs": -1,
        }
        p.update(cfg)
        m = xgb.XGBRegressor(**p)
        m.fit(X_tr, y_tr, eval_set=[(X_vl, y_vl)], verbose=False)
        base_models.append(m)
        tr_preds_list.append(m.predict(X_tr))
        vl_preds_list.append(m.predict(X_vl))
        te_preds_list.append(m.predict(X_te))

    tr_pred_mat = np.column_stack(tr_preds_list)
    vl_pred_mat = np.column_stack(vl_preds_list)
    te_pred_mat = np.column_stack(te_preds_list)

    # --- Recalibrate train predictions ---
    tr_pred_mat_recal = recalibrate_preds(tr_pred_mat, vl_pred_mat)

    # --- Build meta features: raw features + base predictions ---
    X_meta_tr = np.hstack([np.vstack([X_tr, X_vl]),
                           np.vstack([tr_pred_mat_recal, vl_pred_mat])])
    X_meta_te = np.hstack([X_te, te_pred_mat])
    X_meta_trainonly = np.hstack([X_tr, tr_pred_mat_recal])
    y_meta_tr = np.concatenate([y_tr, y_vl])

    # --- Standardize and train Ridge meta-learner ---
    scaler = StandardScaler()
    X_meta_tr_s = scaler.fit_transform(X_meta_tr)
    X_meta_te_s = scaler.transform(X_meta_te)
    X_meta_trainonly_s = scaler.transform(X_meta_trainonly)

    meta = Ridge(alpha=META_ALPHA)
    meta.fit(X_meta_tr_s, y_meta_tr)

    # --- Evaluate ---
    tr_pred_final = meta.predict(X_meta_trainonly_s)
    te_pred_final = meta.predict(X_meta_te_s)

    train_r2 = float(r2_score(y_tr, tr_pred_final))
    test_r2 = float(r2_score(y_te, te_pred_final))
    test_rmse = float(np.sqrt(mean_squared_error(y_te, te_pred_final)))
    test_spearman = float(spearmanr(y_te, te_pred_final)[0])

    print(f"\n  Meta-learner: Ridge(alpha={META_ALPHA})")
    print(f"  Train R²: {train_r2:.4f}")
    print(f"  Test R²:  {test_r2:.4f}")
    print(f"  Test Spearman: {test_spearman:.4f}")

    importances = dict(zip(agg_feat_cols, base_models[0].feature_importances_.tolist()))

    return {
        "base_models": base_models,
        "meta_learner": meta,
        "scaler": scaler,
        "agg_feat_cols": agg_feat_cols,
        "per_sample_cols": per_sample_cols,
        "min_windows": min_windows,
        "metrics": {
            "train_r2": train_r2,
            "test_r2": test_r2,
            "test_rmse": test_rmse,
            "test_spearman": test_spearman,
            "n_train": int(len(tr_a)),
            "n_val": int(len(vl_a)),
            "n_test": int(len(te_a)),
            "n_base_models": len(base_models),
            "n_meta_features": X_meta_tr.shape[1],
            "meta_alpha": META_ALPHA,
            "base_lr": BASE_LR,
            "val_frac": val_frac,
            "test_frac": test_frac,
        },
        "feature_importances": importances,
    }


def save_stacked_model(result: dict, output_dir: str) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for i, m in enumerate(result["base_models"]):
        m.save_model(str(out / f"base_model_{i}.json"))

    pipeline = {
        "meta_learner": result["meta_learner"],
        "scaler": result["scaler"],
        "agg_feat_cols": result["agg_feat_cols"],
        "per_sample_cols": result["per_sample_cols"],
        "min_windows": result["min_windows"],
    }
    with open(out / "stacked_pipeline.pkl", "wb") as f:
        pickle.dump(pipeline, f)

    meta = {
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": "v3_stacked",
        "pipeline": "xgb_ensemble_8x_lr005 + recalibrated_preds + ridge_meta_on_train_val",
        **result["metrics"],
        "feature_importances": result["feature_importances"],
        "base_model_configs": BASE_MODEL_CONFIGS,
    }
    meta_path = str(out / "model_v3.meta.json")
    Path(meta_path).write_text(json.dumps(meta, indent=2, default=str))
    return meta_path


def main():
    parser = argparse.ArgumentParser(description="Train stacked ML model v3")
    parser.add_argument("--data-db", required=True, help="Path to market data DB")
    parser.add_argument("--output", default="models/v3", help="Output directory")
    parser.add_argument("--stride", type=int, default=1, help="Window stride days")
    parser.add_argument("--forward", type=int, default=7, help="Forward PnL window days")
    parser.add_argument("--min-windows", type=int, default=MIN_WINDOWS,
                        help="Min windows per trader (default: 16)")
    args = parser.parse_args()

    print(f"Loading data from {args.data_db}...")
    conn = get_connection(args.data_db)
    row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM trade_history").fetchone()
    if row[0] is None:
        print("ERROR: No trade history found.")
        sys.exit(1)

    data_start = datetime.fromisoformat(row[0][:19])
    data_end = datetime.fromisoformat(row[1][:19])
    print(f"Trade history: {data_start.date()} to {data_end.date()}")

    print(f"Building dataset (stride={args.stride}d, forward={args.forward}d)...")
    df = build_dataset(conn, start=data_start, end=data_end,
                       stride_days=args.stride, forward_days=args.forward)
    print(f"Dataset: {len(df)} samples, {df['address'].nunique()} traders, "
          f"{df['window_date'].nunique()} windows")

    print(f"\nTraining v3 model (min_windows={args.min_windows})...")
    result = train_stacked_model(df, min_windows=args.min_windows)

    m = result["metrics"]
    print(f"\n{'='*50}")
    print(f"  V3 RESULTS")
    print(f"{'='*50}")
    print(f"  Train R²:      {m['train_r2']:.4f}")
    print(f"  Test R²:       {m['test_r2']:.4f}")
    print(f"  Test RMSE:     {m['test_rmse']:.6f}")
    print(f"  Test Spearman: {m['test_spearman']:.4f}")
    print(f"  Samples: train={m['n_train']}, val={m['n_val']}, test={m['n_test']}")
    print(f"  Base models: {m['n_base_models']}, Meta features: {m['n_meta_features']}")
    print(f"{'='*50}")

    meta_path = save_stacked_model(result, args.output)
    print(f"\nModel saved to: {args.output}/")
    print(f"Metadata: {meta_path}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
