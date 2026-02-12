"""
Tests for the ML signal filter: configuration, training, prediction,
model persistence, and the SimpleGradientBoosting fallback.

All tests mock external I/O (joblib, model_integrity) so they run
without real model artefacts on disk.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from pearlalgo.learning.ml_signal_filter import (
    MLFilterConfig,
    MLPrediction,
    MLSignalFilter,
    SimpleGradientBoosting,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trades(n: int = 50, win_rate: float = 0.6) -> list:
    """Generate synthetic trade data for training."""
    trades = []
    n_wins = int(n * win_rate)
    for i in range(n):
        is_win = i < n_wins
        trades.append(
            {
                "confidence": 0.7 if is_win else 0.3,
                "risk_reward": 2.5 if is_win else 1.0,
                "atr": 0.012,
                "volatility_ratio": 1.1,
                "volume_ratio": 1.3,
                "rsi": 60.0 if is_win else 40.0,
                "macd_histogram": 0.002 if is_win else -0.002,
                "bb_position": 0.7 if is_win else 0.3,
                "vwap_distance": 0.0005,
                "signal_type": "momentum_long",
                "regime": {
                    "regime": "trending_bullish",
                    "volatility": "normal",
                    "session": "london",
                },
                "exit_time": "2025-01-15T10:00:00Z",
                "is_win": is_win,
            }
        )
    return trades


def _make_signal(confidence: float = 0.65) -> dict:
    """Return a minimal signal dict for prediction."""
    return {
        "signal_id": "sig-1",
        "type": "momentum_long",
        "confidence": confidence,
        "risk_reward": 2.0,
        "atr": 0.01,
        "volatility_ratio": 1.0,
        "volume_ratio": 1.2,
        "rsi": 55.0,
        "macd_histogram": 0.001,
        "bb_position": 0.5,
        "vwap_distance": 0.001,
    }


def _make_context() -> dict:
    """Return a minimal market context dict."""
    return {
        "regime": {
            "regime": "trending_bullish",
            "volatility": "normal",
            "session": "london",
        }
    }


# ==========================================================================
# Configuration
# ==========================================================================


def test_ml_filter_config_defaults():
    """Default MLFilterConfig has sensible values."""
    cfg = MLFilterConfig()
    assert cfg.enabled is True
    assert cfg.mode == "shadow"
    assert 0.0 < cfg.min_probability < 1.0
    assert cfg.min_training_samples >= 1


def test_ml_filter_config_from_dict():
    """MLFilterConfig.from_dict extracts nested ml_filter values."""
    cfg = MLFilterConfig.from_dict(
        {
            "ml_filter": {
                "min_probability": 0.60,
                "mode": "live",
                "n_estimators": 200,
            }
        }
    )
    assert cfg.min_probability == 0.60
    assert cfg.mode == "live"
    assert cfg.n_estimators == 200


def test_ml_filter_config_from_dict_empty():
    """MLFilterConfig.from_dict with empty dict falls back to defaults."""
    cfg = MLFilterConfig.from_dict({})
    assert cfg.enabled is True
    assert cfg.mode == "shadow"


# ==========================================================================
# Readiness and fallback
# ==========================================================================


def test_ml_filter_not_ready_initially():
    """A fresh MLSignalFilter is not ready for predictions."""
    f = MLSignalFilter()
    assert f.is_ready is False


def test_ml_filter_fallback_prediction_when_not_ready():
    """predict_win_probability returns a safe fallback when the model is not trained."""
    f = MLSignalFilter()
    pred = f.predict_win_probability(_make_signal(), _make_context())

    assert isinstance(pred, MLPrediction)
    assert pred.fallback_used is True
    assert pred.pass_filter is True  # default: don't block
    assert pred.win_probability == 0.5


def test_ml_filter_get_stats_before_training():
    """get_stats works even before any training."""
    f = MLSignalFilter()
    stats = f.get_stats()
    assert stats["is_ready"] is False
    assert stats["predictions_made"] == 0


# ==========================================================================
# Training and prediction
# ==========================================================================


def test_ml_filter_train_insufficient_data():
    """Training with too few samples returns insufficient_data status."""
    f = MLSignalFilter(config=MLFilterConfig(min_training_samples=100))
    result = f.train(_make_trades(10))
    assert result["status"] == "insufficient_data"
    assert f.is_ready is False


def test_ml_filter_train_and_predict():
    """Full train-then-predict cycle succeeds with synthetic data."""
    f = MLSignalFilter(
        config=MLFilterConfig(
            min_training_samples=30,
            calibrate_probabilities=False,
        )
    )
    result = f.train(_make_trades(60, win_rate=0.6))
    assert result["status"] == "trained"
    assert f.is_ready is True

    pred = f.predict_win_probability(_make_signal(0.7), _make_context())
    assert not pred.fallback_used
    assert 0.0 <= pred.win_probability <= 1.0
    assert pred.confidence_level in ("low", "medium", "high")


def test_ml_filter_prediction_output_format():
    """MLPrediction.to_dict contains all expected keys."""
    pred = MLPrediction(
        signal_id="s1",
        signal_type="momentum_long",
        win_probability=0.72,
        pass_filter=True,
        confidence_level="high",
        model_version="v1",
    )
    d = pred.to_dict()
    assert d["signal_id"] == "s1"
    assert d["win_probability"] == 0.72
    assert d["pass_filter"] is True
    assert "features_used" in d
    assert "prediction_time_ms" in d


def test_ml_filter_should_execute_integration():
    """should_execute returns (bool, MLPrediction) tuple."""
    f = MLSignalFilter(
        config=MLFilterConfig(
            min_training_samples=30,
            calibrate_probabilities=False,
        )
    )
    f.train(_make_trades(60))

    execute, pred = f.should_execute(_make_signal(), _make_context())
    assert isinstance(pred, MLPrediction)
    # execute may be a numpy bool; compare truthiness rather than strict type
    assert bool(execute) == bool(pred.pass_filter)


# ==========================================================================
# Edge cases
# ==========================================================================


def test_ml_filter_nan_features_handled_in_training():
    """NaN values in trade features are replaced with 0.0 during training."""
    trades = _make_trades(50)
    trades[0]["confidence"] = float("nan")
    trades[1]["rsi"] = float("nan")

    f = MLSignalFilter(
        config=MLFilterConfig(
            min_training_samples=30,
            calibrate_probabilities=False,
        )
    )
    result = f.train(trades)
    assert result["status"] == "trained"


def test_ml_filter_empty_signal_uses_defaults():
    """An empty signal dict still produces a valid prediction (features default to 0)."""
    f = MLSignalFilter(
        config=MLFilterConfig(
            min_training_samples=30,
            calibrate_probabilities=False,
        )
    )
    f.train(_make_trades(50))

    pred = f.predict_win_probability({}, {})
    assert isinstance(pred, MLPrediction)
    assert 0.0 <= pred.win_probability <= 1.0


def test_ml_filter_none_feature_values():
    """Signal features that are explicitly None are coerced to 0.0."""
    f = MLSignalFilter(
        config=MLFilterConfig(
            min_training_samples=30,
            calibrate_probabilities=False,
        )
    )
    f.train(_make_trades(50))

    sig = _make_signal()
    sig["confidence"] = None
    sig["rsi"] = None
    pred = f.predict_win_probability(sig, _make_context())
    assert isinstance(pred, MLPrediction)
    assert not pred.fallback_used


# ==========================================================================
# Model persistence
# ==========================================================================


def test_ml_filter_load_model_missing_file():
    """load_model returns False when the file does not exist."""
    f = MLSignalFilter()
    assert f.load_model("/nonexistent/path/model.joblib") is False
    assert f.is_ready is False


@patch(
    "pearlalgo.utils.model_integrity.verify_model_hash",
    return_value=(False, "hash mismatch"),
)
def test_ml_filter_load_model_integrity_fail(mock_verify, tmp_path):
    """load_model returns False when the integrity check fails."""
    model_file = tmp_path / "model.joblib"
    model_file.write_text("fake")

    f = MLSignalFilter()
    assert f.load_model(str(model_file)) is False
    mock_verify.assert_called_once()


@patch(
    "pearlalgo.utils.model_integrity.verify_model_hash",
    return_value=(True, "ok"),
)
@patch("joblib.load", side_effect=Exception("corrupt pickle"))
def test_ml_filter_load_model_corrupt_data(mock_load, mock_verify, tmp_path):
    """load_model returns False when joblib fails to unpickle."""
    model_file = tmp_path / "model.joblib"
    model_file.write_text("fake")

    f = MLSignalFilter()
    assert f.load_model(str(model_file)) is False


def test_ml_filter_save_model_untrained():
    """save_model returns False if the model has not been trained."""
    f = MLSignalFilter()
    assert f.save_model("/tmp/never_saved.joblib") is False


# ==========================================================================
# SimpleGradientBoosting fallback
# ==========================================================================


def test_simple_gbm_fit_and_predict_returns_valid_probabilities():
    """SimpleGradientBoosting fits and predicts without external ML libs."""
    rng = np.random.RandomState(42)
    X = rng.randn(100, 5)
    y = (X[:, 0] + X[:, 1] > 0).astype(int)

    model = SimpleGradientBoosting(n_estimators=20, learning_rate=0.1)
    model.fit(X, y)
    assert model.is_fitted is True

    proba = model.predict_proba(X)
    assert proba.shape == (100, 2)
    assert np.allclose(proba.sum(axis=1), 1.0)

    preds = model.predict(X)
    assert set(preds).issubset({0, 1})


def test_simple_gbm_predict_raises_value_error_before_fit():
    """predict_proba raises ValueError before fit."""
    model = SimpleGradientBoosting()
    with pytest.raises(ValueError, match="not fitted"):
        model.predict_proba(np.array([[1.0, 2.0, 3.0]]))


def test_simple_gbm_feature_importances_sum_to_one_after_fit():
    """After fitting, feature_importances_ sums to approximately 1."""
    rng = np.random.RandomState(0)
    X = rng.randn(80, 4)
    y = (X[:, 0] > 0).astype(int)

    model = SimpleGradientBoosting(n_estimators=30, learning_rate=0.1)
    model.fit(X, y)
    assert model.feature_importances_ is not None
    assert abs(model.feature_importances_.sum() - 1.0) < 1e-6


# ==========================================================================
# Configuration edge cases
# ==========================================================================


def test_ml_filter_config_mode_normalization():
    """mode is lowercased regardless of input case."""
    cfg = MLFilterConfig.from_dict({"ml_filter": {"mode": "LIVE"}})
    assert cfg.mode == "live"


def test_ml_filter_config_none_mode_defaults_to_shadow():
    """mode=None in config falls back to 'shadow'."""
    cfg = MLFilterConfig.from_dict({"ml_filter": {"mode": None}})
    assert cfg.mode == "shadow"


def test_ml_filter_config_all_fields_from_dict():
    """MLFilterConfig.from_dict applies all recognized fields."""
    cfg = MLFilterConfig.from_dict(
        {
            "ml_filter": {
                "enabled": False,
                "model_version": "v2.0",
                "min_probability": 0.70,
                "high_probability": 0.85,
                "min_training_samples": 100,
                "n_estimators": 200,
                "max_depth": 8,
                "learning_rate": 0.05,
                "mode": "live",
                "adjust_sizing": True,
            }
        }
    )
    assert cfg.enabled is False
    assert cfg.model_version == "v2.0"
    assert cfg.min_probability == 0.70
    assert cfg.high_probability == 0.85
    assert cfg.min_training_samples == 100
    assert cfg.n_estimators == 200
    assert cfg.max_depth == 8
    assert cfg.learning_rate == 0.05
    assert cfg.mode == "live"
    assert cfg.adjust_sizing is True


# ==========================================================================
# Additional prediction and training tests
# ==========================================================================


def test_ml_filter_prediction_counter_increments():
    """Each successful prediction increments the predictions_made counter."""
    f = MLSignalFilter(
        config=MLFilterConfig(min_training_samples=30, calibrate_probabilities=False)
    )
    f.train(_make_trades(50))

    assert f._predictions_made == 0

    f.predict_win_probability(_make_signal(), _make_context())
    assert f._predictions_made == 1

    f.predict_win_probability(_make_signal(0.8), _make_context())
    assert f._predictions_made == 2


def test_ml_filter_get_stats_after_training():
    """get_stats reflects the trained model state."""
    f = MLSignalFilter(
        config=MLFilterConfig(min_training_samples=30, calibrate_probabilities=False)
    )
    f.train(_make_trades(50))

    stats = f.get_stats()
    assert stats["is_ready"] is True
    assert stats["training_samples"] == 50
    assert stats["feature_count"] > 0
    assert stats["last_train_time"] is not None
    assert stats["model_type"] in ("xgboost", "lightgbm", "simple_gbm")


def test_ml_filter_model_type_before_and_after_training():
    """_get_model_type returns 'none' before training, a valid type after."""
    f = MLSignalFilter(
        config=MLFilterConfig(min_training_samples=30, calibrate_probabilities=False)
    )
    assert f._get_model_type() == "none"

    f.train(_make_trades(50))
    assert f._get_model_type() in ("xgboost", "lightgbm", "simple_gbm")


def test_ml_filter_train_returns_validation_metrics():
    """Training with enough samples returns accuracy, precision, and recall."""
    f = MLSignalFilter(
        config=MLFilterConfig(
            min_training_samples=30,
            calibrate_probabilities=False,
            validation_split=0.2,
        )
    )
    result = f.train(_make_trades(60, win_rate=0.6))
    assert result["status"] == "trained"
    assert "val_accuracy" in result
    assert "precision" in result
    assert "recall" in result
    assert 0.0 <= result["val_accuracy"] <= 1.0
    assert "features" in result
    assert "model_type" in result


def test_ml_filter_nan_in_signal_prediction():
    """NaN in signal features during prediction doesn't crash the model."""
    f = MLSignalFilter(
        config=MLFilterConfig(min_training_samples=30, calibrate_probabilities=False)
    )
    f.train(_make_trades(50))

    sig = _make_signal()
    sig["confidence"] = float("nan")
    sig["rsi"] = float("nan")

    pred = f.predict_win_probability(sig, _make_context())
    assert isinstance(pred, MLPrediction)
    # Model handles NaN gracefully — prediction is still valid
    assert isinstance(pred.win_probability, float)


def test_ml_filter_different_signal_types():
    """Predictions work with various signal type values."""
    f = MLSignalFilter(
        config=MLFilterConfig(min_training_samples=30, calibrate_probabilities=False)
    )
    f.train(_make_trades(50))

    for sig_type in ["momentum_long", "mean_reversion_short", "breakout_long"]:
        sig = _make_signal()
        sig["type"] = sig_type
        pred = f.predict_win_probability(sig, _make_context())
        assert isinstance(pred, MLPrediction)
        assert 0.0 <= pred.win_probability <= 1.0


def test_ml_filter_different_regimes():
    """Predictions work with different market regime contexts."""
    f = MLSignalFilter(
        config=MLFilterConfig(min_training_samples=30, calibrate_probabilities=False)
    )
    f.train(_make_trades(50))

    for regime in ["trending_bullish", "trending_bearish", "ranging"]:
        ctx = {"regime": {"regime": regime, "volatility": "normal", "session": "london"}}
        pred = f.predict_win_probability(_make_signal(), ctx)
        assert isinstance(pred, MLPrediction)
        assert 0.0 <= pred.win_probability <= 1.0


# ==========================================================================
# Factory function
# ==========================================================================


def test_get_ml_signal_filter_default():
    """get_ml_signal_filter with no args returns an untrained filter."""
    from pearlalgo.learning.ml_signal_filter import get_ml_signal_filter

    f = get_ml_signal_filter()
    assert isinstance(f, MLSignalFilter)
    assert f.is_ready is False


def test_get_ml_signal_filter_with_config():
    """get_ml_signal_filter applies config dict values."""
    from pearlalgo.learning.ml_signal_filter import get_ml_signal_filter

    f = get_ml_signal_filter(
        config={"ml_filter": {"min_probability": 0.65, "mode": "live"}}
    )
    assert f.config.min_probability == 0.65
    assert f.config.mode == "live"


def test_get_ml_signal_filter_trains_on_trades():
    """get_ml_signal_filter auto-trains when sufficient trades are provided."""
    from pearlalgo.learning.ml_signal_filter import get_ml_signal_filter

    trades = _make_trades(50)
    f = get_ml_signal_filter(
        config={
            "ml_filter": {
                "min_training_samples": 30,
                "calibrate_probabilities": False,
            }
        },
        trades=trades,
    )
    assert f.is_ready is True
