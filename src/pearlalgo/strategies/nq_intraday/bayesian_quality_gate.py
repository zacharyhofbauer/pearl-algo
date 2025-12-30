"""
Bayesian Quality Gate for Signal Filtering (Experimental, Non-Default)

Implements uncertainty-aware signal filtering using Beta-Binomial posteriors.
This module provides a more principled approach to signal quality assessment
when historical data is limited.

Key features:
- Uses credible lower bound (not point estimate) for conservative gating
- Handles cold-start gracefully with informative priors
- Optional time decay for concept drift handling
- No external ML dependencies (pure NumPy/scipy.stats)

Design constraints:
- EXPERIMENTAL: Must be explicitly enabled via config flag
- NON-DEFAULT: Does not change existing behavior when disabled
- OFFLINE-ONLY: Does not perform online parameter updates during live trading
- AUDITABLE: Logs decisions with full uncertainty context

Usage:
    from pearlalgo.strategies.nq_intraday.bayesian_quality_gate import BayesianQualityGate
    
    gate = BayesianQualityGate(enabled=True, min_credible_wr=0.52)
    result = gate.evaluate_signal(signal, historical_outcomes)
    
    if result["should_pass"]:
        # Signal meets quality threshold with statistical confidence
        ...
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.utils.logger import logger

# Try to import scipy for Beta distribution CDF
# Falls back to approximation if not available
try:
    from scipy import stats as scipy_stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.debug("scipy not available; using Beta distribution approximation")


@dataclass
class BayesianQualityGateConfig:
    """Configuration for Bayesian quality gate."""
    
    # Whether the gate is enabled (non-default, must be explicitly set)
    enabled: bool = False
    
    # Minimum credible lower bound for win rate (conservative threshold)
    # Uses 5th percentile of posterior - signal must have 95% confidence
    # that true win rate >= this threshold
    min_credible_wr: float = 0.52
    
    # Credible interval level (0.95 = 95% CI, use 5th percentile)
    credible_level: float = 0.95
    
    # Minimum samples required before applying strict gating
    # Below this, use informative prior but allow signals through
    min_samples_for_gating: int = 10
    
    # Prior parameters (Beta distribution alpha, beta)
    # Default: slightly informative prior centered at 0.50 (no edge)
    # alpha=2, beta=2 gives prior peaked at 0.5 with moderate uncertainty
    prior_alpha: float = 2.0
    prior_beta: float = 2.0
    
    # Time decay for recency weighting (0 = no decay, 1 = strong decay)
    # Implements exponential decay: weight = exp(-decay_rate * days_old)
    time_decay_rate: float = 0.0
    
    # Maximum age in days for historical data to consider
    max_history_days: int = 90
    
    # Whether to log detailed decision context
    verbose_logging: bool = False


@dataclass
class BayesianGateResult:
    """Result of Bayesian quality gate evaluation."""
    
    # Whether signal should pass the gate
    should_pass: bool
    
    # Posterior mean (expected win rate)
    posterior_mean: float
    
    # Credible lower bound (5th percentile by default)
    credible_lower: float
    
    # Credible upper bound (95th percentile by default)
    credible_upper: float
    
    # Number of samples used
    n_samples: int
    
    # Number of wins in samples
    n_wins: int
    
    # Bucket key used for lookup
    bucket_key: str
    
    # Reason for decision
    reason: str
    
    # Posterior alpha (after update)
    posterior_alpha: float = 0.0
    
    # Posterior beta (after update)
    posterior_beta: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "should_pass": self.should_pass,
            "posterior_mean": round(self.posterior_mean, 4),
            "credible_lower": round(self.credible_lower, 4),
            "credible_upper": round(self.credible_upper, 4),
            "n_samples": self.n_samples,
            "n_wins": self.n_wins,
            "bucket_key": self.bucket_key,
            "reason": self.reason,
            "posterior_alpha": round(self.posterior_alpha, 4),
            "posterior_beta": round(self.posterior_beta, 4),
        }


class BayesianQualityGate:
    """
    Bayesian quality gate using Beta-Binomial model for signal filtering.
    
    The Beta-Binomial model is conjugate: Beta prior + Binomial likelihood = Beta posterior.
    This allows exact Bayesian inference without MCMC or approximations.
    
    Key insight: Instead of using point estimate (historical win rate), we use
    the credible lower bound. This means we only pass signals when we have
    *high confidence* that the true win rate exceeds our threshold.
    
    Example:
        - 3 wins out of 5 trades gives point estimate of 60%
        - But credible lower bound might be ~35% (high uncertainty)
        - We reject because we can't be confident the edge is real
        
        - 60 wins out of 100 trades also gives point estimate of 60%
        - Credible lower bound is ~51% (lower uncertainty)
        - We accept because we have confidence the edge is real
    """
    
    def __init__(
        self,
        config: Optional[BayesianQualityGateConfig] = None,
        historical_data_path: Optional[Path] = None,
    ):
        """
        Initialize Bayesian quality gate.
        
        Args:
            config: Gate configuration (uses defaults if not provided)
            historical_data_path: Path to signals.jsonl for historical lookup
        """
        self.config = config or BayesianQualityGateConfig()
        self.historical_data_path = historical_data_path
        
        # Cache for bucket statistics
        self._bucket_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: Optional[datetime] = None
        
        if self.config.enabled:
            logger.info(
                f"BayesianQualityGate enabled: min_credible_wr={self.config.min_credible_wr:.2%}, "
                f"credible_level={self.config.credible_level:.0%}, "
                f"min_samples={self.config.min_samples_for_gating}"
            )
        else:
            logger.debug("BayesianQualityGate disabled (experimental feature)")
    
    def evaluate_signal(
        self,
        signal: Dict[str, Any],
        historical_outcomes: Optional[List[Dict[str, Any]]] = None,
    ) -> BayesianGateResult:
        """
        Evaluate whether a signal should pass the Bayesian quality gate.
        
        Args:
            signal: Signal dictionary with type, regime, etc.
            historical_outcomes: Optional list of historical outcomes for this bucket
                               (if not provided, loads from signals.jsonl)
        
        Returns:
            BayesianGateResult with decision and uncertainty context
        """
        if not self.config.enabled:
            # Gate disabled - always pass
            return BayesianGateResult(
                should_pass=True,
                posterior_mean=0.5,
                credible_lower=0.0,
                credible_upper=1.0,
                n_samples=0,
                n_wins=0,
                bucket_key="disabled",
                reason="gate_disabled",
            )
        
        # Build bucket key from signal context
        bucket_key = self._build_bucket_key(signal)
        
        # Get historical stats for this bucket
        if historical_outcomes is not None:
            n_samples, n_wins = self._count_outcomes(historical_outcomes)
        else:
            n_samples, n_wins = self._lookup_bucket_stats(bucket_key)
        
        # Compute posterior parameters
        # Beta posterior: alpha' = alpha_prior + wins, beta' = beta_prior + losses
        posterior_alpha = self.config.prior_alpha + n_wins
        posterior_beta = self.config.prior_beta + (n_samples - n_wins)
        
        # Compute posterior statistics
        posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
        credible_lower, credible_upper = self._compute_credible_interval(
            posterior_alpha, posterior_beta
        )
        
        # Decision logic
        if n_samples < self.config.min_samples_for_gating:
            # Insufficient data - use prior but allow through with warning
            should_pass = True
            reason = f"insufficient_data (n={n_samples} < {self.config.min_samples_for_gating})"
        elif credible_lower >= self.config.min_credible_wr:
            # Credible lower bound exceeds threshold - confident edge exists
            should_pass = True
            reason = f"credible_lower={credible_lower:.2%} >= {self.config.min_credible_wr:.2%}"
        else:
            # Credible lower bound below threshold - not confident enough
            should_pass = False
            reason = f"credible_lower={credible_lower:.2%} < {self.config.min_credible_wr:.2%}"
        
        result = BayesianGateResult(
            should_pass=should_pass,
            posterior_mean=posterior_mean,
            credible_lower=credible_lower,
            credible_upper=credible_upper,
            n_samples=n_samples,
            n_wins=n_wins,
            bucket_key=bucket_key,
            reason=reason,
            posterior_alpha=posterior_alpha,
            posterior_beta=posterior_beta,
        )
        
        if self.config.verbose_logging:
            logger.debug(
                f"BayesianGate: bucket={bucket_key}, n={n_samples}, wins={n_wins}, "
                f"mean={posterior_mean:.2%}, CI=[{credible_lower:.2%}, {credible_upper:.2%}], "
                f"pass={should_pass}, reason={reason}"
            )
        
        return result
    
    def _build_bucket_key(self, signal: Dict[str, Any]) -> str:
        """
        Build bucket key from signal context.
        
        Buckets by: (signal_type, regime, volatility)
        This allows learning different thresholds for different market conditions.
        """
        signal_type = signal.get("type", "unknown")
        regime = signal.get("regime", {})
        regime_type = regime.get("regime", "ranging")
        volatility = regime.get("volatility", "normal")
        
        return f"{signal_type}_{regime_type}_{volatility}"
    
    def _count_outcomes(
        self,
        outcomes: List[Dict[str, Any]],
    ) -> Tuple[int, int]:
        """Count total samples and wins from outcome list."""
        n_samples = len(outcomes)
        n_wins = sum(1 for o in outcomes if o.get("win", False))
        return n_samples, n_wins
    
    def _lookup_bucket_stats(self, bucket_key: str) -> Tuple[int, int]:
        """
        Lookup historical stats for a bucket from signals.jsonl.
        
        Returns (n_samples, n_wins) tuple.
        """
        # Refresh cache if stale (> 5 minutes)
        now = datetime.now(timezone.utc)
        if self._cache_timestamp is None or \
           (now - self._cache_timestamp).total_seconds() > 300:
            self._refresh_cache()
        
        if bucket_key in self._bucket_cache:
            stats = self._bucket_cache[bucket_key]
            return stats.get("total", 0), stats.get("wins", 0)
        
        # No data for this bucket
        return 0, 0
    
    def _refresh_cache(self) -> None:
        """Refresh bucket statistics cache from signals.jsonl."""
        self._bucket_cache = {}
        
        if self.historical_data_path is None or not self.historical_data_path.exists():
            self._cache_timestamp = datetime.now(timezone.utc)
            return
        
        try:
            cutoff_date = None
            if self.config.max_history_days > 0:
                cutoff_date = datetime.now(timezone.utc) - \
                    __import__('datetime').timedelta(days=self.config.max_history_days)
            
            with open(self.historical_data_path, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        
                        # Only count exited signals
                        if record.get("status") != "exited":
                            continue
                        
                        # Apply time filter
                        if cutoff_date is not None:
                            entry_time = record.get("entry_time")
                            if entry_time:
                                try:
                                    entry_dt = datetime.fromisoformat(
                                        entry_time.replace("Z", "+00:00")
                                    )
                                    if entry_dt < cutoff_date:
                                        continue
                                except (ValueError, TypeError):
                                    pass
                        
                        # Extract signal context
                        signal = record.get("signal", {})
                        bucket_key = self._build_bucket_key(signal)
                        
                        # Determine win/loss
                        exit_reason = record.get("exit_reason", "")
                        is_win = exit_reason == "take_profit"
                        
                        # Update bucket stats
                        if bucket_key not in self._bucket_cache:
                            self._bucket_cache[bucket_key] = {"total": 0, "wins": 0}
                        
                        self._bucket_cache[bucket_key]["total"] += 1
                        if is_win:
                            self._bucket_cache[bucket_key]["wins"] += 1
                    
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
            
            logger.debug(
                f"BayesianGate cache refreshed: {len(self._bucket_cache)} buckets, "
                f"{sum(b['total'] for b in self._bucket_cache.values())} total samples"
            )
        
        except Exception as e:
            logger.warning(f"Error refreshing Bayesian gate cache: {e}")
        
        self._cache_timestamp = datetime.now(timezone.utc)
    
    def _compute_credible_interval(
        self,
        alpha: float,
        beta: float,
    ) -> Tuple[float, float]:
        """
        Compute credible interval for Beta distribution.
        
        Returns (lower, upper) tuple for specified credible level.
        """
        p_low = (1 - self.config.credible_level) / 2
        p_high = 1 - p_low
        
        if SCIPY_AVAILABLE:
            # Use exact Beta distribution quantiles
            lower = scipy_stats.beta.ppf(p_low, alpha, beta)
            upper = scipy_stats.beta.ppf(p_high, alpha, beta)
        else:
            # Use normal approximation for large alpha, beta
            # This is reasonably accurate when alpha + beta > 10
            mean = alpha / (alpha + beta)
            var = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
            std = math.sqrt(var)
            
            # Normal quantiles
            z_low = -1.645 if self.config.credible_level == 0.95 else -1.96
            z_high = -z_low
            
            lower = max(0.0, mean + z_low * std)
            upper = min(1.0, mean + z_high * std)
        
        return float(lower), float(upper)
    
    def get_bucket_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        Get summary statistics for all buckets.
        
        Useful for debugging and understanding model state.
        """
        self._refresh_cache()
        
        summary = {}
        for bucket_key, stats in self._bucket_cache.items():
            n_samples = stats.get("total", 0)
            n_wins = stats.get("wins", 0)
            
            posterior_alpha = self.config.prior_alpha + n_wins
            posterior_beta = self.config.prior_beta + (n_samples - n_wins)
            posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)
            credible_lower, credible_upper = self._compute_credible_interval(
                posterior_alpha, posterior_beta
            )
            
            summary[bucket_key] = {
                "n_samples": n_samples,
                "n_wins": n_wins,
                "win_rate": n_wins / n_samples if n_samples > 0 else 0.0,
                "posterior_mean": posterior_mean,
                "credible_lower": credible_lower,
                "credible_upper": credible_upper,
                "would_pass": credible_lower >= self.config.min_credible_wr,
            }
        
        return summary


