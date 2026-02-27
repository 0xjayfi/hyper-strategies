#!/usr/bin/env python3
"""Stacked ML model training script v2.

Implements a stacked generalization pipeline:
1. Cross-sectional normalization (demean features + target within each window)
2. Per-trader aggregation (mean + trend) with min_windows filter
3. Diverse XGBoost base models ensemble
4. ElasticNet meta-learner for calibrated predictions

Usage:
    python scripts/train_model_v2.py --data-db data/market_190226 --output models/xgb_trader_v2.json
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.linear_model import ElasticNet
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

META_LEARNER_ALPHA = 0.0025
META_LEARNER_L1_RATIO = 0.75


def train_stacked_model(
    df: pd.DataFrame,
    val_frac: float = 0.2,
    test_frac: float = 0.15,
    min_windows: int = 10,
) -> dict:
    """Train the full stacked pipeline. Returns all model artifacts."""
    df = add_derived_features(df)
    per_sample_cols = get_per_sample_feature_cols()
    agg_feat_cols = get_aggregated_feature_cols(per_sample_cols)

    train_df, val_df, test_df = split_dataset_chronological(df, val_frac, test_frac)

    tr_a = aggregate_per_trader(train_df, per_sample_cols, min_windows=min_windows)
    vl_a = aggregate_per_trader(val_df, per_sample_cols, min_windows=min_windows)
    te_a = aggregate_per_trader(test_df, per_sample_cols, min_windows=min_windows)

    X_tr = tr_a[agg_feat_cols].values
    y_tr = tr_a["target_dm"].values
    X_vl = vl_a[agg_feat_cols].values
    y_vl = vl_a["target_dm"].values
    X_te = te_a[agg_feat_cols].values
    y_te = te_a["target_dm"].values

    # Train diverse base models
    base_models = []
    vl_preds = []
    te_preds = []
    for cfg in BASE_MODEL_CONFIGS:
        p = {
            "n_estimators": 3000,
            "learning_rate": 0.01,
            "subsample": 0.8,
            "colsample_bytree": 0.7,
            "early_stopping_rounds": 100,
            "n_jobs": -1,
        }
        p.update(cfg)
        m = xgb.XGBRegressor(**p)
        m.fit(X_tr, y_tr, eval_set=[(X_vl, y_vl)], verbose=False)
        base_models.append(m)
        vl_preds.append(m.predict(X_vl))
        te_preds.append(m.predict(X_te))

    vl_pred_mat = np.column_stack(vl_preds)
    te_pred_mat = np.column_stack(te_preds)

    # Stack: features + base model predictions
    X_vl_full = np.hstack([X_vl, vl_pred_mat])
    X_te_full = np.hstack([X_te, te_pred_mat])
    scaler = StandardScaler()
    X_vl_full_s = scaler.fit_transform(X_vl_full)
    X_te_full_s = scaler.transform(X_te_full)

    # Meta-learner
    meta = ElasticNet(alpha=META_LEARNER_ALPHA, l1_ratio=META_LEARNER_L1_RATIO, max_iter=10000)
    meta.fit(X_vl_full_s, y_vl)

    # Evaluate
    te_pred_final = meta.predict(X_te_full_s)
    test_r2 = float(r2_score(y_te, te_pred_final))
    test_rmse = float(np.sqrt(mean_squared_error(y_te, te_pred_final)))
    test_spearman = float(spearmanr(y_te, te_pred_final)[0])

    # Train metrics through full pipeline
    tr_pred_mat = np.column_stack([m.predict(X_tr) for m in base_models])
    X_tr_full_s = scaler.transform(np.hstack([X_tr, tr_pred_mat]))
    tr_pred_final = meta.predict(X_tr_full_s)
    train_r2 = float(r2_score(y_tr, tr_pred_final))

    # Feature importances from first base model
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
            "n_train": len(tr_a),
            "n_val": len(vl_a),
            "n_test": len(te_a),
            "n_base_models": len(base_models),
            "n_active_features": int(np.sum(np.abs(meta.coef_) > 1e-10)),
        },
        "feature_importances": importances,
    }


def save_stacked_model(result: dict, output_dir: str) -> str:
    """Save the full stacked model pipeline."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Save base XGBoost models
    for i, m in enumerate(result["base_models"]):
        m.save_model(str(out / f"base_model_{i}.json"))

    # Save meta-learner + scaler as pickle
    pipeline = {
        "meta_learner": result["meta_learner"],
        "scaler": result["scaler"],
        "agg_feat_cols": result["agg_feat_cols"],
        "per_sample_cols": result["per_sample_cols"],
        "min_windows": result["min_windows"],
    }
    with open(out / "stacked_pipeline.pkl", "wb") as f:
        pickle.dump(pipeline, f)

    # Save metadata
    meta = {
        "trained_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": "v2_stacked",
        "pipeline": "xgb_ensemble_8x + elasticnet_meta",
        **result["metrics"],
        "feature_importances": result["feature_importances"],
        "meta_learner_alpha": META_LEARNER_ALPHA,
        "meta_learner_l1_ratio": META_LEARNER_L1_RATIO,
        "base_model_configs": BASE_MODEL_CONFIGS,
    }
    meta_path = str(out / "model_v2.meta.json")
    Path(meta_path).write_text(json.dumps(meta, indent=2))
    return meta_path


def main():
    parser = argparse.ArgumentParser(description="Train stacked ML trader selection model v2")
    parser.add_argument("--data-db", required=True, help="Path to market data DB")
    parser.add_argument("--output", default="models/v2", help="Output directory for model artifacts")
    parser.add_argument("--stride", type=int, default=1, help="Window stride in days (default: 1)")
    parser.add_argument("--forward", type=int, default=7, help="Forward PnL window in days (default: 7)")
    parser.add_argument("--min-windows", type=int, default=10, help="Minimum windows per trader (default: 10)")
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
    df = build_dataset(conn, start=data_start, end=data_end, stride_days=args.stride, forward_days=args.forward)
    print(f"Dataset: {len(df)} samples, {df['address'].nunique()} traders, {df['window_date'].nunique()} windows")

    print("Training stacked model...")
    result = train_stacked_model(df, min_windows=args.min_windows)

    m = result["metrics"]
    print(f"\n=== Results ===")
    print(f"  Train R²:       {m['train_r2']:.4f}")
    print(f"  Test R²:        {m['test_r2']:.4f}")
    print(f"  Test RMSE:      {m['test_rmse']:.6f}")
    print(f"  Test Spearman:  {m['test_spearman']:.4f}")
    print(f"  Samples: train={m['n_train']}, val={m['n_val']}, test={m['n_test']}")
    print(f"  Base models: {m['n_base_models']}, Active meta features: {m['n_active_features']}")

    meta_path = save_stacked_model(result, args.output)
    print(f"\nModel saved to: {args.output}/")
    print(f"Metadata: {meta_path}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
