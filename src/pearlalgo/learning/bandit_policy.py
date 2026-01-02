"""
Adaptive Bandit Policy

Implements Thompson sampling (Beta-Bernoulli) per signal type.
Adjusts execution decisions based on observed win/loss outcomes.

Modes:
- shadow: Observe and learn, but do NOT affect execution decisions
- live: Actually gate/adjust execution based on policy decisions
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pearlalgo.learning.policy_state import PolicyState, SignalTypeStats
from pearlalgo.utils.logger import logger


@dataclass
class BanditConfig:
    """Configuration for the bandit policy."""
    # Master toggle
    enabled: bool = True
    
    # Mode: "shadow" (observe only) or "live" (affects execution)
    mode: str = "shadow"
    
    # Thompson sampling parameters
    min_samples_per_type: int = 10  # Minimum samples before policy has opinion
    explore_rate: float = 0.1       # Random explore rate (epsilon-greedy)
    decision_threshold: float = 0.3  # Skip signal if P(win) < threshold
    
    # Position sizing adjustment
    max_size_multiplier: float = 1.5  # Maximum size boost for high-confidence
    min_size_multiplier: float = 0.5  # Minimum size reduction for low-confidence
    
    # Prior distribution parameters (Beta distribution)
    prior_alpha: float = 2.0  # Starts optimistic (2,2 = 50%)
    prior_beta: float = 2.0
    
    # Decay factor for older observations (not implemented yet)
    decay_factor: float = 0.0
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "BanditConfig":
        """Create from dictionary (e.g., from config.yaml)."""
        return cls(
            enabled=bool(config.get("enabled", True)),
            mode=str(config.get("mode", "shadow")).lower(),
            min_samples_per_type=int(config.get("min_samples_per_type", 10)),
            explore_rate=float(config.get("explore_rate", 0.1)),
            decision_threshold=float(config.get("decision_threshold", 0.3)),
            max_size_multiplier=float(config.get("max_size_multiplier", 1.5)),
            min_size_multiplier=float(config.get("min_size_multiplier", 0.5)),
            prior_alpha=float(config.get("prior_alpha", 2.0)),
            prior_beta=float(config.get("prior_beta", 2.0)),
            decay_factor=float(config.get("decay_factor", 0.0)),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "min_samples_per_type": self.min_samples_per_type,
            "explore_rate": self.explore_rate,
            "decision_threshold": self.decision_threshold,
            "max_size_multiplier": self.max_size_multiplier,
            "min_size_multiplier": self.min_size_multiplier,
            "prior_alpha": self.prior_alpha,
            "prior_beta": self.prior_beta,
            "decay_factor": self.decay_factor,
        }


@dataclass
class BanditDecision:
    """Decision from the bandit policy."""
    execute: bool           # True = recommend execution, False = skip
    reason: str             # Human-readable reason
    signal_type: str
    
    # Thompson sampling result
    sampled_score: float    # Sample from Beta distribution
    expected_win_rate: float  # Mean of Beta distribution
    
    # Size adjustment
    size_multiplier: float = 1.0
    
    # Mode context
    mode: str = "shadow"  # "shadow" or "live"
    is_explore: bool = False  # True if this was an explore decision
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "execute": self.execute,
            "reason": self.reason,
            "signal_type": self.signal_type,
            "sampled_score": self.sampled_score,
            "expected_win_rate": self.expected_win_rate,
            "size_multiplier": self.size_multiplier,
            "mode": self.mode,
            "is_explore": self.is_explore,
        }


class BanditPolicy:
    """
    Thompson Sampling bandit policy for signal type selection.
    
    Uses Beta-Bernoulli model where:
    - Each signal type has a Beta(alpha, beta) distribution
    - alpha = prior + wins
    - beta = prior + losses
    - Decision: sample from Beta, execute if sample > threshold
    
    Shadow mode: Learn from outcomes but don't affect execution.
    Live mode: Actually gate/adjust execution based on policy.
    """
    
    def __init__(
        self,
        config: BanditConfig,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize bandit policy.
        
        Args:
            config: Bandit configuration
            state_dir: Directory for state persistence (optional)
        """
        self.config = config
        self.state_dir = state_dir or Path("state")
        self.state_file = self.state_dir / "policy_state.json"
        
        # Load or create state
        self.state = PolicyState.load(self.state_file)
        
        # Random state for reproducibility in testing
        self._rng = random.Random()
        
        logger.info(
            f"BanditPolicy initialized: mode={config.mode}, "
            f"threshold={config.decision_threshold}, "
            f"signal_types={len(self.state.signal_types)}"
        )
    
    def set_seed(self, seed: int) -> None:
        """Set random seed for reproducibility (testing)."""
        self._rng.seed(seed)
    
    def decide(self, signal: Dict) -> BanditDecision:
        """
        Make a decision about whether to execute a signal.
        
        Args:
            signal: Signal dictionary with 'type', 'direction', etc.
            
        Returns:
            BanditDecision with execute recommendation
        """
        signal_type = signal.get("type", "unknown")
        
        # Get or create stats for this signal type
        stats = self.state.get_or_create_stats(
            signal_type,
            prior_alpha=self.config.prior_alpha,
            prior_beta=self.config.prior_beta,
        )
        
        # Record that we saw this signal
        stats.record_signal()
        
        # Check if we have enough samples to have an opinion
        if stats.sample_count < self.config.min_samples_per_type:
            # Not enough data - always execute (exploration)
            decision = BanditDecision(
                execute=True,
                reason=f"insufficient_samples:{stats.sample_count}/{self.config.min_samples_per_type}",
                signal_type=signal_type,
                sampled_score=stats.expected_win_rate,
                expected_win_rate=stats.expected_win_rate,
                size_multiplier=1.0,
                mode=self.config.mode,
                is_explore=True,
            )
            self._record_decision(decision)
            return decision
        
        # Epsilon-greedy exploration
        if self._rng.random() < self.config.explore_rate:
            decision = BanditDecision(
                execute=True,
                reason="explore",
                signal_type=signal_type,
                sampled_score=stats.expected_win_rate,
                expected_win_rate=stats.expected_win_rate,
                size_multiplier=1.0,
                mode=self.config.mode,
                is_explore=True,
            )
            self._record_decision(decision)
            return decision
        
        # Thompson sampling: sample from Beta distribution
        sampled_score = self._rng.betavariate(stats.alpha, stats.beta)
        expected_win_rate = stats.expected_win_rate
        
        # Decision: execute if sampled score > threshold
        execute = sampled_score >= self.config.decision_threshold
        
        # Calculate size multiplier based on expected win rate
        size_multiplier = self._calculate_size_multiplier(expected_win_rate)
        
        # Build reason
        if execute:
            reason = f"thompson_pass:{sampled_score:.2f}>={self.config.decision_threshold}"
        else:
            reason = f"thompson_skip:{sampled_score:.2f}<{self.config.decision_threshold}"
        
        decision = BanditDecision(
            execute=execute,
            reason=reason,
            signal_type=signal_type,
            sampled_score=sampled_score,
            expected_win_rate=expected_win_rate,
            size_multiplier=size_multiplier,
            mode=self.config.mode,
            is_explore=False,
        )
        
        self._record_decision(decision)
        return decision
    
    def _calculate_size_multiplier(self, expected_win_rate: float) -> float:
        """
        Calculate position size multiplier based on expected win rate.
        
        Higher expected win rate -> larger size (up to max_size_multiplier)
        Lower expected win rate -> smaller size (down to min_size_multiplier)
        """
        # Linear interpolation between min and max based on win rate
        # win_rate 0.0 -> min_size_multiplier
        # win_rate 1.0 -> max_size_multiplier
        # win_rate 0.5 -> 1.0 (neutral)
        
        if expected_win_rate >= 0.5:
            # Above 50% - scale up
            scale = (expected_win_rate - 0.5) / 0.5  # 0 to 1
            multiplier = 1.0 + scale * (self.config.max_size_multiplier - 1.0)
        else:
            # Below 50% - scale down
            scale = (0.5 - expected_win_rate) / 0.5  # 0 to 1
            multiplier = 1.0 - scale * (1.0 - self.config.min_size_multiplier)
        
        return round(multiplier, 2)
    
    def _record_decision(self, decision: BanditDecision) -> None:
        """Record a decision in state."""
        self.state.record_decision(
            signal_type=decision.signal_type,
            execute=decision.execute,
            reason=decision.reason,
            score=decision.sampled_score,
        )
    
    def record_outcome(
        self,
        signal_id: str,
        signal_type: str,
        is_win: bool,
        pnl: float = 0.0,
    ) -> None:
        """
        Record the outcome of a trade for learning.
        
        Args:
            signal_id: Signal identifier (for logging)
            signal_type: Type of signal (e.g., "sr_bounce")
            is_win: True if trade was profitable
            pnl: P&L in dollars
        """
        stats = self.state.get_or_create_stats(
            signal_type,
            prior_alpha=self.config.prior_alpha,
            prior_beta=self.config.prior_beta,
        )
        
        if is_win:
            stats.record_win(pnl)
            logger.info(
                f"BanditPolicy: WIN recorded for {signal_type} | "
                f"pnl=${pnl:.2f} | new_win_rate={stats.win_rate:.0%} | "
                f"samples={stats.sample_count}"
            )
        else:
            stats.record_loss(pnl)
            logger.info(
                f"BanditPolicy: LOSS recorded for {signal_type} | "
                f"pnl=${pnl:.2f} | new_win_rate={stats.win_rate:.0%} | "
                f"samples={stats.sample_count}"
            )
        
        # Save state after each outcome
        self.save_state()
    
    def save_state(self) -> None:
        """Save policy state to disk."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.state.save(self.state_file)
        except Exception as e:
            logger.error(f"Error saving policy state: {e}")
    
    def load_state(self) -> None:
        """Reload policy state from disk."""
        self.state = PolicyState.load(self.state_file)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current policy status for observability."""
        return {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "decision_threshold": self.config.decision_threshold,
            "min_samples": self.config.min_samples_per_type,
            "explore_rate": self.config.explore_rate,
            "total_decisions": self.state.total_decisions,
            "total_executes": self.state.total_executes,
            "total_skips": self.state.total_skips,
            "execute_rate": (
                round(self.state.total_executes / max(1, self.state.total_decisions), 2)
            ),
            "signal_types_tracked": len(self.state.signal_types),
            "last_decision": {
                "signal_type": self.state.last_decision_signal_type,
                "execute": self.state.last_decision_execute,
                "score": self.state.last_decision_score,
                "reason": self.state.last_decision_reason,
                "at": self.state.last_decision_at,
            } if self.state.last_decision_at else None,
        }
    
    def get_signal_type_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get per-signal-type summary for observability."""
        return {
            signal_type: {
                "wins": stats.wins,
                "losses": stats.losses,
                "win_rate": f"{stats.win_rate:.0%}",
                "expected": f"{stats.expected_win_rate:.0%}",
                "samples": stats.sample_count,
                "total_pnl": f"${stats.total_pnl:.2f}",
                "avg_pnl": f"${stats.avg_pnl:.2f}",
            }
            for signal_type, stats in self.state.signal_types.items()
        }
    
    def get_telegram_summary(self) -> str:
        """Get compact summary for Telegram display."""
        lines = ["📊 *AI Policy Status*"]
        lines.append(f"Mode: `{self.config.mode}`")
        lines.append(f"Decisions: {self.state.total_decisions} ({self.state.total_executes}✓ / {self.state.total_skips}✗)")
        
        if self.state.signal_types:
            lines.append("\n*Signal Types:*")
            
            # Sort by sample count (most data first)
            sorted_types = sorted(
                self.state.signal_types.values(),
                key=lambda x: x.sample_count,
                reverse=True,
            )
            
            for stats in sorted_types[:5]:  # Top 5
                if stats.sample_count > 0:
                    emoji = "🟢" if stats.win_rate >= 0.5 else "🔴"
                    lines.append(
                        f"{emoji} `{stats.signal_type}`: "
                        f"{stats.wins}W/{stats.losses}L "
                        f"({stats.win_rate:.0%})"
                    )
        
        return "\n".join(lines)





