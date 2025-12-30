#!/usr/bin/env python3
"""
Train ML Signal Filter Model

This script trains a logistic regression model to predict signal quality
based on historical backtest data.

Usage:
    # Train from backtest reports
    python scripts/ml/train_signal_filter.py \\
        --signals-dir reports/ \\
        --output models/signal_filter_v1.joblib
    
    # Train with specific files
    python scripts/ml/train_signal_filter.py \\
        --signals-csv reports/backtest_*/signals.csv \\
        --trades-csv reports/backtest_*/trades.csv \\
        --output models/signal_filter_v1.joblib
    
    # Train with walk-forward validation
    python scripts/ml/train_signal_filter.py \\
        --signals-dir reports/ \\
        --output models/signal_filter_v1.joblib \\
        --walk-forward

Output:
    - models/signal_filter_v1.joblib: Trained model bundle (model + scaler + metadata)
    - models/signal_filter_v1_report.json: Training metrics and feature importance

Requirements:
    pip install pearlalgo[ml]  # or: pip install scikit-learn joblib pandas
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Check for ML dependencies
try:
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split, cross_val_score, TimeSeriesSplit
    from sklearn.metrics import (
        accuracy_score,
        precision_score,
        recall_score,
        f1_score,
        roc_auc_score,
        classification_report,
    )
    import joblib
except ImportError as e:
    print(f"Error: ML dependencies not installed. Install with: pip install pearlalgo[ml]")
    print(f"Missing: {e}")
    sys.exit(1)


# Default feature names (must match MLSignalFilter)
DEFAULT_FEATURES = [
    "confidence",
    "regime_trending",
    "regime_bullish",
    "volatility_high",
    "volatility_low",
    "session_opening",
    "session_morning",
    "session_lunch",
    "session_afternoon",
    "session_closing",
    "rsi",
    "risk_reward_ratio",
    "hour_of_day",
    "day_of_week",
]


def find_backtest_files(reports_dir: Path) -> Tuple[List[Path], List[Path]]:
    """Find all signals.csv and trades.csv files in reports directory."""
    signals_files = list(reports_dir.glob("**/signals.csv"))
    trades_files = list(reports_dir.glob("**/trades.csv"))
    return signals_files, trades_files


def load_and_join_data(
    signals_files: List[Path],
    trades_files: List[Path],
) -> pd.DataFrame:
    """Load and join signals with trade outcomes."""
    
    # Load all signals
    signals_dfs = []
    for path in signals_files:
        try:
            df = pd.read_csv(path)
            df["_source_file"] = str(path)
            signals_dfs.append(df)
            print(f"  Loaded {len(df)} signals from {path}")
        except Exception as e:
            print(f"  Warning: Could not load {path}: {e}")
    
    if not signals_dfs:
        raise ValueError("No signals data found")
    
    signals_df = pd.concat(signals_dfs, ignore_index=True)
    print(f"Total signals: {len(signals_df)}")
    
    # Load all trades
    trades_dfs = []
    for path in trades_files:
        try:
            df = pd.read_csv(path)
            df["_source_file"] = str(path)
            trades_dfs.append(df)
            print(f"  Loaded {len(df)} trades from {path}")
        except Exception as e:
            print(f"  Warning: Could not load {path}: {e}")
    
    if not trades_dfs:
        raise ValueError("No trades data found")
    
    trades_df = pd.concat(trades_dfs, ignore_index=True)
    print(f"Total trades: {len(trades_df)}")
    
    # Create label: win = pnl > 0
    trades_df["win"] = (trades_df["pnl"] > 0).astype(int)
    
    # Parse timestamps
    signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"], errors="coerce")
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"], errors="coerce")
    
    # Join signals with trade outcomes by timestamp proximity
    print("Matching signals to trades...")
    labeled_data = []
    
    for _, trade in trades_df.iterrows():
        if pd.isna(trade["entry_time"]):
            continue
        
        # Find signals within 5 minutes of trade entry
        time_diff = abs((signals_df["timestamp"] - trade["entry_time"]).dt.total_seconds())
        mask = time_diff < 300  # 5 minutes
        
        matching = signals_df[mask]
        if len(matching) > 0:
            # Take closest match
            closest_idx = time_diff[mask].idxmin()
            signal = signals_df.loc[closest_idx].to_dict()
            signal["win"] = trade["win"]
            signal["pnl"] = trade["pnl"]
            signal["entry_time"] = trade["entry_time"]
            labeled_data.append(signal)
    
    if not labeled_data:
        raise ValueError("No matching signal-trade pairs found")
    
    labeled_df = pd.DataFrame(labeled_data)
    print(f"Matched pairs: {len(labeled_df)}")
    print(f"Win rate: {labeled_df['win'].mean():.1%}")
    
    return labeled_df


def extract_features(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Extract feature matrix and labels from labeled DataFrame."""
    
    X_list = []
    y_list = []
    
    for _, row in df.iterrows():
        features = {}
        
        # Basic confidence
        features["confidence"] = float(row.get("confidence", 0.5) or 0.5)
        
        # Regime encoding - handle JSON string or dict
        regime = row.get("regime", {})
        if isinstance(regime, str):
            try:
                regime = json.loads(regime)
            except (json.JSONDecodeError, TypeError):
                regime = {}
        
        regime_type = regime.get("regime", "") if isinstance(regime, dict) else ""
        features["regime_trending"] = 1.0 if "trending" in str(regime_type) else 0.0
        features["regime_bullish"] = 1.0 if "bullish" in str(regime_type) else 0.0
        
        # Volatility encoding
        volatility = regime.get("volatility", "normal") if isinstance(regime, dict) else "normal"
        features["volatility_high"] = 1.0 if volatility == "high" else 0.0
        features["volatility_low"] = 1.0 if volatility == "low" else 0.0
        
        # Session encoding
        session = regime.get("session", "") if isinstance(regime, dict) else ""
        features["session_opening"] = 1.0 if session == "opening" else 0.0
        features["session_morning"] = 1.0 if session == "morning_trend" else 0.0
        features["session_lunch"] = 1.0 if session == "lunch_lull" else 0.0
        features["session_afternoon"] = 1.0 if session == "afternoon" else 0.0
        features["session_closing"] = 1.0 if session == "closing" else 0.0
        
        # RSI - handle indicators JSON
        indicators = row.get("indicators", {})
        if isinstance(indicators, str):
            try:
                indicators = json.loads(indicators)
            except (json.JSONDecodeError, TypeError):
                indicators = {}
        
        rsi = indicators.get("rsi", 50) if isinstance(indicators, dict) else 50
        features["rsi"] = float(rsi or 50) / 100.0
        
        # Risk/reward
        entry = float(row.get("entry_price", 0) or 0)
        stop = float(row.get("stop_loss", 0) or 0)
        target = float(row.get("take_profit", 0) or 0)
        if entry > 0 and stop > 0 and target > 0:
            risk = abs(entry - stop)
            reward = abs(target - entry)
            features["risk_reward_ratio"] = reward / risk if risk > 0 else 1.0
        else:
            features["risk_reward_ratio"] = 1.0
        
        # Time features
        entry_time = row.get("entry_time") or row.get("timestamp")
        if pd.notna(entry_time):
            try:
                if isinstance(entry_time, str):
                    dt = pd.to_datetime(entry_time)
                else:
                    dt = entry_time
                features["hour_of_day"] = dt.hour / 24.0
                features["day_of_week"] = dt.weekday() / 6.0
            except Exception:
                features["hour_of_day"] = 0.5
                features["day_of_week"] = 0.5
        else:
            features["hour_of_day"] = 0.5
            features["day_of_week"] = 0.5
        
        # Build feature array in consistent order
        feature_array = [features.get(name, 0.0) for name in DEFAULT_FEATURES]
        X_list.append(feature_array)
        y_list.append(int(row["win"]))
    
    return np.array(X_list), np.array(y_list), DEFAULT_FEATURES


def train_model(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: List[str],
    walk_forward: bool = False,
) -> Tuple[LogisticRegression, StandardScaler, Dict[str, Any]]:
    """Train logistic regression model with optional walk-forward validation."""
    
    print(f"\nTraining on {len(y)} samples...")
    print(f"Class distribution: {np.bincount(y)}")
    
    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Train model
    model = LogisticRegression(
        C=1.0,
        class_weight="balanced",  # Handle class imbalance
        max_iter=1000,
        random_state=42,
    )
    
    # Evaluate with cross-validation
    if walk_forward:
        # Time series split (respects temporal order)
        print("Using walk-forward (time series) cross-validation...")
        cv = TimeSeriesSplit(n_splits=5)
    else:
        # Standard k-fold
        cv = 5
    
    cv_scores = cross_val_score(model, X_scaled, y, cv=cv, scoring="roc_auc")
    print(f"Cross-validation ROC-AUC: {cv_scores.mean():.3f} (+/- {cv_scores.std():.3f})")
    
    # Final fit on all data
    model.fit(X_scaled, y)
    
    # Compute metrics
    y_pred = model.predict(X_scaled)
    y_proba = model.predict_proba(X_scaled)[:, 1]
    
    metrics = {
        "accuracy": float(accuracy_score(y, y_pred)),
        "precision": float(precision_score(y, y_pred, zero_division=0)),
        "recall": float(recall_score(y, y_pred, zero_division=0)),
        "f1": float(f1_score(y, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y, y_proba)),
        "cv_roc_auc_mean": float(cv_scores.mean()),
        "cv_roc_auc_std": float(cv_scores.std()),
    }
    
    # Feature importance (coefficients)
    feature_importance = dict(zip(feature_names, model.coef_[0].tolist()))
    
    print(f"\nTraining Metrics:")
    print(f"  Accuracy:  {metrics['accuracy']:.3f}")
    print(f"  Precision: {metrics['precision']:.3f}")
    print(f"  Recall:    {metrics['recall']:.3f}")
    print(f"  F1:        {metrics['f1']:.3f}")
    print(f"  ROC-AUC:   {metrics['roc_auc']:.3f}")
    
    print(f"\nFeature Importance (coefficients):")
    for name, coef in sorted(feature_importance.items(), key=lambda x: abs(x[1]), reverse=True):
        print(f"  {name}: {coef:+.3f}")
    
    return model, scaler, {"metrics": metrics, "feature_importance": feature_importance}


def save_model(
    model: LogisticRegression,
    scaler: StandardScaler,
    feature_names: List[str],
    metrics: Dict[str, Any],
    output_path: Path,
    version: str,
) -> None:
    """Save model bundle to disk."""
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create bundle
    bundle = {
        "model": model,
        "scaler": scaler,
        "metadata": {
            "version": version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "feature_names": feature_names,
            "n_features": len(feature_names),
            "metrics": metrics.get("metrics", {}),
            "feature_importance": metrics.get("feature_importance", {}),
        },
    }
    
    # Save model
    joblib.dump(bundle, output_path)
    print(f"\nModel saved to: {output_path}")
    
    # Save report
    report_path = output_path.with_suffix(".json").with_name(
        output_path.stem + "_report.json"
    )
    with open(report_path, "w") as f:
        json.dump(bundle["metadata"], f, indent=2)
    print(f"Report saved to: {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train ML signal filter model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--signals-dir",
        type=Path,
        help="Directory to search for signals.csv and trades.csv files",
    )
    parser.add_argument(
        "--signals-csv",
        nargs="+",
        type=str,
        help="Glob pattern(s) for signals CSV files",
    )
    parser.add_argument(
        "--trades-csv",
        nargs="+",
        type=str,
        help="Glob pattern(s) for trades CSV files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("models/signal_filter.joblib"),
        help="Output path for trained model",
    )
    parser.add_argument(
        "--version",
        type=str,
        default="v1.0.0",
        help="Model version string",
    )
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Use walk-forward (time series) cross-validation",
    )
    
    args = parser.parse_args()
    
    # Find data files
    signals_files: List[Path] = []
    trades_files: List[Path] = []
    
    if args.signals_dir:
        s, t = find_backtest_files(args.signals_dir)
        signals_files.extend(s)
        trades_files.extend(t)
    
    if args.signals_csv:
        for pattern in args.signals_csv:
            signals_files.extend(Path(p) for p in glob.glob(pattern))
    
    if args.trades_csv:
        for pattern in args.trades_csv:
            trades_files.extend(Path(p) for p in glob.glob(pattern))
    
    if not signals_files or not trades_files:
        print("Error: No data files found. Specify --signals-dir or --signals-csv/--trades-csv")
        return 1
    
    print(f"Found {len(signals_files)} signals files and {len(trades_files)} trades files")
    
    try:
        # Load and prepare data
        print("\nLoading data...")
        labeled_df = load_and_join_data(signals_files, trades_files)
        
        # Extract features
        print("\nExtracting features...")
        X, y, feature_names = extract_features(labeled_df)
        
        # Train model
        model, scaler, metrics = train_model(
            X, y, feature_names,
            walk_forward=args.walk_forward,
        )
        
        # Save model
        save_model(
            model, scaler, feature_names, metrics,
            args.output, args.version,
        )
        
        return 0
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())


