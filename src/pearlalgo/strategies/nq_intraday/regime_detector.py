"""
Market Regime Detector

Classifies market conditions into regimes (trending/ranging, volatility, session context)
to enable adaptive strategy parameters.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Dict, Optional

import pandas as pd

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

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    Detects market regime: trending vs ranging, volatility regime, session context.
    
    Regime classification enables adaptive strategy parameters:
    - Momentum signals work better in trending markets
    - Mean reversion works better in ranging markets
    - Volatility regime affects stop placement and target sizing
    - Session context affects signal quality
    """

    def __init__(self):
        """Initialize regime detector."""
        logger.info("RegimeDetector initialized")

    def detect_regime(self, df: pd.DataFrame) -> Dict:
        """
        Detect current market regime.
        
        Args:
            df: DataFrame with OHLCV data and indicators (must have ATR, EMA calculated)
            
        Returns:
            Dictionary with regime classification:
            {
                "regime": "trending_bullish" | "trending_bearish" | "ranging",
                "volatility": "low" | "normal" | "high",
                "session": "opening" | "morning_trend" | "lunch_lull" | "afternoon" | "closing",
                "confidence": float (0-1)
            }
        """
        if df.empty or len(df) < 20:
            return self._default_regime()

        latest = df.iloc[-1]

        # Detect trend vs range
        trend_regime, trend_confidence = self._detect_trend(df, latest)

        # Detect volatility regime
        volatility_regime, vol_confidence = self._detect_volatility(df, latest)

        # Detect session context
        session = self._detect_session()

        # Overall confidence (weighted average)
        overall_confidence = (trend_confidence * 0.5 + vol_confidence * 0.3 + 0.2)

        return {
            "regime": trend_regime,
            "volatility": volatility_regime,
            "session": session,
            "confidence": min(overall_confidence, 1.0),
        }

    def _detect_trend(self, df: pd.DataFrame, latest: pd.Series) -> tuple[str, float]:
        """
        Detect if market is trending or ranging.
        
        Uses ADX (Average Directional Index) + price position relative to EMAs.
        
        Args:
            df: DataFrame with indicators
            latest: Latest bar
            
        Returns:
            Tuple of (regime, confidence)
            Regime: "trending_bullish", "trending_bearish", or "ranging"
        """
        if len(df) < 14:
            return ("ranging", 0.5)

        # Calculate ADX if not present
        if "adx" not in df.columns:
            df = self._calculate_adx(df)
            latest = df.iloc[-1]

        adx = latest.get("adx", 0)
        ema_20 = latest.get("ema_20", latest.get("close", 0))
        close = latest.get("close", 0)

        # Calculate +DI and -DI for direction
        plus_di = latest.get("plus_di", 0)
        minus_di = latest.get("minus_di", 0)

        # Trending: ADX > 25
        # Ranging: ADX < 20
        if adx > 25:
            # Strong trend
            if plus_di > minus_di and close > ema_20:
                return ("trending_bullish", min(0.9, 0.6 + (adx - 25) / 50))
            elif minus_di > plus_di and close < ema_20:
                return ("trending_bearish", min(0.9, 0.6 + (adx - 25) / 50))
            else:
                # ADX high but direction unclear
                if close > ema_20:
                    return ("trending_bullish", 0.65)
                else:
                    return ("trending_bearish", 0.65)
        elif adx < 20:
            # Ranging market
            return ("ranging", min(0.85, 0.5 + (20 - adx) / 40))
        else:
            # Transitional (20 <= ADX <= 25)
            # Check price action relative to EMA
            if close > ema_20 * 1.002:  # 0.2% above EMA
                return ("trending_bullish", 0.55)
            elif close < ema_20 * 0.998:  # 0.2% below EMA
                return ("trending_bearish", 0.55)
            else:
                return ("ranging", 0.6)

    def _detect_volatility(self, df: pd.DataFrame, latest: pd.Series) -> tuple[str, float]:
        """
        Detect volatility regime: low, normal, or high.
        
        Uses ATR percentile (20-period rolling) to classify volatility.
        
        Args:
            df: DataFrame with ATR calculated
            latest: Latest bar
            
        Returns:
            Tuple of (volatility_regime, confidence)
            Regime: "low", "normal", or "high"
        """
        if len(df) < 20 or "atr" not in df.columns:
            return ("normal", 0.5)

        # Get ATR values for percentile calculation
        atr_values = df["atr"].tail(20).dropna()
        if len(atr_values) < 10:
            return ("normal", 0.5)

        current_atr = latest.get("atr", 0)
        if current_atr == 0:
            return ("normal", 0.5)

        # Calculate percentiles
        atr_20th = atr_values.quantile(0.20)
        atr_80th = atr_values.quantile(0.80)
        atr_median = atr_values.median()

        # Classify
        if current_atr < atr_20th:
            # Low volatility (compression, potential breakout)
            confidence = min(0.9, 0.6 + (atr_20th - current_atr) / atr_median)
            return ("low", confidence)
        elif current_atr > atr_80th:
            # High volatility (expansion, potential exhaustion)
            confidence = min(0.9, 0.6 + (current_atr - atr_80th) / atr_median)
            return ("high", confidence)
        else:
            # Normal volatility
            return ("normal", 0.7)

    def _detect_session(self) -> str:
        """
        Detect current session phase.
        
        Returns:
            Session phase: "opening", "morning_trend", "lunch_lull", "afternoon", "closing"
        """
        now = datetime.now(timezone.utc)

        # Convert to ET
        if ET_TIMEZONE is not None:
            if now.tzinfo != timezone.utc:
                now_utc = now.astimezone(timezone.utc)
            else:
                now_utc = now
            et_dt = now_utc.astimezone(ET_TIMEZONE)
        else:
            # Fallback
            from datetime import timedelta
            et_dt = now + timedelta(hours=-5)

        et_time = et_dt.time()

        # Session phases (ET time)
        opening_start = time(9, 30)  # 9:30 AM
        opening_end = time(10, 0)   # 10:00 AM
        lunch_start = time(11, 30)   # 11:30 AM
        lunch_end = time(13, 0)     # 1:00 PM
        closing_start = time(15, 30) # 3:30 PM
        closing_end = time(16, 0)   # 4:00 PM

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
            # Outside market hours
            return "afternoon"  # Default

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Calculate ADX (Average Directional Index) and DI+ / DI-.
        
        Args:
            df: DataFrame with OHLCV data
            period: ADX period (default: 14)
            
        Returns:
            DataFrame with adx, plus_di, minus_di columns added
        """
        df = df.copy()

        if len(df) < period + 1:
            df["adx"] = 0.0
            df["plus_di"] = 0.0
            df["minus_di"] = 0.0
            return df

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

        # Smooth TR, +DM, -DM using Wilder's smoothing
        atr = tr.rolling(window=period).mean()  # Simplified - should use Wilder's
        plus_dm_smooth = plus_dm.rolling(window=period).mean()
        minus_dm_smooth = minus_dm.rolling(window=period).mean()

        # Calculate DI+ and DI-
        df["plus_di"] = 100 * (plus_dm_smooth / atr)
        df["minus_di"] = 100 * (minus_dm_smooth / atr)

        # Calculate DX
        di_sum = df["plus_di"] + df["minus_di"]
        di_diff = abs(df["plus_di"] - df["minus_di"])
        dx = 100 * (di_diff / di_sum.replace(0, 1))  # Avoid division by zero

        # Calculate ADX (smoothed DX)
        df["adx"] = dx.rolling(window=period).mean()

        # Fill NaN values
        df["adx"] = df["adx"].fillna(0)
        df["plus_di"] = df["plus_di"].fillna(0)
        df["minus_di"] = df["minus_di"].fillna(0)

        return df

    def _default_regime(self) -> Dict:
        """Return default regime when data is insufficient."""
        return {
            "regime": "ranging",
            "volatility": "normal",
            "session": self._detect_session(),
            "confidence": 0.5,
        }

    def adjust_confidence_by_regime(
        self,
        signal_type: str,
        signal_confidence: float,
        regime: Dict,
    ) -> float:
        """
        Adjust signal confidence based on regime alignment.
        
        Args:
            signal_type: Signal type ("momentum_long", "mean_reversion_long", "breakout_long")
            signal_confidence: Base signal confidence (0-1)
            regime: Regime dictionary from detect_regime()
            
        Returns:
            Adjusted confidence (0-1)
        """
        regime_type = regime.get("regime", "ranging")
        volatility = regime.get("volatility", "normal")

        adjusted = signal_confidence

        # Momentum signals
        if "momentum" in signal_type:
            if "trending_bullish" in regime_type and "long" in signal_type:
                adjusted += 0.15  # Momentum long in bullish trend
            elif "trending_bearish" in regime_type and "long" in signal_type:
                adjusted -= 0.20  # Momentum long in bearish trend (fighting trend)
            elif "ranging" in regime_type:
                adjusted -= 0.20  # Momentum in ranging market (whipsaws)

        # Mean reversion signals
        elif "mean_reversion" in signal_type:
            if "ranging" in regime_type:
                adjusted += 0.15  # Mean reversion in ranging market
            elif "trending" in regime_type:
                adjusted -= 0.25  # Mean reversion in trending market (fighting trend)

        # Breakout signals
        elif "breakout" in signal_type:
            if "trending" in regime_type:
                adjusted += 0.10  # Breakout in trending market
            elif "ranging" in regime_type:
                adjusted -= 0.10  # Breakout in ranging market (false breakouts)

            # Volatility adjustment for breakouts
            if volatility == "low":
                adjusted += 0.10  # Low vol compression often precedes breakouts
            elif volatility == "high":
                adjusted -= 0.10  # High vol expansion may mean exhaustion

        # Volatility adjustments (general)
        if volatility == "low":
            # Low vol: tighter stops, wider targets, higher confidence for breakouts
            if "breakout" in signal_type:
                adjusted += 0.05
        elif volatility == "high":
            # High vol: wider stops, lower confidence (exhaustion risk)
            adjusted -= 0.05

        # Session-based adjustments
        session = regime.get("session", "afternoon")
        if session == "lunch_lull":
            if "momentum" in signal_type:
                adjusted -= 0.15  # Disable momentum during lunch (low volume, choppy)
        elif session == "opening":
            if "mean_reversion" in signal_type:
                adjusted -= 0.10  # Opening too volatile for mean reversion

        # Clamp to [0, 1]
        return max(0.0, min(1.0, adjusted))



