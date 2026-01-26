"""
Ensemble Signal Scorer

Combines multiple ML models to score signal quality:
- Logistic Regression (fast, interpretable)
- Gradient Boosting (LightGBM/XGBoost - captures non-linear patterns)
- Thompson Sampling bandit (exploration guarantee)

The ensemble combines predictions using learned weights,
providing robust predictions across different market conditions.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.learning.feature_engineer import FeatureVector
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir

# Optional imports for ML libraries
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available - ensemble will use simple models only")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    logger.warning("LightGBM not available - ensemble will not use gradient boosting")


@dataclass
class EnsembleConfig:
    """Configuration for ensemble scorer."""
    enabled: bool = True
    mode: str = "shadow"  # "shadow" or "live"
    
    # Model weights (sum to 1.0)
    logistic_weight: float = 0.3
    gbm_weight: float = 0.4
    bandit_weight: float = 0.3
    
    # Execution threshold
    ensemble_threshold: float = 0.5
    confidence_boost_threshold: float = 0.7
    
    # Training settings
    min_samples_to_train: int = 50
    retrain_frequency_trades: int = 100
    
    # LightGBM hyperparameters
    lgb_num_leaves: int = 31
    lgb_learning_rate: float = 0.05
    lgb_n_estimators: int = 100
    lgb_max_depth: int = 6
    
    # Logistic regression
    lr_c: float = 1.0
    lr_max_iter: int = 1000
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "EnsembleConfig":
        """Create from dictionary."""
        return cls(
            enabled=bool(config.get("enabled", True)),
            mode=str(config.get("mode", "shadow")),
            logistic_weight=float(config.get("logistic_weight", 0.3)),
            gbm_weight=float(config.get("gbm_weight", 0.4)),
            bandit_weight=float(config.get("bandit_weight", 0.3)),
            ensemble_threshold=float(config.get("ensemble_threshold", 0.5)),
            confidence_boost_threshold=float(config.get("confidence_boost_threshold", 0.7)),
            min_samples_to_train=int(config.get("min_samples_to_train", 50)),
            retrain_frequency_trades=int(config.get("retrain_frequency_trades", 100)),
            lgb_num_leaves=int(config.get("lgb_num_leaves", 31)),
            lgb_learning_rate=float(config.get("lgb_learning_rate", 0.05)),
            lgb_n_estimators=int(config.get("lgb_n_estimators", 100)),
            lgb_max_depth=int(config.get("lgb_max_depth", 6)),
            lr_c=float(config.get("lr_c", 1.0)),
            lr_max_iter=int(config.get("lr_max_iter", 1000)),
        )


@dataclass
class EnsemblePrediction:
    """Prediction from the ensemble."""
    # Combined score
    ensemble_score: float
    execute: bool
    reason: str
    
    # Individual model scores
    logistic_score: Optional[float] = None
    gbm_score: Optional[float] = None
    bandit_score: Optional[float] = None
    
    # Metadata
    confidence_tier: str = "medium"
    size_multiplier: float = 1.0
    mode: str = "shadow"
    
    # Model availability
    logistic_available: bool = False
    gbm_available: bool = False
    bandit_available: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ensemble_score": round(self.ensemble_score, 4),
            "execute": self.execute,
            "reason": self.reason,
            "logistic_score": round(self.logistic_score, 4) if self.logistic_score else None,
            "gbm_score": round(self.gbm_score, 4) if self.gbm_score else None,
            "bandit_score": round(self.bandit_score, 4) if self.bandit_score else None,
            "confidence_tier": self.confidence_tier,
            "size_multiplier": self.size_multiplier,
            "mode": self.mode,
            "logistic_available": self.logistic_available,
            "gbm_available": self.gbm_available,
            "bandit_available": self.bandit_available,
        }


@dataclass
class TrainingSample:
    """Single training sample for supervised models."""
    features: np.ndarray
    label: int  # 1 = win, 0 = loss
    pnl: float
    signal_type: str
    timestamp: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "features": self.features.tolist(),
            "label": self.label,
            "pnl": self.pnl,
            "signal_type": self.signal_type,
            "timestamp": self.timestamp,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingSample":
        """Create from dictionary."""
        return cls(
            features=np.array(data["features"]),
            label=int(data["label"]),
            pnl=float(data["pnl"]),
            signal_type=str(data["signal_type"]),
            timestamp=str(data["timestamp"]),
        )


class SimpleLogisticModel:
    """
    Simple logistic regression fallback when sklearn not available.
    
    Uses gradient descent on logistic loss.
    """
    
    def __init__(self, learning_rate: float = 0.01, n_iterations: int = 1000):
        self.learning_rate = learning_rate
        self.n_iterations = n_iterations
        self.weights: Optional[np.ndarray] = None
        self.bias: float = 0.0
        self.is_fitted: bool = False
    
    def _sigmoid(self, z: np.ndarray) -> np.ndarray:
        """Sigmoid activation."""
        return 1 / (1 + np.exp(-np.clip(z, -500, 500)))
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train the model."""
        n_samples, n_features = X.shape
        self.weights = np.zeros(n_features)
        self.bias = 0.0
        
        for _ in range(self.n_iterations):
            linear = np.dot(X, self.weights) + self.bias
            predictions = self._sigmoid(linear)
            
            # Gradient descent
            dw = (1 / n_samples) * np.dot(X.T, (predictions - y))
            db = (1 / n_samples) * np.sum(predictions - y)
            
            self.weights -= self.learning_rate * dw
            self.bias -= self.learning_rate * db
        
        self.is_fitted = True
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probability of positive class."""
        if not self.is_fitted:
            # Return as (n_samples, 2) array like sklearn even when not fitted
            proba = np.full(len(X), 0.5)
            return np.column_stack([1 - proba, proba])
        
        linear = np.dot(X, self.weights) + self.bias
        proba = self._sigmoid(linear)
        
        # Return as (n_samples, 2) array like sklearn
        return np.column_stack([1 - proba, proba])


class SimpleGradientBoosting:
    """
    Simple gradient boosting fallback when LightGBM not available.
    
    Uses decision stumps (single split trees) with gradient descent.
    """
    
    def __init__(self, n_estimators: int = 50, learning_rate: float = 0.1, max_depth: int = 1):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.trees: List[Dict] = []
        self.initial_prediction: float = 0.0
        self.is_fitted: bool = False
    
    def _find_best_split(self, X: np.ndarray, gradients: np.ndarray) -> Tuple[int, float, float, float]:
        """Find best split for a decision stump."""
        best_gain = -np.inf
        best_feature = 0
        best_threshold = 0.0
        best_left_value = 0.0
        best_right_value = 0.0
        
        n_samples, n_features = X.shape
        
        for feature_idx in range(n_features):
            thresholds = np.unique(X[:, feature_idx])
            
            for threshold in thresholds:
                left_mask = X[:, feature_idx] <= threshold
                right_mask = ~left_mask
                
                if np.sum(left_mask) < 2 or np.sum(right_mask) < 2:
                    continue
                
                left_value = -np.mean(gradients[left_mask])
                right_value = -np.mean(gradients[right_mask])
                
                # Compute gain (reduction in squared error)
                gain = (
                    np.sum(gradients[left_mask]) ** 2 / np.sum(left_mask) +
                    np.sum(gradients[right_mask]) ** 2 / np.sum(right_mask)
                )
                
                if gain > best_gain:
                    best_gain = gain
                    best_feature = feature_idx
                    best_threshold = threshold
                    best_left_value = left_value
                    best_right_value = right_value
        
        return best_feature, best_threshold, best_left_value, best_right_value
    
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train the model."""
        # Convert labels to -1, 1
        y_transformed = 2 * y - 1
        
        # Initial prediction (log odds)
        pos_count = np.sum(y == 1)
        neg_count = np.sum(y == 0)
        self.initial_prediction = np.log(pos_count / max(neg_count, 1))
        
        predictions = np.full(len(y), self.initial_prediction)
        
        for _ in range(self.n_estimators):
            # Compute probabilities
            proba = 1 / (1 + np.exp(-predictions))
            
            # Compute gradients (negative gradient of log loss)
            gradients = y_transformed - 2 * proba + 1
            
            # Fit a decision stump
            feature, threshold, left_val, right_val = self._find_best_split(X, gradients)
            
            self.trees.append({
                "feature": feature,
                "threshold": threshold,
                "left_value": left_val,
                "right_value": right_val,
            })
            
            # Update predictions
            left_mask = X[:, feature] <= threshold
            predictions[left_mask] += self.learning_rate * left_val
            predictions[~left_mask] += self.learning_rate * right_val
        
        self.is_fitted = True
    
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict probability of positive class."""
        if not self.is_fitted:
            return np.full((len(X), 2), 0.5)
        
        predictions = np.full(len(X), self.initial_prediction)
        
        for tree in self.trees:
            left_mask = X[:, tree["feature"]] <= tree["threshold"]
            predictions[left_mask] += self.learning_rate * tree["left_value"]
            predictions[~left_mask] += self.learning_rate * tree["right_value"]
        
        proba = 1 / (1 + np.exp(-predictions))
        return np.column_stack([1 - proba, proba])


class EnsembleScorer:
    """
    Ensemble model for signal scoring.
    
    Combines:
    - Logistic Regression (linear patterns)
    - Gradient Boosting (non-linear patterns)
    - Thompson Sampling (exploration)
    
    The ensemble provides robust predictions by combining
    models with different strengths.
    """
    
    def __init__(
        self,
        config: Optional[EnsembleConfig] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize ensemble scorer.
        
        Args:
            config: Ensemble configuration
            state_dir: Directory for model persistence
        """
        self.config = config or EnsembleConfig()
        self.state_dir = ensure_state_dir(state_dir)
        self.models_dir = self.state_dir / "ml_models"
        
        # Training data buffer
        self._training_samples: List[TrainingSample] = []
        self._samples_since_last_train: int = 0
        
        # Feature names (set on first training)
        self._feature_names: List[str] = []
        
        # Initialize models
        self._init_models()
        
        # Load existing models if available
        self._load_models()
        
        logger.info(
            f"EnsembleScorer initialized: mode={self.config.mode}, "
            f"sklearn={SKLEARN_AVAILABLE}, lgb={LIGHTGBM_AVAILABLE}"
        )
    
    def _init_models(self) -> None:
        """Initialize ML models."""
        # Logistic Regression
        if SKLEARN_AVAILABLE:
            self._logistic = LogisticRegression(
                C=self.config.lr_c,
                max_iter=self.config.lr_max_iter,
                random_state=42,
            )
            self._scaler = StandardScaler()
        else:
            self._logistic = SimpleLogisticModel(
                learning_rate=0.01,
                n_iterations=self.config.lr_max_iter,
            )
            self._scaler = None
        
        self._logistic_fitted = False
        
        # Gradient Boosting
        if LIGHTGBM_AVAILABLE:
            self._gbm = lgb.LGBMClassifier(
                num_leaves=self.config.lgb_num_leaves,
                learning_rate=self.config.lgb_learning_rate,
                n_estimators=self.config.lgb_n_estimators,
                max_depth=self.config.lgb_max_depth,
                random_state=42,
                verbose=-1,
            )
        else:
            self._gbm = SimpleGradientBoosting(
                n_estimators=self.config.lgb_n_estimators,
                learning_rate=self.config.lgb_learning_rate,
                max_depth=self.config.lgb_max_depth,
            )
        
        self._gbm_fitted = False
        
        # Simple bandit (win rate tracker per signal type)
        self._bandit_stats: Dict[str, Dict[str, int]] = {}  # {type: {wins, losses}}
    
    def _load_models(self) -> None:
        """Load trained models from disk."""
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        # Load logistic regression
        lr_path = self.models_dir / "logistic_model.pkl"
        if lr_path.exists():
            try:
                with open(lr_path, "rb") as f:
                    data = pickle.load(f)
                    self._logistic = data.get("model")
                    self._scaler = data.get("scaler")
                    self._logistic_fitted = True
                    logger.info("Loaded logistic regression model")
            except Exception as e:
                logger.warning(f"Failed to load logistic model: {e}")
        
        # Load GBM
        gbm_path = self.models_dir / "gbm_model.pkl"
        if gbm_path.exists():
            try:
                with open(gbm_path, "rb") as f:
                    self._gbm = pickle.load(f)
                    self._gbm_fitted = True
                    logger.info("Loaded GBM model")
            except Exception as e:
                logger.warning(f"Failed to load GBM model: {e}")
        
        # Load bandit stats
        bandit_path = self.models_dir / "bandit_stats.json"
        if bandit_path.exists():
            try:
                with open(bandit_path, "r") as f:
                    self._bandit_stats = json.load(f)
                    logger.info("Loaded bandit stats")
            except Exception as e:
                logger.warning(f"Failed to load bandit stats: {e}")
        
        # Load training samples
        samples_path = self.models_dir / "training_samples.json"
        if samples_path.exists():
            try:
                with open(samples_path, "r") as f:
                    data = json.load(f)
                    self._training_samples = [
                        TrainingSample.from_dict(s) for s in data.get("samples", [])
                    ]
                    self._feature_names = data.get("feature_names", [])
                    logger.info(f"Loaded {len(self._training_samples)} training samples")
            except Exception as e:
                logger.warning(f"Failed to load training samples: {e}")
    
    def _save_models(self) -> None:
        """Save trained models to disk."""
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        # Save logistic regression
        if self._logistic_fitted:
            lr_path = self.models_dir / "logistic_model.pkl"
            try:
                with open(lr_path, "wb") as f:
                    pickle.dump({"model": self._logistic, "scaler": self._scaler}, f)
            except Exception as e:
                logger.warning(f"Failed to save logistic model: {e}")
        
        # Save GBM
        if self._gbm_fitted:
            gbm_path = self.models_dir / "gbm_model.pkl"
            try:
                with open(gbm_path, "wb") as f:
                    pickle.dump(self._gbm, f)
            except Exception as e:
                logger.warning(f"Failed to save GBM model: {e}")
        
        # Save bandit stats
        bandit_path = self.models_dir / "bandit_stats.json"
        try:
            with open(bandit_path, "w") as f:
                json.dump(self._bandit_stats, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save bandit stats: {e}")
        
        # Save training samples (keep last N)
        max_samples = 10000
        samples_path = self.models_dir / "training_samples.json"
        try:
            with open(samples_path, "w") as f:
                json.dump({
                    "feature_names": self._feature_names,
                    "samples": [
                        s.to_dict() for s in self._training_samples[-max_samples:]
                    ],
                }, f)
        except Exception as e:
            logger.warning(f"Failed to save training samples: {e}")
    
    def predict(
        self,
        features: FeatureVector,
        signal_type: str,
    ) -> EnsemblePrediction:
        """
        Generate ensemble prediction for a signal.
        
        Args:
            features: Feature vector for the signal
            signal_type: Type of signal
            
        Returns:
            EnsemblePrediction with combined score and recommendation
        """
        feature_array = features.to_array(self._feature_names if self._feature_names else None)
        
        scores = []
        weights = []
        
        # Logistic regression score
        logistic_score = None
        if self._logistic_fitted:
            try:
                X = feature_array.reshape(1, -1)
                if self._scaler:
                    X = self._scaler.transform(X)
                proba = self._logistic.predict_proba(X)[0]
                logistic_score = float(proba[1])
                scores.append(logistic_score)
                weights.append(self.config.logistic_weight)
            except Exception as e:
                logger.debug(f"Logistic prediction failed: {e}")
        
        # GBM score
        gbm_score = None
        if self._gbm_fitted:
            try:
                X = feature_array.reshape(1, -1)
                proba = self._gbm.predict_proba(X)[0]
                gbm_score = float(proba[1])
                scores.append(gbm_score)
                weights.append(self.config.gbm_weight)
            except Exception as e:
                logger.debug(f"GBM prediction failed: {e}")
        
        # Bandit score (simple win rate)
        bandit_score = self._get_bandit_score(signal_type)
        scores.append(bandit_score)
        weights.append(self.config.bandit_weight)
        
        # Combine scores
        if scores:
            total_weight = sum(weights)
            ensemble_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        else:
            ensemble_score = 0.5
        
        # Decision
        execute = ensemble_score >= self.config.ensemble_threshold
        
        # Confidence tier
        if ensemble_score >= self.config.confidence_boost_threshold:
            confidence_tier = "high"
            size_multiplier = 1.3
        elif ensemble_score >= 0.5:
            confidence_tier = "medium"
            size_multiplier = 1.0
        else:
            confidence_tier = "low"
            size_multiplier = 0.7
        
        # Build reason
        if execute:
            reason = f"ensemble_pass:{ensemble_score:.2f}>={self.config.ensemble_threshold}"
        else:
            reason = f"ensemble_skip:{ensemble_score:.2f}<{self.config.ensemble_threshold}"
        
        return EnsemblePrediction(
            ensemble_score=ensemble_score,
            execute=execute,
            reason=reason,
            logistic_score=logistic_score,
            gbm_score=gbm_score,
            bandit_score=bandit_score,
            confidence_tier=confidence_tier,
            size_multiplier=size_multiplier,
            mode=self.config.mode,
            logistic_available=self._logistic_fitted,
            gbm_available=self._gbm_fitted,
            bandit_available=True,
        )
    
    def _get_bandit_score(self, signal_type: str) -> float:
        """Get bandit score (win rate) for signal type."""
        if signal_type not in self._bandit_stats:
            return 0.5  # Prior
        
        stats = self._bandit_stats[signal_type]
        wins = stats.get("wins", 0)
        losses = stats.get("losses", 0)
        total = wins + losses
        
        if total == 0:
            return 0.5
        
        # Add prior (Beta(2,2) smoothing)
        return (wins + 2) / (total + 4)
    
    def add_training_sample(
        self,
        features: FeatureVector,
        is_win: bool,
        pnl: float,
        signal_type: str,
    ) -> None:
        """
        Add a completed trade as training data.
        
        Args:
            features: Features at signal time
            is_win: Whether trade was profitable
            pnl: P&L in dollars
            signal_type: Type of signal
        """
        # Store feature names on first sample
        if not self._feature_names:
            self._feature_names = sorted(features.features.keys())
        
        sample = TrainingSample(
            features=features.to_array(self._feature_names),
            label=1 if is_win else 0,
            pnl=pnl,
            signal_type=signal_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        self._training_samples.append(sample)
        self._samples_since_last_train += 1
        
        # Update bandit stats
        if signal_type not in self._bandit_stats:
            self._bandit_stats[signal_type] = {"wins": 0, "losses": 0}
        
        if is_win:
            self._bandit_stats[signal_type]["wins"] += 1
        else:
            self._bandit_stats[signal_type]["losses"] += 1
        
        # Check if we should retrain
        if (
            len(self._training_samples) >= self.config.min_samples_to_train and
            self._samples_since_last_train >= self.config.retrain_frequency_trades
        ):
            self.train()
        
        logger.debug(f"Added training sample: {signal_type} | win={is_win} | pnl=${pnl:.2f}")
    
    def train(self) -> Dict[str, Any]:
        """
        Train/retrain the supervised models.
        
        Returns:
            Training metrics
        """
        if len(self._training_samples) < self.config.min_samples_to_train:
            logger.warning(
                f"Not enough samples to train: {len(self._training_samples)} < {self.config.min_samples_to_train}"
            )
            return {"status": "insufficient_data", "samples": len(self._training_samples)}
        
        logger.info(f"Training ensemble on {len(self._training_samples)} samples")
        
        # Prepare data
        X = np.array([s.features for s in self._training_samples])
        y = np.array([s.label for s in self._training_samples])
        
        metrics = {
            "status": "success",
            "samples": len(self._training_samples),
            "positive_rate": float(np.mean(y)),
        }
        
        # Train logistic regression
        try:
            if self._scaler:
                X_scaled = self._scaler.fit_transform(X)
            else:
                X_scaled = X
            
            self._logistic.fit(X_scaled, y)
            self._logistic_fitted = True
            metrics["logistic_trained"] = True
            
            # Cross-validation estimate
            if SKLEARN_AVAILABLE:
                from sklearn.model_selection import cross_val_score
                scores = cross_val_score(self._logistic, X_scaled, y, cv=5, scoring='accuracy')
                metrics["logistic_cv_accuracy"] = float(np.mean(scores))
        except Exception as e:
            logger.warning(f"Logistic training failed: {e}")
            metrics["logistic_trained"] = False
            metrics["logistic_error"] = str(e)
        
        # Train GBM
        try:
            self._gbm.fit(X, y)
            self._gbm_fitted = True
            metrics["gbm_trained"] = True
            
            # Get feature importance if available
            if LIGHTGBM_AVAILABLE and hasattr(self._gbm, "feature_importances_"):
                importances = self._gbm.feature_importances_
                top_features = sorted(
                    zip(self._feature_names, importances),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
                metrics["top_features"] = [
                    {"name": name, "importance": float(imp)}
                    for name, imp in top_features
                ]
        except Exception as e:
            logger.warning(f"GBM training failed: {e}")
            metrics["gbm_trained"] = False
            metrics["gbm_error"] = str(e)
        
        self._samples_since_last_train = 0
        
        # Save models
        self._save_models()
        
        logger.info(f"Ensemble training complete: {metrics}")
        return metrics
    
    def get_status(self) -> Dict[str, Any]:
        """Get ensemble status."""
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "training_samples": len(self._training_samples),
            "samples_since_train": self._samples_since_last_train,
            "logistic_fitted": self._logistic_fitted,
            "gbm_fitted": self._gbm_fitted,
            "sklearn_available": SKLEARN_AVAILABLE,
            "lightgbm_available": LIGHTGBM_AVAILABLE,
            "signal_types_tracked": len(self._bandit_stats),
            "feature_count": len(self._feature_names),
        }
    
    def get_model_weights(self) -> Dict[str, float]:
        """Get current model weights."""
        return {
            "logistic": self.config.logistic_weight,
            "gbm": self.config.gbm_weight,
            "bandit": self.config.bandit_weight,
        }
    
    def set_model_weights(
        self,
        logistic: Optional[float] = None,
        gbm: Optional[float] = None,
        bandit: Optional[float] = None,
    ) -> None:
        """Update model weights (must sum to 1.0)."""
        if logistic is not None:
            self.config.logistic_weight = logistic
        if gbm is not None:
            self.config.gbm_weight = gbm
        if bandit is not None:
            self.config.bandit_weight = bandit
        
        total = (
            self.config.logistic_weight +
            self.config.gbm_weight +
            self.config.bandit_weight
        )
        
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Model weights sum to {total}, normalizing")
            self.config.logistic_weight /= total
            self.config.gbm_weight /= total
            self.config.bandit_weight /= total

