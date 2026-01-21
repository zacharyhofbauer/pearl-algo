"""
Regime-Aware Adaptive Trading

Detects market regimes and adapts trading parameters accordingly.

Regimes:
- trending_bullish: Strong uptrend, favor long momentum
- trending_bearish: Strong downtrend, favor short momentum  
- ranging: Sideways, favor mean reversion
- volatile: High volatility, reduce size, widen stops
- quiet: Low volatility, may skip trading

Uses Hidden Markov Model (HMM) or simpler heuristics for regime detection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir

# Optional HMM library
try:
    from hmmlearn import hmm
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn not available - using heuristic regime detection")


@dataclass
class RegimeConfig:
    """Configuration for regime detection and adaptation."""
    enabled: bool = True
    
    # Detection method
    use_hmm: bool = True  # Use HMM if available, else heuristics
    hmm_n_states: int = 4  # Number of hidden states
    hmm_covariance_type: str = "diag"
    
    # Heuristic thresholds
    trend_threshold: float = 0.002  # % change for trend
    volatility_high_percentile: float = 0.75
    volatility_low_percentile: float = 0.25
    
    # Lookback windows
    short_window: int = 5
    medium_window: int = 20
    long_window: int = 50
    
    # Update frequency
    update_bars: int = 5  # Update regime every N bars
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "RegimeConfig":
        """Create from dictionary."""
        return cls(
            enabled=bool(config.get("enabled", True)),
            use_hmm=bool(config.get("use_hmm", True)),
            hmm_n_states=int(config.get("hmm_n_states", 4)),
            hmm_covariance_type=str(config.get("hmm_covariance_type", "diag")),
            trend_threshold=float(config.get("trend_threshold", 0.002)),
            volatility_high_percentile=float(config.get("volatility_high_percentile", 0.75)),
            volatility_low_percentile=float(config.get("volatility_low_percentile", 0.25)),
            short_window=int(config.get("short_window", 5)),
            medium_window=int(config.get("medium_window", 20)),
            long_window=int(config.get("long_window", 50)),
            update_bars=int(config.get("update_bars", 5)),
        )


@dataclass
class RegimeParameters:
    """
    Trading parameters adapted for a specific regime.
    
    These override default strategy parameters when the regime is active.
    """
    regime: str
    
    # Signal generation adjustments
    confidence_threshold: float = 0.65
    min_rr_ratio: float = 1.5
    
    # Position sizing
    size_multiplier: float = 1.0
    max_positions: int = 1
    
    # Risk management
    stop_loss_multiplier: float = 1.0  # Multiply default SL distance
    take_profit_multiplier: float = 1.0  # Multiply default TP distance
    
    # Signal type preferences (boost or penalize)
    signal_type_boosts: Dict[str, float] = field(default_factory=dict)
    
    # Time restrictions (optional)
    allowed_hours: Optional[List[int]] = None  # None = all hours
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "regime": self.regime,
            "confidence_threshold": self.confidence_threshold,
            "min_rr_ratio": self.min_rr_ratio,
            "size_multiplier": self.size_multiplier,
            "max_positions": self.max_positions,
            "stop_loss_multiplier": self.stop_loss_multiplier,
            "take_profit_multiplier": self.take_profit_multiplier,
            "signal_type_boosts": self.signal_type_boosts,
            "allowed_hours": self.allowed_hours,
        }


# Default regime parameters
DEFAULT_REGIME_PARAMS = {
    "trending_bullish": RegimeParameters(
        regime="trending_bullish",
        confidence_threshold=0.60,
        min_rr_ratio=1.3,
        size_multiplier=1.2,
        stop_loss_multiplier=1.2,  # Wider stops in trends
        take_profit_multiplier=1.5,  # Let winners run
        signal_type_boosts={
            "momentum_long": 0.1,
            "breakout_long": 0.1,
            "sr_bounce_long": 0.05,
            "momentum_short": -0.1,  # Penalize counter-trend
        },
    ),
    "trending_bearish": RegimeParameters(
        regime="trending_bearish",
        confidence_threshold=0.60,
        min_rr_ratio=1.3,
        size_multiplier=1.2,
        stop_loss_multiplier=1.2,
        take_profit_multiplier=1.5,
        signal_type_boosts={
            "momentum_short": 0.1,
            "breakout_short": 0.1,
            "sr_bounce_short": 0.05,
            "momentum_long": -0.1,
        },
    ),
    "ranging": RegimeParameters(
        regime="ranging",
        confidence_threshold=0.70,  # More selective
        min_rr_ratio=1.2,  # Lower R:R acceptable for reversions
        size_multiplier=1.0,
        stop_loss_multiplier=0.8,  # Tighter stops
        take_profit_multiplier=0.8,  # Take profits quicker
        signal_type_boosts={
            "mean_reversion_long": 0.15,
            "mean_reversion_short": 0.15,
            "sr_bounce_long": 0.1,
            "sr_bounce_short": 0.1,
            "momentum_long": -0.1,
            "momentum_short": -0.1,
        },
    ),
    "volatile": RegimeParameters(
        regime="volatile",
        confidence_threshold=0.80,  # Very selective
        min_rr_ratio=2.0,  # Require higher R:R
        size_multiplier=0.5,  # Half size
        max_positions=1,
        stop_loss_multiplier=1.5,  # Wider stops
        take_profit_multiplier=1.5,
        signal_type_boosts={
            "breakout_long": 0.1,
            "breakout_short": 0.1,
            "mean_reversion_long": -0.1,  # Penalize reversions in vol
            "mean_reversion_short": -0.1,
        },
    ),
    "quiet": RegimeParameters(
        regime="quiet",
        confidence_threshold=0.85,  # Very selective (may skip most)
        min_rr_ratio=1.0,
        size_multiplier=0.5,  # Small size
        stop_loss_multiplier=0.7,  # Tight stops
        take_profit_multiplier=0.7,
        signal_type_boosts={},  # No strong preferences
    ),
}


@dataclass
class RegimeState:
    """Current regime detection state."""
    current_regime: str = "unknown"
    regime_confidence: float = 0.5
    regime_duration_bars: int = 0
    
    # Feature values used for detection
    trend_strength: float = 0.0  # -1 to 1 (negative = bearish)
    volatility_percentile: float = 0.5  # 0 to 1
    volume_percentile: float = 0.5
    price_position: float = 0.5  # Position in recent range
    
    # History
    regime_history: List[str] = field(default_factory=list)
    transition_times: List[str] = field(default_factory=list)
    
    # Metadata
    last_updated: Optional[str] = None
    bars_since_update: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "current_regime": self.current_regime,
            "regime_confidence": self.regime_confidence,
            "regime_duration_bars": self.regime_duration_bars,
            "trend_strength": self.trend_strength,
            "volatility_percentile": self.volatility_percentile,
            "volume_percentile": self.volume_percentile,
            "price_position": self.price_position,
            "regime_history": self.regime_history[-20:],  # Keep last 20
            "transition_times": self.transition_times[-20:],
            "last_updated": self.last_updated,
            "bars_since_update": self.bars_since_update,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegimeState":
        """Create from dictionary."""
        return cls(
            current_regime=data.get("current_regime", "unknown"),
            regime_confidence=float(data.get("regime_confidence", 0.5)),
            regime_duration_bars=int(data.get("regime_duration_bars", 0)),
            trend_strength=float(data.get("trend_strength", 0.0)),
            volatility_percentile=float(data.get("volatility_percentile", 0.5)),
            volume_percentile=float(data.get("volume_percentile", 0.5)),
            price_position=float(data.get("price_position", 0.5)),
            regime_history=data.get("regime_history", []),
            transition_times=data.get("transition_times", []),
            last_updated=data.get("last_updated"),
            bars_since_update=int(data.get("bars_since_update", 0)),
        )


class HeuristicRegimeDetector:
    """
    Simple heuristic-based regime detection.
    
    Uses trend, volatility, and volume to classify regime.
    """
    
    def __init__(self, config: RegimeConfig):
        self.config = config
        self._vol_history: List[float] = []
        self._max_vol_history = 100
    
    def detect(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Tuple[str, float, Dict[str, float]]:
        """
        Detect current regime.
        
        Args:
            close: Close prices
            high: High prices
            low: Low prices
            volume: Volume
            
        Returns:
            (regime_name, confidence, features)
        """
        if len(close) < self.config.medium_window:
            return "unknown", 0.5, {}
        
        # Compute features
        features = {}
        
        # Trend strength (-1 to 1)
        short_ma = np.mean(close[-self.config.short_window:])
        medium_ma = np.mean(close[-self.config.medium_window:])
        long_ma = np.mean(close[-self.config.long_window:]) if len(close) >= self.config.long_window else medium_ma
        
        trend = (short_ma - long_ma) / long_ma if long_ma > 0 else 0
        features["trend_strength"] = np.clip(trend / 0.01, -1, 1)  # Normalize
        
        # Volatility (ATR percentile)
        tr = np.maximum(
            high[-self.config.medium_window:] - low[-self.config.medium_window:],
            np.maximum(
                np.abs(high[-self.config.medium_window:] - np.roll(close[-self.config.medium_window:], 1)[1:]),
                np.abs(low[-self.config.medium_window:] - np.roll(close[-self.config.medium_window:], 1)[1:])
            )
        )
        current_atr = np.mean(tr) if len(tr) > 0 else 0
        
        # Track volatility history for percentile
        self._vol_history.append(current_atr)
        if len(self._vol_history) > self._max_vol_history:
            self._vol_history = self._vol_history[-self._max_vol_history:]
        
        if len(self._vol_history) > 1:
            vol_percentile = np.sum(np.array(self._vol_history) < current_atr) / len(self._vol_history)
        else:
            vol_percentile = 0.5
        features["volatility_percentile"] = vol_percentile
        
        # Volume percentile
        if len(volume) >= self.config.medium_window:
            avg_vol = np.mean(volume[-self.config.medium_window:])
            recent_vol = np.mean(volume[-self.config.short_window:])
            features["volume_percentile"] = min(recent_vol / avg_vol, 2.0) / 2.0
        else:
            features["volume_percentile"] = 0.5
        
        # Price position in range
        if len(high) >= self.config.medium_window:
            range_high = np.max(high[-self.config.medium_window:])
            range_low = np.min(low[-self.config.medium_window:])
            range_size = range_high - range_low
            if range_size > 0:
                features["price_position"] = (close[-1] - range_low) / range_size
            else:
                features["price_position"] = 0.5
        else:
            features["price_position"] = 0.5
        
        # Classify regime
        regime, confidence = self._classify_regime(features)
        
        return regime, confidence, features
    
    def _classify_regime(self, features: Dict[str, float]) -> Tuple[str, float]:
        """Classify regime based on features."""
        trend = features.get("trend_strength", 0)
        vol = features.get("volatility_percentile", 0.5)
        
        # High volatility = volatile regime (overrides others)
        if vol > self.config.volatility_high_percentile:
            return "volatile", vol
        
        # Low volatility = quiet regime
        if vol < self.config.volatility_low_percentile:
            return "quiet", 1 - vol
        
        # Strong trend
        if trend > 0.3:
            confidence = min((trend + 1) / 2, 1.0)
            return "trending_bullish", confidence
        
        if trend < -0.3:
            confidence = min((-trend + 1) / 2, 1.0)
            return "trending_bearish", confidence
        
        # Default to ranging
        return "ranging", 0.6


class HMMRegimeDetector:
    """
    Hidden Markov Model based regime detection.
    
    Uses Gaussian HMM to model latent market states.
    """
    
    def __init__(self, config: RegimeConfig):
        self.config = config
        self.model: Optional[Any] = None
        self._is_fitted = False
        self._feature_history: List[np.ndarray] = []
        self._min_samples = 100
        
        # Regime labels (ordered by expected states)
        self._regime_labels = [
            "ranging",
            "trending_bullish",
            "trending_bearish", 
            "volatile",
        ][:config.hmm_n_states]
    
    def detect(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Tuple[str, float, Dict[str, float]]:
        """Detect regime using HMM."""
        if not HMM_AVAILABLE:
            # Fallback to heuristics
            heuristic = HeuristicRegimeDetector(self.config)
            return heuristic.detect(close, high, low, volume)
        
        # Compute feature vector
        features = self._compute_features(close, high, low, volume)
        if features is None:
            return "unknown", 0.5, {}
        
        self._feature_history.append(features)
        if len(self._feature_history) > 1000:
            self._feature_history = self._feature_history[-1000:]
        
        # Train or update model if needed
        if not self._is_fitted and len(self._feature_history) >= self._min_samples:
            self._fit_model()
        
        if not self._is_fitted:
            return "unknown", 0.5, {}
        
        # Predict current state
        try:
            X = features.reshape(1, -1)
            state_probs = self.model.predict_proba(X)[0]
            predicted_state = np.argmax(state_probs)
            confidence = state_probs[predicted_state]
            
            regime = self._regime_labels[predicted_state]
            
            return regime, confidence, {
                "state_probs": state_probs.tolist(),
                "trend_strength": float(features[0]),
                "volatility_percentile": float(features[1]),
            }
        except Exception as e:
            logger.warning(f"HMM prediction failed: {e}")
            return "unknown", 0.5, {}
    
    def _compute_features(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> Optional[np.ndarray]:
        """Compute feature vector for HMM."""
        if len(close) < self.config.medium_window:
            return None
        
        # Returns
        returns = np.diff(close[-self.config.medium_window:]) / close[-self.config.medium_window:-1]
        
        # Feature 1: Return momentum (mean of recent returns)
        momentum = np.mean(returns)
        
        # Feature 2: Volatility (std of returns)
        volatility = np.std(returns)
        
        # Feature 3: Volume change
        if len(volume) >= self.config.medium_window:
            vol_change = (
                np.mean(volume[-self.config.short_window:]) /
                np.mean(volume[-self.config.medium_window:])
            ) - 1
        else:
            vol_change = 0
        
        return np.array([momentum, volatility, vol_change])
    
    def _fit_model(self) -> None:
        """Fit the HMM model."""
        if not HMM_AVAILABLE:
            return
        
        try:
            X = np.array(self._feature_history)
            
            self.model = hmm.GaussianHMM(
                n_components=self.config.hmm_n_states,
                covariance_type=self.config.hmm_covariance_type,
                n_iter=100,
                random_state=42,
            )
            
            self.model.fit(X)
            self._is_fitted = True
            
            logger.info(f"HMM model fitted with {len(X)} samples")
        except Exception as e:
            logger.warning(f"HMM fitting failed: {e}")


class RegimeAdaptivePolicy:
    """
    Adapts trading parameters based on detected market regime.
    
    Provides:
    - Real-time regime detection
    - Parameter adaptation per regime
    - Signal type boosting/penalizing
    """
    
    def __init__(
        self,
        config: Optional[RegimeConfig] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize regime adaptive policy.
        
        Args:
            config: Regime configuration
            state_dir: Directory for state persistence
        """
        self.config = config or RegimeConfig()
        self.state_dir = ensure_state_dir(state_dir)
        self.state_file = self.state_dir / "regime_state.json"
        
        # Initialize detector
        if self.config.use_hmm and HMM_AVAILABLE:
            self._detector = HMMRegimeDetector(self.config)
        else:
            self._detector = HeuristicRegimeDetector(self.config)
        
        # Current state
        self.state = self._load_state()
        
        # Regime parameters
        self._regime_params = DEFAULT_REGIME_PARAMS.copy()
        
        logger.info(f"RegimeAdaptivePolicy initialized: method={'HMM' if isinstance(self._detector, HMMRegimeDetector) else 'heuristic'}")
    
    def _load_state(self) -> RegimeState:
        """Load state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                return RegimeState.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to load regime state: {e}")
        
        return RegimeState()
    
    def _save_state(self) -> None:
        """Save state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save regime state: {e}")
    
    def update(
        self,
        close: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        volume: np.ndarray,
    ) -> str:
        """
        Update regime detection.
        
        Args:
            close: Close prices (most recent last)
            high: High prices
            low: Low prices
            volume: Volume
            
        Returns:
            Current regime name
        """
        self.state.bars_since_update += 1
        
        # Only update every N bars
        if self.state.bars_since_update < self.config.update_bars:
            return self.state.current_regime
        
        self.state.bars_since_update = 0
        
        # Detect regime
        regime, confidence, features = self._detector.detect(close, high, low, volume)
        
        # Update state
        if regime != self.state.current_regime:
            # Regime change
            self.state.regime_history.append(self.state.current_regime)
            self.state.transition_times.append(datetime.now(timezone.utc).isoformat())
            self.state.regime_duration_bars = 0
            
            logger.info(f"Regime change: {self.state.current_regime} -> {regime} (confidence: {confidence:.2f})")
        else:
            self.state.regime_duration_bars += 1
        
        self.state.current_regime = regime
        self.state.regime_confidence = confidence
        self.state.trend_strength = features.get("trend_strength", 0)
        self.state.volatility_percentile = features.get("volatility_percentile", 0.5)
        self.state.volume_percentile = features.get("volume_percentile", 0.5)
        self.state.price_position = features.get("price_position", 0.5)
        self.state.last_updated = datetime.now(timezone.utc).isoformat()
        
        self._save_state()
        
        return regime
    
    def get_current_regime(self) -> str:
        """Get current regime."""
        return self.state.current_regime
    
    def get_parameters(self, regime: Optional[str] = None) -> RegimeParameters:
        """
        Get trading parameters for a regime.
        
        Args:
            regime: Regime name (default: current)
            
        Returns:
            RegimeParameters for the regime
        """
        if regime is None:
            regime = self.state.current_regime
        
        return self._regime_params.get(
            regime,
            RegimeParameters(regime=regime),  # Default parameters
        )
    
    def adjust_signal_score(
        self,
        signal_type: str,
        base_score: float,
        regime: Optional[str] = None,
    ) -> float:
        """
        Adjust signal score based on regime preferences.
        
        Args:
            signal_type: Type of signal
            base_score: Original score (0-1)
            regime: Regime (default: current)
            
        Returns:
            Adjusted score (0-1)
        """
        params = self.get_parameters(regime)
        boost = params.signal_type_boosts.get(signal_type, 0.0)
        
        adjusted = base_score + boost
        return max(0.0, min(1.0, adjusted))
    
    def should_skip_signal(
        self,
        signal: Dict,
        confidence: float,
        regime: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Check if a signal should be skipped based on regime parameters.
        
        Args:
            signal: Signal dictionary
            confidence: Signal confidence (0-1)
            regime: Regime (default: current)
            
        Returns:
            (should_skip, reason)
        """
        params = self.get_parameters(regime)
        
        # Check confidence threshold
        if confidence < params.confidence_threshold:
            return True, f"confidence {confidence:.2f} < threshold {params.confidence_threshold}"
        
        # Check R:R ratio
        entry = float(signal.get("entry_price", 0))
        sl = float(signal.get("stop_loss", 0))
        tp = float(signal.get("take_profit", 0))
        
        if entry > 0 and sl > 0 and tp > 0:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = reward / risk if risk > 0 else 0
            
            if rr < params.min_rr_ratio:
                return True, f"R:R {rr:.2f} < min {params.min_rr_ratio}"
        
        # Check allowed hours
        if params.allowed_hours:
            current_hour = datetime.now().hour
            if current_hour not in params.allowed_hours:
                return True, f"hour {current_hour} not in allowed hours"
        
        return False, "ok"
    
    def get_status(self) -> Dict[str, Any]:
        """Get current regime status."""
        return {
            "current_regime": self.state.current_regime,
            "regime_confidence": round(self.state.regime_confidence, 2),
            "regime_duration_bars": self.state.regime_duration_bars,
            "trend_strength": round(self.state.trend_strength, 2),
            "volatility_percentile": round(self.state.volatility_percentile, 2),
            "volume_percentile": round(self.state.volume_percentile, 2),
            "price_position": round(self.state.price_position, 2),
            "last_updated": self.state.last_updated,
            "recent_regimes": self.state.regime_history[-5:],
        }
    
    def set_regime_parameters(self, regime: str, params: RegimeParameters) -> None:
        """Override parameters for a regime."""
        self._regime_params[regime] = params
        logger.info(f"Updated parameters for regime: {regime}")
    
    def get_telegram_summary(self) -> str:
        """Get compact summary for Telegram."""
        regime_emoji = {
            "trending_bullish": "📈",
            "trending_bearish": "📉",
            "ranging": "↔️",
            "volatile": "🌊",
            "quiet": "😴",
            "unknown": "❓",
        }
        
        emoji = regime_emoji.get(self.state.current_regime, "❓")
        
        lines = [
            f"{emoji} *Regime:* `{self.state.current_regime}`",
            f"Confidence: {self.state.regime_confidence:.0%}",
            f"Duration: {self.state.regime_duration_bars} bars",
        ]
        
        return "\n".join(lines)





