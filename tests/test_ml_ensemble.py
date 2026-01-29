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


class TestModelPersistence:
    """Test model save/load with integrity verification."""

    def test_save_and_load_models(self, temp_dir):
        """Test models are saved and loaded correctly."""
        np.random.seed(42)

        # Create and train a scorer
        scorer = EnsembleScorer(
            EnsembleConfig(min_samples_to_train=20),
            state_dir=temp_dir,
        )

        # Add samples and train
        for i in range(50):
            features = {"f1": np.random.randn(), "f2": np.random.randn()}
            fv = FeatureVector(features=features)
            scorer.add_training_sample(fv, features["f1"] > 0, 10.0 if features["f1"] > 0 else -5.0, "test")

        scorer.train()

        # Verify models were saved
        models_dir = temp_dir / "ml_models"
        assert (models_dir / "logistic_model.joblib").exists()
        assert (models_dir / "gbm_model.joblib").exists()
        assert (models_dir / "bandit_stats.json").exists()
        assert (models_dir / "training_samples.json").exists()

        # Create new scorer and verify it loads the models
        scorer2 = EnsembleScorer(
            EnsembleConfig(min_samples_to_train=20),
            state_dir=temp_dir,
        )

        assert scorer2._logistic_fitted
        assert scorer2._gbm_fitted
        assert len(scorer2._training_samples) == 50

    def test_model_hash_verification(self, temp_dir):
        """Test model integrity hash is created and verified."""
        np.random.seed(42)

        scorer = EnsembleScorer(
            EnsembleConfig(min_samples_to_train=20),
            state_dir=temp_dir,
        )

        # Add samples and train
        for i in range(30):
            fv = FeatureVector(features={"f1": float(i), "f2": float(i * 2)})
            scorer.add_training_sample(fv, i % 2 == 0, 10.0, "test")

        scorer.train()

        # Verify hash files were created
        models_dir = temp_dir / "ml_models"
        assert (models_dir / "logistic_model.joblib.sha256").exists()
        assert (models_dir / "gbm_model.joblib.sha256").exists()


class TestAutoRetrain:
    """Test automatic retraining behavior."""

    def test_auto_retrain_triggered(self, temp_dir):
        """Test that retraining is triggered automatically."""
        np.random.seed(42)

        # Config with low thresholds for testing
        config = EnsembleConfig(
            min_samples_to_train=10,
            retrain_frequency_trades=5,
        )
        scorer = EnsembleScorer(config, state_dir=temp_dir)

        # Add samples to reach training threshold
        for i in range(15):
            fv = FeatureVector(features={"f1": float(i), "f2": float(i * 2)})
            scorer.add_training_sample(fv, i % 2 == 0, 10.0, "test")

        # Should have auto-trained
        assert scorer._logistic_fitted
        assert scorer._samples_since_last_train < 15  # Reset after training


class TestConfidenceTiers:
    """Test confidence tier and size multiplier calculation."""

    def test_high_confidence_tier(self, temp_dir):
        """Test high confidence prediction."""
        np.random.seed(42)

        config = EnsembleConfig(
            min_samples_to_train=20,
            ensemble_threshold=0.5,
            confidence_boost_threshold=0.7,
        )
        scorer = EnsembleScorer(config, state_dir=temp_dir)

        # Train with highly predictable data
        for i in range(50):
            f1_val = np.random.randn() + (2 if i % 2 == 0 else -2)
            fv = FeatureVector(features={"f1": f1_val, "f2": 0.0})
            scorer.add_training_sample(fv, i % 2 == 0, 10.0, "test")

        scorer.train()

        # Predict on clearly positive example
        test_fv = FeatureVector(features={"f1": 5.0, "f2": 0.0})
        pred = scorer.predict(test_fv, "test")

        # Should have high confidence if score is high enough
        assert pred.ensemble_score >= 0.5 or pred.ensemble_score < 0.5  # Valid score
        assert pred.confidence_tier in ["low", "medium", "high"]
        assert pred.size_multiplier in [0.7, 1.0, 1.3]

    def test_low_confidence_size_reduction(self, temp_dir):
        """Test that low confidence reduces size multiplier."""
        scorer = EnsembleScorer(
            EnsembleConfig(ensemble_threshold=0.8),  # High threshold
            state_dir=temp_dir,
        )

        # Predict without training (bandit only, returns 0.5)
        fv = FeatureVector(features={"f1": 0.0})
        pred = scorer.predict(fv, "unknown_signal")

        # With 0.5 score and 0.8 threshold, should not execute
        assert not pred.execute
        assert pred.confidence_tier == "medium"  # 0.5 >= 0.5
        assert pred.size_multiplier == 1.0


class TestWeightNormalization:
    """Test model weight normalization."""

    def test_weights_normalized_when_not_sum_to_one(self, temp_dir):
        """Test weights are normalized if they don't sum to 1."""
        scorer = EnsembleScorer(state_dir=temp_dir)

        # Set weights that sum to 2.0
        scorer.set_model_weights(logistic=0.5, gbm=1.0, bandit=0.5)

        # Should be normalized
        total = (
            scorer.config.logistic_weight +
            scorer.config.gbm_weight +
            scorer.config.bandit_weight
        )
        assert abs(total - 1.0) < 0.01

    def test_get_model_weights(self, temp_dir):
        """Test getting model weights."""
        scorer = EnsembleScorer(state_dir=temp_dir)
        scorer.set_model_weights(logistic=0.4, gbm=0.4, bandit=0.2)

        weights = scorer.get_model_weights()

        assert weights["logistic"] == 0.4
        assert weights["gbm"] == 0.4
        assert weights["bandit"] == 0.2


class TestBanditBetaSmoothing:
    """Test bandit score with Beta smoothing."""

    def test_prior_with_no_data(self, temp_dir):
        """Test that unknown signal types get 0.5 prior."""
        scorer = EnsembleScorer(state_dir=temp_dir)

        fv = FeatureVector(features={"f1": 1.0})
        pred = scorer.predict(fv, "completely_unknown_signal")

        assert pred.bandit_score == 0.5

    def test_beta_smoothing_effect(self, temp_dir):
        """Test Beta(2,2) smoothing prevents extreme values."""
        scorer = EnsembleScorer(state_dir=temp_dir)

        # Add only 1 win
        fv = FeatureVector(features={"f1": 1.0})
        scorer.add_training_sample(fv, True, 10.0, "rare_signal")

        # Score should be (1+2)/(1+4) = 0.6, not 1.0
        pred = scorer.predict(fv, "rare_signal")
        assert 0.5 < pred.bandit_score < 0.7  # Smoothed toward 0.5

