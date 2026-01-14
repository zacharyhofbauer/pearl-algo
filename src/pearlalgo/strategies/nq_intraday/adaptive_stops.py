"""
Adaptive Stop Loss and Take Profit Calculator

Context-aware stop loss and take profit calculation that adapts to:
- Market regime (ranging vs trending)
- Session (Tokyo, London, NY)
- Volatility state (low, normal, high)
- Signal type historical performance
- Market structure (swing points, S/R zones)

Replaces generic ATR-based stops with intelligent, context-sensitive stops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pearlalgo.utils.logger import logger

# Import market depth analyzer for structure-based stops
try:
    from pearlalgo.strategies.nq_intraday.market_depth import (
        MarketDepthAnalyzer,
        get_market_depth_analyzer,
    )
    MARKET_DEPTH_AVAILABLE = True
except ImportError:
    MARKET_DEPTH_AVAILABLE = False
    MarketDepthAnalyzer = None  # type: ignore


# =============================================================================
# Risk Profile Definitions
# =============================================================================

@dataclass
class SignalTypeRiskProfile:
    """Risk profile for a specific signal type."""
    signal_type: str
    enabled: bool = True
    
    # Stop loss settings
    base_stop_multiplier: float = 1.5  # Base ATR multiplier
    min_stop_multiplier: float = 1.0   # Minimum ATR multiplier
    max_stop_multiplier: float = 3.0   # Maximum ATR multiplier
    
    # Take profit settings
    target_risk_reward: float = 1.5    # Target R:R ratio
    min_risk_reward: float = 1.2       # Minimum R:R to accept
    
    # Time management
    max_hold_minutes: int = 30         # Max hold time
    
    # Regime preferences
    favorable_regimes: List[str] = field(default_factory=list)
    unfavorable_regimes: List[str] = field(default_factory=list)
    
    # Session preferences  
    favorable_sessions: List[str] = field(default_factory=list)
    
    # Sizing behavior
    size_scaling: str = "normal"  # "aggressive", "normal", "conservative"
    
    # Historical performance (updated dynamically)
    historical_win_rate: float = 0.5
    historical_avg_win: float = 200.0
    historical_avg_loss: float = 150.0


# Default risk profiles based on observed performance
DEFAULT_RISK_PROFILES: Dict[str, SignalTypeRiskProfile] = {
    "mean_reversion_long": SignalTypeRiskProfile(
        signal_type="mean_reversion_long",
        enabled=True,
        base_stop_multiplier=1.3,
        target_risk_reward=1.5,
        max_hold_minutes=30,
        favorable_regimes=["ranging", "trending_bullish"],
        unfavorable_regimes=["trending_bearish"],
        favorable_sessions=["new_york", "london"],
        size_scaling="aggressive",
        historical_win_rate=0.47,
        historical_avg_win=400.0,
        historical_avg_loss=180.0,
    ),
    "mean_reversion_short": SignalTypeRiskProfile(
        signal_type="mean_reversion_short",
        enabled=True,
        base_stop_multiplier=1.8,  # Wider stops for lower WR
        target_risk_reward=2.0,    # Higher R:R required
        max_hold_minutes=30,
        favorable_regimes=["ranging", "trending_bearish"],
        unfavorable_regimes=["trending_bullish"],
        favorable_sessions=["new_york"],
        size_scaling="conservative",
        historical_win_rate=0.33,
        historical_avg_win=300.0,
        historical_avg_loss=200.0,
    ),
    "sr_bounce_long": SignalTypeRiskProfile(
        signal_type="sr_bounce_long",
        enabled=True,
        base_stop_multiplier=1.5,
        target_risk_reward=2.0,
        max_hold_minutes=20,
        favorable_regimes=["trending_bullish"],
        unfavorable_regimes=["trending_bearish"],
        favorable_sessions=["new_york"],
        size_scaling="normal",
        historical_win_rate=0.40,
        historical_avg_win=350.0,
        historical_avg_loss=200.0,
    ),
    "sr_bounce_short": SignalTypeRiskProfile(
        signal_type="sr_bounce_short",
        enabled=False,  # DISABLED - 0% WR
        base_stop_multiplier=2.0,
        target_risk_reward=2.5,
        historical_win_rate=0.0,
    ),
    "momentum_long": SignalTypeRiskProfile(
        signal_type="momentum_long",
        enabled=False,  # DISABLED - 0% WR
        base_stop_multiplier=1.5,
        target_risk_reward=1.5,
        historical_win_rate=0.0,
    ),
    "momentum_short": SignalTypeRiskProfile(
        signal_type="momentum_short",
        enabled=True,
        base_stop_multiplier=1.5,
        target_risk_reward=1.5,
        max_hold_minutes=20,
        favorable_regimes=["trending_bearish"],
        unfavorable_regimes=["trending_bullish"],
        favorable_sessions=["new_york"],
        size_scaling="normal",
        historical_win_rate=0.50,
        historical_avg_win=290.0,
        historical_avg_loss=250.0,
    ),
    "breakout_long": SignalTypeRiskProfile(
        signal_type="breakout_long",
        enabled=True,
        base_stop_multiplier=1.5,
        target_risk_reward=2.0,
        favorable_regimes=["trending_bullish"],
        favorable_sessions=["new_york"],
        size_scaling="conservative",
        historical_win_rate=0.45,
    ),
    "breakout_short": SignalTypeRiskProfile(
        signal_type="breakout_short",
        enabled=True,
        base_stop_multiplier=1.5,
        target_risk_reward=2.0,
        favorable_regimes=["trending_bearish"],
        favorable_sessions=["new_york"],
        size_scaling="conservative",
        historical_win_rate=0.45,
    ),
    "vwap_reversion": SignalTypeRiskProfile(
        signal_type="vwap_reversion",
        enabled=True,
        base_stop_multiplier=1.3,
        target_risk_reward=1.5,
        favorable_regimes=["ranging"],
        favorable_sessions=["new_york", "london"],
        size_scaling="normal",
        historical_win_rate=0.50,
    ),
}


# =============================================================================
# Multiplier Configuration
# =============================================================================

# Regime-based stop multiplier adjustments
REGIME_MULTIPLIERS = {
    "ranging": 1.0,           # Base stops for ranging markets
    "trending_bullish": 1.2,  # Wider stops in trending markets
    "trending_bearish": 1.2,  # Wider stops in trending markets
    "high_volatility": 1.4,   # Even wider in high volatility
    "unknown": 1.1,           # Slightly wider when uncertain
}

# Session-based stop multiplier adjustments
SESSION_MULTIPLIERS = {
    "tokyo": 0.8,      # Tighter stops during Tokyo (low vol)
    "london": 0.9,     # Slightly tighter during London
    "new_york": 1.0,   # Full stops during NY (highest vol)
    "asia": 0.8,       # Alias for Tokyo
    "overlap": 1.1,    # Wider during session overlaps
    "unknown": 0.9,    # Conservative when unknown
}

# Volatility-based stop multiplier adjustments
VOLATILITY_MULTIPLIERS = {
    "low": 0.9,        # Tighter stops in low volatility
    "normal": 1.0,     # Base stops
    "high": 1.3,       # Wider stops in high volatility
    "extreme": 1.5,    # Much wider in extreme volatility
}


# =============================================================================
# Adaptive Stop Calculator
# =============================================================================

@dataclass
class StopTakeProfit:
    """Result of stop loss and take profit calculation."""
    stop_loss: float
    take_profit: float
    
    # Metadata
    atr_used: float
    final_multiplier: float
    risk_reward_ratio: float
    
    # Adjustment factors
    regime_multiplier: float = 1.0
    session_multiplier: float = 1.0
    volatility_multiplier: float = 1.0
    performance_multiplier: float = 1.0
    
    # Structure-based adjustments
    structure_stop_used: bool = False
    structure_stop_price: Optional[float] = None
    
    # Market depth adjustments
    stop_adjusted_for_zones: bool = False
    original_stop: Optional[float] = None
    adjustment_reason: str = ""
    
    # Anti-hunt jitter
    jitter_applied: float = 0.0  # Points of jitter added to stop
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "atr_used": self.atr_used,
            "final_multiplier": self.final_multiplier,
            "risk_reward_ratio": self.risk_reward_ratio,
            "regime_multiplier": self.regime_multiplier,
            "session_multiplier": self.session_multiplier,
            "volatility_multiplier": self.volatility_multiplier,
            "performance_multiplier": self.performance_multiplier,
            "structure_stop_used": self.structure_stop_used,
            "structure_stop_price": self.structure_stop_price,
            "stop_adjusted_for_zones": self.stop_adjusted_for_zones,
            "original_stop": self.original_stop,
            "adjustment_reason": self.adjustment_reason,
            "jitter_applied": self.jitter_applied,
        }


class AdaptiveStopCalculator:
    """
    Context-aware stop loss and take profit calculator.
    
    Adapts stops based on:
    1. Signal type risk profile
    2. Market regime (ranging, trending_bullish, trending_bearish)
    3. Trading session (Tokyo, London, NY)
    4. Current volatility state
    5. Historical performance of signal type
    6. Market structure (swing points, S/R zones)
    """
    
    def __init__(
        self,
        risk_profiles: Optional[Dict[str, SignalTypeRiskProfile]] = None,
        use_structure_stops: bool = True,
        use_market_depth: bool = True,
        max_stop_points: float = 25.0,  # Maximum stop distance in points
        min_stop_points: float = 5.0,   # Minimum stop distance in points
        anti_hunt_jitter: bool = True,  # Add randomization to avoid predictable stops
        jitter_range_points: float = 3.0,  # Max jitter range in points (±)
    ):
        """
        Initialize the adaptive stop calculator.
        
        Args:
            risk_profiles: Custom risk profiles per signal type
            use_structure_stops: Use swing-based structure stops
            use_market_depth: Use market depth for stop adjustment
            max_stop_points: Maximum stop distance from entry
            min_stop_points: Minimum stop distance from entry
            anti_hunt_jitter: Add randomization to stops to avoid predictable hunting
            jitter_range_points: Maximum jitter range in points (±)
        """
        self.risk_profiles = risk_profiles or DEFAULT_RISK_PROFILES.copy()
        self.use_structure_stops = use_structure_stops
        self.use_market_depth = use_market_depth
        self.max_stop_points = max_stop_points
        self.min_stop_points = min_stop_points
        self.anti_hunt_jitter = anti_hunt_jitter
        self.jitter_range_points = jitter_range_points
        
        # Initialize market depth analyzer if available
        self._depth_analyzer: Optional[MarketDepthAnalyzer] = None
        if use_market_depth and MARKET_DEPTH_AVAILABLE:
            self._depth_analyzer = get_market_depth_analyzer()
        
        logger.info(
            f"AdaptiveStopCalculator initialized: "
            f"structure_stops={use_structure_stops}, "
            f"market_depth={use_market_depth and self._depth_analyzer is not None}, "
            f"max_stop={max_stop_points}pts, "
            f"anti_hunt_jitter={anti_hunt_jitter} (±{jitter_range_points}pts)"
        )
    
    def calculate_stop_take_profit(
        self,
        signal_type: str,
        direction: str,
        entry_price: float,
        atr: float,
        context: Dict[str, Any],
        df: Optional[pd.DataFrame] = None,
    ) -> StopTakeProfit:
        """
        Calculate adaptive stop loss and take profit.
        
        Args:
            signal_type: Type of signal (e.g., "mean_reversion_long")
            direction: "long" or "short"
            entry_price: Entry price
            atr: Current ATR value
            context: Market context dict with regime, session, volatility
            df: Optional DataFrame for structure-based stops
            
        Returns:
            StopTakeProfit with calculated levels and metadata
        """
        # Get risk profile for this signal type
        profile = self._get_risk_profile(signal_type)
        
        # Extract context
        regime = context.get("regime", {}).get("regime", "unknown")
        volatility = context.get("regime", {}).get("volatility", "normal")
        session = context.get("regime", {}).get("session", "unknown")
        
        # Calculate multipliers
        regime_mult = self._get_regime_multiplier(regime, signal_type, profile)
        session_mult = self._get_session_multiplier(session, signal_type, profile)
        vol_mult = self._get_volatility_multiplier(volatility)
        perf_mult = self._get_performance_multiplier(profile)
        
        # Calculate final multiplier
        final_mult = (
            profile.base_stop_multiplier *
            regime_mult *
            session_mult *
            vol_mult *
            perf_mult
        )
        
        # Clamp to profile limits
        final_mult = np.clip(
            final_mult,
            profile.min_stop_multiplier,
            profile.max_stop_multiplier,
        )
        
        # Calculate raw ATR-based stop
        stop_distance = atr * final_mult
        
        # Apply hard limits
        stop_distance = np.clip(
            stop_distance,
            self.min_stop_points,
            self.max_stop_points,
        )
        
        if direction == "long":
            raw_stop = entry_price - stop_distance
        else:
            raw_stop = entry_price + stop_distance
        
        # Check for structure-based stop
        structure_stop = None
        structure_used = False
        
        if self.use_structure_stops and df is not None and self._depth_analyzer:
            structure_stop = self._depth_analyzer.find_structure_stop(
                direction=direction,
                entry_price=entry_price,
                df=df,
                atr=atr,
                max_stop_distance=self.max_stop_points,
            )
            
            if structure_stop is not None:
                # Use structure stop if it's better (tighter but not too tight)
                structure_distance = abs(entry_price - structure_stop)
                
                if self.min_stop_points <= structure_distance <= stop_distance:
                    # Structure stop is tighter but respects minimum
                    raw_stop = structure_stop
                    structure_used = True
                    logger.debug(
                        f"Using structure stop: ${structure_stop:.2f} "
                        f"(saved {stop_distance - structure_distance:.2f} pts)"
                    )
        
        # Check market depth for stop adjustment
        adjusted_stop = raw_stop
        stop_adjusted = False
        adjustment_reason = ""
        
        if self.use_market_depth and df is not None and self._depth_analyzer:
            advice = self._depth_analyzer.get_stop_placement_advice(
                direction=direction,
                entry_price=entry_price,
                raw_stop=raw_stop,
                atr=atr,
                df=df,
            )
            
            if advice.recommended_stop != raw_stop:
                adjusted_stop = advice.recommended_stop
                stop_adjusted = True
                adjustment_reason = advice.adjustment_reason
                logger.debug(f"Stop adjusted: {adjustment_reason}")
        
        # Calculate final stop
        final_stop = adjusted_stop
        
        # Ensure stop respects hard limits
        stop_distance_final = abs(entry_price - final_stop)
        if stop_distance_final > self.max_stop_points:
            if direction == "long":
                final_stop = entry_price - self.max_stop_points
            else:
                final_stop = entry_price + self.max_stop_points
            adjustment_reason = f"Capped to max {self.max_stop_points} pts"
        
        # Anti-hunt jitter: add small random offset to avoid clustering stops at obvious levels
        # This makes stops less predictable and harder for market makers to hunt
        jitter_applied = 0.0
        if self.anti_hunt_jitter and self.jitter_range_points > 0:
            # Generate random jitter (always widen the stop, never tighten)
            # This gives the trade more room while maintaining unpredictability
            jitter = np.random.uniform(0, self.jitter_range_points)
            
            if direction == "long":
                final_stop = final_stop - jitter  # Widen by moving stop lower
            else:
                final_stop = final_stop + jitter  # Widen by moving stop higher
            
            jitter_applied = jitter
            
            # Log jitter application
            logger.debug(
                f"Anti-hunt jitter applied: {jitter:.2f} pts "
                f"(stop moved from {adjusted_stop:.2f} to {final_stop:.2f})"
            )
        
        # Calculate take profit based on risk-reward
        risk = abs(entry_price - final_stop)
        reward = risk * profile.target_risk_reward
        
        if direction == "long":
            take_profit = entry_price + reward
        else:
            take_profit = entry_price - reward
        
        # Calculate actual R:R
        actual_rr = reward / risk if risk > 0 else 0
        
        return StopTakeProfit(
            stop_loss=final_stop,
            take_profit=take_profit,
            atr_used=atr,
            final_multiplier=final_mult,
            risk_reward_ratio=actual_rr,
            regime_multiplier=regime_mult,
            session_multiplier=session_mult,
            volatility_multiplier=vol_mult,
            performance_multiplier=perf_mult,
            structure_stop_used=structure_used,
            structure_stop_price=structure_stop,
            stop_adjusted_for_zones=stop_adjusted,
            original_stop=raw_stop if stop_adjusted else None,
            adjustment_reason=adjustment_reason,
            jitter_applied=jitter_applied,
        )
    
    def _get_risk_profile(self, signal_type: str) -> SignalTypeRiskProfile:
        """Get risk profile for a signal type."""
        if signal_type in self.risk_profiles:
            return self.risk_profiles[signal_type]
        
        # Try to match by prefix (e.g., "sr_bounce_long" -> "sr_bounce")
        for profile_name, profile in self.risk_profiles.items():
            if signal_type.startswith(profile_name):
                return profile
        
        # Return default profile
        return SignalTypeRiskProfile(
            signal_type=signal_type,
            base_stop_multiplier=1.5,
            target_risk_reward=1.5,
        )
    
    def _get_regime_multiplier(
        self,
        regime: str,
        signal_type: str,
        profile: SignalTypeRiskProfile,
    ) -> float:
        """Get regime-based stop multiplier."""
        base_mult = REGIME_MULTIPLIERS.get(regime.lower(), 1.0)
        
        # Adjust based on signal type's regime preferences
        if profile.favorable_regimes and regime.lower() in [r.lower() for r in profile.favorable_regimes]:
            # Favorable regime - can use tighter stops
            base_mult *= 0.9
        elif profile.unfavorable_regimes and regime.lower() in [r.lower() for r in profile.unfavorable_regimes]:
            # Unfavorable regime - need wider stops
            base_mult *= 1.2
        
        return base_mult
    
    def _get_session_multiplier(
        self,
        session: str,
        signal_type: str,
        profile: SignalTypeRiskProfile,
    ) -> float:
        """Get session-based stop multiplier."""
        base_mult = SESSION_MULTIPLIERS.get(session.lower(), 0.9)
        
        # Adjust based on signal type's session preferences
        if profile.favorable_sessions and session.lower() in [s.lower() for s in profile.favorable_sessions]:
            # Favorable session - normal stops
            pass  # Keep base multiplier
        elif profile.favorable_sessions:
            # Not in favorable sessions - need wider stops
            base_mult *= 1.1
        
        return base_mult
    
    def _get_volatility_multiplier(self, volatility: str) -> float:
        """Get volatility-based stop multiplier."""
        return VOLATILITY_MULTIPLIERS.get(volatility.lower(), 1.0)
    
    def _get_performance_multiplier(self, profile: SignalTypeRiskProfile) -> float:
        """Get performance-based stop multiplier."""
        win_rate = profile.historical_win_rate
        
        # Low win rate = need wider stops to let winners run
        # High win rate = can use tighter stops
        if win_rate >= 0.55:
            return 0.9  # Tighter stops for high WR
        elif win_rate >= 0.45:
            return 1.0  # Normal stops
        elif win_rate >= 0.35:
            return 1.1  # Slightly wider for low WR
        else:
            return 1.2  # Much wider for very low WR (or disable signal type)
    
    def update_risk_profile(
        self,
        signal_type: str,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> None:
        """
        Update risk profile with new performance data.
        
        Args:
            signal_type: Signal type to update
            win_rate: New win rate (0-1)
            avg_win: Average win amount
            avg_loss: Average loss amount
        """
        if signal_type in self.risk_profiles:
            profile = self.risk_profiles[signal_type]
            profile.historical_win_rate = win_rate
            profile.historical_avg_win = avg_win
            profile.historical_avg_loss = avg_loss
            
            # Adjust target R:R based on win rate (Kelly-like)
            if win_rate > 0 and win_rate < 1:
                # For lower win rates, need higher R:R
                # For higher win rates, can accept lower R:R
                kelly_rr = (1 - win_rate) / win_rate
                profile.target_risk_reward = max(1.2, min(3.0, kelly_rr * 1.2))
                
            logger.debug(
                f"Updated risk profile for {signal_type}: "
                f"WR={win_rate:.0%}, target_rr={profile.target_risk_reward:.1f}"
            )
    
    def get_profile_summary(self) -> Dict[str, Any]:
        """Get summary of all risk profiles."""
        return {
            name: {
                "enabled": profile.enabled,
                "base_stop_mult": profile.base_stop_multiplier,
                "target_rr": profile.target_risk_reward,
                "win_rate": profile.historical_win_rate,
                "favorable_regimes": profile.favorable_regimes,
                "size_scaling": profile.size_scaling,
            }
            for name, profile in self.risk_profiles.items()
        }


# =============================================================================
# Factory Function
# =============================================================================

def get_adaptive_stop_calculator(
    config: Optional[Dict[str, Any]] = None,
) -> AdaptiveStopCalculator:
    """
    Create an AdaptiveStopCalculator from configuration.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        AdaptiveStopCalculator instance
    """
    if config is None:
        config = {}
    
    adaptive_config = config.get("adaptive_stops", {})
    
    # Build risk profiles from config overrides
    risk_profiles = DEFAULT_RISK_PROFILES.copy()

    # Pull per-signal regime/session constraints from the canonical config location:
    # config.yaml -> signals.regime_filters
    signals_cfg = config.get("signals", {}) or {}
    regime_filters = signals_cfg.get("regime_filters", {}) or {}
    if isinstance(regime_filters, dict):
        for signal_type, filt in regime_filters.items():
            if signal_type not in risk_profiles or not isinstance(filt, dict):
                continue
            profile = risk_profiles[signal_type]

            allowed_regimes = filt.get("allowed_regimes")
            if allowed_regimes:
                profile.favorable_regimes = list(allowed_regimes)

            forbidden_regimes = filt.get("forbidden_regimes") or filt.get("disallowed_regimes")
            if forbidden_regimes:
                profile.unfavorable_regimes = list(forbidden_regimes)

            allowed_sessions = filt.get("allowed_sessions")
            if allowed_sessions:
                profile.favorable_sessions = list(allowed_sessions)
    
    return AdaptiveStopCalculator(
        risk_profiles=risk_profiles,
        use_structure_stops=adaptive_config.get("use_structure_stops", True),
        use_market_depth=adaptive_config.get("use_level2_zones", True),
        max_stop_points=config.get("signals", {}).get("max_stop_points", 25.0),
        min_stop_points=adaptive_config.get("min_stop_points", 5.0),
        anti_hunt_jitter=adaptive_config.get("anti_hunt_jitter", True),
        jitter_range_points=adaptive_config.get("jitter_range_points", 3.0),
    )

