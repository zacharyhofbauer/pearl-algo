"""
ML-Based Signal Quality Filter

Uses machine learning to predict trade success probability.
Filters out signals with low predicted win probability.

Features:
- XGBoost/LightGBM classifier (if available)
- Simple gradient boosting fallback
- Probability calibration
- Online learning support
- Feature extraction from market context
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.utils.logger import logger
from pearlalgo.utils.optional_imports import (
    XGBOOST_AVAILABLE,
    LIGHTGBM_AVAILABLE,
    SKLEARN_AVAILABLE,
    xgb,
    lgb,
    CalibratedClassifierCV,
)

# Import feature engineer if available
try:
    from pearlalgo.learning.feature_engineer import FeatureEngineer, FeatureConfig
    FEATURE_ENGINEER_AVAILABLE = True
except ImportError:
    FEATURE_ENGINEER_AVAILABLE = False
    FeatureEngineer = None  # type: ignore
    FeatureConfig = None  # type: ignore


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class MLFilterConfig:
    """Configuration for ML signal filter."""
    
    enabled: bool = True
    model_path: Optional[str] = None
    model_version: str = "v1.0.0"

    # Operation mode
    # - "shadow": score-only (never blocks signals; logs predictions for lift measurement)
    # - "live": can block signals (subject to optional lift gating)
    mode: str = "shadow"

    # Safety: require demonstrated lift before allowing live blocking.
    # This prevents turning on ML gating before it proves value on your own data.
    require_lift_to_block: bool = True
    lift_lookback_trades: int = 200
    lift_min_trades: int = 50
    lift_min_winrate_delta: float = 0.05  # Require +5% absolute WR lift (pass vs would-block)
    
    # Prediction thresholds
    min_probability: float = 0.55      # Minimum P(win) to pass filter
    high_probability: float = 0.70     # High confidence threshold

    # Optional sizing adjustments (shadow-safe; does not bypass risk gates)
    adjust_sizing: bool = False
    size_multiplier_min: float = 1.0
    size_multiplier_max: float = 1.5
    
    # Training settings
    min_training_samples: int = 30     # Minimum samples to train
    retrain_interval_days: int = 7     # Days between retraining
    validation_split: float = 0.2      # Validation split for training
    
    # Model hyperparameters
    n_estimators: int = 100
    max_depth: int = 6
    learning_rate: float = 0.1
    
    # Calibration
    calibrate_probabilities: bool = True
    calibration_method: str = "isotonic"  # "isotonic" or "sigmoid"
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "MLFilterConfig":
        """Create from dictionary configuration."""
        ml_config = config.get("ml_filter", {})
        
        return cls(
            enabled=ml_config.get("enabled", True),
            model_path=ml_config.get("model_path"),
            model_version=ml_config.get("model_version", "v1.0.0"),
            mode=str(ml_config.get("mode", "shadow") or "shadow").lower(),
            require_lift_to_block=bool(ml_config.get("require_lift_to_block", True)),
            lift_lookback_trades=int(ml_config.get("lift_lookback_trades", 200)),
            lift_min_trades=int(ml_config.get("lift_min_trades", 50)),
            lift_min_winrate_delta=float(ml_config.get("lift_min_winrate_delta", 0.05)),
            min_probability=ml_config.get("min_probability", 0.55),
            high_probability=ml_config.get("high_probability", 0.70),
            adjust_sizing=bool(ml_config.get("adjust_sizing", False)),
            size_multiplier_min=float(ml_config.get("size_multiplier_min", 1.0)),
            size_multiplier_max=float(ml_config.get("size_multiplier_max", 1.5)),
            min_training_samples=ml_config.get("min_training_samples", 30),
            retrain_interval_days=ml_config.get("retrain_interval_days", 7),
            n_estimators=ml_config.get("n_estimators", 100),
            max_depth=ml_config.get("max_depth", 6),
            learning_rate=ml_config.get("learning_rate", 0.1),
            calibrate_probabilities=ml_config.get("calibrate_probabilities", True),
        )


# =============================================================================
# Prediction Result
# =============================================================================

@dataclass
class MLPrediction:
    """Result of ML signal prediction."""
    
    signal_id: str
    signal_type: str
    
    # Prediction
    win_probability: float
    pass_filter: bool
    confidence_level: str  # "low", "medium", "high"
    
    # Metadata
    model_version: str = ""
    features_used: int = 0
    prediction_time_ms: int = 0
    fallback_used: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "win_probability": self.win_probability,
            "pass_filter": self.pass_filter,
            "confidence_level": self.confidence_level,
            "model_version": self.model_version,
            "features_used": self.features_used,
            "prediction_time_ms": self.prediction_time_ms,
            "fallback_used": self.fallback_used,
        }


# =============================================================================
# Simple Gradient Boosting (Fallback)
# =============================================================================

class SimpleGradientBoosting:
    """
    Simple gradient boosting classifier as fallback when XGBoost/LightGBM unavailable.
    Uses decision stumps with gradient descent.
    """
    
    def __init__(
        self,
        n_estimators: int = 50,
        learning_rate: float = 0.1,
        max_depth: int = 1,
    ):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.trees: List[Dict] = []
        self.initial_prediction: float = 0.0
        self.is_fitted: bool = False
        self.feature_importances_: Optional[np.ndarray] = None
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> "SimpleGradientBoosting":
        """Fit the model."""
        n_samples = len(y)
        
        # Initial prediction (log-odds of positive class)
        p = np.clip(np.mean(y), 0.01, 0.99)
        self.initial_prediction = np.log(p / (1 - p))
        
        # Current predictions (log-odds)
        F = np.full(n_samples, self.initial_prediction)
        
        self.trees = []
        feature_importance = np.zeros(X.shape[1])
        
        for _ in range(self.n_estimators):
            # Compute probabilities
            prob = 1 / (1 + np.exp(-F))
            
            # Compute residuals (gradient)
            residuals = y - prob
            
            # Fit a simple decision stump
            best_feature = 0
            best_threshold = 0.0
            best_improvement = -np.inf
            best_left_value = 0.0
            best_right_value = 0.0
            
            for feature_idx in range(X.shape[1]):
                feature_values = X[:, feature_idx]
                
                # Try different thresholds
                unique_values = np.unique(feature_values)
                if len(unique_values) <= 1:
                    continue
                
                thresholds = (unique_values[:-1] + unique_values[1:]) / 2
                
                for threshold in thresholds[:20]:  # Limit for speed
                    left_mask = feature_values <= threshold
                    right_mask = ~left_mask
                    
                    if left_mask.sum() < 2 or right_mask.sum() < 2:
                        continue
                    
                    # Calculate leaf values (Newton step approximation)
                    left_residuals = residuals[left_mask]
                    right_residuals = residuals[right_mask]
                    
                    left_prob = prob[left_mask]
                    right_prob = prob[right_mask]
                    
                    # Hessian approximation
                    left_hessian = np.sum(left_prob * (1 - left_prob)) + 1e-6
                    right_hessian = np.sum(right_prob * (1 - right_prob)) + 1e-6
                    
                    left_value = np.sum(left_residuals) / left_hessian
                    right_value = np.sum(right_residuals) / right_hessian
                    
                    # Calculate improvement
                    improvement = (
                        np.sum(left_residuals) ** 2 / left_hessian +
                        np.sum(right_residuals) ** 2 / right_hessian
                    )
                    
                    if improvement > best_improvement:
                        best_improvement = improvement
                        best_feature = feature_idx
                        best_threshold = threshold
                        best_left_value = left_value
                        best_right_value = right_value
            
            # Store tree
            tree = {
                "feature": best_feature,
                "threshold": best_threshold,
                "left_value": best_left_value,
                "right_value": best_right_value,
            }
            self.trees.append(tree)
            
            # Update predictions
            predictions = np.where(
                X[:, best_feature] <= best_threshold,
                best_left_value,
                best_right_value,
            )
            F += self.learning_rate * predictions
            
            # Track feature importance
            feature_importance[best_feature] += best_improvement
        
        # Normalize feature importance
        if feature_importance.sum() > 0:
            self.feature_importances_ = feature_importance / feature_importance.sum()
        else:
            self.feature_importances_ = np.ones(X.shape[1]) / X.shape[1]
        
        self.is_fitted = True
        return self
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities."""
        if not self.is_fitted:
            raise ValueError("Model not fitted")
        
        n_samples = X.shape[0]
        F = np.full(n_samples, self.initial_prediction)
        
        for tree in self.trees:
            predictions = np.where(
                X[:, tree["feature"]] <= tree["threshold"],
                tree["left_value"],
                tree["right_value"],
            )
            F += self.learning_rate * predictions
        
        # Convert log-odds to probabilities
        prob = 1 / (1 + np.exp(-F))
        
        # Return in sklearn format [P(0), P(1)]
        return np.column_stack([1 - prob, prob])
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict classes."""
        proba = self.predict_proba(X)
        return (proba[:, 1] >= 0.5).astype(int)


# =============================================================================
# ML Signal Filter
# =============================================================================

class MLSignalFilter:
    """
    ML-based signal quality predictor.
    
    Uses historical trade data to train a classifier that predicts
    whether a signal will result in a winning trade.
    """
    
    # Feature names for extraction
    SIGNAL_FEATURES = [
        "confidence",
        "risk_reward",
        "atr",
        "volatility_ratio",
        "volume_ratio",
        "rsi",
        "macd_histogram",
        "bb_position",
        "vwap_distance",
    ]
    
    CONTEXT_FEATURES = [
        "regime_trending_bullish",
        "regime_trending_bearish",
        "regime_ranging",
        "volatility_low",
        "volatility_normal",
        "volatility_high",
        "session_tokyo",
        "session_london",
        "session_new_york",
        "hour_of_day",
        "day_of_week",
    ]
    
    SIGNAL_TYPE_FEATURES = [
        "type_mean_reversion_long",
        "type_mean_reversion_short",
        "type_momentum_long",
        "type_momentum_short",
        "type_sr_bounce_long",
        "type_sr_bounce_short",
        "type_breakout_long",
        "type_breakout_short",
        "type_vwap_reversion",
    ]
    
    def __init__(self, config: Optional[MLFilterConfig] = None):
        """
        Initialize the ML signal filter.
        
        Args:
            config: Filter configuration
        """
        self.config = config or MLFilterConfig()
        
        # Model
        self._model: Any = None
        self._calibrated_model: Any = None
        self._is_fitted: bool = False
        self._feature_names: List[str] = []
        
        # Statistics
        self._training_samples: int = 0
        self._last_train_time: Optional[datetime] = None
        self._predictions_made: int = 0
        self._predictions_correct: int = 0
        
        # Feature engineer
        self._feature_engineer: Any = None
        if FEATURE_ENGINEER_AVAILABLE:
            try:
                self._feature_engineer = FeatureEngineer(FeatureConfig())
            except Exception as e:
                logger.warning(f"Could not initialize FeatureEngineer: {e}")
        
        logger.info(
            f"MLSignalFilter initialized: "
            f"xgboost={'yes' if XGBOOST_AVAILABLE else 'no'}, "
            f"lightgbm={'yes' if LIGHTGBM_AVAILABLE else 'no'}, "
            f"min_prob={self.config.min_probability}"
        )
    
    @property
    def is_ready(self) -> bool:
        """Check if filter is ready for predictions."""
        return self._is_fitted and self._model is not None
    
    def train(
        self,
        trades: List[Dict],
        signals: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Train the model on historical trades.
        
        Args:
            trades: List of completed trade dictionaries
            signals: Optional list of corresponding signals with features
            
        Returns:
            Training metrics dictionary
        """
        if len(trades) < self.config.min_training_samples:
            logger.warning(
                f"Insufficient training data: {len(trades)} < "
                f"{self.config.min_training_samples} required"
            )
            return {"status": "insufficient_data", "samples": len(trades)}
        
        logger.info(f"Training ML filter on {len(trades)} trades...")
        
        # Extract features and labels
        X, y, feature_names = self._extract_features_from_trades(trades)
        
        if X is None or len(X) == 0:
            return {"status": "feature_extraction_failed"}
        
        self._feature_names = feature_names
        
        # Split data
        n_samples = len(X)
        val_size = int(n_samples * self.config.validation_split)
        train_size = n_samples - val_size
        
        indices = np.random.permutation(n_samples)
        train_idx = indices[:train_size]
        val_idx = indices[train_size:]
        
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        
        # Create and train model
        self._model = self._create_model()
        self._model.fit(X_train, y_train)
        
        # Calibrate probabilities if sklearn available
        if self.config.calibrate_probabilities and SKLEARN_AVAILABLE and train_size >= 50:
            try:
                self._calibrated_model = CalibratedClassifierCV(
                    self._model,
                    method=self.config.calibration_method,
                    cv=3,
                )
                self._calibrated_model.fit(X_train, y_train)
            except Exception as e:
                logger.warning(f"Calibration failed: {e}")
                self._calibrated_model = None
        
        self._is_fitted = True
        self._training_samples = len(trades)
        self._last_train_time = datetime.now(timezone.utc)
        
        # Evaluate
        if len(X_val) > 0:
            val_proba = self._predict_proba(X_val)
            val_pred = (val_proba >= 0.5).astype(int)
            
            accuracy = np.mean(val_pred == y_val)
            
            # Calculate metrics by threshold
            tp = np.sum((val_pred == 1) & (y_val == 1))
            fp = np.sum((val_pred == 1) & (y_val == 0))
            fn = np.sum((val_pred == 0) & (y_val == 1))
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            
            metrics = {
                "status": "trained",
                "samples": len(trades),
                "train_size": train_size,
                "val_size": val_size,
                "val_accuracy": float(accuracy),
                "precision": float(precision),
                "recall": float(recall),
                "features": len(feature_names),
                "model_type": self._get_model_type(),
                "calibrated": self._calibrated_model is not None,
            }
        else:
            metrics = {
                "status": "trained_no_validation",
                "samples": len(trades),
                "features": len(feature_names),
            }
        
        logger.info(
            f"ML filter trained: accuracy={metrics.get('val_accuracy', 'N/A'):.2%}, "
            f"precision={metrics.get('precision', 'N/A'):.2%}, "
            f"features={len(feature_names)}"
        )
        
        return metrics
    
    def predict_win_probability(
        self,
        signal: Dict[str, Any],
        context: Dict[str, Any],
    ) -> MLPrediction:
        """
        Predict win probability for a signal.
        
        Args:
            signal: Signal dictionary
            context: Market context dictionary
            
        Returns:
            MLPrediction with probability and filter decision
        """
        import time
        start_time = time.time()
        
        signal_id = signal.get("signal_id", "unknown")
        signal_type = signal.get("type", "unknown")
        
        # Fallback if not ready
        if not self.is_ready:
            return self._create_fallback_prediction(signal_id, signal_type, "model_not_ready")
        
        try:
            # Extract features
            features = self._extract_features_from_signal(signal, context)
            
            if features is None or len(features) == 0:
                return self._create_fallback_prediction(signal_id, signal_type, "feature_extraction_failed")
            
            # Ensure features match training
            X = np.array([features])
            
            # Predict probability
            prob = self._predict_proba(X)[0]
            
            # Determine confidence level
            if prob >= self.config.high_probability:
                confidence_level = "high"
            elif prob >= self.config.min_probability:
                confidence_level = "medium"
            else:
                confidence_level = "low"
            
            # Determine if passes filter
            pass_filter = prob >= self.config.min_probability
            
            prediction_time = int((time.time() - start_time) * 1000)
            
            self._predictions_made += 1
            
            return MLPrediction(
                signal_id=signal_id,
                signal_type=signal_type,
                win_probability=float(prob),
                pass_filter=pass_filter,
                confidence_level=confidence_level,
                model_version=self.config.model_version,
                features_used=len(features),
                prediction_time_ms=prediction_time,
                fallback_used=False,
            )
            
        except Exception as e:
            logger.warning(f"ML prediction failed: {e}")
            return self._create_fallback_prediction(signal_id, signal_type, str(e))
    
    def should_execute(
        self,
        signal: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, MLPrediction]:
        """
        Determine if signal should be executed.
        
        Args:
            signal: Signal dictionary
            context: Market context
            
        Returns:
            Tuple of (should_execute, prediction)
        """
        prediction = self.predict_win_probability(signal, context)
        return prediction.pass_filter, prediction
    
    def _create_model(self) -> Any:
        """Create the appropriate ML model."""
        if XGBOOST_AVAILABLE:
            return xgb.XGBClassifier(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                random_state=42,
                eval_metric="logloss",
                use_label_encoder=False,
            )
        elif LIGHTGBM_AVAILABLE:
            return lgb.LGBMClassifier(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
                random_state=42,
                verbose=-1,
            )
        else:
            return SimpleGradientBoosting(
                n_estimators=self.config.n_estimators,
                max_depth=self.config.max_depth,
                learning_rate=self.config.learning_rate,
            )
    
    def _get_model_type(self) -> str:
        """Get the type of model being used."""
        if self._model is None:
            return "none"
        if XGBOOST_AVAILABLE and hasattr(self._model, "get_booster"):
            return "xgboost"
        elif LIGHTGBM_AVAILABLE and hasattr(self._model, "booster_"):
            return "lightgbm"
        else:
            return "simple_gbm"
    
    def _predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probabilities using the appropriate model.

        NOTE: This may be CPU-bound for large models.  When called from an
        async context, prefer wrapping in ``asyncio.loop.run_in_executor``
        to avoid blocking the event loop.
        """
        if self._calibrated_model is not None:
            proba = self._calibrated_model.predict_proba(X)
        elif self._model is not None:
            proba = self._model.predict_proba(X)
        else:
            raise ValueError("No model available")
        
        return proba[:, 1]  # Return P(win)

    async def should_execute_async(
        self,
        signal: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, "MLPrediction"]:
        """Async version of :meth:`should_execute`.

        Runs the CPU-bound model inference in a thread-pool executor so
        it does not block the async event loop.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.should_execute, signal, context,
        )
    
    def _extract_features_from_trades(
        self,
        trades: List[Dict],
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], List[str]]:
        """Extract features and labels from historical trades."""
        features_list = []
        labels = []
        feature_names: List[str] = []
        
        for trade in trades:
            # Extract features from trade
            features = []
            names = []
            
            # Signal features (from trade metadata)
            for feat_name in self.SIGNAL_FEATURES:
                value = trade.get(feat_name, 0.0)
                if value is None:
                    value = 0.0
                features.append(float(value))
                names.append(feat_name)
            
            # Signal type one-hot encoding
            signal_type = trade.get("signal_type", "")
            for type_feat in self.SIGNAL_TYPE_FEATURES:
                type_name = type_feat.replace("type_", "")
                features.append(1.0 if type_name == signal_type else 0.0)
                names.append(type_feat)
            
            # Context features (if available in trade)
            regime = trade.get("regime", {})
            if isinstance(regime, dict):
                regime_type = regime.get("regime", "")
                volatility = regime.get("volatility", "")
                session = regime.get("session", "")
            else:
                regime_type = ""
                volatility = ""
                session = ""
            
            # Regime one-hot
            features.append(1.0 if regime_type == "trending_bullish" else 0.0)
            names.append("regime_trending_bullish")
            features.append(1.0 if regime_type == "trending_bearish" else 0.0)
            names.append("regime_trending_bearish")
            features.append(1.0 if regime_type == "ranging" else 0.0)
            names.append("regime_ranging")
            
            # Volatility one-hot
            features.append(1.0 if volatility == "low" else 0.0)
            names.append("volatility_low")
            features.append(1.0 if volatility == "normal" else 0.0)
            names.append("volatility_normal")
            features.append(1.0 if volatility == "high" else 0.0)
            names.append("volatility_high")
            
            # Session one-hot
            features.append(1.0 if "tokyo" in session.lower() else 0.0)
            names.append("session_tokyo")
            features.append(1.0 if "london" in session.lower() else 0.0)
            names.append("session_london")
            features.append(1.0 if "york" in session.lower() else 0.0)
            names.append("session_new_york")
            
            # Time features
            exit_time = trade.get("exit_time", "")
            if isinstance(exit_time, str) and exit_time:
                try:
                    dt = datetime.fromisoformat(exit_time.replace("Z", "+00:00"))
                    features.append(float(dt.hour))
                    features.append(float(dt.weekday()))
                except Exception:
                    features.append(12.0)
                    features.append(2.0)
            else:
                features.append(12.0)
                features.append(2.0)
            names.append("hour_of_day")
            names.append("day_of_week")
            
            features_list.append(features)
            labels.append(1 if trade.get("is_win", False) else 0)
            
            if not feature_names:
                feature_names = names
        
        if not features_list:
            return None, None, []
        
        X = np.array(features_list, dtype=np.float32)
        y = np.array(labels, dtype=np.int32)
        
        # Handle NaN/Inf
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        return X, y, feature_names
    
    def _extract_features_from_signal(
        self,
        signal: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[List[float]]:
        """Extract features from a signal for prediction."""
        features = []
        
        # Signal features
        for feat_name in self.SIGNAL_FEATURES:
            value = signal.get(feat_name, 0.0)
            if value is None:
                value = 0.0
            features.append(float(value))
        
        # Signal type one-hot
        signal_type = signal.get("type", "")
        for type_feat in self.SIGNAL_TYPE_FEATURES:
            type_name = type_feat.replace("type_", "")
            features.append(1.0 if type_name == signal_type else 0.0)
        
        # Context features
        regime = context.get("regime", {})
        if isinstance(regime, dict):
            regime_type = regime.get("regime", "")
            volatility = regime.get("volatility", "")
            session = regime.get("session", "")
        else:
            regime_type = ""
            volatility = ""
            session = ""
        
        # Regime one-hot
        features.append(1.0 if regime_type == "trending_bullish" else 0.0)
        features.append(1.0 if regime_type == "trending_bearish" else 0.0)
        features.append(1.0 if regime_type == "ranging" else 0.0)
        
        # Volatility one-hot
        features.append(1.0 if volatility == "low" else 0.0)
        features.append(1.0 if volatility == "normal" else 0.0)
        features.append(1.0 if volatility == "high" else 0.0)
        
        # Session one-hot
        features.append(1.0 if "tokyo" in session.lower() else 0.0)
        features.append(1.0 if "london" in session.lower() else 0.0)
        features.append(1.0 if "york" in session.lower() else 0.0)
        
        # Time features
        now = datetime.now(timezone.utc)
        features.append(float(now.hour))
        features.append(float(now.weekday()))
        
        return features
    
    def _create_fallback_prediction(
        self,
        signal_id: str,
        signal_type: str,
        reason: str,
    ) -> MLPrediction:
        """Create fallback prediction when model unavailable."""
        return MLPrediction(
            signal_id=signal_id,
            signal_type=signal_type,
            win_probability=0.5,  # Neutral probability
            pass_filter=True,     # Default to pass (don't block)
            confidence_level="low",
            model_version=self.config.model_version,
            features_used=0,
            prediction_time_ms=0,
            fallback_used=True,
        )
    
    def save_model(self, path: str) -> bool:
        """
        Save trained model to file using joblib with integrity hash.

        Args:
            path: Path to save model

        Returns:
            True if successful
        """
        if not self.is_ready:
            logger.warning("Cannot save: model not trained")
            return False

        try:
            import joblib
            from pathlib import Path as PathLib
            from pearlalgo.utils.model_integrity import save_model_hash

            model_state = {
                "model": self._model,
                "calibrated_model": self._calibrated_model,
                "feature_names": self._feature_names,
                "config": {
                    "model_version": self.config.model_version,
                    "min_probability": self.config.min_probability,
                },
                "stats": {
                    "training_samples": self._training_samples,
                    "last_train_time": self._last_train_time.isoformat() if self._last_train_time else None,
                },
            }

            joblib.dump(model_state, path)
            save_model_hash(PathLib(path))

            logger.info(f"ML filter model saved to {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save model: {e}")
            return False
    
    def load_model(self, path: str) -> bool:
        """
        Load model from file using joblib with integrity verification.

        Args:
            path: Path to model file

        Returns:
            True if successful
        """
        try:
            import joblib
            from pathlib import Path
            from pearlalgo.utils.model_integrity import verify_model_hash

            model_path = Path(path).resolve()

            if not model_path.exists():
                logger.error(f"Model file not found: {path}")
                return False

            # Verify model integrity before loading
            is_valid, reason = verify_model_hash(model_path)
            if not is_valid:
                logger.error(f"Model integrity check failed: {reason}")
                return False

            model_state = joblib.load(model_path)

            # Validate expected structure
            if not isinstance(model_state, dict):
                logger.error("Invalid model file: expected dictionary structure")
                return False

            expected_keys = {"model"}
            if not expected_keys.issubset(model_state.keys()):
                logger.warning(f"Model file missing expected keys: {expected_keys - model_state.keys()}")

            self._model = model_state.get("model")
            self._calibrated_model = model_state.get("calibrated_model")
            self._feature_names = model_state.get("feature_names", [])
            self._is_fitted = self._model is not None

            stats = model_state.get("stats", {})
            self._training_samples = stats.get("training_samples", 0)

            logger.info(f"ML filter model loaded from {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get filter statistics."""
        return {
            "is_ready": self.is_ready,
            "model_type": self._get_model_type(),
            "training_samples": self._training_samples,
            "last_train_time": self._last_train_time.isoformat() if self._last_train_time else None,
            "predictions_made": self._predictions_made,
            "feature_count": len(self._feature_names),
            "config": {
                "min_probability": self.config.min_probability,
                "model_version": self.config.model_version,
            },
        }


# =============================================================================
# Factory Function
# =============================================================================

def get_ml_signal_filter(
    config: Optional[Dict[str, Any]] = None,
    trades: Optional[List[Dict]] = None,
) -> MLSignalFilter:
    """
    Create an MLSignalFilter from configuration.
    
    Args:
        config: Configuration dictionary
        trades: Optional historical trades for training
        
    Returns:
        MLSignalFilter instance
    """
    if config is None:
        config = {}
    
    filter_config = MLFilterConfig.from_dict(config)
    ml_filter = MLSignalFilter(config=filter_config)
    
    # Try to load existing model
    if filter_config.model_path and os.path.exists(filter_config.model_path):
        ml_filter.load_model(filter_config.model_path)
    
    # Train on provided trades
    if trades and len(trades) >= filter_config.min_training_samples:
        ml_filter.train(trades)
    
    return ml_filter

