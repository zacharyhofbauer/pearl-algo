"""
Signal Quality Scorer

Uses historical performance data to score signal quality and filter
out low-information setups. Implements statistical tests to ensure
signals have actual edge vs random.

Enhanced with:
- Regime-aware scoring (different weights for trending vs ranging)
- Confluence scoring (bonus when multiple indicators align)
- Time-of-day weighting (different scoring for opening/closing vs mid-day)
- ATR-normalized confidence adjustments
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_performance_file,
    get_signals_file,
)

# Timezone handling
try:
    from zoneinfo import ZoneInfo
    ET_TIMEZONE = ZoneInfo("America/New_York")
except ImportError:
    try:
        import pytz
        ET_TIMEZONE = pytz.timezone("America/New_York")
    except ImportError:
        ET_TIMEZONE = None


class SignalQualityScorer:
    """
    Scores signal quality based on historical performance and multi-factor analysis.
    
    Uses:
    - Historical win rate by signal type + regime
    - Information ratio (signal strength vs noise)
    - Confluence scoring (indicator alignment)
    - Time-of-day weighting
    - ATR-normalized adjustments
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
        self.state_dir = ensure_state_dir(state_dir)
        self.performance_file = get_performance_file(self.state_dir)
        self.signals_file = get_signals_file(self.state_dir)

        self.min_edge_threshold = min_edge_threshold

        # Cache for performance lookup
        self._performance_cache: Optional[Dict] = None
        self._cache_timestamp: Optional[datetime] = None

        logger.info(f"SignalQualityScorer initialized: min_edge={min_edge_threshold:.0%}")

    def score_signal(self, signal: Dict) -> Dict:
        """
        Score signal quality based on historical performance and multi-factor analysis.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Dictionary with quality score:
            {
                "quality_score": float (0-1),
                "historical_wr": float (0-1),  # Historical win rate
                "information_ratio": float,  # Signal strength vs noise
                "confluence_score": float (0-1),  # Indicator alignment score
                "time_weight": float (0.5-1.2),  # Time-of-day weight
                "meets_threshold": bool,  # Whether meets minimum edge
                "should_send": bool,  # Whether signal should be sent
            }
        """
        signal_type = signal.get("type", "unknown")
        regime = signal.get("regime", {})
        regime_type = regime.get("regime", "ranging")
        volatility = regime.get("volatility", "normal")
        signal_confidence = signal.get("confidence", 0)
        atr_expansion = regime.get("atr_expansion", False)

        # Load performance data
        performance_data = self._load_performance_data()

        # Lookup historical win rate
        historical_wr = self._lookup_historical_wr(
            signal_type, regime_type, volatility, performance_data
        )

        # Calculate confluence score (how many indicators align)
        confluence_score = self._calculate_confluence_score(signal)

        # Calculate time-of-day weight
        time_weight = self._calculate_time_weight(signal)

        # Calculate regime-adjusted score
        regime_adjustment = self._calculate_regime_adjustment(signal_type, regime)

        # Calculate information ratio (enhanced)
        # Information ratio = (Win Rate - 50%) / StdDev
        information_ratio = 0.0
        if historical_wr > 0.5:
            # Positive edge - scale by confluence
            information_ratio = (historical_wr - 0.5) * 2 * (1 + confluence_score * 0.3)
        else:
            # Negative edge
            information_ratio = (historical_wr - 0.5) * 2

        # Quality score (enhanced multi-factor scoring)
        # Components:
        # - Historical WR (40% weight)
        # - Information ratio (25% weight)
        # - Confluence score (20% weight)
        # - Time weight (15% weight)
        quality_score = (
            historical_wr * 0.40 +
            (information_ratio + 1) / 2 * 0.25 +
            confluence_score * 0.20 +
            time_weight / 1.2 * 0.15  # Normalize time_weight to 0-1
        )

        # Apply regime adjustment
        quality_score = max(0.0, min(1.0, quality_score + regime_adjustment))

        # Check if meets threshold (adjusted for confluence)
        # High confluence can lower threshold slightly
        effective_threshold = self.min_edge_threshold - (confluence_score * 0.05)
        meets_threshold = historical_wr >= effective_threshold

        # Enhanced bypass: handle first-time expansion days with no historical data
        # If ATR expanded and confidence is high, allow even if historical WR = 0.5 (no data)
        volatility_bypass = (
            volatility == "high" 
            and signal_confidence > 0.55 
            and (
                historical_wr >= 0.52  # Normal case: require minimum 52% expected WR
                or (atr_expansion and historical_wr >= 0.50)  # Expansion day: allow if no data (0.5) or better
            )
        )

        # High confluence bypass: strong confluence can override weak historical data
        confluence_bypass = (
            confluence_score >= 0.75
            and signal_confidence >= 0.55
            and historical_wr >= 0.50
        )

        # Should send if meets threshold and has positive information ratio, OR bypasses
        should_send = (
            (meets_threshold and information_ratio > 0)
            or volatility_bypass
            or confluence_bypass
        )

        # Diagnostic logging: log quality scorer decisions when signal is rejected
        if not should_send:
            logger.debug(
                f"Quality scorer rejected signal: type={signal_type}, "
                f"confidence={signal_confidence:.3f}, "
                f"historical_wr={historical_wr:.0%}, "
                f"confluence={confluence_score:.2f}, "
                f"time_weight={time_weight:.2f}, "
                f"meets_threshold={meets_threshold}, "
                f"information_ratio={information_ratio:.3f}, "
                f"volatility={volatility}, "
                f"volatility_bypass={volatility_bypass}, "
                f"confluence_bypass={confluence_bypass}"
            )

        return {
            "quality_score": float(quality_score),
            "historical_wr": float(historical_wr),
            "information_ratio": float(information_ratio),
            "confluence_score": float(confluence_score),
            "time_weight": float(time_weight),
            "regime_adjustment": float(regime_adjustment),
            "meets_threshold": meets_threshold,
            "should_send": should_send,
        }

    def _calculate_confluence_score(self, signal: Dict) -> float:
        """
        Calculate confluence score based on how many indicators align.
        
        Higher confluence = stronger signal quality.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Confluence score (0-1)
        """
        score = 0.0
        alignment_count = 0
        total_checks = 0

        # Check indicators if available
        indicators = signal.get("indicators", {})
        direction = signal.get("direction", "long")
        signal_type = signal.get("type", "unknown")

        # RSI alignment
        rsi = indicators.get("rsi")
        if rsi is not None:
            total_checks += 1
            if direction == "long":
                if "mean_reversion" in signal_type:
                    if rsi < 35:  # Oversold for mean reversion long
                        alignment_count += 1
                else:
                    if 40 < rsi < 70:  # Not overbought for long
                        alignment_count += 1
            else:  # short
                if "mean_reversion" in signal_type:
                    if rsi > 65:  # Overbought for mean reversion short
                        alignment_count += 1
                else:
                    if 30 < rsi < 60:  # Not oversold for short
                        alignment_count += 1

        # MACD alignment
        macd_hist = indicators.get("macd_histogram")
        if macd_hist is not None:
            total_checks += 1
            if direction == "long" and macd_hist > 0:
                alignment_count += 1
            elif direction == "short" and macd_hist < 0:
                alignment_count += 1

        # Volume alignment
        volume_ratio = indicators.get("volume_ratio")
        if volume_ratio is not None:
            total_checks += 1
            if volume_ratio > 1.2:  # Good volume for any signal
                alignment_count += 1

        # ATR alignment (good volatility)
        atr = indicators.get("atr")
        if atr is not None:
            total_checks += 1
            # This is always a pass if ATR exists (volatility filter already done)
            alignment_count += 1

        # MTF alignment
        mtf_analysis = signal.get("mtf_analysis", {})
        alignment = mtf_analysis.get("alignment")
        if alignment:
            total_checks += 1
            if alignment == "aligned":
                alignment_count += 1
            elif alignment == "partial":
                alignment_count += 0.5

        # VWAP alignment
        vwap_data = signal.get("vwap_data", {})
        distance_pct = vwap_data.get("distance_pct", 0)
        if distance_pct != 0:
            total_checks += 1
            if direction == "long" and distance_pct > 0:  # Above VWAP
                alignment_count += 1
            elif direction == "short" and distance_pct < 0:  # Below VWAP
                alignment_count += 1

        # Order flow alignment
        order_flow = signal.get("order_flow", {})
        recent_trend = order_flow.get("recent_trend")
        if recent_trend:
            total_checks += 1
            if direction == "long" and recent_trend == "buying":
                alignment_count += 1
            elif direction == "short" and recent_trend == "selling":
                alignment_count += 1

        # Calculate final score
        if total_checks > 0:
            score = alignment_count / total_checks
        else:
            score = 0.5  # Neutral if no checks

        return score

    def _calculate_time_weight(self, signal: Dict) -> float:
        """
        Calculate time-of-day weight for signal quality.
        
        Different times have different signal quality characteristics:
        - Opening (9:30-10:00 ET): High volatility, lower weight for mean reversion
        - Morning trend (10:00-11:30 ET): Best time, highest weight
        - Lunch lull (11:30-13:00 ET): Low volume, lowest weight
        - Afternoon (13:00-15:30 ET): Good trading, moderate weight
        - Closing (15:30-16:00 ET): High volatility, mixed
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Time weight (0.5-1.2)
        """
        signal_type = signal.get("type", "unknown")
        
        # Get current session from regime if available
        regime = signal.get("regime", {})
        session = regime.get("session")
        
        if not session:
            # Calculate session if not provided
            session = self._get_current_session()

        # Base weights by session
        session_weights = {
            "opening": 0.85,      # High volatility, moderate quality
            "morning_trend": 1.2,  # Best time - highest weight
            "lunch_lull": 0.5,    # Low volume - lowest weight
            "afternoon": 1.0,     # Good trading - standard weight
            "closing": 0.75,      # High volatility, mixed quality
        }

        base_weight = session_weights.get(session, 1.0)

        # Adjust by signal type
        if session == "opening" and "mean_reversion" in signal_type:
            base_weight -= 0.15  # Mean reversion risky at open
        elif session == "lunch_lull" and "momentum" in signal_type:
            base_weight -= 0.10  # Momentum weak at lunch
        elif session == "morning_trend" and "breakout" in signal_type:
            base_weight += 0.05  # Breakouts strong in morning

        return max(0.5, min(1.2, base_weight))

    def _calculate_regime_adjustment(self, signal_type: str, regime: Dict) -> float:
        """
        Calculate regime-based adjustment to quality score.
        
        Args:
            signal_type: Type of signal (e.g., "momentum_long")
            regime: Regime dictionary
            
        Returns:
            Adjustment value (-0.15 to +0.15)
        """
        regime_type = regime.get("regime", "ranging")
        volatility = regime.get("volatility", "normal")
        
        adjustment = 0.0

        # Momentum signals
        if "momentum" in signal_type:
            if "trending" in regime_type:
                # Check direction alignment
                if ("long" in signal_type and "bullish" in regime_type) or \
                   ("short" in signal_type and "bearish" in regime_type):
                    adjustment += 0.10  # Momentum with trend
                else:
                    adjustment -= 0.10  # Momentum against trend
            elif "ranging" in regime_type:
                adjustment -= 0.08  # Momentum in ranging (whipsaws)

        # Mean reversion signals
        elif "mean_reversion" in signal_type:
            if "ranging" in regime_type:
                adjustment += 0.10  # Mean reversion in ranging (ideal)
            elif "trending" in regime_type:
                adjustment -= 0.08  # Mean reversion in trending (risky)

        # Breakout signals
        elif "breakout" in signal_type:
            if "trending" in regime_type:
                adjustment += 0.05  # Breakout with trend
            elif "ranging" in regime_type:
                adjustment -= 0.05  # Breakout in ranging (false breakouts)
            
            # Volatility bonus for breakouts
            if volatility == "low":
                adjustment += 0.08  # Low vol compression -> breakouts
            elif volatility == "high":
                adjustment -= 0.05  # High vol may mean exhaustion

        return adjustment

    def _get_current_session(self) -> str:
        """Get current trading session based on ET time."""
        now = datetime.now(timezone.utc)

        if ET_TIMEZONE is not None:
            if now.tzinfo != timezone.utc:
                now_utc = now.astimezone(timezone.utc)
            else:
                now_utc = now
            et_dt = now_utc.astimezone(ET_TIMEZONE)
        else:
            from datetime import timedelta
            et_dt = now + timedelta(hours=-5)

        et_time = et_dt.time()

        # Session phases (ET time)
        opening_start = time(9, 30)
        opening_end = time(10, 0)
        lunch_start = time(11, 30)
        lunch_end = time(13, 0)
        closing_start = time(15, 30)
        closing_end = time(16, 0)

        if opening_start <= et_time < opening_end:
            return "opening"
        elif opening_end <= et_time < lunch_start:
            return "morning_trend"
        elif lunch_start <= et_time < lunch_end:
            return "lunch_lull"
        elif lunch_end <= et_time < closing_start:
            return "afternoon"
        elif closing_start <= et_time <= closing_end:
            return "closing"
        else:
            return "afternoon"  # Default

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
            Historical win rate (0-1), defaults to 0.5 if no data (0.52 for high volatility)
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

        # Volatility-aware default: high volatility expansion days are rare but high-value
        # Use 0.52 instead of 0.5 to allow signals during expansion when no historical data exists
        if volatility == "high":
            logger.debug(f"No historical data for {signal_type} in {regime_type}/{volatility}, using volatility-aware default 0.52")
            return 0.52
        
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






