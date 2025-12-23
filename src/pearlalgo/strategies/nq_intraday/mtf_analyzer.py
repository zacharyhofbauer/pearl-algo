"""
Multi-Timeframe Analyzer

Analyzes higher timeframes (5m, 15m) to provide context and confirmation
for 1-minute signals. Prevents trading against the larger trend.

Enhanced with:
- Trend strength scoring (EMA slope, ADX)
- Structure level detection (swing highs/lows)
- RSI/MACD divergence detection across timeframes
- Improved alignment score calculation
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

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
        Analyze multi-timeframe structure with enhanced metrics.
        
        Args:
            df_5m: DataFrame with 5-minute bars (OHLCV)
            df_15m: DataFrame with 15-minute bars (OHLCV)
            
        Returns:
            Dictionary with MTF analysis:
            {
                "5m": {
                    "trend": "bullish" | "bearish" | "neutral",
                    "trend_strength": float (0-1),
                    "ema_slope": float,  # EMA slope indicator
                    "adx": float,  # ADX value
                    "key_levels": {"support": float, "resistance": float},
                    "swing_high": float,
                    "swing_low": float,
                    "pivot_levels": [float, ...],  # Swing pivots
                },
                "15m": {
                    "trend": "bullish" | "bearish" | "neutral",
                    "trend_strength": float (0-1),
                    "ema_slope": float,
                    "adx": float,
                    "key_levels": {"support": float, "resistance": float},
                },
                "alignment": "aligned" | "partial" | "conflicting",
                "alignment_score": float (0-1),
                "divergences": {
                    "rsi_divergence": "bullish" | "bearish" | None,
                    "macd_divergence": "bullish" | "bearish" | None,
                },
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

        # Detect divergences
        result["divergences"] = self._detect_divergences(df_5m, df_15m)

        return result

    def _analyze_timeframe(self, df: pd.DataFrame, timeframe: str) -> Dict:
        """
        Analyze a single timeframe with enhanced metrics.
        
        Args:
            df: DataFrame with OHLCV data
            timeframe: Timeframe label ("5m" or "15m")
            
        Returns:
            Dictionary with timeframe analysis
        """
        if df.empty or len(df) < 10:
            return self._default_timeframe_analysis()

        df = df.copy()
        latest = df.iloc[-1]
        close = latest.get("close", 0)

        # Calculate EMAs if not present
        if "ema_20" not in df.columns:
            df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
            df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
            latest = df.iloc[-1]

        ema_20 = latest.get("ema_20", close)
        ema_50 = latest.get("ema_50", close)

        # Calculate EMA slope for trend strength
        ema_slope = self._calculate_ema_slope(df)

        # Calculate ADX for trend strength
        adx = self._calculate_adx(df)

        # Determine trend with enhanced metrics
        trend, trend_strength = self._determine_trend_enhanced(df, latest, ema_20, ema_50, ema_slope, adx)

        # Identify key levels
        key_levels = self._identify_key_levels(df, latest)

        # Identify swing pivots
        pivot_levels = self._identify_swing_pivots(df)

        # For 5m, also identify swing highs/lows
        swing_high = None
        swing_low = None
        if timeframe == "5m" and len(df) >= 10:
            swing_high = df["high"].tail(10).max()
            swing_low = df["low"].tail(10).min()

        return {
            "trend": trend,
            "trend_strength": trend_strength,
            "ema_slope": ema_slope,
            "adx": adx,
            "key_levels": key_levels,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "pivot_levels": pivot_levels,
            "current_price": close,
            "ema_20": ema_20,
            "ema_50": ema_50,
        }

    def _calculate_ema_slope(self, df: pd.DataFrame, lookback: int = 5) -> float:
        """
        Calculate EMA slope as a measure of trend strength.
        
        Args:
            df: DataFrame with EMA calculated
            lookback: Number of bars to measure slope
            
        Returns:
            EMA slope (positive = uptrend, negative = downtrend)
        """
        if len(df) < lookback + 1 or "ema_20" not in df.columns:
            return 0.0

        ema_now = df["ema_20"].iloc[-1]
        ema_prev = df["ema_20"].iloc[-lookback]

        if ema_prev > 0:
            # Percent change in EMA over lookback period
            slope = (ema_now - ema_prev) / ema_prev * 100
            return float(slope)
        return 0.0

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        Calculate ADX (Average Directional Index) for trend strength.
        
        Args:
            df: DataFrame with OHLCV data
            period: ADX period (default: 14)
            
        Returns:
            ADX value (0-100)
        """
        if len(df) < period + 1:
            return 0.0

        try:
            # Calculate True Range
            high_low = df["high"] - df["low"]
            high_close_prev = abs(df["high"] - df["close"].shift(1))
            low_close_prev = abs(df["low"] - df["close"].shift(1))
            tr = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)

            # Calculate +DM and -DM
            up_move = df["high"] - df["high"].shift(1)
            down_move = df["low"].shift(1) - df["low"]

            plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
            minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)

            # Smooth TR, +DM, -DM
            atr = tr.rolling(window=period).mean()
            plus_dm_smooth = plus_dm.rolling(window=period).mean()
            minus_dm_smooth = minus_dm.rolling(window=period).mean()

            # Calculate DI+ and DI-
            plus_di = 100 * (plus_dm_smooth / atr)
            minus_di = 100 * (minus_dm_smooth / atr)

            # Calculate DX
            di_sum = plus_di + minus_di
            di_diff = abs(plus_di - minus_di)
            dx = 100 * (di_diff / di_sum.replace(0, 1))

            # Calculate ADX
            adx = dx.rolling(window=period).mean()

            return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0
        except Exception:
            return 0.0

    def _determine_trend_enhanced(
        self,
        df: pd.DataFrame,
        latest: pd.Series,
        ema_20: float,
        ema_50: float,
        ema_slope: float,
        adx: float,
    ) -> Tuple[str, float]:
        """
        Determine trend direction and strength using enhanced metrics.
        
        Args:
            df: DataFrame
            latest: Latest bar
            ema_20: 20-period EMA value
            ema_50: 50-period EMA value
            ema_slope: EMA slope (percent change)
            adx: ADX value
            
        Returns:
            Tuple of (trend, strength)
        """
        close = latest.get("close", 0)

        # Check EMA alignment
        ema_bullish = ema_20 > ema_50
        ema_bearish = ema_20 < ema_50

        # Check price position relative to EMAs
        price_above_ema20 = close > ema_20
        price_above_ema50 = close > ema_50

        # Base strength calculation using ADX
        # ADX > 25 = strong trend
        # ADX 20-25 = moderate trend
        # ADX < 20 = weak/ranging
        if adx > 25:
            base_strength = 0.7 + min(0.3, (adx - 25) / 50)
        elif adx > 20:
            base_strength = 0.5 + (adx - 20) / 10
        else:
            base_strength = max(0.3, adx / 40)

        # Adjust by EMA slope
        slope_adjustment = min(0.15, abs(ema_slope) / 2)

        # Determine trend
        if ema_bullish and price_above_ema20:
            # Bullish trend
            strength = min(1.0, base_strength + slope_adjustment)
            return ("bullish", strength)
        elif ema_bearish and not price_above_ema20:
            # Bearish trend
            strength = min(1.0, base_strength + slope_adjustment)
            return ("bearish", strength)
        else:
            # Neutral/transitional
            if price_above_ema50:
                return ("neutral", 0.4)
            else:
                return ("neutral", 0.4)

    def _identify_swing_pivots(self, df: pd.DataFrame, lookback: int = 5) -> List[float]:
        """
        Identify swing high/low pivot levels.
        
        Args:
            df: DataFrame with OHLCV data
            lookback: Bars on each side to confirm pivot
            
        Returns:
            List of pivot price levels
        """
        if len(df) < lookback * 2 + 1:
            return []

        pivots = []

        for i in range(lookback, len(df) - lookback):
            # Check for swing high
            is_swing_high = all(
                df["high"].iloc[i] > df["high"].iloc[i - j] and
                df["high"].iloc[i] > df["high"].iloc[i + j]
                for j in range(1, lookback + 1)
            )
            if is_swing_high:
                pivots.append(float(df["high"].iloc[i]))

            # Check for swing low
            is_swing_low = all(
                df["low"].iloc[i] < df["low"].iloc[i - j] and
                df["low"].iloc[i] < df["low"].iloc[i + j]
                for j in range(1, lookback + 1)
            )
            if is_swing_low:
                pivots.append(float(df["low"].iloc[i]))

        # Return last 5 pivots
        return pivots[-5:] if len(pivots) > 5 else pivots

    def _detect_divergences(
        self,
        df_5m: Optional[pd.DataFrame],
        df_15m: Optional[pd.DataFrame],
    ) -> Dict:
        """
        Detect RSI and MACD divergences across timeframes.
        
        Divergences indicate potential reversals:
        - Bullish divergence: Price makes lower low, indicator makes higher low
        - Bearish divergence: Price makes higher high, indicator makes lower high
        
        Args:
            df_5m: 5-minute DataFrame
            df_15m: 15-minute DataFrame
            
        Returns:
            Dictionary with divergence information
        """
        result = {
            "rsi_divergence": None,
            "macd_divergence": None,
        }

        # Use 15m for more reliable divergence detection
        df = df_15m if df_15m is not None and not df_15m.empty else df_5m
        if df is None or df.empty or len(df) < 20:
            return result

        df = df.copy()

        # Calculate RSI if not present
        if "rsi" not in df.columns:
            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df["rsi"] = 100 - (100 / (1 + rs))

        # Calculate MACD if not present
        if "macd" not in df.columns:
            ema_12 = df["close"].ewm(span=12, adjust=False).mean()
            ema_26 = df["close"].ewm(span=26, adjust=False).mean()
            df["macd"] = ema_12 - ema_26

        # Check RSI divergence
        result["rsi_divergence"] = self._check_divergence(
            df["close"], df["rsi"], lookback=10
        )

        # Check MACD divergence
        result["macd_divergence"] = self._check_divergence(
            df["close"], df["macd"], lookback=10
        )

        return result

    def _check_divergence(
        self,
        price_series: pd.Series,
        indicator_series: pd.Series,
        lookback: int = 10,
    ) -> Optional[str]:
        """
        Check for divergence between price and indicator.
        
        Args:
            price_series: Price series (close)
            indicator_series: Indicator series (RSI, MACD, etc.)
            lookback: Number of bars to check for divergence
            
        Returns:
            "bullish", "bearish", or None
        """
        if len(price_series) < lookback or len(indicator_series) < lookback:
            return None

        try:
            # Get recent price and indicator values
            recent_prices = price_series.tail(lookback)
            recent_indicator = indicator_series.tail(lookback)

            # Find local extremes
            price_min_idx = recent_prices.idxmin()
            price_max_idx = recent_prices.idxmax()
            
            # Current values
            current_price = price_series.iloc[-1]
            current_indicator = indicator_series.iloc[-1]

            # Previous low/high
            prev_price_low = recent_prices.min()
            prev_indicator_at_low = indicator_series.loc[price_min_idx] if price_min_idx in indicator_series.index else None
            
            prev_price_high = recent_prices.max()
            prev_indicator_at_high = indicator_series.loc[price_max_idx] if price_max_idx in indicator_series.index else None

            # Check bullish divergence
            # Price makes lower low, indicator makes higher low
            if prev_indicator_at_low is not None:
                if current_price < prev_price_low and current_indicator > prev_indicator_at_low:
                    return "bullish"

            # Check bearish divergence
            # Price makes higher high, indicator makes lower high
            if prev_indicator_at_high is not None:
                if current_price > prev_price_high and current_indicator < prev_indicator_at_high:
                    return "bearish"

        except Exception as e:
            logger.debug(f"Error checking divergence: {e}")

        return None

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









