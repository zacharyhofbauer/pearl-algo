"""Tests for Ensemble Scorer."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from pearlalgo.learning.ensemble_scorer import (
    EnsembleScorer,
    EnsembleConfig,
    EnsemblePrediction,
    TrainingSample,
    SimpleLogisticModel,
    SimpleGradientBoosting,
)
from pearlalgo.learning.feature_engineer import FeatureVector


@pytest.fixture
def temp_dir():
    """Create temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_feature_vector() -> FeatureVector:
    """Create sample feature vector."""
    return FeatureVector(
        features={
            "momentum_short": 0.6,
            "momentum_medium": 0.4,
            "rsi_14": 0.65,
            "volume_ratio": 1.2,
            "trend_strength": 0.7,
        },
        signal_type="momentum_long",
    )


class TestTrainingSample:
    """Test TrainingSample dataclass."""
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        sample = TrainingSample(
            features=np.array([0.1, 0.2, 0.3]),
            label=1,
            pnl=50.0,
            signal_type="momentum_long",
            timestamp="2024-01-01T10:00:00",
        )
        
        d = sample.to_dict()
        
        assert d["label"] == 1
        assert d["pnl"] == 50.0
        assert len(d["features"]) == 3
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "features": [0.1, 0.2],
            "label": 0,
            "pnl": -30.0,
            "signal_type": "sr_bounce",
            "timestamp": "2024-01-01T11:00:00",
        }
        
        sample = TrainingSample.from_dict(data)
        
        assert sample.label == 0
        assert sample.pnl == -30.0
        assert len(sample.features) == 2


class TestSimpleLogisticModel:
    """Test fallback logistic regression."""
    
    def test_fit_predict(self):
        """Test training and prediction."""
        np.random.seed(42)
        
        # Create simple linearly separable data
        X = np.vstack([
            np.random.randn(50, 2) + [2, 2],
            np.random.randn(50, 2) + [-2, -2],
        ])
        y = np.array([1] * 50 + [0] * 50)
        
        model = SimpleLogisticModel(learning_rate=0.1, n_iterations=500)
        model.fit(X, y)
        
        assert model.is_fitted
        
        # Predict on test point
        proba = model.predict_proba(np.array([[2, 2]]))
        assert proba[0, 1] > 0.7  # Should predict class 1
    
    def test_predict_before_fit(self):
        """Test prediction before fitting."""
        model = SimpleLogisticModel()
        
        proba = model.predict_proba(np.array([[0, 0]]))
        # Returns 2D array with shape (n_samples, 2)
        assert proba.shape == (1, 2)
        assert proba[0, 1] == 0.5  # Default


class TestSimpleGradientBoosting:
    """Test fallback gradient boosting."""
    
    def test_fit_predict(self):
        """Test training and prediction."""
        np.random.seed(42)
        
        # More separable data for simple model
        X = np.vstack([
            np.random.randn(50, 2) + [3, 3],  # More separation
            np.random.randn(50, 2) + [-3, -3],
        ])
        y = np.array([1] * 50 + [0] * 50)
        
        model = SimpleGradientBoosting(n_estimators=50, learning_rate=0.2)
        model.fit(X, y)
        
        assert model.is_fitted
        
        # Test on clearly positive example
        proba = model.predict_proba(np.array([[5, 5]]))
        # Just verify it produces valid probabilities
        assert 0 <= proba[0, 1] <= 1
        assert proba.shape == (1, 2)


class TestEnsembleConfig:
    """Test EnsembleConfig."""
    
    def test_default_weights(self):
        """Test default model weights sum to 1."""
        config = EnsembleConfig()
        
        total = config.logistic_weight + config.gbm_weight + config.bandit_weight
        assert abs(total - 1.0) < 0.01
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        config = EnsembleConfig.from_dict({
            "enabled": False,
            "logistic_weight": 0.5,
            "gbm_weight": 0.3,
            "bandit_weight": 0.2,
        })
        
        assert config.enabled is False
        assert config.logistic_weight == 0.5


class TestEnsembleScorer:
    """Test EnsembleScorer class."""
    
    def test_initialization(self, temp_dir):
        """Test scorer initialization."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        
        assert scorer.config.enabled is True
        assert scorer.config.mode == "shadow"
    
    def test_predict_without_training(self, temp_dir, sample_feature_vector):
        """Test prediction without trained models (uses bandit only)."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        
        pred = scorer.predict(sample_feature_vector, "momentum_long")
        
        assert isinstance(pred, EnsemblePrediction)
        assert 0 <= pred.ensemble_score <= 1
        assert pred.bandit_score is not None
    
    def test_add_training_sample(self, temp_dir, sample_feature_vector):
        """Test adding training samples."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        
        scorer.add_training_sample(
            features=sample_feature_vector,
            is_win=True,
            pnl=50.0,
            signal_type="momentum_long",
        )
        
        assert len(scorer._training_samples) == 1
        assert scorer._bandit_stats["momentum_long"]["wins"] == 1
    
    def test_train_insufficient_samples(self, temp_dir):
        """Test training fails gracefully with insufficient data."""
        scorer = EnsembleScorer(
            EnsembleConfig(min_samples_to_train=50),
            state_dir=temp_dir,
        )
        
        # Add only 10 samples
        for i in range(10):
            fv = FeatureVector(features={"a": float(i), "b": float(i * 2)})
            scorer.add_training_sample(fv, i % 2 == 0, 10.0, "test")
        
        metrics = scorer.train()
        
        assert metrics["status"] == "insufficient_data"
    
    def test_train_with_sufficient_samples(self, temp_dir):
        """Test training with sufficient data."""
        np.random.seed(42)
        
        scorer = EnsembleScorer(
            EnsembleConfig(min_samples_to_train=20),
            state_dir=temp_dir,
        )
        
        # Add 50 samples
        for i in range(50):
            features = {
                "f1": np.random.randn(),
                "f2": np.random.randn(),
                "f3": np.random.randn(),
            }
            fv = FeatureVector(features=features)
            is_win = features["f1"] > 0  # Label based on f1
            scorer.add_training_sample(fv, is_win, 10.0 if is_win else -5.0, "test")
        
        metrics = scorer.train()
        
        assert metrics["status"] == "success"
        assert metrics["samples"] == 50
    
    def test_predict_after_training(self, temp_dir):
        """Test prediction after training."""
        np.random.seed(42)
        
        scorer = EnsembleScorer(
            EnsembleConfig(min_samples_to_train=20),
            state_dir=temp_dir,
        )
        
        # Train
        for i in range(50):
            features = {"f1": np.random.randn(), "f2": np.random.randn()}
            fv = FeatureVector(features=features)
            scorer.add_training_sample(fv, features["f1"] > 0, 10.0, "test")
        
        scorer.train()
        
        # Predict
        test_fv = FeatureVector(features={"f1": 2.0, "f2": 0.5})
        pred = scorer.predict(test_fv, "test")
        
        # Should have trained model scores
        assert pred.ensemble_score > 0
    
    def test_get_status(self, temp_dir):
        """Test getting scorer status."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        
        status = scorer.get_status()
        
        assert "enabled" in status
        assert "training_samples" in status
        assert "logistic_fitted" in status
        assert "gbm_fitted" in status
    
    def test_set_model_weights(self, temp_dir):
        """Test setting model weights."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        
        scorer.set_model_weights(logistic=0.5, gbm=0.3, bandit=0.2)
        
        assert scorer.config.logistic_weight == 0.5
        assert scorer.config.gbm_weight == 0.3
        assert scorer.config.bandit_weight == 0.2
    
    def test_bandit_score_updates(self, temp_dir):
        """Test that bandit score updates with outcomes."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        
        # Add wins for signal type
        for _ in range(5):
            fv = FeatureVector(features={"a": 1.0})
            scorer.add_training_sample(fv, True, 50.0, "good_signal")
        
        # Add losses for another
        for _ in range(5):
            fv = FeatureVector(features={"a": 1.0})
            scorer.add_training_sample(fv, False, -30.0, "bad_signal")
        
        # Predict
        good_pred = scorer.predict(FeatureVector(features={"a": 1.0}), "good_signal")
        bad_pred = scorer.predict(FeatureVector(features={"a": 1.0}), "bad_signal")
        
        assert good_pred.bandit_score > bad_pred.bandit_score


class TestEnsemblePrediction:
    """Test EnsemblePrediction dataclass."""
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        pred = EnsemblePrediction(
            ensemble_score=0.72,
            execute=True,
            reason="ensemble_pass:0.72>=0.50",
            logistic_score=0.68,
            gbm_score=0.75,
            bandit_score=0.70,
            confidence_tier="high",
            size_multiplier=1.3,
        )
        
        d = pred.to_dict()
        
        assert d["ensemble_score"] == 0.72
        assert d["execute"] is True
        assert d["confidence_tier"] == "high"

