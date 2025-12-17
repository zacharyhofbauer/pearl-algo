"""
Multi-Timeframe Analyzer

Analyzes higher timeframes (5m, 15m) to provide context and confirmation
for 1-minute signals. Prevents trading against the larger trend.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger


class MTFAnalyzer:
    """
    Multi-timeframe analyzer for signal confirmation.
    
    Analyzes 5m and 15m timeframes to:
    - Determine trend direction
    - Identify key support/resistance levels
    - Confirm or reject 1m signals based on higher timeframe alignment
    """

    def __init__(self):
        """Initialize MTF analyzer."""
        logger.info("MTFAnalyzer initialized")

    def analyze(self, df_5m: Optional[pd.DataFrame], df_15m: Optional[pd.DataFrame]) -> Dict:
        """
        Analyze multi-timeframe structure.
        
        Args:
            df_5m: DataFrame with 5-minute bars (OHLCV)
            df_15m: DataFrame with 15-minute bars (OHLCV)
            
        Returns:
            Dictionary with MTF analysis:
            {
                "5m": {
                    "trend": "bullish" | "bearish" | "neutral",
                    "trend_strength": float (0-1),
                    "key_levels": {"support": float, "resistance": float},
                    "swing_high": float,
                    "swing_low": float,
                },
                "15m": {
                    "trend": "bullish" | "bearish" | "neutral",
                    "trend_strength": float (0-1),
                    "key_levels": {"support": float, "resistance": float},
                },
                "alignment": "aligned" | "partial" | "conflicting",
                "alignment_score": float (0-1),
            }
        """
        result = {
            "5m": self._analyze_timeframe(df_5m, "5m") if df_5m is not None and not df_5m.empty else None,
            "15m": self._analyze_timeframe(df_15m, "15m") if df_15m is not None and not df_15m.empty else None,
        }

        # Calculate alignment
        alignment, alignment_score = self._calculate_alignment(result["5m"], result["15m"])
        result["alignment"] = alignment
        result["alignment_score"] = alignment_score

        return result

    def _analyze_timeframe(self, df: pd.DataFrame, timeframe: str) -> Dict:
        """
        Analyze a single timeframe.
        
        Args:
            df: DataFrame with OHLCV data
            timeframe: Timeframe label ("5m" or "15m")
            
        Returns:
            Dictionary with timeframe analysis
        """
        if df.empty or len(df) < 10:
            return self._default_timeframe_analysis()

        latest = df.iloc[-1]
        close = latest.get("close", 0)

        # Calculate EMAs if not present
        if "ema_20" not in df.columns:
            df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
            df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
            latest = df.iloc[-1]

        ema_20 = latest.get("ema_20", close)
        ema_50 = latest.get("ema_50", close)

        # Determine trend
        trend, trend_strength = self._determine_trend(df, latest, ema_20, ema_50)

        # Identify key levels
        key_levels = self._identify_key_levels(df, latest)

        # For 5m, also identify swing highs/lows
        swing_high = None
        swing_low = None
        if timeframe == "5m" and len(df) >= 10:
            swing_high = df["high"].tail(10).max()
            swing_low = df["low"].tail(10).min()

        return {
            "trend": trend,
            "trend_strength": trend_strength,
            "key_levels": key_levels,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "current_price": close,
            "ema_20": ema_20,
            "ema_50": ema_50,
        }

    def _determine_trend(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        ema_20: float,
        ema_50: float,
    ) -> tuple[str, float]:
        """
        Determine trend direction and strength.
        
        Args:
            df: DataFrame
            latest: Latest bar
            ema_20: 20-period EMA value
            ema_50: 50-period EMA value
            
        Returns:
            Tuple of (trend, strength)
            Trend: "bullish", "bearish", or "neutral"
            Strength: 0-1 (1 = strong trend, 0 = no trend)
        """
        close = latest.get("close", 0)

        # Check EMA alignment
        ema_bullish = ema_20 > ema_50
        ema_bearish = ema_20 < ema_50

        # Check price position relative to EMAs
        price_above_ema20 = close > ema_20
        price_above_ema50 = close > ema_50

        # Calculate EMA slope (trend strength indicator)
        if len(df) >= 2:
            prev_ema20 = df.iloc[-2].get("ema_20", ema_20)
            ema_slope = (ema_20 - prev_ema20) / prev_ema20 if prev_ema20 > 0 else 0
        else:
            ema_slope = 0

        # Determine trend
        if ema_bullish and price_above_ema20:
            # Bullish trend
            strength = min(1.0, 0.6 + abs(ema_slope) * 1000)  # Scale slope
            return ("bullish", strength)
        elif ema_bearish and not price_above_ema20:
            # Bearish trend
            strength = min(1.0, 0.6 + abs(ema_slope) * 1000)
            return ("bearish", strength)
        else:
            # Neutral/transitional
            if price_above_ema50:
                return ("neutral", 0.4)  # Slightly bullish but not confirmed
            else:
                return ("neutral", 0.4)  # Slightly bearish but not confirmed

    def _identify_key_levels(self, df: pd.DataFrame, latest: pd.Series) -> Dict:
        """
        Identify key support and resistance levels.
        
        Args:
            df: DataFrame
            latest: Latest bar
            
        Returns:
            Dictionary with support and resistance levels
        """
        if len(df) < 20:
            close = latest.get("close", 0)
            return {"support": close * 0.99, "resistance": close * 1.01}

        # Use recent highs/lows as key levels
        recent_high = df["high"].tail(20).max()
        recent_low = df["low"].tail(20).min()
        current = latest.get("close", 0)

        # Support: recent low or below current price
        support = min(recent_low, current * 0.995)

        # Resistance: recent high or above current price
        resistance = max(recent_high, current * 1.005)

        return {
            "support": float(support),
            "resistance": float(resistance),
        }

    def _calculate_alignment(
        self,
        tf_5m: Optional[Dict],
        tf_15m: Optional[Dict],
    ) -> tuple[str, float]:
        """
        Calculate alignment between timeframes.
        
        Args:
            tf_5m: 5m timeframe analysis (or None)
            tf_15m: 15m timeframe analysis (or None)
            
        Returns:
            Tuple of (alignment, score)
            Alignment: "aligned", "partial", or "conflicting"
            Score: 0-1 (1 = fully aligned, 0 = conflicting)
        """
        if tf_5m is None and tf_15m is None:
            return ("partial", 0.5)  # No data, assume neutral

        if tf_5m is None:
            # Only 15m available
            return ("partial", 0.6)

        if tf_15m is None:
            # Only 5m available
            return ("partial", 0.6)

        # Both available - check alignment
        trend_5m = tf_5m.get("trend", "neutral")
        trend_15m = tf_15m.get("trend", "neutral")

        # Check if trends align
        if trend_5m == trend_15m and trend_5m != "neutral":
            # Fully aligned
            strength_5m = tf_5m.get("trend_strength", 0.5)
            strength_15m = tf_15m.get("trend_strength", 0.5)
            score = (strength_5m + strength_15m) / 2
            return ("aligned", score)
        elif trend_5m == "neutral" or trend_15m == "neutral":
            # One is neutral - partial alignment
            if trend_5m == "neutral":
                score = tf_15m.get("trend_strength", 0.5) * 0.7
            else:
                score = tf_5m.get("trend_strength", 0.5) * 0.7
            return ("partial", score)
        elif (trend_5m == "bullish" and trend_15m == "bearish") or \
             (trend_5m == "bearish" and trend_15m == "bullish"):
            # Conflicting
            return ("conflicting", 0.2)
        else:
            # Both neutral or other combination
            return ("partial", 0.5)

    def _default_timeframe_analysis(self) -> Dict:
        """Return default analysis when data is insufficient."""
        return {
            "trend": "neutral",
            "trend_strength": 0.5,
            "key_levels": {"support": 0.0, "resistance": 0.0},
            "swing_high": None,
            "swing_low": None,
            "current_price": 0.0,
            "ema_20": 0.0,
            "ema_50": 0.0,
        }

    def check_signal_alignment(
        self,
        signal_direction: str,
        mtf_analysis: Dict,
    ) -> tuple[bool, float]:
        """
        Check if a signal aligns with multi-timeframe structure.
        
        Args:
            signal_direction: "long" or "short"
            mtf_analysis: MTF analysis from analyze()
            
        Returns:
            Tuple of (is_aligned, confidence_adjustment)
            is_aligned: True if signal should be allowed
            confidence_adjustment: Confidence adjustment (-0.3 to +0.2)
        """
        alignment = mtf_analysis.get("alignment", "partial")
        alignment_score = mtf_analysis.get("alignment_score", 0.5)

        tf_5m = mtf_analysis.get("5m")
        tf_15m = mtf_analysis.get("15m")

        # Get trend directions
        trend_5m = tf_5m.get("trend", "neutral") if tf_5m else "neutral"
        trend_15m = tf_15m.get("trend", "neutral") if tf_15m else "neutral"

        # Check alignment for long signals
        if signal_direction == "long":
            # Long signals need bullish or neutral trends
            aligned_5m = trend_5m in ("bullish", "neutral")
            aligned_15m = trend_15m in ("bullish", "neutral")

            if aligned_5m and aligned_15m:
                # Fully aligned
                if alignment == "aligned":
                    return (True, +0.20)  # Strong boost
                else:
                    return (True, +0.10)  # Moderate boost
            elif aligned_5m or aligned_15m:
                # Partial alignment
                return (True, 0.0)  # No adjustment
            else:
                # Conflicting (both bearish)
                if alignment == "conflicting":
                    return (False, -0.30)  # Reject signal
                else:
                    return (True, -0.15)  # Allow but reduce confidence

        # Check alignment for short signals
        elif signal_direction == "short":
            # Short signals need bearish or neutral trends
            aligned_5m = trend_5m in ("bearish", "neutral")
            aligned_15m = trend_15m in ("bearish", "neutral")

            if aligned_5m and aligned_15m:
                # Fully aligned
                if alignment == "aligned":
                    return (True, +0.20)
                else:
                    return (True, +0.10)
            elif aligned_5m or aligned_15m:
                # Partial alignment
                return (True, 0.0)
            else:
                # Conflicting (both bullish)
                if alignment == "conflicting":
                    return (False, -0.30)
                else:
                    return (True, -0.15)

        # Unknown direction
        return (True, 0.0)

    def get_breakout_levels(self, mtf_analysis: Dict) -> Dict:
        """
        Get key breakout levels from higher timeframes.
        
        Args:
            mtf_analysis: MTF analysis from analyze()
            
        Returns:
            Dictionary with breakout levels:
            {
                "resistance_5m": float,
                "resistance_15m": float,
                "support_5m": float,
                "support_15m": float,
            }
        """
        tf_5m = mtf_analysis.get("5m")
        tf_15m = mtf_analysis.get("15m")

        result = {}

        if tf_5m:
            key_levels = tf_5m.get("key_levels", {})
            result["resistance_5m"] = key_levels.get("resistance")
            result["support_5m"] = key_levels.get("support")
            swing_high = tf_5m.get("swing_high")
            if swing_high:
                result["swing_high_5m"] = swing_high

        if tf_15m:
            key_levels = tf_15m.get("key_levels", {})
            result["resistance_15m"] = key_levels.get("resistance")
            result["support_15m"] = key_levels.get("support")

        return result






