# Design: Update predict.py for v3 Stacked Pipeline

**Date**: 2026-02-27
**Status**: Approved

## Problem

`predict.py` only supports v1 single-XGBoost inference (18 raw features → single model → prediction). The v3 stacked pipeline requires: 8 base XGBoost models, cross-sectional feature engineering, per-trader aggregation over multiple time windows, and a Ridge meta-learner. The serving path does not exist.

## Approach

Extend `predict.py` with v3 stacked inference alongside the existing v1 path. Auto-detect model version in the shadow mode hook.

## Components

### 1. Shared feature engineering in `features.py`

Move these functions from `scripts/train_model_v3.py` into `src/snap/ml/features.py` so both training and inference share identical code:

- `EXTRA_RAW_FEATURES` — list of 6 momentum/interaction feature names
- `add_derived_features(df)` — inf capping, cross-sectional z-scores, ranks, momentum features
- `get_per_sample_feature_cols()` — returns 48 per-sample column names
- `aggregate_per_trader(df, feature_cols, target_col, min_windows)` — mean + trend aggregation
- `get_aggregated_feature_cols(per_sample_cols)` — returns 97 aggregated column names

At inference time, `add_derived_features()` is called without target winsorization/demeaning (those are training-only transforms). A `training=False` flag controls this.

### 2. `StackedPipeline` dataclass in `predict.py`

Holds loaded model artifacts:
- `base_models: list[xgb.XGBRegressor]` — 8 base models
- `meta_learner: Ridge` — from pickle
- `scaler: StandardScaler` — from pickle
- `agg_feat_cols: list[str]` — 97 feature column names
- `per_sample_cols: list[str]` — 48 per-sample column names
- `min_windows: int` — minimum observation windows (16 for v3)
- `feature_caps: dict` — inf capping values from meta.json

### 3. `load_stacked_pipeline(model_dir)` in `predict.py`

- Glob `base_model_*.json` files, load each as XGBRegressor
- Load `stacked_pipeline.pkl` (meta_learner, scaler, column lists, min_windows)
- Load `model_v*.meta.json` for feature_caps
- Return `StackedPipeline`

### 4. `predict_stacked_scores(model_dir, conn, as_of)` in `predict.py`

Inference pipeline:
1. Query `ml_feature_snapshots` table for snapshots within [as_of - 90d, as_of]
2. Build DataFrame: address, window_date (= snapshot_date), 18 FEATURE_COLUMNS
3. Call `add_derived_features(df, training=False)` — inf cap, z-scores, ranks, momentum (no target demeaning)
4. Call `aggregate_per_trader()` — mean + trend, filter by `min_windows`
5. Build feature matrix from `agg_feat_cols`
6. Run 8 base models → 8 prediction columns
7. Stack [97 features | 8 predictions] = 105 meta features
8. `scaler.transform()` → `meta_learner.predict()` → final scores
9. Return `[{address, ml_predicted_pnl}]`

### 5. Update shadow mode hook in `scoring.py`

Auto-detect model version:
- If `Path(ML_MODEL_DIR) / "stacked_pipeline.pkl"` exists → call `predict_stacked_scores(ML_MODEL_DIR, conn, now)`
- Else fall back to existing v1 glob for `xgb_trader_*.json`

### 6. Tests

- `test_load_stacked_pipeline` — load from synthetic model dir
- `test_predict_stacked_scores` — end-to-end with synthetic snapshots in DB
- `test_predict_stacked_empty_snapshots` — returns empty when no data
- `test_predict_stacked_insufficient_windows` — returns empty when traders have < min_windows
- `test_shadow_mode_auto_detects_v3` — shadow hook dispatches correctly
- Existing v1 tests unchanged

## Data flow

```
ml_feature_snapshots (DB, last 90d)
  → DataFrame (address, snapshot_date, 18 features)
  → add_derived_features(training=False)
    - inf cap at p95
    - cross-sectional z-score + rank per snapshot_date
    - momentum/interaction features + their z-score/rank
  → aggregate_per_trader(min_windows=16)
    - mean + trend per feature
    - filter traders with < 16 snapshots
  → 97 aggregated features per trader
  → 8 XGBoost base model predictions
  → [97 features | 8 predictions] = 105 meta features
  → StandardScaler → Ridge → predicted demeaned PnL
  → [{address, ml_predicted_pnl}]
```

## Key decisions

- **No v1 breakage**: existing functions untouched, v1 tests pass as-is
- **Shared feature code**: single source of truth prevents train/serve skew
- **Multi-window from DB**: queries accumulated daily snapshots for proper aggregation
- **training flag**: `add_derived_features(training=False)` skips target winsorization/demeaning at inference
