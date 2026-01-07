"""
Power Channel Indicator

Port of ChartPrime-style power channel that adapts to price structure.

The power channel is a dynamic channel that:
1. Uses ATR-based bands around a central moving average
2. Expands/contracts based on volatility
3. Identifies trend direction and strength
4. Detects channel breakouts and pullbacks

Features extracted:
- Position within channel (0-1)
- Channel width (volatility proxy)
- Distance from channel midline
- Trend direction and strength
- Breakout detection

Signals generated:
- pc_breakout_long: Price breaking above upper channel
- pc_breakout_short: Price breaking below lower channel
- pc_pullback_long: Pullback to lower channel in uptrend
- pc_pullback_short: Pullback to upper channel in downtrend
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pearlalgo.strategies.nq_intraday.indicators.base import IndicatorBase, IndicatorSignal


class PowerChannel(IndicatorBase):
    """
    Power Channel indicator with trend-following and mean-reversion signals.
    
    Configuration:
    - length: Lookback period for channel calculation (default: 130)
    - atr_mult: ATR multiplier for channel width (default: 2.0)
    - source: Price source for calculation (default: "close")
    """
    
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.length = int(self.config.get("length", 130))
        self.atr_mult = float(self.config.get("atr_mult", 2.0))
        self.source = str(self.config.get("source", "close"))
    
    @property
    def name(self) -> str:
        return "power_channel"
    
    @property
    def description(self) -> str:
        return "ChartPrime-style adaptive power channel for trend and volatility"
    
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate power channel bands."""
        if not self.validate_dataframe(df):
            return df
        
        df = self.normalize_columns(df)
        
        # Ensure minimum data
        if len(df) < self.length:
            df = self._add_empty_columns(df)
            return df
        
        # Get source price
        if self.source == "hlc3":
            src = (df["high"] + df["low"] + df["close"]) / 3
        elif self.source == "hl2":
            src = (df["high"] + df["low"]) / 2
        else:
            src = df["close"]
        
        # Calculate ATR for channel width
        atr = self._calculate_atr(df, period=14)
        
        # Calculate channel midline (EMA of source)
        midline = src.ewm(span=self.length, adjust=False).mean()
        
        # Calculate adaptive channel bands
        upper = midline + atr * self.atr_mult
        lower = midline - atr * self.atr_mult
        
        # Calculate channel position (0 = at lower, 1 = at upper)
        channel_width = upper - lower
        channel_position = (src - lower) / channel_width.replace(0, np.nan)
        channel_position = channel_position.fillna(0.5).clip(0, 1)
        
        # Trend detection (based on midline slope)
        midline_slope = (midline - midline.shift(5)) / atr.replace(0, 1)
        trend_direction = np.where(midline_slope > 0.2, 1, np.where(midline_slope < -0.2, -1, 0))
        trend_strength = np.abs(midline_slope).clip(0, 2) / 2  # Normalize to 0-1
        
        # Breakout detection
        prev_upper = upper.shift(1)
        prev_lower = lower.shift(1)
        breakout_up = (src > prev_upper) & (src.shift(1) <= prev_upper.shift(1))
        breakout_down = (src < prev_lower) & (src.shift(1) >= prev_lower.shift(1))
        
        # Add columns
        df["pc_upper"] = upper
        df["pc_lower"] = lower
        df["pc_midline"] = midline
        df["pc_width"] = channel_width
        df["pc_position"] = channel_position
        df["pc_trend"] = trend_direction
        df["pc_trend_strength"] = trend_strength
        df["pc_breakout_up"] = breakout_up
        df["pc_breakout_down"] = breakout_down
        df["pc_atr"] = atr
        
        return df
    
    def _add_empty_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add empty columns when insufficient data."""
        df = df.copy()
        df["pc_upper"] = np.nan
        df["pc_lower"] = np.nan
        df["pc_midline"] = np.nan
        df["pc_width"] = np.nan
        df["pc_position"] = 0.5
        df["pc_trend"] = 0
        df["pc_trend_strength"] = 0.0
        df["pc_breakout_up"] = False
        df["pc_breakout_down"] = False
        df["pc_atr"] = np.nan
        return df
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        return tr.rolling(window=period).mean()
    
    def as_features(self, latest: pd.Series, df: Optional[pd.DataFrame] = None) -> Dict[str, float]:
        """Extract features for the learning system."""
        features = {}
        
        try:
            close = float(latest.get("close", 0))
            if close <= 0:
                return self._default_features()
            
            # Channel position (already 0-1)
            features["pc_channel_position"] = float(latest.get("pc_position", 0.5))
            
            # Channel width as percentage of price (volatility proxy)
            width = float(latest.get("pc_width", 0))
            features["pc_width_pct"] = width / close if close > 0 else 0.0
            
            # Distance from midline (normalized by channel width)
            midline = float(latest.get("pc_midline", close))
            features["pc_midline_distance"] = (close - midline) / max(width, 0.001)
            
            # Trend features
            features["pc_trend_bullish"] = 1.0 if latest.get("pc_trend", 0) > 0 else 0.0
            features["pc_trend_bearish"] = 1.0 if latest.get("pc_trend", 0) < 0 else 0.0
            features["pc_trend_strength"] = float(latest.get("pc_trend_strength", 0))
            
            # Breakout features
            features["pc_breakout_up"] = 1.0 if latest.get("pc_breakout_up", False) else 0.0
            features["pc_breakout_down"] = 1.0 if latest.get("pc_breakout_down", False) else 0.0
            
            # Near band features
            upper = float(latest.get("pc_upper", close * 1.01))
            lower = float(latest.get("pc_lower", close * 0.99))
            
            features["pc_near_upper"] = 1.0 if (upper - close) / close < 0.002 else 0.0
            features["pc_near_lower"] = 1.0 if (close - lower) / close < 0.002 else 0.0
            
        except Exception:
            return self._default_features()
        
        return features
    
    def _default_features(self) -> Dict[str, float]:
        """Return default feature values."""
        return {
            "pc_channel_position": 0.5,
            "pc_width_pct": 0.01,
            "pc_midline_distance": 0.0,
            "pc_trend_bullish": 0.0,
            "pc_trend_bearish": 0.0,
            "pc_trend_strength": 0.0,
            "pc_breakout_up": 0.0,
            "pc_breakout_down": 0.0,
            "pc_near_upper": 0.0,
            "pc_near_lower": 0.0,
        }
    
    def generate_signal(
        self,
        latest: pd.Series,
        df: pd.DataFrame,
        atr: Optional[float] = None,
    ) -> Optional[IndicatorSignal]:
        """Generate signal based on channel position and breakouts."""
        try:
            close = float(latest.get("close", 0))
            if close <= 0:
                return None
            
            # Use indicator's ATR if not provided
            if atr is None or atr <= 0:
                atr = float(latest.get("pc_atr", close * 0.005))
            
            trend = int(latest.get("pc_trend", 0))
            trend_strength = float(latest.get("pc_trend_strength", 0))
            position = float(latest.get("pc_position", 0.5))
            
            # Breakout long
            if latest.get("pc_breakout_up", False):
                confidence = 0.50 + trend_strength * 0.2
                
                return IndicatorSignal(
                    type="pc_breakout_long",
                    direction="long",
                    confidence=min(confidence, 0.80),
                    entry_price=close,
                    stop_loss=float(latest.get("pc_midline", close - atr)),
                    take_profit=close + atr * 2.5,
                    reason=f"Power channel breakout to upside (trend strength: {trend_strength:.0%})",
                    metadata={
                        "channel_position": position,
                        "trend_strength": trend_strength,
                        "breakout_type": "upper",
                    },
                )
            
            # Breakout short
            if latest.get("pc_breakout_down", False):
                confidence = 0.50 + trend_strength * 0.2
                
                return IndicatorSignal(
                    type="pc_breakout_short",
                    direction="short",
                    confidence=min(confidence, 0.80),
                    entry_price=close,
                    stop_loss=float(latest.get("pc_midline", close + atr)),
                    take_profit=close - atr * 2.5,
                    reason=f"Power channel breakout to downside (trend strength: {trend_strength:.0%})",
                    metadata={
                        "channel_position": position,
                        "trend_strength": trend_strength,
                        "breakout_type": "lower",
                    },
                )
            
            # Pullback long (in uptrend, touching lower band)
            if trend > 0 and position < 0.15:
                confidence = 0.45 + trend_strength * 0.25
                
                return IndicatorSignal(
                    type="pc_pullback_long",
                    direction="long",
                    confidence=min(confidence, 0.75),
                    entry_price=close,
                    stop_loss=float(latest.get("pc_lower", close - atr)) - atr * 0.3,
                    take_profit=float(latest.get("pc_midline", close + atr)),
                    reason=f"Pullback to lower channel in uptrend",
                    metadata={
                        "channel_position": position,
                        "trend_strength": trend_strength,
                        "pullback_type": "lower",
                    },
                )
            
            # Pullback short (in downtrend, touching upper band)
            if trend < 0 and position > 0.85:
                confidence = 0.45 + trend_strength * 0.25
                
                return IndicatorSignal(
                    type="pc_pullback_short",
                    direction="short",
                    confidence=min(confidence, 0.75),
                    entry_price=close,
                    stop_loss=float(latest.get("pc_upper", close + atr)) + atr * 0.3,
                    take_profit=float(latest.get("pc_midline", close - atr)),
                    reason=f"Pullback to upper channel in downtrend",
                    metadata={
                        "channel_position": position,
                        "trend_strength": trend_strength,
                        "pullback_type": "upper",
                    },
                )
            
        except Exception:
            pass
        
        return None
    
    def get_signal_types(self) -> List[str]:
        """Get signal types this indicator generates."""
        return [
            "pc_breakout_long",
            "pc_breakout_short",
            "pc_pullback_long",
            "pc_pullback_short",
        ]

