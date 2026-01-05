"""
Policy State Persistence

Stores and retrieves bandit policy state (per-signal-type statistics).
Provides serialization/deserialization for state.json persistence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger


@dataclass
class SignalTypeStats:
    """
    Statistics for a single signal type.
    
    Uses Beta distribution parameters (alpha, beta) for Thompson sampling.
    alpha = prior + wins
    beta = prior + losses
    """
    signal_type: str
    
    # Beta distribution parameters (starts with prior)
    alpha: float = 2.0  # Prior + successes (wins)
    beta: float = 2.0   # Prior + failures (losses)
    
    # Raw counts for observability
    wins: int = 0
    losses: int = 0
    total_signals: int = 0
    total_executions: int = 0  # Signals that were actually executed
    
    # Performance tracking
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    
    # Timestamps
    last_signal_at: Optional[str] = None
    last_win_at: Optional[str] = None
    last_loss_at: Optional[str] = None
    
    @property
    def win_rate(self) -> float:
        """Calculate observed win rate."""
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.5
    
    @property
    def sample_count(self) -> int:
        """Number of completed trades (win + loss)."""
        return self.wins + self.losses
    
    @property
    def expected_win_rate(self) -> float:
        """Expected win rate from Beta distribution (mean)."""
        return self.alpha / (self.alpha + self.beta)
    
    def record_win(self, pnl: float = 0.0) -> None:
        """Record a winning trade."""
        self.wins += 1
        self.alpha += 1.0
        self.total_pnl += pnl
        self.total_executions += 1
        self._update_avg_pnl()
        self.last_win_at = datetime.now(timezone.utc).isoformat()
    
    def record_loss(self, pnl: float = 0.0) -> None:
        """Record a losing trade."""
        self.losses += 1
        self.beta += 1.0
        self.total_pnl += pnl
        self.total_executions += 1
        self._update_avg_pnl()
        self.last_loss_at = datetime.now(timezone.utc).isoformat()
    
    def record_signal(self) -> None:
        """Record a signal was generated (regardless of execution)."""
        self.total_signals += 1
        self.last_signal_at = datetime.now(timezone.utc).isoformat()
    
    def _update_avg_pnl(self) -> None:
        """Update average P&L."""
        if self.total_executions > 0:
            self.avg_pnl = self.total_pnl / self.total_executions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "signal_type": self.signal_type,
            "alpha": self.alpha,
            "beta": self.beta,
            "wins": self.wins,
            "losses": self.losses,
            "total_signals": self.total_signals,
            "total_executions": self.total_executions,
            "total_pnl": self.total_pnl,
            "avg_pnl": self.avg_pnl,
            "win_rate": self.win_rate,
            "expected_win_rate": self.expected_win_rate,
            "sample_count": self.sample_count,
            "last_signal_at": self.last_signal_at,
            "last_win_at": self.last_win_at,
            "last_loss_at": self.last_loss_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignalTypeStats":
        """Create from dictionary."""
        stats = cls(
            signal_type=data.get("signal_type", "unknown"),
            alpha=float(data.get("alpha", 2.0)),
            beta=float(data.get("beta", 2.0)),
            wins=int(data.get("wins", 0)),
            losses=int(data.get("losses", 0)),
            total_signals=int(data.get("total_signals", 0)),
            total_executions=int(data.get("total_executions", 0)),
            total_pnl=float(data.get("total_pnl", 0.0)),
            avg_pnl=float(data.get("avg_pnl", 0.0)),
            last_signal_at=data.get("last_signal_at"),
            last_win_at=data.get("last_win_at"),
            last_loss_at=data.get("last_loss_at"),
        )
        return stats


@dataclass
class PolicyState:
    """
    Complete state of the bandit policy.
    
    Tracks per-signal-type statistics and overall policy metadata.
    """
    # Per-signal-type statistics
    signal_types: Dict[str, SignalTypeStats] = field(default_factory=dict)
    
    # Global counters
    total_decisions: int = 0
    total_executes: int = 0
    total_skips: int = 0
    
    # Last decision info (for observability)
    last_decision_at: Optional[str] = None
    last_decision_signal_type: Optional[str] = None
    last_decision_execute: Optional[bool] = None
    last_decision_reason: Optional[str] = None
    last_decision_score: Optional[float] = None
    
    # Persistence metadata
    state_version: str = "1.0"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def __post_init__(self):
        """Initialize timestamps."""
        now = datetime.now(timezone.utc).isoformat()
        if self.created_at is None:
            self.created_at = now
        self.updated_at = now
    
    def get_or_create_stats(self, signal_type: str, prior_alpha: float = 2.0, prior_beta: float = 2.0) -> SignalTypeStats:
        """Get stats for a signal type, creating if not exists."""
        if signal_type not in self.signal_types:
            self.signal_types[signal_type] = SignalTypeStats(
                signal_type=signal_type,
                alpha=prior_alpha,
                beta=prior_beta,
            )
        return self.signal_types[signal_type]
    
    def record_decision(
        self,
        signal_type: str,
        execute: bool,
        reason: str,
        score: float,
    ) -> None:
        """Record a policy decision."""
        self.total_decisions += 1
        if execute:
            self.total_executes += 1
        else:
            self.total_skips += 1
        
        self.last_decision_at = datetime.now(timezone.utc).isoformat()
        self.last_decision_signal_type = signal_type
        self.last_decision_execute = execute
        self.last_decision_reason = reason
        self.last_decision_score = score
        self.updated_at = self.last_decision_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "state_version": self.state_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_decisions": self.total_decisions,
            "total_executes": self.total_executes,
            "total_skips": self.total_skips,
            "last_decision": {
                "at": self.last_decision_at,
                "signal_type": self.last_decision_signal_type,
                "execute": self.last_decision_execute,
                "reason": self.last_decision_reason,
                "score": self.last_decision_score,
            } if self.last_decision_at else None,
            "signal_types": {
                k: v.to_dict() for k, v in self.signal_types.items()
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyState":
        """Create from dictionary."""
        state = cls(
            state_version=data.get("state_version", "1.0"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            total_decisions=int(data.get("total_decisions", 0)),
            total_executes=int(data.get("total_executes", 0)),
            total_skips=int(data.get("total_skips", 0)),
        )
        
        # Load last decision
        last_decision = data.get("last_decision")
        if last_decision:
            state.last_decision_at = last_decision.get("at")
            state.last_decision_signal_type = last_decision.get("signal_type")
            state.last_decision_execute = last_decision.get("execute")
            state.last_decision_reason = last_decision.get("reason")
            state.last_decision_score = last_decision.get("score")
        
        # Load signal type stats
        for signal_type, stats_data in data.get("signal_types", {}).items():
            state.signal_types[signal_type] = SignalTypeStats.from_dict(stats_data)
        
        return state
    
    def save(self, file_path: Path) -> None:
        """Save state to file."""
        try:
            self.updated_at = datetime.now(timezone.utc).isoformat()
            with open(file_path, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
            logger.debug(f"Policy state saved to {file_path}")
        except Exception as e:
            logger.error(f"Error saving policy state: {e}")
    
    @classmethod
    def load(cls, file_path: Path) -> "PolicyState":
        """Load state from file, or create new if not exists."""
        if not file_path.exists():
            logger.info(f"No policy state file found at {file_path}, creating new")
            return cls()
        
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
            state = cls.from_dict(data)
            logger.info(
                f"Policy state loaded: {len(state.signal_types)} signal types, "
                f"{state.total_decisions} decisions"
            )
            return state
        except Exception as e:
            logger.error(f"Error loading policy state: {e}")
            return cls()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a compact summary for Telegram display."""
        # Top performers by expected win rate
        sorted_types = sorted(
            self.signal_types.values(),
            key=lambda x: x.expected_win_rate,
            reverse=True,
        )
        
        top_types = []
        for stats in sorted_types[:3]:
            if stats.sample_count > 0:
                top_types.append({
                    "type": stats.signal_type,
                    "win_rate": f"{stats.win_rate*100:.0f}%",
                    "expected": f"{stats.expected_win_rate*100:.0f}%",
                    "samples": stats.sample_count,
                })
        
        return {
            "total_decisions": self.total_decisions,
            "execute_rate": (
                f"{self.total_executes / self.total_decisions * 100:.0f}%"
                if self.total_decisions > 0 else "N/A"
            ),
            "signal_types_tracked": len(self.signal_types),
            "top_performers": top_types,
            "last_decision": {
                "type": self.last_decision_signal_type,
                "execute": self.last_decision_execute,
                "score": f"{self.last_decision_score:.2f}" if self.last_decision_score else None,
            } if self.last_decision_at else None,
        }






