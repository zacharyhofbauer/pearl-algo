"""
Smart Money Divergence Indicator

Detects divergences between price action and volume/momentum indicators,
which can signal potential reversals when "smart money" is positioning.

This indicator identifies:
1. Regular divergences (price makes new high/low but indicator doesn't)
2. Hidden divergences (trend continuation signals)
3. Volume divergences (price moves without volume confirmation)

Features extracted:
- Bullish divergence strength (0-1)
- Bearish divergence strength (0-1)
- Volume-price divergence
- RSI divergence
- MACD divergence

Signals generated:
- smd_bullish_divergence: Price making lower lows but momentum making higher lows
- smd_bearish_divergence: Price making higher highs but momentum making lower highs
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pearlalgo.strategies.nq_intraday.indicators.base import IndicatorBase, IndicatorSignal


class SmartMoneyDivergence(IndicatorBase):
    """
    Smart Money Divergence indicator for detecting institutional positioning.
    
    Configuration:
    - lookback: Bars to look back for divergence detection (default: 14)
    - pivot_lookback: Bars for pivot point detection (default: 5)
    - rsi_period: RSI calculation period (default: 14)
    - min_divergence_bars: Minimum bars between pivots (default: 3)
    """
    
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self.lookback = int(self.config.get("lookback", 14))
        self.pivot_lookback = int(self.config.get("pivot_lookback", 5))
        self.rsi_period = int(self.config.get("rsi_period", 14))
        self.min_divergence_bars = int(self.config.get("min_divergence_bars", 3))
    
    @property
    def name(self) -> str:
        return "smart_money_divergence"
    
    @property
    def description(self) -> str:
        return "Detects price-momentum divergences indicating smart money positioning"
    
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate divergence indicators."""
        if not self.validate_dataframe(df):
            return df
        
        df = self.normalize_columns(df)
        
        min_required = max(self.lookback, self.rsi_period) + self.pivot_lookback + 10
        if len(df) < min_required:
            df = self._add_empty_columns(df)
            return df
        
        # Calculate RSI
        df["smd_rsi"] = self._calculate_rsi(df["close"], self.rsi_period)
        
        # Calculate OBV (On-Balance Volume) for volume divergence
        df["smd_obv"] = self._calculate_obv(df)
        
        # Find pivot highs and lows in price
        df["smd_pivot_high"] = self._find_pivot_highs(df["high"], self.pivot_lookback)
        df["smd_pivot_low"] = self._find_pivot_lows(df["low"], self.pivot_lookback)
        
        # Find corresponding pivots in RSI
        df["smd_rsi_pivot_high"] = self._find_pivot_highs(df["smd_rsi"], self.pivot_lookback)
        df["smd_rsi_pivot_low"] = self._find_pivot_lows(df["smd_rsi"], self.pivot_lookback)
        
        # Detect divergences
        df = self._detect_divergences(df)
        
        return df
    
    def _add_empty_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add empty columns when insufficient data."""
        df = df.copy()
        df["smd_rsi"] = 50.0
        df["smd_obv"] = 0.0
        df["smd_pivot_high"] = np.nan
        df["smd_pivot_low"] = np.nan
        df["smd_rsi_pivot_high"] = np.nan
        df["smd_rsi_pivot_low"] = np.nan
        df["smd_bullish_divergence"] = False
        df["smd_bearish_divergence"] = False
        df["smd_bullish_strength"] = 0.0
        df["smd_bearish_strength"] = 0.0
        df["smd_volume_divergence"] = 0.0
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.fillna(50)
    
    def _calculate_obv(self, df: pd.DataFrame) -> pd.Series:
        """Calculate On-Balance Volume."""
        obv = np.zeros(len(df))
        obv[0] = df["volume"].iloc[0]
        
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i-1]:
                obv[i] = obv[i-1] + df["volume"].iloc[i]
            elif df["close"].iloc[i] < df["close"].iloc[i-1]:
                obv[i] = obv[i-1] - df["volume"].iloc[i]
            else:
                obv[i] = obv[i-1]
        
        return pd.Series(obv, index=df.index)
    
    def _find_pivot_highs(self, series: pd.Series, lookback: int) -> pd.Series:
        """Find pivot high points."""
        pivots = pd.Series(np.nan, index=series.index)
        
        for i in range(lookback, len(series) - lookback):
            window = series.iloc[i-lookback:i+lookback+1]
            if series.iloc[i] == window.max():
                pivots.iloc[i] = series.iloc[i]
        
        return pivots
    
    def _find_pivot_lows(self, series: pd.Series, lookback: int) -> pd.Series:
        """Find pivot low points."""
        pivots = pd.Series(np.nan, index=series.index)
        
        for i in range(lookback, len(series) - lookback):
            window = series.iloc[i-lookback:i+lookback+1]
            if series.iloc[i] == window.min():
                pivots.iloc[i] = series.iloc[i]
        
        return pivots
    
    def _detect_divergences(self, df: pd.DataFrame) -> pd.DataFrame:
        """Detect bullish and bearish divergences."""
        df = df.copy()
        n = len(df)
        
        bullish_div = np.zeros(n, dtype=bool)
        bearish_div = np.zeros(n, dtype=bool)
        bullish_strength = np.zeros(n)
        bearish_strength = np.zeros(n)
        volume_div = np.zeros(n)
        
        # Get pivot indices
        price_lows = df["smd_pivot_low"].dropna()
        price_highs = df["smd_pivot_high"].dropna()
        rsi_lows = df["smd_rsi_pivot_low"].dropna()
        rsi_highs = df["smd_rsi_pivot_high"].dropna()
        
        # Detect bullish divergence (price lower low, RSI higher low)
        for i in range(1, len(price_lows)):
            curr_idx = price_lows.index[i]
            prev_idx = price_lows.index[i-1]
            
            # Get bar positions
            curr_pos = df.index.get_loc(curr_idx)
            prev_pos = df.index.get_loc(prev_idx)
            
            if curr_pos - prev_pos < self.min_divergence_bars:
                continue
            
            # Price making lower low
            if price_lows.iloc[i] < price_lows.iloc[i-1]:
                # Look for RSI higher low in the same period
                rsi_in_range = rsi_lows[(rsi_lows.index >= prev_idx) & (rsi_lows.index <= curr_idx)]
                
                if len(rsi_in_range) >= 2:
                    if rsi_in_range.iloc[-1] > rsi_in_range.iloc[0]:
                        # Bullish divergence detected
                        bullish_div[curr_pos] = True
                        
                        # Calculate strength based on divergence magnitude
                        price_change = (price_lows.iloc[i-1] - price_lows.iloc[i]) / price_lows.iloc[i-1]
                        rsi_change = (rsi_in_range.iloc[-1] - rsi_in_range.iloc[0]) / 100
                        bullish_strength[curr_pos] = min(abs(price_change) + abs(rsi_change), 1.0)
        
        # Detect bearish divergence (price higher high, RSI lower high)
        for i in range(1, len(price_highs)):
            curr_idx = price_highs.index[i]
            prev_idx = price_highs.index[i-1]
            
            curr_pos = df.index.get_loc(curr_idx)
            prev_pos = df.index.get_loc(prev_idx)
            
            if curr_pos - prev_pos < self.min_divergence_bars:
                continue
            
            # Price making higher high
            if price_highs.iloc[i] > price_highs.iloc[i-1]:
                # Look for RSI lower high in the same period
                rsi_in_range = rsi_highs[(rsi_highs.index >= prev_idx) & (rsi_highs.index <= curr_idx)]
                
                if len(rsi_in_range) >= 2:
                    if rsi_in_range.iloc[-1] < rsi_in_range.iloc[0]:
                        # Bearish divergence detected
                        bearish_div[curr_pos] = True
                        
                        price_change = (price_highs.iloc[i] - price_highs.iloc[i-1]) / price_highs.iloc[i-1]
                        rsi_change = (rsi_in_range.iloc[0] - rsi_in_range.iloc[-1]) / 100
                        bearish_strength[curr_pos] = min(abs(price_change) + abs(rsi_change), 1.0)
        
        # Volume divergence (price moving but volume declining)
        for i in range(5, n):
            price_change = abs(df["close"].iloc[i] - df["close"].iloc[i-5]) / df["close"].iloc[i-5]
            vol_change = (df["volume"].iloc[i-5:i].mean() - df["volume"].iloc[i]) / df["volume"].iloc[i-5:i].mean()
            
            if price_change > 0.003 and vol_change > 0.2:  # Price moved but volume declined
                volume_div[i] = min(price_change * vol_change * 10, 1.0)
        
        df["smd_bullish_divergence"] = bullish_div
        df["smd_bearish_divergence"] = bearish_div
        df["smd_bullish_strength"] = bullish_strength
        df["smd_bearish_strength"] = bearish_strength
        df["smd_volume_divergence"] = volume_div
        
        return df
    
    def as_features(self, latest: pd.Series, df: Optional[pd.DataFrame] = None) -> Dict[str, float]:
        """Extract features for the learning system."""
        features = {}
        
        try:
            # RSI level (normalized to 0-1)
            features["smd_rsi_level"] = float(latest.get("smd_rsi", 50)) / 100.0
            
            # Divergence detection (boolean as 0/1)
            features["smd_bullish_divergence"] = 1.0 if latest.get("smd_bullish_divergence", False) else 0.0
            features["smd_bearish_divergence"] = 1.0 if latest.get("smd_bearish_divergence", False) else 0.0
            
            # Divergence strength (already 0-1)
            features["smd_bullish_strength"] = float(latest.get("smd_bullish_strength", 0))
            features["smd_bearish_strength"] = float(latest.get("smd_bearish_strength", 0))
            
            # Volume divergence (already 0-1)
            features["smd_volume_divergence"] = float(latest.get("smd_volume_divergence", 0))
            
            # RSI extreme zones
            rsi = float(latest.get("smd_rsi", 50))
            features["smd_rsi_oversold"] = 1.0 if rsi < 30 else 0.0
            features["smd_rsi_overbought"] = 1.0 if rsi > 70 else 0.0
            
            # Recent OBV trend (if df provided)
            if df is not None and len(df) >= 5 and "smd_obv" in df.columns:
                obv_now = df["smd_obv"].iloc[-1]
                obv_prev = df["smd_obv"].iloc[-5]
                if obv_prev != 0:
                    obv_change = (obv_now - obv_prev) / abs(obv_prev)
                    features["smd_obv_trend"] = (np.tanh(obv_change * 10) + 1) / 2  # Normalize to 0-1
                else:
                    features["smd_obv_trend"] = 0.5
            else:
                features["smd_obv_trend"] = 0.5
            
        except Exception:
            return self._default_features()
        
        return features
    
    def _default_features(self) -> Dict[str, float]:
        """Return default feature values."""
        return {
            "smd_rsi_level": 0.5,
            "smd_bullish_divergence": 0.0,
            "smd_bearish_divergence": 0.0,
            "smd_bullish_strength": 0.0,
            "smd_bearish_strength": 0.0,
            "smd_volume_divergence": 0.0,
            "smd_rsi_oversold": 0.0,
            "smd_rsi_overbought": 0.0,
            "smd_obv_trend": 0.5,
        }
    
    def generate_signal(
        self,
        latest: pd.Series,
        df: pd.DataFrame,
        atr: Optional[float] = None,
    ) -> Optional[IndicatorSignal]:
        """Generate signal on divergence detection."""
        try:
            close = float(latest.get("close", 0))
            if close <= 0:
                return None
            
            if atr is None or atr <= 0:
                atr = close * 0.005
            
            # Bullish divergence signal
            if latest.get("smd_bullish_divergence", False):
                strength = float(latest.get("smd_bullish_strength", 0.5))
                rsi = float(latest.get("smd_rsi", 50))
                
                # Stronger signal if RSI is oversold
                confidence = 0.50 + strength * 0.2
                if rsi < 35:
                    confidence += 0.1
                
                return IndicatorSignal(
                    type="smd_bullish_divergence",
                    direction="long",
                    confidence=min(confidence, 0.80),
                    entry_price=close,
                    stop_loss=close - atr * 1.5,
                    take_profit=close + atr * 2.5,
                    reason=f"Bullish RSI divergence detected (RSI: {rsi:.0f}, strength: {strength:.0%})",
                    metadata={
                        "divergence_strength": strength,
                        "rsi": rsi,
                        "divergence_type": "bullish_regular",
                    },
                )
            
            # Bearish divergence signal
            if latest.get("smd_bearish_divergence", False):
                strength = float(latest.get("smd_bearish_strength", 0.5))
                rsi = float(latest.get("smd_rsi", 50))
                
                confidence = 0.50 + strength * 0.2
                if rsi > 65:
                    confidence += 0.1
                
                return IndicatorSignal(
                    type="smd_bearish_divergence",
                    direction="short",
                    confidence=min(confidence, 0.80),
                    entry_price=close,
                    stop_loss=close + atr * 1.5,
                    take_profit=close - atr * 2.5,
                    reason=f"Bearish RSI divergence detected (RSI: {rsi:.0f}, strength: {strength:.0%})",
                    metadata={
                        "divergence_strength": strength,
                        "rsi": rsi,
                        "divergence_type": "bearish_regular",
                    },
                )
            
        except Exception:
            pass
        
        return None
    
    def get_signal_types(self) -> List[str]:
        """Get signal types this indicator generates."""
        return ["smd_bullish_divergence", "smd_bearish_divergence"]


