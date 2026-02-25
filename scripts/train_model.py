#!/usr/bin/env python3
"""End-to-end ML model training script.

Usage:
    python scripts/train_model.py --data-db data/market_190226 --output models/xgb_trader_v1.json
    python scripts/train_model.py --data-db data/market_190226 --output models/xgb_trader_v1.json --stride 3 --forward 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from snap.database import get_connection
from snap.ml.dataset import build_dataset
from snap.ml.train import train_model, save_model, evaluate_model
from snap.ml.features import FEATURE_COLUMNS


def main():
    parser = argparse.ArgumentParser(description="Train ML trader selection model")
    parser.add_argument("--data-db", required=True, help="Path to market data DB")
    parser.add_argument("--output", default="models/xgb_trader_v1.json", help="Output model path")
    parser.add_argument("--start", default=None, help="Dataset start date (YYYY-MM-DD), default: earliest data")
    parser.add_argument("--end", default=None, help="Dataset end date (YYYY-MM-DD), default: latest data")
    parser.add_argument("--stride", type=int, default=3, help="Window stride in days (default: 3)")
    parser.add_argument("--forward", type=int, default=7, help="Forward PnL window in days (default: 7)")
    parser.add_argument("--val-frac", type=float, default=0.2, help="Validation fraction (default: 0.2)")
    parser.add_argument("--test-frac", type=float, default=0.15, help="Test fraction (default: 0.15)")
    args = parser.parse_args()

    print(f"Loading data from {args.data_db}...")
    conn = get_connection(args.data_db)

    # Determine date range from data
    row = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM trade_history").fetchone()
    if row[0] is None:
        print("ERROR: No trade history found in database.")
        sys.exit(1)

    data_start = datetime.fromisoformat(row[0][:19])
    data_end = datetime.fromisoformat(row[1][:19])
    print(f"Trade history range: {data_start.date()} to {data_end.date()}")

    start = datetime.fromisoformat(args.start) if args.start else data_start
    end = datetime.fromisoformat(args.end) if args.end else data_end
    print(f"Using window range: {start.date()} to {end.date()}")

    # Build dataset
    print(f"Building dataset (stride={args.stride}d, forward={args.forward}d)...")
    df = build_dataset(
        conn,
        start=start,
        end=end,
        stride_days=args.stride,
        forward_days=args.forward,
    )
    print(f"Dataset: {len(df)} samples, {df['address'].nunique()} unique traders, "
          f"{df['window_date'].nunique()} windows")

    if len(df) < 100:
        print("WARNING: Very small dataset. Results may be unreliable.")

    # Train
    print("Training XGBoost model...")
    result = train_model(df, val_frac=args.val_frac, test_frac=args.test_frac)

    print(f"\n=== Training Results ===")
    print(f"  Train RMSE:         {result.train_rmse:.6f}")
    print(f"  Validation RMSE:    {result.val_rmse:.6f}")
    print(f"  Test RMSE:          {result.test_rmse:.6f}")
    print(f"  Top-15 backtest PnL: {result.top15_backtest_pnl:+.4f}")

    print(f"\n=== Feature Importances (top 10) ===")
    sorted_imp = sorted(result.feature_importances.items(), key=lambda x: x[1], reverse=True)
    for name, imp in sorted_imp[:10]:
        bar = "#" * int(imp * 100)
        print(f"  {name:25s} {imp:.4f} {bar}")

    # Save
    meta_path = save_model(result, args.output)
    print(f"\nModel saved to: {args.output}")
    print(f"Metadata saved to: {meta_path}")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
