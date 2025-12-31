"""
Contextual Bandit Policy

Extends Thompson Sampling to incorporate contextual features:
- Market regime (trending, ranging, volatile)
- Volatility percentile
- Time of session
- Recent performance

Instead of just learning "signal_type X wins 60%", learns:
"signal_type X wins 80% in trending + high_vol, but only 40% in ranging + low_vol"

This allows the system to adapt its decisions based on current market conditions.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pearlalgo.utils.logger import logger


@dataclass
class ContextFeatures:
    """
    Context features for contextual bandit decisions.
    
    These features describe the MARKET STATE at decision time,
    not the signal itself.
    """
    # Market regime (categorical)
    regime: str = "unknown"  # trending_bullish, trending_bearish, ranging, volatile
    
    # Volatility (0-1 percentile)
    volatility_percentile: float = 0.5
    
    # Time features
    hour_of_day: int = 12
    minutes_since_session_open: int = 0
    is_first_hour: bool = False
    is_last_hour: bool = False
    
    # Recent performance (from last N trades)
    recent_win_rate: float = 0.5
    recent_streak: int = 0  # Positive = win streak, negative = loss streak
    
    # Volume
    volume_percentile: float = 0.5
    
    # Trend strength (0-1)
    trend_strength: float = 0.5
    
    def to_context_key(self) -> str:
        """
        Convert to a discrete context key for table lookup.
        
        Discretizes continuous features into buckets.
        """
        # Discretize volatility into buckets
        if self.volatility_percentile < 0.33:
            vol_bucket = "low_vol"
        elif self.volatility_percentile < 0.67:
            vol_bucket = "med_vol"
        else:
            vol_bucket = "high_vol"
        
        # Discretize time into session phases
        if self.is_first_hour:
            time_bucket = "open"
        elif self.is_last_hour:
            time_bucket = "close"
        elif self.hour_of_day < 12:
            time_bucket = "morning"
        else:
            time_bucket = "afternoon"
        
        # Discretize recent performance
        if self.recent_win_rate > 0.6:
            perf_bucket = "hot"
        elif self.recent_win_rate < 0.4:
            perf_bucket = "cold"
        else:
            perf_bucket = "normal"
        
        # Combine into context key
        return f"{self.regime}_{vol_bucket}_{time_bucket}_{perf_bucket}"
    
    def to_vector(self) -> np.ndarray:
        """
        Convert to feature vector for linear models.
        
        Includes one-hot encoding for categorical features.
        """
        features = []
        
        # Regime one-hot (5 categories)
        regimes = ["trending_bullish", "trending_bearish", "ranging", "volatile", "unknown"]
        for r in regimes:
            features.append(1.0 if self.regime == r else 0.0)
        
        # Continuous features (normalized 0-1)
        features.append(self.volatility_percentile)
        features.append(self.hour_of_day / 24.0)
        features.append(min(self.minutes_since_session_open / 480.0, 1.0))  # 8-hour session
        features.append(1.0 if self.is_first_hour else 0.0)
        features.append(1.0 if self.is_last_hour else 0.0)
        features.append(self.recent_win_rate)
        features.append((self.recent_streak + 10) / 20.0)  # Normalize -10 to 10 -> 0 to 1
        features.append(self.volume_percentile)
        features.append(self.trend_strength)
        
        return np.array(features, dtype=np.float32)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "regime": self.regime,
            "volatility_percentile": self.volatility_percentile,
            "hour_of_day": self.hour_of_day,
            "minutes_since_session_open": self.minutes_since_session_open,
            "is_first_hour": self.is_first_hour,
            "is_last_hour": self.is_last_hour,
            "recent_win_rate": self.recent_win_rate,
            "recent_streak": self.recent_streak,
            "volume_percentile": self.volume_percentile,
            "trend_strength": self.trend_strength,
            "context_key": self.to_context_key(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextFeatures":
        """Create from dictionary."""
        return cls(
            regime=str(data.get("regime", "unknown")),
            volatility_percentile=float(data.get("volatility_percentile", 0.5)),
            hour_of_day=int(data.get("hour_of_day", 12)),
            minutes_since_session_open=int(data.get("minutes_since_session_open", 0)),
            is_first_hour=bool(data.get("is_first_hour", False)),
            is_last_hour=bool(data.get("is_last_hour", False)),
            recent_win_rate=float(data.get("recent_win_rate", 0.5)),
            recent_streak=int(data.get("recent_streak", 0)),
            volume_percentile=float(data.get("volume_percentile", 0.5)),
            trend_strength=float(data.get("trend_strength", 0.5)),
        )


@dataclass
class ContextualArmStats:
    """
    Statistics for a signal type in a specific context.
    
    Uses Beta distribution for Thompson Sampling.
    """
    signal_type: str
    context_key: str
    
    # Beta distribution parameters
    alpha: float = 2.0  # Prior + wins
    beta: float = 2.0   # Prior + losses
    
    # Raw counts
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    
    # Metadata
    last_updated: Optional[str] = None
    
    @property
    def sample_count(self) -> int:
        """Total observations."""
        return self.wins + self.losses
    
    @property
    def win_rate(self) -> float:
        """Observed win rate."""
        if self.sample_count == 0:
            return 0.5
        return self.wins / self.sample_count
    
    @property
    def expected_win_rate(self) -> float:
        """Expected win rate from Beta distribution (mean)."""
        return self.alpha / (self.alpha + self.beta)
    
    def sample(self, rng: random.Random) -> float:
        """Sample from Beta distribution."""
        return rng.betavariate(self.alpha, self.beta)
    
    def record_outcome(self, is_win: bool, pnl: float = 0.0) -> None:
        """Record a trade outcome."""
        if is_win:
            self.wins += 1
            self.alpha += 1.0
        else:
            self.losses += 1
            self.beta += 1.0
        
        self.total_pnl += pnl
        self.last_updated = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "signal_type": self.signal_type,
            "context_key": self.context_key,
            "alpha": self.alpha,
            "beta": self.beta,
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "expected_win_rate": self.expected_win_rate,
            "sample_count": self.sample_count,
            "last_updated": self.last_updated,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextualArmStats":
        """Create from dictionary."""
        return cls(
            signal_type=data.get("signal_type", "unknown"),
            context_key=data.get("context_key", "unknown"),
            alpha=float(data.get("alpha", 2.0)),
            beta=float(data.get("beta", 2.0)),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            total_pnl=float(data.get("total_pnl", 0.0)),
            last_updated=data.get("last_updated"),
        )


@dataclass
class ContextualBanditConfig:
    """Configuration for contextual bandit."""
    # Enable/disable
    enabled: bool = True
    mode: str = "shadow"  # "shadow" or "live"
    
    # Exploration
    explore_rate: float = 0.1
    min_samples_per_context: int = 5
    
    # Thresholds
    decision_threshold: float = 0.3
    confidence_boost_threshold: float = 0.7
    
    # Prior distribution
    prior_alpha: float = 2.0
    prior_beta: float = 2.0
    
    # Context discretization
    use_context_clustering: bool = True  # Cluster similar contexts
    max_context_buckets: int = 100       # Limit unique contexts
    
    # Fallback behavior
    fallback_to_global: bool = True  # Use global stats if context has few samples
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "ContextualBanditConfig":
        """Create from dictionary."""
        return cls(
            enabled=bool(config.get("enabled", True)),
            mode=str(config.get("mode", "shadow")),
            explore_rate=float(config.get("explore_rate", 0.1)),
            min_samples_per_context=int(config.get("min_samples_per_context", 5)),
            decision_threshold=float(config.get("decision_threshold", 0.3)),
            confidence_boost_threshold=float(config.get("confidence_boost_threshold", 0.7)),
            prior_alpha=float(config.get("prior_alpha", 2.0)),
            prior_beta=float(config.get("prior_beta", 2.0)),
            use_context_clustering=bool(config.get("use_context_clustering", True)),
            max_context_buckets=int(config.get("max_context_buckets", 100)),
            fallback_to_global=bool(config.get("fallback_to_global", True)),
        )


@dataclass
class ContextualDecision:
    """Decision from the contextual bandit."""
    execute: bool
    reason: str
    signal_type: str
    context_key: str
    
    # Scores
    sampled_score: float
    expected_win_rate: float
    context_sample_count: int
    
    # Adjustments
    size_multiplier: float = 1.0
    confidence_tier: str = "medium"  # "low", "medium", "high"
    
    # Mode info
    mode: str = "shadow"
    is_explore: bool = False
    used_global_fallback: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "execute": self.execute,
            "reason": self.reason,
            "signal_type": self.signal_type,
            "context_key": self.context_key,
            "sampled_score": self.sampled_score,
            "expected_win_rate": self.expected_win_rate,
            "context_sample_count": self.context_sample_count,
            "size_multiplier": self.size_multiplier,
            "confidence_tier": self.confidence_tier,
            "mode": self.mode,
            "is_explore": self.is_explore,
            "used_global_fallback": self.used_global_fallback,
        }


class ContextualBanditState:
    """
    Persistent state for contextual bandit.
    
    Stores:
    - Per-context arm statistics
    - Global (context-agnostic) statistics
    - Decision history
    """
    
    def __init__(self, prior_alpha: float = 2.0, prior_beta: float = 2.0):
        """Initialize state."""
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        
        # Context-specific stats: {signal_type: {context_key: ContextualArmStats}}
        self.contextual_stats: Dict[str, Dict[str, ContextualArmStats]] = {}
        
        # Global stats (fallback): {signal_type: ContextualArmStats}
        self.global_stats: Dict[str, ContextualArmStats] = {}
        
        # Counters
        self.total_decisions: int = 0
        self.total_executes: int = 0
        self.total_skips: int = 0
        
        # Metadata
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.created_at
    
    def get_stats(self, signal_type: str, context_key: str) -> ContextualArmStats:
        """Get or create stats for signal type + context."""
        if signal_type not in self.contextual_stats:
            self.contextual_stats[signal_type] = {}
        
        if context_key not in self.contextual_stats[signal_type]:
            self.contextual_stats[signal_type][context_key] = ContextualArmStats(
                signal_type=signal_type,
                context_key=context_key,
                alpha=self.prior_alpha,
                beta=self.prior_beta,
            )
        
        return self.contextual_stats[signal_type][context_key]
    
    def get_global_stats(self, signal_type: str) -> ContextualArmStats:
        """Get or create global stats for signal type."""
        if signal_type not in self.global_stats:
            self.global_stats[signal_type] = ContextualArmStats(
                signal_type=signal_type,
                context_key="global",
                alpha=self.prior_alpha,
                beta=self.prior_beta,
            )
        
        return self.global_stats[signal_type]
    
    def record_outcome(
        self,
        signal_type: str,
        context_key: str,
        is_win: bool,
        pnl: float = 0.0,
    ) -> None:
        """Record trade outcome for learning."""
        # Update context-specific stats
        ctx_stats = self.get_stats(signal_type, context_key)
        ctx_stats.record_outcome(is_win, pnl)
        
        # Also update global stats
        global_stats = self.get_global_stats(signal_type)
        global_stats.record_outcome(is_win, pnl)
        
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def record_decision(self, execute: bool) -> None:
        """Record a decision."""
        self.total_decisions += 1
        if execute:
            self.total_executes += 1
        else:
            self.total_skips += 1
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "prior_alpha": self.prior_alpha,
            "prior_beta": self.prior_beta,
            "contextual_stats": {
                st: {ck: stats.to_dict() for ck, stats in ctx_dict.items()}
                for st, ctx_dict in self.contextual_stats.items()
            },
            "global_stats": {st: stats.to_dict() for st, stats in self.global_stats.items()},
            "total_decisions": self.total_decisions,
            "total_executes": self.total_executes,
            "total_skips": self.total_skips,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextualBanditState":
        """Create from dictionary."""
        state = cls(
            prior_alpha=float(data.get("prior_alpha", 2.0)),
            prior_beta=float(data.get("prior_beta", 2.0)),
        )
        
        # Load contextual stats
        for signal_type, ctx_dict in data.get("contextual_stats", {}).items():
            state.contextual_stats[signal_type] = {}
            for ctx_key, stats_data in ctx_dict.items():
                state.contextual_stats[signal_type][ctx_key] = ContextualArmStats.from_dict(stats_data)
        
        # Load global stats
        for signal_type, stats_data in data.get("global_stats", {}).items():
            state.global_stats[signal_type] = ContextualArmStats.from_dict(stats_data)
        
        state.total_decisions = int(data.get("total_decisions", 0))
        state.total_executes = int(data.get("total_executes", 0))
        state.total_skips = int(data.get("total_skips", 0))
        state.created_at = data.get("created_at", state.created_at)
        state.updated_at = data.get("updated_at", state.updated_at)
        
        return state
    
    def save(self, file_path: Path) -> None:
        """Save state to file."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.debug(f"Contextual bandit state saved to {file_path}")
    
    @classmethod
    def load(cls, file_path: Path) -> "ContextualBanditState":
        """Load state from file."""
        if not file_path.exists():
            logger.info(f"No contextual bandit state at {file_path}, creating new")
            return cls()
        
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            state = cls.from_dict(data)
            logger.info(f"Contextual bandit state loaded: {state.total_decisions} decisions")
            return state
        except Exception as e:
            logger.error(f"Error loading contextual bandit state: {e}")
            return cls()


class ContextualBanditPolicy:
    """
    Contextual Thompson Sampling policy.
    
    Learns signal quality per CONTEXT, not just per signal type.
    This allows adapting to different market conditions.
    """
    
    def __init__(
        self,
        config: Optional[ContextualBanditConfig] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize contextual bandit policy.
        
        Args:
            config: Policy configuration
            state_dir: Directory for state persistence
        """
        self.config = config or ContextualBanditConfig()
        self.state_dir = state_dir or Path("data/nq_agent_state")
        self.state_file = self.state_dir / "contextual_bandit_state.json"
        
        # Load state
        self.state = ContextualBanditState.load(self.state_file)
        self.state.prior_alpha = self.config.prior_alpha
        self.state.prior_beta = self.config.prior_beta
        
        # Random generator
        self._rng = random.Random()
        
        logger.info(
            f"ContextualBanditPolicy initialized: mode={self.config.mode}, "
            f"threshold={self.config.decision_threshold}"
        )
    
    def set_seed(self, seed: int) -> None:
        """Set random seed for reproducibility."""
        self._rng.seed(seed)
    
    def decide(
        self,
        signal: Dict,
        context: ContextFeatures,
    ) -> ContextualDecision:
        """
        Make a contextual decision about whether to execute a signal.
        
        Args:
            signal: Signal dictionary
            context: Current context features
            
        Returns:
            ContextualDecision with recommendation
        """
        signal_type = signal.get("type", "unknown")
        context_key = context.to_context_key()
        
        # Get stats
        ctx_stats = self.state.get_stats(signal_type, context_key)
        global_stats = self.state.get_global_stats(signal_type)
        
        # Decide which stats to use
        use_global = False
        if ctx_stats.sample_count < self.config.min_samples_per_context:
            if self.config.fallback_to_global and global_stats.sample_count >= self.config.min_samples_per_context:
                use_global = True
                active_stats = global_stats
            else:
                # Explore - not enough data
                decision = ContextualDecision(
                    execute=True,
                    reason=f"explore:context_samples={ctx_stats.sample_count}",
                    signal_type=signal_type,
                    context_key=context_key,
                    sampled_score=ctx_stats.expected_win_rate,
                    expected_win_rate=ctx_stats.expected_win_rate,
                    context_sample_count=ctx_stats.sample_count,
                    mode=self.config.mode,
                    is_explore=True,
                    used_global_fallback=False,
                )
                self.state.record_decision(True)
                return decision
        else:
            active_stats = ctx_stats
        
        # Epsilon-greedy exploration
        if self._rng.random() < self.config.explore_rate:
            decision = ContextualDecision(
                execute=True,
                reason="explore:epsilon_greedy",
                signal_type=signal_type,
                context_key=context_key,
                sampled_score=active_stats.expected_win_rate,
                expected_win_rate=active_stats.expected_win_rate,
                context_sample_count=active_stats.sample_count,
                mode=self.config.mode,
                is_explore=True,
                used_global_fallback=use_global,
            )
            self.state.record_decision(True)
            return decision
        
        # Thompson Sampling: sample from Beta distribution
        sampled_score = active_stats.sample(self._rng)
        expected_wr = active_stats.expected_win_rate
        
        # Decision: execute if sample >= threshold
        execute = sampled_score >= self.config.decision_threshold
        
        # Confidence tier and size adjustment
        if expected_wr >= self.config.confidence_boost_threshold:
            confidence_tier = "high"
            size_multiplier = 1.3
        elif expected_wr >= 0.5:
            confidence_tier = "medium"
            size_multiplier = 1.0
        else:
            confidence_tier = "low"
            size_multiplier = 0.7
        
        # Build reason
        if execute:
            reason = f"thompson_pass:{sampled_score:.2f}>={self.config.decision_threshold}"
        else:
            reason = f"thompson_skip:{sampled_score:.2f}<{self.config.decision_threshold}"
        
        if use_global:
            reason += ":global_fallback"
        
        decision = ContextualDecision(
            execute=execute,
            reason=reason,
            signal_type=signal_type,
            context_key=context_key,
            sampled_score=sampled_score,
            expected_win_rate=expected_wr,
            context_sample_count=active_stats.sample_count,
            size_multiplier=size_multiplier,
            confidence_tier=confidence_tier,
            mode=self.config.mode,
            is_explore=False,
            used_global_fallback=use_global,
        )
        
        self.state.record_decision(execute)
        return decision
    
    def record_outcome(
        self,
        signal_id: str,
        signal_type: str,
        context: ContextFeatures,
        is_win: bool,
        pnl: float = 0.0,
    ) -> None:
        """
        Record trade outcome for learning.
        
        Args:
            signal_id: Signal identifier
            signal_type: Type of signal
            context: Context at signal time
            is_win: Whether trade was profitable
            pnl: P&L in dollars
        """
        context_key = context.to_context_key()
        
        self.state.record_outcome(signal_type, context_key, is_win, pnl)
        
        logger.info(
            f"ContextualBandit: {'WIN' if is_win else 'LOSS'} for {signal_type} "
            f"in context {context_key} | pnl=${pnl:.2f}"
        )
        
        self.save_state()
    
    def save_state(self) -> None:
        """Save policy state."""
        self.state.save(self.state_file)
    
    def load_state(self) -> None:
        """Reload policy state."""
        self.state = ContextualBanditState.load(self.state_file)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current policy status."""
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "total_decisions": self.state.total_decisions,
            "total_executes": self.state.total_executes,
            "total_skips": self.state.total_skips,
            "execute_rate": (
                round(self.state.total_executes / max(1, self.state.total_decisions), 2)
            ),
            "unique_contexts": sum(
                len(ctx_dict) for ctx_dict in self.state.contextual_stats.values()
            ),
            "signal_types_tracked": len(self.state.global_stats),
        }
    
    def get_context_summary(self, signal_type: str) -> Dict[str, Dict]:
        """Get summary of performance by context for a signal type."""
        if signal_type not in self.state.contextual_stats:
            return {}
        
        return {
            ctx_key: {
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": f"{stats.win_rate:.0%}",
                "expected": f"{stats.expected_win_rate:.0%}",
                "samples": stats.sample_count,
            }
            for ctx_key, stats in self.state.contextual_stats[signal_type].items()
        }
    
    def get_best_contexts(self, signal_type: str, top_n: int = 5) -> List[Dict]:
        """Get best performing contexts for a signal type."""
        if signal_type not in self.state.contextual_stats:
            return []
        
        contexts = list(self.state.contextual_stats[signal_type].values())
        
        # Sort by expected win rate (with minimum samples filter)
        min_samples = self.config.min_samples_per_context
        qualified = [c for c in contexts if c.sample_count >= min_samples]
        qualified.sort(key=lambda x: x.expected_win_rate, reverse=True)
        
        return [
            {
                "context_key": c.context_key,
                "win_rate": f"{c.win_rate:.0%}",
                "expected": f"{c.expected_win_rate:.0%}",
                "samples": c.sample_count,
                "total_pnl": f"${c.total_pnl:.2f}",
            }
            for c in qualified[:top_n]
        ]
    
    def get_worst_contexts(self, signal_type: str, top_n: int = 5) -> List[Dict]:
        """Get worst performing contexts for a signal type."""
        if signal_type not in self.state.contextual_stats:
            return []
        
        contexts = list(self.state.contextual_stats[signal_type].values())
        
        min_samples = self.config.min_samples_per_context
        qualified = [c for c in contexts if c.sample_count >= min_samples]
        qualified.sort(key=lambda x: x.expected_win_rate)
        
        return [
            {
                "context_key": c.context_key,
                "win_rate": f"{c.win_rate:.0%}",
                "expected": f"{c.expected_win_rate:.0%}",
                "samples": c.sample_count,
                "total_pnl": f"${c.total_pnl:.2f}",
            }
            for c in qualified[:top_n]
        ]



