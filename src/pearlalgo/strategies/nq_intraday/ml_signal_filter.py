"""
ML-based Signal Filter (Experimental, Non-Default)

Provides offline-trained machine learning model for signal quality filtering.
This module loads a pre-trained model and applies it as a read-only filter.

Key features:
- Offline training only (no online learning in production)
- Model versioning and pinning for reproducibility
- Graceful fallback when model unavailable
- Detailed logging for auditability

Design constraints:
- EXPERIMENTAL: Must be explicitly enabled via config flag
- NON-DEFAULT: Does not change existing behavior when disabled
- OFFLINE-ONLY: Model is trained separately, loaded read-only
- OPTIONAL DEPS: Requires scikit-learn (install with `pip install pearlalgo[ml]`)

Usage:
    from pearlalgo.strategies.nq_intraday.ml_signal_filter import MLSignalFilter
    
    # Load pre-trained model
    filter = MLSignalFilter(model_path="models/signal_filter_v1.joblib")
    
    # Apply filter to signal
    result = filter.predict(signal)
    if result["should_pass"]:
        ...

Training:
    Use scripts/ml/train_signal_filter.py to train a new model:
    
    python scripts/ml/train_signal_filter.py \\
        --signals-csv reports/backtest_*/signals.csv \\
        --trades-csv reports/backtest_*/trades.csv \\
        --output models/signal_filter_v2.joblib
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.utils.logger import logger

# Try to import ML dependencies
ML_AVAILABLE = False
try:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import joblib
    ML_AVAILABLE = True
except ImportError:
    logger.debug(
        "ML dependencies not available. "
        "Install with: pip install pearlalgo[ml] or pip install scikit-learn joblib"
    )


@dataclass
class MLFilterConfig:
    """Configuration for ML signal filter."""
    
    # Whether the filter is enabled (non-default, must be explicitly set)
    enabled: bool = False
    
    # Path to trained model file (.joblib)
    model_path: Optional[str] = None
    
    # Model version for tracking (should match trained model)
    model_version: str = "v0.0.0"
    
    # Minimum probability threshold to pass filter
    # Model outputs P(win), signal passes if P(win) >= threshold
    min_probability: float = 0.55
    
    # Whether to use model for confidence calibration instead of hard filtering
    # If True, model probability is used to adjust signal confidence
    # If False, model acts as a hard gate
    calibration_mode: bool = False
    
    # Confidence scaling factor when in calibration mode
    # adjusted_confidence = original_confidence * (0.5 + scaling * (p - 0.5))
    calibration_scaling: float = 0.5
    
    # Whether to log detailed predictions
    verbose_logging: bool = False
    
    # Features to extract from signal (if None, uses defaults)
    feature_names: Optional[List[str]] = None


@dataclass
class MLFilterResult:
    """Result of ML filter prediction."""
    
    # Whether signal should pass the filter
    should_pass: bool
    
    # Model's predicted probability of win
    probability: float
    
    # Adjusted confidence (if calibration_mode)
    adjusted_confidence: Optional[float]
    
    # Model version used
    model_version: str
    
    # Reason for decision
    reason: str
    
    # Feature values used for prediction (for debugging)
    features: Optional[Dict[str, float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "should_pass": self.should_pass,
            "probability": round(self.probability, 4),
            "adjusted_confidence": round(self.adjusted_confidence, 4) if self.adjusted_confidence else None,
            "model_version": self.model_version,
            "reason": self.reason,
            "features": self.features,
        }


class MLSignalFilter:
    """
    ML-based signal filter using offline-trained model.
    
    The model is trained on historical backtest data to predict
    probability of a signal resulting in a winning trade.
    
    Training data:
        - Signal features: confidence, regime, volatility, time_of_day, etc.
        - Label: 1 if trade was profitable, 0 otherwise
    
    Model:
        - Logistic regression (simple, interpretable, fast)
        - StandardScaler for feature normalization
        - Trained offline, loaded read-only
    """
    
    # Default feature extraction
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
    
    def __init__(
        self,
        config: Optional[MLFilterConfig] = None,
    ):
        """
        Initialize ML signal filter.
        
        Args:
            config: Filter configuration (uses defaults if not provided)
        """
        self.config = config or MLFilterConfig()
        self.model = None
        self.scaler = None
        self.model_metadata: Dict[str, Any] = {}
        self._loaded = False
        
        if self.config.enabled:
            if not ML_AVAILABLE:
                logger.warning(
                    "MLSignalFilter enabled but ML dependencies not available. "
                    "Install with: pip install pearlalgo[ml]"
                )
            elif self.config.model_path:
                self._load_model()
            else:
                logger.warning("MLSignalFilter enabled but no model_path specified")
        else:
            logger.debug("MLSignalFilter disabled (experimental feature)")
    
    def _load_model(self) -> bool:
        """
        Load trained model from disk.
        
        Returns:
            True if model loaded successfully, False otherwise
        """
        if not ML_AVAILABLE:
            return False
        
        model_path = Path(self.config.model_path)
        if not model_path.exists():
            logger.warning(f"ML model not found: {model_path}")
            return False
        
        try:
            # Load model bundle (model + scaler + metadata)
            bundle = joblib.load(model_path)
            
            if isinstance(bundle, dict):
                self.model = bundle.get("model")
                self.scaler = bundle.get("scaler")
                self.model_metadata = bundle.get("metadata", {})
            else:
                # Legacy format: just the model
                self.model = bundle
                self.scaler = None
                self.model_metadata = {}
            
            self._loaded = True
            
            logger.info(
                f"MLSignalFilter loaded: {model_path}, "
                f"version={self.model_metadata.get('version', 'unknown')}, "
                f"trained={self.model_metadata.get('trained_at', 'unknown')}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"Error loading ML model: {e}")
            return False
    
    def predict(self, signal: Dict[str, Any]) -> MLFilterResult:
        """
        Predict whether signal should pass the filter.
        
        Args:
            signal: Signal dictionary with features
        
        Returns:
            MLFilterResult with prediction and context
        """
        if not self.config.enabled:
            return MLFilterResult(
                should_pass=True,
                probability=0.5,
                adjusted_confidence=None,
                model_version="disabled",
                reason="filter_disabled",
            )
        
        if not ML_AVAILABLE or not self._loaded:
            return MLFilterResult(
                should_pass=True,
                probability=0.5,
                adjusted_confidence=None,
                model_version="unavailable",
                reason="model_not_loaded",
            )
        
        # Extract features
        features = self._extract_features(signal)
        feature_array = self._features_to_array(features)
        
        # Apply scaler if available
        if self.scaler is not None:
            feature_array = self.scaler.transform([feature_array])[0]
        
        # Predict probability
        try:
            proba = self.model.predict_proba([feature_array])[0]
            # proba[1] is probability of class 1 (win)
            p_win = float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception as e:
            logger.warning(f"ML prediction failed: {e}")
            return MLFilterResult(
                should_pass=True,
                probability=0.5,
                adjusted_confidence=None,
                model_version=self.config.model_version,
                reason=f"prediction_error: {e}",
            )
        
        # Apply decision logic
        if self.config.calibration_mode:
            # Calibration mode: adjust confidence, always pass
            original_confidence = signal.get("confidence", 0.5)
            scale = self.config.calibration_scaling
            adjustment = 0.5 + scale * (p_win - 0.5)
            adjusted_confidence = original_confidence * adjustment
            
            should_pass = True
            reason = f"calibration: {original_confidence:.2f} -> {adjusted_confidence:.2f}"
        else:
            # Hard filter mode
            adjusted_confidence = None
            should_pass = p_win >= self.config.min_probability
            reason = f"p_win={p_win:.2%} {'≥' if should_pass else '<'} {self.config.min_probability:.2%}"
        
        result = MLFilterResult(
            should_pass=should_pass,
            probability=p_win,
            adjusted_confidence=adjusted_confidence,
            model_version=self.config.model_version,
            reason=reason,
            features=features if self.config.verbose_logging else None,
        )
        
        if self.config.verbose_logging:
            logger.debug(f"MLFilter: {result.to_dict()}")
        
        return result
    
    def _extract_features(self, signal: Dict[str, Any]) -> Dict[str, float]:
        """
        Extract numerical features from signal dictionary.
        
        Args:
            signal: Signal dictionary
        
        Returns:
            Dictionary of feature name -> float value
        """
        features: Dict[str, float] = {}
        
        # Basic confidence
        features["confidence"] = float(signal.get("confidence", 0.5))
        
        # Regime encoding (one-hot)
        regime = signal.get("regime", {})
        regime_type = regime.get("regime", "ranging")
        features["regime_trending"] = 1.0 if "trending" in regime_type else 0.0
        features["regime_bullish"] = 1.0 if "bullish" in regime_type else 0.0
        
        # Volatility encoding
        volatility = regime.get("volatility", "normal")
        features["volatility_high"] = 1.0 if volatility == "high" else 0.0
        features["volatility_low"] = 1.0 if volatility == "low" else 0.0
        
        # Session encoding
        session = regime.get("session", "")
        features["session_opening"] = 1.0 if session == "opening" else 0.0
        features["session_morning"] = 1.0 if session == "morning_trend" else 0.0
        features["session_lunch"] = 1.0 if session == "lunch_lull" else 0.0
        features["session_afternoon"] = 1.0 if session == "afternoon" else 0.0
        features["session_closing"] = 1.0 if session == "closing" else 0.0
        
        # Indicators
        indicators = signal.get("indicators", {})
        features["rsi"] = float(indicators.get("rsi", 50)) / 100.0  # Normalize to 0-1
        
        # Risk/reward
        entry = float(signal.get("entry_price", 0))
        stop = float(signal.get("stop_loss", 0))
        target = float(signal.get("take_profit", 0))
        if entry > 0 and stop > 0 and target > 0:
            risk = abs(entry - stop)
            reward = abs(target - entry)
            features["risk_reward_ratio"] = reward / risk if risk > 0 else 1.0
        else:
            features["risk_reward_ratio"] = 1.0
        
        # Time features
        timestamp = signal.get("timestamp")
        if timestamp:
            try:
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                else:
                    dt = timestamp
                features["hour_of_day"] = dt.hour / 24.0  # Normalize to 0-1
                features["day_of_week"] = dt.weekday() / 6.0  # Normalize to 0-1
            except Exception:
                features["hour_of_day"] = 0.5
                features["day_of_week"] = 0.5
        else:
            features["hour_of_day"] = 0.5
            features["day_of_week"] = 0.5
        
        return features
    
    def _features_to_array(self, features: Dict[str, float]) -> List[float]:
        """Convert feature dict to ordered array matching training features."""
        feature_names = self.config.feature_names or self.DEFAULT_FEATURES
        return [features.get(name, 0.0) for name in feature_names]
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about loaded model."""
        return {
            "enabled": self.config.enabled,
            "loaded": self._loaded,
            "model_path": self.config.model_path,
            "model_version": self.config.model_version,
            "metadata": self.model_metadata,
            "calibration_mode": self.config.calibration_mode,
            "min_probability": self.config.min_probability,
        }


def create_training_dataset(
    signals_csv_paths: List[Path],
    trades_csv_paths: List[Path],
) -> Tuple[Any, Any, List[str]]:
    """
    Create training dataset from backtest outputs.
    
    Joins signals with trade outcomes to create labeled dataset.
    
    Args:
        signals_csv_paths: List of paths to signals.csv files
        trades_csv_paths: List of paths to trades.csv files
    
    Returns:
        (X, y, feature_names) tuple for sklearn
    """
    if not ML_AVAILABLE:
        raise ImportError("ML dependencies required. Install with: pip install pearlalgo[ml]")
    
    import pandas as pd
    
    # Load all signals
    signals_dfs = []
    for path in signals_csv_paths:
        if path.exists():
            df = pd.read_csv(path)
            signals_dfs.append(df)
    
    if not signals_dfs:
        raise ValueError("No signals data found")
    
    signals_df = pd.concat(signals_dfs, ignore_index=True)
    
    # Load all trades
    trades_dfs = []
    for path in trades_csv_paths:
        if path.exists():
            df = pd.read_csv(path)
            trades_dfs.append(df)
    
    if not trades_dfs:
        raise ValueError("No trades data found")
    
    trades_df = pd.concat(trades_dfs, ignore_index=True)
    
    # Create label: win = pnl > 0
    trades_df["win"] = (trades_df["pnl"] > 0).astype(int)
    
    # Join signals with trade outcomes (by timestamp proximity)
    # This is a simplified join - production would use signal_id
    signals_df["timestamp"] = pd.to_datetime(signals_df["timestamp"])
    trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
    
    # For each trade, find matching signal
    # (within 5 minutes of entry time)
    labeled_data = []
    for _, trade in trades_df.iterrows():
        mask = abs((signals_df["timestamp"] - trade["entry_time"]).dt.total_seconds()) < 300
        matching = signals_df[mask]
        if len(matching) > 0:
            signal = matching.iloc[0].to_dict()
            signal["win"] = trade["win"]
            labeled_data.append(signal)
    
    if not labeled_data:
        raise ValueError("No matching signal-trade pairs found")
    
    labeled_df = pd.DataFrame(labeled_data)
    
    # Extract features
    feature_names = MLSignalFilter.DEFAULT_FEATURES
    X = []
    y = []
    
    filter_instance = MLSignalFilter(MLFilterConfig(enabled=True))
    
    for _, row in labeled_df.iterrows():
        signal_dict = row.to_dict()
        features = filter_instance._extract_features(signal_dict)
        feature_array = filter_instance._features_to_array(features)
        X.append(feature_array)
        y.append(int(row["win"]))
    
    return np.array(X), np.array(y), feature_names


