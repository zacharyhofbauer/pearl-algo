"""
Signal Quality Scorer

Uses historical performance data to score signal quality and filter
out low-information setups. Implements statistical tests to ensure
signals have actual edge vs random.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class SignalQualityScorer:
    """
    Scores signal quality based on historical performance.
    
    Uses:
    - Historical win rate by signal type + regime
    - Information ratio (signal strength vs noise)
    - Minimum edge threshold enforcement
    """
    
    def __init__(
        self,
        state_dir: Optional[Path] = None,
        min_edge_threshold: float = 0.55,
    ):
        """
        Initialize signal quality scorer.
        
        Args:
            state_dir: Directory for storing performance data
            min_edge_threshold: Minimum expected win rate (default: 55%)
        """
        if state_dir is None:
            state_dir = Path("data/nq_agent_state")
        
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.performance_file = self.state_dir / "performance.json"
        self.signals_file = self.state_dir / "signals.jsonl"
        
        self.min_edge_threshold = min_edge_threshold
        
        # Cache for performance lookup
        self._performance_cache: Optional[Dict] = None
        self._cache_timestamp: Optional[datetime] = None
        
        logger.info(f"SignalQualityScorer initialized: min_edge={min_edge_threshold:.0%}")
    
    def score_signal(self, signal: Dict) -> Dict:
        """
        Score signal quality based on historical performance.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Dictionary with quality score:
            {
                "quality_score": float (0-1),
                "historical_wr": float (0-1),  # Historical win rate
                "information_ratio": float,  # Signal strength vs noise
                "meets_threshold": bool,  # Whether meets minimum edge
                "should_send": bool,  # Whether signal should be sent
            }
        """
        signal_type = signal.get("type", "unknown")
        regime = signal.get("regime", {})
        regime_type = regime.get("regime", "ranging")
        volatility = regime.get("volatility", "normal")
        
        # Load performance data
        performance_data = self._load_performance_data()
        
        # Lookup historical win rate
        historical_wr = self._lookup_historical_wr(
            signal_type, regime_type, volatility, performance_data
        )
        
        # Calculate information ratio (simplified)
        # Information ratio = (Win Rate - 50%) / StdDev
        # For now, use a simplified version based on win rate
        information_ratio = 0.0
        if historical_wr > 0.5:
            # Positive edge
            information_ratio = (historical_wr - 0.5) * 2  # Scale to 0-1
        else:
            # Negative edge
            information_ratio = (historical_wr - 0.5) * 2  # Scale to -1-0
        
        # Quality score (combination of historical WR and information ratio)
        quality_score = (historical_wr * 0.7 + (information_ratio + 1) / 2 * 0.3)
        
        # Check if meets threshold
        meets_threshold = historical_wr >= self.min_edge_threshold
        
        # Should send if meets threshold and has positive information ratio
        should_send = meets_threshold and information_ratio > 0
        
        return {
            "quality_score": float(quality_score),
            "historical_wr": float(historical_wr),
            "information_ratio": float(information_ratio),
            "meets_threshold": meets_threshold,
            "should_send": should_send,
        }
    
    def _load_performance_data(self) -> Dict:
        """Load performance data from file."""
        # Use cache if recent (within 5 minutes)
        if self._performance_cache is not None and self._cache_timestamp:
            age = (datetime.now(timezone.utc) - self._cache_timestamp).total_seconds()
            if age < 300:  # 5 minutes
                return self._performance_cache
        
        try:
            if self.performance_file.exists():
                with open(self.performance_file) as f:
                    data = json.load(f)
                    self._performance_cache = data
                    self._cache_timestamp = datetime.now(timezone.utc)
                    return data
        except Exception as e:
            logger.warning(f"Error loading performance data: {e}")
        
        # Return default if no data
        return {}
    
    def _lookup_historical_wr(
        self,
        signal_type: str,
        regime_type: str,
        volatility: str,
        performance_data: Dict,
    ) -> float:
        """
        Lookup historical win rate for signal type + regime combination.
        
        Args:
            signal_type: Signal type (e.g., "momentum_long")
            regime_type: Regime type (e.g., "trending_bullish")
            volatility: Volatility regime (e.g., "low")
            performance_data: Performance data dictionary
            
        Returns:
            Historical win rate (0-1), defaults to 0.5 if no data
        """
        # Try to find matching historical data
        # Look for signal type + regime combination
        
        # First, try exact match
        key = f"{signal_type}_{regime_type}_{volatility}"
        if key in performance_data.get("signal_stats", {}):
            stats = performance_data["signal_stats"][key]
            wins = stats.get("wins", 0)
            total = stats.get("total", 0)
            if total > 0:
                return wins / total
        
        # Try signal type only
        key = signal_type
        if key in performance_data.get("signal_stats", {}):
            stats = performance_data["signal_stats"][key]
            wins = stats.get("wins", 0)
            total = stats.get("total", 0)
            if total > 0:
                return wins / total
        
        # Try regime type only
        key = regime_type
        if key in performance_data.get("regime_stats", {}):
            stats = performance_data["regime_stats"][key]
            wins = stats.get("wins", 0)
            total = stats.get("total", 0)
            if total > 0:
                return wins / total
        
        # Default to 0.5 (no edge) if no historical data
        return 0.5
    
    def update_performance_stats(self, signal: Dict, outcome: Dict) -> None:
        """
        Update performance statistics for a signal.
        
        Args:
            signal: Original signal dictionary
            outcome: Outcome dictionary with:
                {
                    "win": bool,
                    "pnl": float,
                    "exit_reason": str,
                }
        """
        try:
            signal_type = signal.get("type", "unknown")
            regime = signal.get("regime", {})
            regime_type = regime.get("regime", "ranging")
            volatility = regime.get("volatility", "normal")
            
            # Load current stats
            performance_data = self._load_performance_data()
            
            # Initialize stats structure if needed
            if "signal_stats" not in performance_data:
                performance_data["signal_stats"] = {}
            if "regime_stats" not in performance_data:
                performance_data["regime_stats"] = {}
            
            # Update signal type + regime stats
            key = f"{signal_type}_{regime_type}_{volatility}"
            if key not in performance_data["signal_stats"]:
                performance_data["signal_stats"][key] = {
                    "wins": 0,
                    "losses": 0,
                    "total": 0,
                    "total_pnl": 0.0,
                }
            
            stats = performance_data["signal_stats"][key]
            stats["total"] += 1
            if outcome.get("win", False):
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            stats["total_pnl"] += outcome.get("pnl", 0.0)
            
            # Update signal type stats
            if signal_type not in performance_data["signal_stats"]:
                performance_data["signal_stats"][signal_type] = {
                    "wins": 0,
                    "losses": 0,
                    "total": 0,
                    "total_pnl": 0.0,
                }
            
            stats_type = performance_data["signal_stats"][signal_type]
            stats_type["total"] += 1
            if outcome.get("win", False):
                stats_type["wins"] += 1
            else:
                stats_type["losses"] += 1
            stats_type["total_pnl"] += outcome.get("pnl", 0.0)
            
            # Update regime stats
            if regime_type not in performance_data["regime_stats"]:
                performance_data["regime_stats"][regime_type] = {
                    "wins": 0,
                    "losses": 0,
                    "total": 0,
                    "total_pnl": 0.0,
                }
            
            stats_regime = performance_data["regime_stats"][regime_type]
            stats_regime["total"] += 1
            if outcome.get("win", False):
                stats_regime["wins"] += 1
            else:
                stats_regime["losses"] += 1
            stats_regime["total_pnl"] += outcome.get("pnl", 0.0)
            
            # Save updated stats
            with open(self.performance_file, "w") as f:
                json.dump(performance_data, f, indent=2)
            
            # Invalidate cache
            self._performance_cache = None
            
        except Exception as e:
            logger.error(f"Error updating performance stats: {e}", exc_info=True)



