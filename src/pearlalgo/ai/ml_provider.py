"""
ML Provider - Custom ML model provider for signal scoring and predictions.

Wraps the existing ML signal filter and provides a unified interface for
ML-based predictions in the AI provider framework.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from pearlalgo.ai.base import (
    AIProvider,
    AIProviderAPIError,
    AIProviderNotAvailableError,
)
from pearlalgo.ai.types import (
    AIMessage,
    AIResponse,
    CompletionConfig,
    StreamChunk,
)
from pearlalgo.utils.logger import logger


# Try to import ML dependencies
try:
    import joblib
    import numpy as np
    ML_AVAILABLE = True
except ImportError:
    joblib = None  # type: ignore
    np = None  # type: ignore
    ML_AVAILABLE = False


DEFAULT_MODEL_PATH = "models/signal_filter_v1.joblib"


class MLProvider(AIProvider):
    """
    Custom ML model provider for signal scoring.
    
    This provider wraps trained ML models (XGBoost, LightGBM, etc.)
    and exposes them through the unified AI provider interface.
    
    Unlike LLM providers, this doesn't do text generation - instead
    it performs structured predictions on feature vectors.
    
    Usage:
        provider = MLProvider()
        
        # For signal scoring, pass features as JSON in the message
        response = await provider.complete([
            AIMessage.user(json.dumps({
                "task": "score_signal",
                "features": {
                    "confidence": 0.72,
                    "risk_reward": 2.3,
                    "rsi": 58.2,
                    "volume_ratio": 1.2,
                    ...
                }
            }))
        ])
        
        # Response content contains the prediction
        result = json.loads(response.content)
        print(result["probability"])  # 0.68
        print(result["recommendation"])  # "ALLOW" or "BLOCK"
    """
    
    def __init__(
        self,
        model_path: Optional[str] = None,
        threshold: float = 0.55,
    ):
        """
        Initialize ML provider.
        
        Args:
            model_path: Path to the trained model file (.joblib)
            threshold: Probability threshold for ALLOW/BLOCK decisions
        """
        if not ML_AVAILABLE:
            raise AIProviderNotAvailableError(
                "ML dependencies not installed. Install with: pip install scikit-learn joblib"
            )
        
        self._model_path = model_path or os.getenv("ML_MODEL_PATH", DEFAULT_MODEL_PATH)
        self._threshold = threshold
        self._model = None
        self._feature_names: list[str] = []
        
        # Try to load the model
        self._load_model()
        
        logger.info(
            "ML provider initialized",
            extra={"model_path": self._model_path, "threshold": self._threshold}
        )
    
    def _load_model(self) -> None:
        """Load the trained model from disk."""
        model_path = Path(self._model_path)
        
        if not model_path.exists():
            logger.warning(f"ML model not found at {model_path}")
            return
        
        try:
            data = joblib.load(model_path)
            
            if isinstance(data, dict):
                self._model = data.get("model")
                self._feature_names = data.get("feature_names", [])
            else:
                self._model = data
            
            logger.info(f"ML model loaded from {model_path}")
        
        except Exception as e:
            logger.error(f"Failed to load ML model: {e}")
    
    @property
    def name(self) -> str:
        return "ml"
    
    @property
    def default_model(self) -> str:
        return self._model_path
    
    def supports_thinking(self) -> bool:
        return False
    
    def supports_tools(self) -> bool:
        return False
    
    def supports_streaming(self) -> bool:
        return False  # ML predictions are instant
    
    def is_available(self) -> bool:
        """Check if the ML model is loaded and ready."""
        return self._model is not None
    
    async def complete(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AIResponse:
        """
        Generate a prediction based on the input features.
        
        The last user message should contain JSON with:
        - task: "score_signal" (currently the only supported task)
        - features: dict of feature name -> value
        """
        import json
        
        if not self._model:
            raise AIProviderNotAvailableError("ML model not loaded")
        
        # Get the last user message
        user_message = None
        for msg in reversed(messages):
            if msg.role.value == "user":
                user_message = msg.content
                break
        
        if not user_message:
            raise AIProviderAPIError("No user message with features provided")
        
        try:
            request = json.loads(user_message)
        except json.JSONDecodeError as e:
            raise AIProviderAPIError("User message must be valid JSON") from e
        
        task = request.get("task", "score_signal")
        features = request.get("features", {})
        
        if task == "score_signal":
            result = self._score_signal(features)
        else:
            raise AIProviderAPIError(f"Unknown task: {task}")
        
        return AIResponse(
            content=json.dumps(result),
            thinking_blocks=[],
            tool_calls=[],
            provider=self.name,
            model=self._model_path,
            finish_reason="stop",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )
    
    def _score_signal(self, features: dict[str, Any]) -> dict[str, Any]:
        """
        Score a trading signal using the ML model.
        
        Args:
            features: Dictionary of feature name -> value
            
        Returns:
            Dictionary with probability, recommendation, and feature importance
        """
        # Build feature vector
        if self._feature_names:
            feature_vector = [features.get(name, 0.0) for name in self._feature_names]
        else:
            # Use all provided features in order
            feature_vector = list(features.values())
        
        X = np.array([feature_vector])
        
        # Get prediction
        try:
            if hasattr(self._model, "predict_proba"):
                probas = self._model.predict_proba(X)
                probability = float(probas[0][1])  # Probability of positive class
            else:
                prediction = self._model.predict(X)
                probability = float(prediction[0])
        except Exception as e:
            logger.error(f"ML prediction failed: {e}")
            # Return neutral prediction on error
            return {
                "probability": 0.5,
                "recommendation": "UNKNOWN",
                "confidence": 0.0,
                "error": str(e),
            }
        
        # Determine recommendation
        if probability >= self._threshold:
            recommendation = "ALLOW"
        else:
            recommendation = "BLOCK"
        
        # Calculate confidence (distance from threshold)
        confidence = abs(probability - self._threshold) / (1 - self._threshold)
        
        # Get feature importance if available
        feature_importance = {}
        if hasattr(self._model, "feature_importances_") and self._feature_names:
            importances = self._model.feature_importances_
            for i, name in enumerate(self._feature_names):
                if i < len(importances):
                    feature_importance[name] = float(importances[i])
        
        return {
            "probability": probability,
            "recommendation": recommendation,
            "confidence": confidence,
            "threshold": self._threshold,
            "feature_importance": feature_importance,
        }
    
    async def stream(
        self,
        messages: list[AIMessage],
        config: Optional[CompletionConfig] = None,
    ) -> AsyncIterator[StreamChunk]:
        """ML predictions don't support streaming."""
        response = await self.complete(messages, config)
        yield StreamChunk(content=response.content, is_final=True)
    
    async def health_check(self) -> bool:
        """Check if the ML model is loaded."""
        return self._model is not None


def get_ml_provider() -> Optional[MLProvider]:
    """
    Factory function to get an ML provider instance.
    
    Returns:
        MLProvider if available, None otherwise.
    """
    if not ML_AVAILABLE:
        logger.debug("ML provider not available: dependencies not installed")
        return None
    
    try:
        provider = MLProvider()
        if not provider.is_available():
            logger.debug("ML provider not available: model not loaded")
            return None
        return provider
    except AIProviderNotAvailableError as e:
        logger.debug(f"Could not initialize ML provider: {e}")
        return None
