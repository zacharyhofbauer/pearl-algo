from __future__ import annotations

from pathlib import Path

from pearlalgo.learning.ml_signal_filter import MLFilterConfig, MLSignalFilter


def test_ml_filter_artifact_loads() -> None:
    model_path = Path("models/signal_filter_v1.joblib")
    assert model_path.exists(), "ML model artifact is missing from models/"

    config = MLFilterConfig(model_path=str(model_path))
    ml_filter = MLSignalFilter(config=config)
    assert ml_filter.load_model(str(model_path)) is True
