"""
Meta-Learning Layer

Learns HOW to learn:
- Tracks learning curves per signal type
- Identifies optimal exploration rates  
- Experience replay for reinforced learning
- Detects when features lose predictive power
- Adapts learning parameters in real-time
"""

from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.utils.logger import logger


@dataclass
class MetaConfig:
    """Configuration for meta-learning."""
    enabled: bool = True
    
    # Experience replay
    replay_buffer_size: int = 1000
    replay_batch_size: int = 32
    replay_priority_alpha: float = 0.6  # Priority exponent
    
    # Learning curve tracking
    learning_curve_window: int = 50
    convergence_threshold: float = 0.05  # Variance threshold for convergence
    
    # Exploration adaptation
    min_explore_rate: float = 0.05
    max_explore_rate: float = 0.3
    explore_decay_rate: float = 0.99
    
    # Feature importance tracking
    feature_importance_window: int = 100
    importance_decay_threshold: float = 0.3
    
    # Adaptation rates
    meta_learning_rate: float = 0.01
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "MetaConfig":
        """Create from dictionary."""
        return cls(
            enabled=bool(config.get("enabled", True)),
            replay_buffer_size=int(config.get("replay_buffer_size", 1000)),
            replay_batch_size=int(config.get("replay_batch_size", 32)),
            replay_priority_alpha=float(config.get("replay_priority_alpha", 0.6)),
            learning_curve_window=int(config.get("learning_curve_window", 50)),
            convergence_threshold=float(config.get("convergence_threshold", 0.05)),
            min_explore_rate=float(config.get("min_explore_rate", 0.05)),
            max_explore_rate=float(config.get("max_explore_rate", 0.3)),
            explore_decay_rate=float(config.get("explore_decay_rate", 0.99)),
            feature_importance_window=int(config.get("feature_importance_window", 100)),
            importance_decay_threshold=float(config.get("importance_decay_threshold", 0.3)),
            meta_learning_rate=float(config.get("meta_learning_rate", 0.01)),
        )


@dataclass
class Experience:
    """Single experience for replay buffer."""
    signal_id: str
    signal_type: str
    features: Dict[str, float]
    context_key: str
    is_win: bool
    pnl: float
    timestamp: str
    regime: str
    
    # Priority for importance sampling
    priority: float = 1.0
    td_error: float = 0.0  # For prioritized replay
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "features": self.features,
            "context_key": self.context_key,
            "is_win": self.is_win,
            "pnl": self.pnl,
            "timestamp": self.timestamp,
            "regime": self.regime,
            "priority": self.priority,
            "td_error": self.td_error,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experience":
        """Create from dictionary."""
        return cls(
            signal_id=data.get("signal_id", ""),
            signal_type=data.get("signal_type", ""),
            features=data.get("features", {}),
            context_key=data.get("context_key", ""),
            is_win=data.get("is_win", False),
            pnl=float(data.get("pnl", 0)),
            timestamp=data.get("timestamp", ""),
            regime=data.get("regime", "unknown"),
            priority=float(data.get("priority", 1.0)),
            td_error=float(data.get("td_error", 0.0)),
        )


@dataclass
class LearningCurveStats:
    """Tracks learning curve for a signal type."""
    signal_type: str
    
    # Win rate history (for convergence detection)
    win_rate_history: List[float] = field(default_factory=list)
    sample_count_history: List[int] = field(default_factory=list)
    
    # Current estimates
    current_win_rate: float = 0.5
    win_rate_variance: float = 0.0
    is_converged: bool = False
    
    # Learning speed
    samples_to_converge: Optional[int] = None
    
    def update(self, is_win: bool, window: int = 50) -> None:
        """Update learning curve."""
        # Update running win rate
        if not self.win_rate_history:
            self.current_win_rate = 1.0 if is_win else 0.0
        else:
            # Exponential moving average
            alpha = 2 / (window + 1)
            self.current_win_rate = alpha * (1.0 if is_win else 0.0) + (1 - alpha) * self.current_win_rate
        
        self.win_rate_history.append(self.current_win_rate)
        self.sample_count_history.append(len(self.win_rate_history))
        
        # Keep window
        if len(self.win_rate_history) > window * 2:
            self.win_rate_history = self.win_rate_history[-window*2:]
            self.sample_count_history = self.sample_count_history[-window*2:]
        
        # Check convergence
        if len(self.win_rate_history) >= window:
            recent = self.win_rate_history[-window:]
            self.win_rate_variance = np.var(recent)
            
            if self.win_rate_variance < 0.01 and not self.is_converged:
                self.is_converged = True
                self.samples_to_converge = len(self.win_rate_history)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_type": self.signal_type,
            "win_rate_history": self.win_rate_history[-50:],
            "sample_count_history": self.sample_count_history[-50:],
            "current_win_rate": self.current_win_rate,
            "win_rate_variance": self.win_rate_variance,
            "is_converged": self.is_converged,
            "samples_to_converge": self.samples_to_converge,
        }


@dataclass  
class MetaState:
    """Complete meta-learning state."""
    # Experience replay buffer
    experiences: List[Experience] = field(default_factory=list)
    
    # Learning curves per signal type
    learning_curves: Dict[str, LearningCurveStats] = field(default_factory=dict)
    
    # Adaptive exploration rates per signal type
    explore_rates: Dict[str, float] = field(default_factory=dict)
    
    # Feature importance tracking
    feature_correlations: Dict[str, float] = field(default_factory=dict)
    feature_importance_history: Dict[str, List[float]] = field(default_factory=dict)
    
    # Global counters
    total_experiences: int = 0
    total_replays: int = 0
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "experiences": [e.to_dict() for e in self.experiences[-1000:]],
            "learning_curves": {k: v.to_dict() for k, v in self.learning_curves.items()},
            "explore_rates": self.explore_rates,
            "feature_correlations": self.feature_correlations,
            "feature_importance_history": {
                k: v[-100:] for k, v in self.feature_importance_history.items()
            },
            "total_experiences": self.total_experiences,
            "total_replays": self.total_replays,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetaState":
        """Create from dictionary."""
        state = cls(
            experiences=[Experience.from_dict(e) for e in data.get("experiences", [])],
            explore_rates=data.get("explore_rates", {}),
            feature_correlations=data.get("feature_correlations", {}),
            feature_importance_history=data.get("feature_importance_history", {}),
            total_experiences=int(data.get("total_experiences", 0)),
            total_replays=int(data.get("total_replays", 0)),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
        
        # Load learning curves
        for signal_type, curve_data in data.get("learning_curves", {}).items():
            curve = LearningCurveStats(signal_type=signal_type)
            curve.win_rate_history = curve_data.get("win_rate_history", [])
            curve.sample_count_history = curve_data.get("sample_count_history", [])
            curve.current_win_rate = float(curve_data.get("current_win_rate", 0.5))
            curve.win_rate_variance = float(curve_data.get("win_rate_variance", 0.0))
            curve.is_converged = bool(curve_data.get("is_converged", False))
            curve.samples_to_converge = curve_data.get("samples_to_converge")
            state.learning_curves[signal_type] = curve
        
        return state


class MetaLearner:
    """
    Meta-learning system that learns how to learn.
    
    Features:
    - Experience replay buffer with prioritization
    - Learning curve tracking per signal type
    - Adaptive exploration rates
    - Feature importance decay detection
    """
    
    def __init__(
        self,
        config: Optional[MetaConfig] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize meta-learner.
        
        Args:
            config: Meta-learning configuration
            state_dir: Directory for state persistence
        """
        self.config = config or MetaConfig()
        self.state_dir = state_dir or Path("data/nq_agent_state")
        self.state_file = self.state_dir / "meta_state.json"
        
        # Load state
        self.state = self._load_state()
        
        # Random generator
        self._rng = random.Random()
        
        logger.info(f"MetaLearner initialized: buffer_size={self.config.replay_buffer_size}")
    
    def _load_state(self) -> MetaState:
        """Load state from disk."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                return MetaState.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to load meta state: {e}")
        
        return MetaState()
    
    def _save_state(self) -> None:
        """Save state to disk."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save meta state: {e}")
    
    def add_experience(
        self,
        signal_id: str,
        signal_type: str,
        features: Dict[str, float],
        context_key: str,
        is_win: bool,
        pnl: float,
        regime: str = "unknown",
    ) -> None:
        """
        Add a new experience to the replay buffer.
        
        Args:
            signal_id: Signal identifier
            signal_type: Type of signal
            features: Feature dictionary at signal time
            context_key: Context key for contextual bandit
            is_win: Whether trade was profitable
            pnl: P&L in dollars
            regime: Market regime at signal time
        """
        experience = Experience(
            signal_id=signal_id,
            signal_type=signal_type,
            features=features,
            context_key=context_key,
            is_win=is_win,
            pnl=pnl,
            timestamp=datetime.now(timezone.utc).isoformat(),
            regime=regime,
            priority=abs(pnl) + 1.0,  # Prioritize by P&L magnitude
            td_error=abs(pnl),
        )
        
        # Add to buffer
        self.state.experiences.append(experience)
        self.state.total_experiences += 1
        
        # Maintain buffer size
        if len(self.state.experiences) > self.config.replay_buffer_size:
            self.state.experiences = self.state.experiences[-self.config.replay_buffer_size:]
        
        # Update learning curve
        self._update_learning_curve(signal_type, is_win)
        
        # Update feature importance
        self._update_feature_importance(features, is_win)
        
        # Update exploration rate
        self._update_explore_rate(signal_type)
        
        self._save_state()
        
        logger.debug(f"Added experience: {signal_type} | win={is_win} | buffer_size={len(self.state.experiences)}")
    
    def _update_learning_curve(self, signal_type: str, is_win: bool) -> None:
        """Update learning curve for signal type."""
        if signal_type not in self.state.learning_curves:
            self.state.learning_curves[signal_type] = LearningCurveStats(signal_type=signal_type)
        
        curve = self.state.learning_curves[signal_type]
        curve.update(is_win, window=self.config.learning_curve_window)
    
    def _update_feature_importance(self, features: Dict[str, float], is_win: bool) -> None:
        """Track feature-outcome correlations."""
        label = 1.0 if is_win else 0.0
        
        for name, value in features.items():
            # Initialize if needed
            if name not in self.state.feature_importance_history:
                self.state.feature_importance_history[name] = []
            
            # Simple correlation: feature * label
            correlation = value * label
            self.state.feature_importance_history[name].append(correlation)
            
            # Maintain window
            window = self.config.feature_importance_window
            if len(self.state.feature_importance_history[name]) > window:
                self.state.feature_importance_history[name] = self.state.feature_importance_history[name][-window:]
            
            # Update running correlation
            history = self.state.feature_importance_history[name]
            if len(history) >= 10:
                self.state.feature_correlations[name] = float(np.mean(history))
    
    def _update_explore_rate(self, signal_type: str) -> None:
        """Adapt exploration rate based on learning curve."""
        curve = self.state.learning_curves.get(signal_type)
        
        if curve is None:
            self.state.explore_rates[signal_type] = self.config.max_explore_rate
            return
        
        # Start with current rate or max
        current_rate = self.state.explore_rates.get(signal_type, self.config.max_explore_rate)
        
        if curve.is_converged:
            # Reduce exploration if converged
            new_rate = current_rate * self.config.explore_decay_rate
        else:
            # Maintain exploration
            new_rate = current_rate
        
        # Clamp to bounds
        new_rate = max(self.config.min_explore_rate, min(self.config.max_explore_rate, new_rate))
        
        self.state.explore_rates[signal_type] = new_rate
    
    def sample_replay_batch(self, batch_size: Optional[int] = None) -> List[Experience]:
        """
        Sample a batch of experiences for replay.
        
        Uses prioritized sampling based on TD error / P&L magnitude.
        
        Args:
            batch_size: Number of experiences to sample
            
        Returns:
            List of sampled experiences
        """
        if batch_size is None:
            batch_size = self.config.replay_batch_size
        
        if len(self.state.experiences) < batch_size:
            return self.state.experiences.copy()
        
        # Compute sampling probabilities
        priorities = np.array([e.priority for e in self.state.experiences])
        priorities = priorities ** self.config.replay_priority_alpha
        probabilities = priorities / np.sum(priorities)
        
        # Sample indices
        indices = np.random.choice(
            len(self.state.experiences),
            size=batch_size,
            replace=False,
            p=probabilities,
        )
        
        self.state.total_replays += batch_size
        
        return [self.state.experiences[i] for i in indices]
    
    def get_explore_rate(self, signal_type: str) -> float:
        """Get adaptive exploration rate for signal type."""
        return self.state.explore_rates.get(signal_type, self.config.max_explore_rate)
    
    def get_learning_curve(self, signal_type: str) -> Optional[LearningCurveStats]:
        """Get learning curve stats for signal type."""
        return self.state.learning_curves.get(signal_type)
    
    def is_converged(self, signal_type: str) -> bool:
        """Check if learning has converged for signal type."""
        curve = self.state.learning_curves.get(signal_type)
        return curve.is_converged if curve else False
    
    def get_top_features(self, n: int = 10) -> List[Tuple[str, float]]:
        """Get top N features by importance."""
        sorted_features = sorted(
            self.state.feature_correlations.items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        )
        return sorted_features[:n]
    
    def get_decaying_features(self) -> List[str]:
        """Get features whose importance is decaying."""
        decaying = []
        
        for name, history in self.state.feature_importance_history.items():
            if len(history) < 20:
                continue
            
            # Compare recent vs older importance
            mid = len(history) // 2
            older = np.mean(history[:mid])
            recent = np.mean(history[mid:])
            
            if abs(older) > 0.1 and abs(recent) / abs(older) < self.config.importance_decay_threshold:
                decaying.append(name)
        
        return decaying
    
    def get_best_experiences(self, n: int = 10) -> List[Experience]:
        """Get best performing experiences."""
        sorted_exp = sorted(self.state.experiences, key=lambda e: e.pnl, reverse=True)
        return sorted_exp[:n]
    
    def get_worst_experiences(self, n: int = 10) -> List[Experience]:
        """Get worst performing experiences."""
        sorted_exp = sorted(self.state.experiences, key=lambda e: e.pnl)
        return sorted_exp[:n]
    
    def get_status(self) -> Dict[str, Any]:
        """Get meta-learner status."""
        return {
            "enabled": self.config.enabled,
            "buffer_size": len(self.state.experiences),
            "total_experiences": self.state.total_experiences,
            "total_replays": self.state.total_replays,
            "signal_types_tracked": len(self.state.learning_curves),
            "converged_signal_types": sum(1 for c in self.state.learning_curves.values() if c.is_converged),
            "features_tracked": len(self.state.feature_correlations),
            "decaying_features": len(self.get_decaying_features()),
            "explore_rates": {
                st: round(rate, 3) for st, rate in self.state.explore_rates.items()
            },
        }
    
    def get_telegram_summary(self) -> str:
        """Get compact summary for Telegram."""
        lines = [
            "🧠 *Meta-Learning*",
            f"Buffer: {len(self.state.experiences)}/{self.config.replay_buffer_size}",
            f"Total exp: {self.state.total_experiences}",
            f"Replays: {self.state.total_replays}",
        ]
        
        # Convergence status
        converged = [st for st, c in self.state.learning_curves.items() if c.is_converged]
        if converged:
            lines.append(f"Converged: `{', '.join(converged[:3])}`")
        
        # Top features
        top = self.get_top_features(3)
        if top:
            lines.append("Top features:")
            for name, corr in top:
                lines.append(f"  `{name}`: {corr:.2f}")
        
        return "\n".join(lines)



