# ML Trader Selection — Design Document

**Date**: 2026-02-25
**Status**: Approved
**Goal**: Replace the hand-tuned composite scoring formula with an XGBoost model that predicts forward 7-day PnL to select the best traders.

---

## Problem Definition

The current system uses a hand-tuned composite score (weighted combination of ROI, Sharpe, win rate, consistency, etc.) to rank traders and select the top 15. This works but has limitations:

- Weights are static and manually chosen
- No feedback loop — the formula doesn't learn from outcomes
- May miss nonlinear patterns (e.g. "high win rate is good, but extremely high is suspicious")

**Approach**: Train an XGBoost regressor to predict each trader's forward 7-day PnL (as % of account value) using the same features the scoring pipeline already computes, plus a few new ones. Rank by predicted PnL instead of composite score.

---

## Data Pipeline

### Training data construction (backfill)

Use the existing 1.2M trade history records (Nov 2025 – Feb 2026) with a sliding window:

1. Pick evaluation dates every 3 days from Dec 1 to Feb 16 (~26 windows)
2. At each window, for every trader with enough history:
   - Compute features from the lookback period
   - Measure actual PnL over the next 7 days
3. Estimated sample size: ~25,000–50,000 training samples

### Live data collection (ongoing)

A daily job snapshots all scored trader features into `ml_feature_snapshots`. After 7 days, the actual forward PnL is backfilled. This accumulates new training data continuously for periodic retraining.

### Feature set

**Existing features (from scoring.py)**:
- roi_7d, roi_30d, roi_90d
- pnl_7d, pnl_30d, pnl_90d
- win_rate, profit_factor
- pseudo_sharpe
- trade_count, avg_hold_hours, trades_per_day
- consistency_score
- smart_money_bonus
- risk_mgmt_score

**New features to add**:
- position_concentration (% of portfolio in top token)
- num_open_positions
- avg_leverage
- pnl_volatility_7d
- market_correlation (beta to BTC)
- days_since_last_trade
- max_drawdown_30d

### Target variable

`forward_pnl_7d` — trader's total realized + unrealized PnL over the 7 days following the feature snapshot, normalized as a percentage of account value.

---

## Model Architecture & Training

### Model

XGBoost regressor. Regression (not classification) so we can rank by expected dollar value.

### Train/validation/test split

Strictly chronological to prevent data leakage:

```
|--- Train (Dec 1 – Jan 20) ---|--- Val (Jan 20 – Feb 3) ---|--- Test (Feb 3 – Feb 16) ---|
         ~17 windows                    ~5 windows                    ~4 windows
```

### Hyperparameters

Starting point, tuned on validation set:
- max_depth: 4–6
- n_estimators: 100–500 with early stopping
- learning_rate: 0.05–0.1
- min_child_weight: 10+
- subsample: 0.8

### Evaluation metrics

| Metric | Purpose |
|--------|---------|
| RMSE | Overall prediction accuracy |
| Top-15 actual PnL | "If we picked top 15 by model, what did they actually make?" |
| Spearman rank correlation | Does model ordering match reality? |
| vs. baseline | Compare against current composite_score ranking |

### Feature importance

Inspected after training to understand what drives predictions. Feeds back into improving the hand-tuned scoring even independently of the model.

---

## Integration with Snap System

### Architecture

The model replaces one step — the composite score calculation:

```
Current:
  Nansen API -> ingestion -> scoring.py -> [hand-tuned composite_score] -> top 15 -> portfolio -> execution

New:
  Nansen API -> ingestion -> scoring.py -> [feature extraction] -> [XGBoost predict] -> top 15 -> portfolio -> execution
```

Everything else (ingestion, portfolio construction, risk overlay, execution, monitoring) stays the same. The tier-1 / consistency / quality gates still filter before scoring — the model only ranks candidates that pass.

### Deployment modes

1. **Shadow mode** (start here) — model scores traders alongside existing formula. Both logged. Hand-tuned score still drives decisions. Compare over time.
2. **Live mode** — model's predicted PnL replaces composite_score for ranking.

### New files

| File | Purpose |
|------|---------|
| `src/snap/ml/features.py` | Feature extraction from trade history (backfill + live) |
| `src/snap/ml/dataset.py` | Sliding window dataset construction, train/val/test splits |
| `src/snap/ml/train.py` | Training loop, hyperparameter tuning, evaluation |
| `src/snap/ml/predict.py` | Load model, score traders, integrate with scoring.py |
| `src/snap/ml/daily_snapshot.py` | Daily feature logging job for ongoing data collection |
| `scripts/train_model.py` | CLI entry point: build dataset -> train -> evaluate -> save |
| `models/` | Saved model artifacts + metrics |

### New DB tables

```sql
-- Features captured at a point in time
ml_feature_snapshots (
    id INTEGER PRIMARY KEY,
    address TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    roi_7d REAL, roi_30d REAL, roi_90d REAL,
    pnl_7d REAL, pnl_30d REAL, pnl_90d REAL,
    win_rate REAL, profit_factor REAL, pseudo_sharpe REAL,
    trade_count INTEGER, avg_hold_hours REAL, trades_per_day REAL,
    consistency_score REAL, smart_money_bonus REAL, risk_mgmt_score REAL,
    position_concentration REAL, num_open_positions INTEGER,
    avg_leverage REAL, pnl_volatility_7d REAL,
    market_correlation REAL, days_since_last_trade REAL,
    max_drawdown_30d REAL,
    forward_pnl_7d REAL,  -- NULL initially, backfilled after 7 days
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)

-- Model metadata and performance tracking
ml_models (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    trained_at TEXT NOT NULL,
    train_rmse REAL, val_rmse REAL, test_rmse REAL,
    top15_backtest_pnl REAL,
    feature_importances TEXT,  -- JSON blob
    model_path TEXT,
    is_active INTEGER DEFAULT 0
)
```

### Config additions

```python
# ML settings
ML_TRADER_SELECTION = False          # shadow mode by default
ML_MODEL_DIR = "models/"
ML_FORWARD_WINDOW_DAYS = 7
ML_RETRAIN_CADENCE_DAYS = 7
ML_SNAPSHOT_HOUR_UTC = 1             # daily snapshot at 01:00 UTC
ML_MIN_TRAIN_SAMPLES = 5000
```

---

## Implementation Phases

### Phase 1 — Backfill & Train
1. Feature extraction module (reuse scoring.py computations + new features)
2. Sliding window dataset construction over 3 months of trade history
3. XGBoost training pipeline with chronological split and evaluation
4. CLI script to run end-to-end

### Phase 2 — Shadow Mode
5. Prediction module — load model, score eligible traders
6. Wire into scoring.py — log model score alongside composite_score
7. Daily snapshot job for ongoing data collection
8. New DB tables

### Phase 3 — Live Mode
9. Config toggle to use model score for selection
10. Weekly retrain via scripts/train_model.py
11. Model versioning and rollback

### Dependencies

- xgboost
- scikit-learn (metrics, utilities)
- pandas (dataset manipulation)
