"""
Feature Engineering for ML-Enhanced Trading

Extracts 50+ predictive features from market data for machine learning models.
Features are grouped into categories:
- Price Action (trend, momentum, volatility)
- Volume Profile (distribution, anomalies)
- Microstructure (order flow, imbalance)
- Time-based (session timing, patterns)
- Sequential (recent trade outcomes)
- Cross-timeframe (multi-resolution alignment)

All features are normalized to 0-1 or standardized for ML compatibility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pearlalgo.utils.logger import logger


@dataclass
class FeatureConfig:
    """Configuration for feature engineering."""
    # Lookback windows
    short_window: int = 5
    medium_window: int = 20
    long_window: int = 50
    
    # Feature toggles
    compute_price_action: bool = True
    compute_volume_profile: bool = True
    compute_microstructure: bool = True
    compute_time_features: bool = True
    compute_sequential: bool = True
    compute_cross_timeframe: bool = True
    
    # Normalization
    normalize_features: bool = True
    clip_outliers: bool = True
    outlier_std: float = 3.0
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "FeatureConfig":
        """Create from dictionary."""
        return cls(
            short_window=int(config.get("short_window", 5)),
            medium_window=int(config.get("medium_window", 20)),
            long_window=int(config.get("long_window", 50)),
            compute_price_action=bool(config.get("compute_price_action", True)),
            compute_volume_profile=bool(config.get("compute_volume_profile", True)),
            compute_microstructure=bool(config.get("compute_microstructure", True)),
            compute_time_features=bool(config.get("compute_time_features", True)),
            compute_sequential=bool(config.get("compute_sequential", True)),
            compute_cross_timeframe=bool(config.get("compute_cross_timeframe", True)),
            normalize_features=bool(config.get("normalize_features", True)),
            clip_outliers=bool(config.get("clip_outliers", True)),
            outlier_std=float(config.get("outlier_std", 3.0)),
        )


@dataclass
class FeatureVector:
    """Container for computed features with metadata."""
    features: Dict[str, float] = field(default_factory=dict)
    timestamp: Optional[str] = None
    symbol: Optional[str] = None
    signal_type: Optional[str] = None
    
    # Feature categories
    price_action: Dict[str, float] = field(default_factory=dict)
    volume_profile: Dict[str, float] = field(default_factory=dict)
    microstructure: Dict[str, float] = field(default_factory=dict)
    time_features: Dict[str, float] = field(default_factory=dict)
    sequential: Dict[str, float] = field(default_factory=dict)
    cross_timeframe: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "features": self.features,
            "price_action": self.price_action,
            "volume_profile": self.volume_profile,
            "microstructure": self.microstructure,
            "time_features": self.time_features,
            "sequential": self.sequential,
            "cross_timeframe": self.cross_timeframe,
        }
    
    def to_array(self, feature_names: Optional[List[str]] = None) -> np.ndarray:
        """Convert to numpy array for ML models."""
        if feature_names is None:
            feature_names = sorted(self.features.keys())
        return np.array([self.features.get(name, 0.0) for name in feature_names])
    
    @property
    def num_features(self) -> int:
        """Number of features computed."""
        return len(self.features)


class FeatureEngineer:
    """
    Extracts predictive features from market data.
    
    Features are designed to capture:
    - Short-term momentum and mean reversion signals
    - Volume anomalies and distribution patterns
    - Order flow imbalance and microstructure
    - Time-of-day and session patterns
    - Sequential patterns from recent trades
    - Cross-timeframe alignment
    
    All features are normalized for ML model consumption.
    """
    
    def __init__(self, config: Optional[FeatureConfig] = None):
        """
        Initialize feature engineer.
        
        Args:
            config: Feature configuration (defaults if not provided)
        """
        self.config = config or FeatureConfig()
        self._feature_names: List[str] = []
        self._running_stats: Dict[str, Dict[str, float]] = {}  # For online normalization
        
        logger.info(f"FeatureEngineer initialized with {self._count_enabled_categories()} feature categories")
    
    def _count_enabled_categories(self) -> int:
        """Count enabled feature categories."""
        count = 0
        if self.config.compute_price_action:
            count += 1
        if self.config.compute_volume_profile:
            count += 1
        if self.config.compute_microstructure:
            count += 1
        if self.config.compute_time_features:
            count += 1
        if self.config.compute_sequential:
            count += 1
        if self.config.compute_cross_timeframe:
            count += 1
        return count
    
    def compute_features(
        self,
        df: pd.DataFrame,
        signal: Optional[Dict] = None,
        recent_outcomes: Optional[List[Dict]] = None,
        higher_tf_data: Optional[pd.DataFrame] = None,
    ) -> FeatureVector:
        """
        Compute all features from market data.
        
        Args:
            df: OHLCV DataFrame (must have Open, High, Low, Close, Volume columns)
            signal: Current signal dictionary (optional, for signal-specific features)
            recent_outcomes: List of recent trade outcomes (for sequential features)
            higher_tf_data: Higher timeframe data (for cross-TF features)
            
        Returns:
            FeatureVector with all computed features
        """
        if df is None or df.empty or len(df) < self.config.short_window:
            logger.warning("Insufficient data for feature computation")
            return FeatureVector()
        
        # Ensure columns are properly named
        df = self._normalize_columns(df)
        
        fv = FeatureVector(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=signal.get("symbol") if signal else None,
            signal_type=signal.get("type") if signal else None,
        )
        
        # Compute each category
        if self.config.compute_price_action:
            fv.price_action = self._compute_price_action_features(df)
            fv.features.update(fv.price_action)
        
        if self.config.compute_volume_profile:
            fv.volume_profile = self._compute_volume_features(df)
            fv.features.update(fv.volume_profile)
        
        if self.config.compute_microstructure:
            fv.microstructure = self._compute_microstructure_features(df, signal)
            fv.features.update(fv.microstructure)
        
        if self.config.compute_time_features:
            fv.time_features = self._compute_time_features(df)
            fv.features.update(fv.time_features)
        
        if self.config.compute_sequential and recent_outcomes:
            fv.sequential = self._compute_sequential_features(recent_outcomes)
            fv.features.update(fv.sequential)
        
        if self.config.compute_cross_timeframe and higher_tf_data is not None:
            fv.cross_timeframe = self._compute_cross_timeframe_features(df, higher_tf_data)
            fv.features.update(fv.cross_timeframe)
        
        # Normalize features
        if self.config.normalize_features:
            fv.features = self._normalize_features(fv.features)
        
        # Update feature names list
        if not self._feature_names:
            self._feature_names = sorted(fv.features.keys())
        
        logger.debug(f"Computed {fv.num_features} features")
        return fv
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize column names to standard OHLCV."""
        df = df.copy()
        
        # Common column name mappings
        col_map = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "OPEN": "Open",
            "HIGH": "High",
            "LOW": "Low",
            "CLOSE": "Close",
            "VOLUME": "Volume",
        }
        
        df.columns = [col_map.get(c, c) for c in df.columns]
        return df
    
    # =========================================================================
    # PRICE ACTION FEATURES (15+ features)
    # =========================================================================
    
    def _compute_price_action_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Compute price action features."""
        features = {}
        
        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values
        open_ = df["Open"].values
        
        # Returns
        returns = np.diff(close) / close[:-1]
        if len(returns) == 0:
            returns = np.array([0.0])
        
        # 1. Short-term momentum (5-bar)
        if len(close) >= self.config.short_window:
            features["momentum_short"] = (close[-1] - close[-self.config.short_window]) / close[-self.config.short_window]
        else:
            features["momentum_short"] = 0.0
        
        # 2. Medium-term momentum (20-bar)
        if len(close) >= self.config.medium_window:
            features["momentum_medium"] = (close[-1] - close[-self.config.medium_window]) / close[-self.config.medium_window]
        else:
            features["momentum_medium"] = 0.0
        
        # 3. Long-term momentum (50-bar)
        if len(close) >= self.config.long_window:
            features["momentum_long"] = (close[-1] - close[-self.config.long_window]) / close[-self.config.long_window]
        else:
            features["momentum_long"] = 0.0
        
        # 4. RSI (14-period)
        features["rsi_14"] = self._compute_rsi(close, 14)
        
        # 5. RSI (7-period) - faster
        features["rsi_7"] = self._compute_rsi(close, 7)
        
        # 6. Price position in range (0-1)
        if len(high) >= self.config.medium_window:
            hh = np.max(high[-self.config.medium_window:])
            ll = np.min(low[-self.config.medium_window:])
            range_size = hh - ll
            if range_size > 0:
                features["price_position"] = (close[-1] - ll) / range_size
            else:
                features["price_position"] = 0.5
        else:
            features["price_position"] = 0.5
        
        # 7. ATR (14-period) normalized
        features["atr_14_pct"] = self._compute_atr(high, low, close, 14) / close[-1]
        
        # 8. ATR ratio (short/long)
        atr_short = self._compute_atr(high, low, close, self.config.short_window)
        atr_long = self._compute_atr(high, low, close, self.config.medium_window)
        features["atr_ratio"] = atr_short / atr_long if atr_long > 0 else 1.0
        
        # 9. Volatility percentile
        if len(returns) >= self.config.medium_window:
            vol_window = np.std(returns[-self.config.medium_window:])
            vol_longer = np.std(returns[-min(len(returns), self.config.long_window):])
            features["volatility_percentile"] = vol_window / vol_longer if vol_longer > 0 else 1.0
        else:
            features["volatility_percentile"] = 1.0
        
        # 10. Candle body ratio (body / range)
        body = abs(close[-1] - open_[-1])
        range_ = high[-1] - low[-1]
        features["candle_body_ratio"] = body / range_ if range_ > 0 else 0.5
        
        # 11. Upper wick ratio
        upper_wick = high[-1] - max(close[-1], open_[-1])
        features["upper_wick_ratio"] = upper_wick / range_ if range_ > 0 else 0.0
        
        # 12. Lower wick ratio
        lower_wick = min(close[-1], open_[-1]) - low[-1]
        features["lower_wick_ratio"] = lower_wick / range_ if range_ > 0 else 0.0
        
        # 13. Consecutive direction (positive/negative bars)
        features["consecutive_up"] = self._count_consecutive_direction(returns, positive=True)
        features["consecutive_down"] = self._count_consecutive_direction(returns, positive=False)
        
        # 14. Mean reversion score (distance from moving average)
        if len(close) >= self.config.medium_window:
            ma = np.mean(close[-self.config.medium_window:])
            features["ma_deviation"] = (close[-1] - ma) / ma
        else:
            features["ma_deviation"] = 0.0
        
        # 15. Trend strength (ADX-like)
        features["trend_strength"] = self._compute_trend_strength(high, low, close)
        
        # 16. Higher high / lower low pattern
        if len(high) >= 3:
            features["higher_high"] = 1.0 if high[-1] > high[-2] > high[-3] else 0.0
            features["lower_low"] = 1.0 if low[-1] < low[-2] < low[-3] else 0.0
        else:
            features["higher_high"] = 0.0
            features["lower_low"] = 0.0
        
        return features
    
    def _compute_rsi(self, close: np.ndarray, period: int = 14) -> float:
        """Compute RSI indicator."""
        if len(close) < period + 1:
            return 50.0
        
        deltas = np.diff(close[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi / 100.0  # Normalize to 0-1
    
    def _compute_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
        """Compute Average True Range."""
        if len(high) < period + 1:
            return 0.0
        
        tr = np.zeros(len(high) - 1)
        for i in range(1, len(high)):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i-1])
            lc = abs(low[i] - close[i-1])
            tr[i-1] = max(hl, hc, lc)
        
        return np.mean(tr[-period:])
    
    def _compute_trend_strength(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> float:
        """Compute trend strength (simplified ADX-like measure)."""
        if len(close) < self.config.medium_window:
            return 0.5
        
        # Use linear regression slope normalized by ATR
        x = np.arange(self.config.medium_window)
        y = close[-self.config.medium_window:]
        
        # Simple linear regression
        slope = np.polyfit(x, y, 1)[0]
        atr = self._compute_atr(high, low, close, self.config.medium_window)
        
        if atr == 0:
            return 0.5
        
        # Normalize slope by ATR
        normalized_slope = slope / atr
        
        # Map to 0-1 range (sigmoid-like)
        return 1 / (1 + np.exp(-normalized_slope * 10))
    
    def _count_consecutive_direction(self, returns: np.ndarray, positive: bool = True) -> float:
        """Count consecutive positive or negative returns."""
        count = 0
        for r in reversed(returns):
            if (positive and r > 0) or (not positive and r < 0):
                count += 1
            else:
                break
        return min(count / 10.0, 1.0)  # Cap at 10, normalize to 0-1
    
    # =========================================================================
    # VOLUME FEATURES (10+ features)
    # =========================================================================
    
    def _compute_volume_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Compute volume-based features."""
        features = {}
        
        volume = df["Volume"].values
        close = df["Close"].values
        
        if len(volume) < self.config.short_window:
            return features
        
        # 1. Volume ratio (current / average)
        avg_vol = np.mean(volume[-self.config.medium_window:]) if len(volume) >= self.config.medium_window else np.mean(volume)
        features["volume_ratio"] = volume[-1] / avg_vol if avg_vol > 0 else 1.0
        
        # 2. Volume trend (short-term)
        if len(volume) >= self.config.short_window:
            vol_short = np.mean(volume[-self.config.short_window:])
            vol_longer = np.mean(volume[-self.config.medium_window:]) if len(volume) >= self.config.medium_window else vol_short
            features["volume_trend"] = vol_short / vol_longer if vol_longer > 0 else 1.0
        else:
            features["volume_trend"] = 1.0
        
        # 3. Volume spike (current vs recent max)
        if len(volume) >= self.config.medium_window:
            max_vol = np.max(volume[-self.config.medium_window:-1])
            features["volume_spike"] = volume[-1] / max_vol if max_vol > 0 else 1.0
        else:
            features["volume_spike"] = 1.0
        
        # 4. Volume-weighted price (relative)
        if len(volume) >= self.config.short_window:
            vwap = np.average(close[-self.config.short_window:], weights=volume[-self.config.short_window:])
            features["vwap_deviation"] = (close[-1] - vwap) / vwap if vwap > 0 else 0.0
        else:
            features["vwap_deviation"] = 0.0
        
        # 5. On-Balance Volume trend
        obv = self._compute_obv(close, volume)
        if len(obv) >= self.config.short_window:
            obv_short = np.mean(obv[-self.config.short_window:])
            obv_longer = np.mean(obv[-self.config.medium_window:]) if len(obv) >= self.config.medium_window else obv_short
            features["obv_trend"] = 1.0 if obv_short > obv_longer else 0.0
        else:
            features["obv_trend"] = 0.5
        
        # 6. Volume momentum
        if len(volume) >= self.config.short_window:
            vol_change = (volume[-1] - volume[-self.config.short_window]) / volume[-self.config.short_window] if volume[-self.config.short_window] > 0 else 0
            features["volume_momentum"] = max(min(vol_change, 2.0), -2.0) / 2.0 + 0.5  # Normalize to 0-1
        else:
            features["volume_momentum"] = 0.5
        
        # 7. Price-volume correlation (short window)
        if len(volume) >= self.config.short_window:
            price_returns = np.diff(close[-self.config.short_window:])
            vol_changes = np.diff(volume[-self.config.short_window:])
            if len(price_returns) > 1 and np.std(price_returns) > 0 and np.std(vol_changes) > 0:
                corr = np.corrcoef(price_returns, vol_changes)[0, 1]
                features["price_volume_corr"] = (corr + 1) / 2  # Normalize to 0-1
            else:
                features["price_volume_corr"] = 0.5
        else:
            features["price_volume_corr"] = 0.5
        
        # 8. Volume distribution skewness
        if len(volume) >= self.config.medium_window:
            vol_std = np.std(volume[-self.config.medium_window:])
            vol_mean = np.mean(volume[-self.config.medium_window:])
            if vol_std > 0:
                skew = np.mean(((volume[-self.config.medium_window:] - vol_mean) / vol_std) ** 3)
                features["volume_skewness"] = max(min(skew / 3.0 + 0.5, 1.0), 0.0)
            else:
                features["volume_skewness"] = 0.5
        else:
            features["volume_skewness"] = 0.5
        
        # 9. Volume percentile
        if len(volume) >= self.config.long_window:
            percentile = np.sum(volume[-self.config.long_window:-1] < volume[-1]) / (self.config.long_window - 1)
            features["volume_percentile"] = percentile
        else:
            features["volume_percentile"] = 0.5
        
        # 10. Quiet bar detection (low volume + small range)
        avg_vol = np.mean(volume[-self.config.medium_window:]) if len(volume) >= self.config.medium_window else np.mean(volume)
        avg_range = np.mean(df["High"].values[-self.config.medium_window:] - df["Low"].values[-self.config.medium_window:]) if len(volume) >= self.config.medium_window else 1.0
        current_range = df["High"].values[-1] - df["Low"].values[-1]
        
        is_quiet_vol = volume[-1] < avg_vol * 0.5
        is_quiet_range = current_range < avg_range * 0.5
        features["quiet_bar"] = 1.0 if (is_quiet_vol and is_quiet_range) else 0.0
        
        return features
    
    def _compute_obv(self, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
        """Compute On-Balance Volume."""
        obv = np.zeros(len(close))
        obv[0] = volume[0]
        
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv[i] = obv[i-1] + volume[i]
            elif close[i] < close[i-1]:
                obv[i] = obv[i-1] - volume[i]
            else:
                obv[i] = obv[i-1]
        
        return obv
    
    # =========================================================================
    # MICROSTRUCTURE FEATURES (8+ features)
    # =========================================================================
    
    def _compute_microstructure_features(self, df: pd.DataFrame, signal: Optional[Dict] = None) -> Dict[str, float]:
        """Compute microstructure features."""
        features = {}
        
        close = df["Close"].values
        high = df["High"].values
        low = df["Low"].values
        
        # 1. Bid-Ask spread approximation (using high-low)
        spread = (high[-1] - low[-1]) / close[-1]
        features["spread_estimate"] = min(spread * 100, 1.0)  # Normalize
        
        # 2. Spread ratio (current vs average)
        avg_spread = np.mean((high[-self.config.medium_window:] - low[-self.config.medium_window:]) / close[-self.config.medium_window:]) if len(close) >= self.config.medium_window else spread
        features["spread_ratio"] = spread / avg_spread if avg_spread > 0 else 1.0
        
        # 3. Order flow imbalance approximation
        # Use close position in bar as proxy
        bar_range = high[-1] - low[-1]
        if bar_range > 0:
            close_position = (close[-1] - low[-1]) / bar_range
            features["order_flow_imbalance"] = close_position  # 1 = buying, 0 = selling
        else:
            features["order_flow_imbalance"] = 0.5
        
        # 4. Accumulated order flow (last N bars)
        if len(close) >= self.config.short_window:
            imbalances = []
            for i in range(-self.config.short_window, 0):
                br = high[i] - low[i]
                if br > 0:
                    imbalances.append((close[i] - low[i]) / br)
                else:
                    imbalances.append(0.5)
            features["order_flow_accumulated"] = np.mean(imbalances)
        else:
            features["order_flow_accumulated"] = 0.5
        
        # 5. Tick intensity (number of significant price changes)
        if len(close) >= self.config.short_window:
            tick_changes = np.sum(np.abs(np.diff(close[-self.config.short_window:])) > 0.001 * close[-1])
            features["tick_intensity"] = tick_changes / (self.config.short_window - 1)
        else:
            features["tick_intensity"] = 0.5
        
        # 6. Price impact estimate (return per volume unit)
        if "Volume" in df.columns and len(df) >= self.config.short_window:
            volume = df["Volume"].values
            returns = np.diff(close[-self.config.short_window:])
            vols = volume[-self.config.short_window:-1]
            if np.sum(vols) > 0:
                avg_impact = np.mean(np.abs(returns) / (vols + 1))
                features["price_impact"] = min(avg_impact * 1000, 1.0)  # Normalize
            else:
                features["price_impact"] = 0.0
        else:
            features["price_impact"] = 0.0
        
        # 7. Signal-specific: Distance to entry price
        if signal and signal.get("entry_price"):
            entry = float(signal["entry_price"])
            features["entry_distance_pct"] = abs(close[-1] - entry) / entry
        else:
            features["entry_distance_pct"] = 0.0
        
        # 8. Signal-specific: Risk-reward ratio
        if signal and signal.get("entry_price") and signal.get("stop_loss") and signal.get("take_profit"):
            entry = float(signal["entry_price"])
            sl = float(signal["stop_loss"])
            tp = float(signal["take_profit"])
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            features["risk_reward_ratio"] = reward / risk if risk > 0 else 0.0
        else:
            features["risk_reward_ratio"] = 0.0
        
        return features
    
    # =========================================================================
    # TIME-BASED FEATURES (10+ features)
    # =========================================================================
    
    def _compute_time_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Compute time-based features."""
        features = {}
        
        # Get current timestamp
        if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
            current_time = df.index[-1]
            if hasattr(current_time, 'hour'):
                hour = current_time.hour
                minute = current_time.minute
                day_of_week = current_time.dayofweek
            else:
                hour = 12
                minute = 0
                day_of_week = 0
        else:
            now = datetime.now()
            hour = now.hour
            minute = now.minute
            day_of_week = now.weekday()
        
        # 1. Hour of day (cyclical encoding)
        features["hour_sin"] = math.sin(2 * math.pi * hour / 24)
        features["hour_cos"] = math.cos(2 * math.pi * hour / 24)
        
        # 2. Minute of hour (cyclical encoding)
        features["minute_sin"] = math.sin(2 * math.pi * minute / 60)
        features["minute_cos"] = math.cos(2 * math.pi * minute / 60)
        
        # 3. Day of week (cyclical encoding)
        features["day_sin"] = math.sin(2 * math.pi * day_of_week / 7)
        features["day_cos"] = math.cos(2 * math.pi * day_of_week / 7)
        
        # 4. Session phases (0-1 encoding)
        # Assuming US futures session: 18:00 - 17:00 ET next day
        # Pre-market: 18:00-09:30, Market: 09:30-16:00, After-hours: 16:00-17:00
        if 18 <= hour or hour < 6:
            features["session_phase"] = 0.0  # Overnight
        elif 6 <= hour < 9:
            features["session_phase"] = 0.25  # Pre-market
        elif 9 <= hour < 12:
            features["session_phase"] = 0.5  # Morning session
        elif 12 <= hour < 15:
            features["session_phase"] = 0.75  # Afternoon session
        else:
            features["session_phase"] = 1.0  # Close/After-hours
        
        # 5. Time since session open (normalized)
        # Assume session opens at 18:00 ET (futures)
        if hour >= 18:
            hours_since_open = hour - 18 + minute / 60
        else:
            hours_since_open = (hour + 24 - 18) + minute / 60
        features["hours_since_open"] = min(hours_since_open / 23.0, 1.0)  # 23-hour session
        
        # 6. Is market open (regular trading hours)
        is_rth = 9 <= hour < 16 and day_of_week < 5
        features["is_rth"] = 1.0 if is_rth else 0.0
        
        # 7. Is first hour of session
        features["is_first_hour"] = 1.0 if (9 <= hour < 10) else 0.0
        
        # 8. Is last hour of session
        features["is_last_hour"] = 1.0 if (15 <= hour < 16) else 0.0
        
        # 9. Is lunch hour (typically lower volume)
        features["is_lunch_hour"] = 1.0 if (12 <= hour < 13) else 0.0
        
        # 10. Weekend proximity
        if day_of_week == 4:  # Friday
            features["weekend_proximity"] = 1.0
        elif day_of_week == 0:  # Monday
            features["weekend_proximity"] = 0.5
        else:
            features["weekend_proximity"] = 0.0
        
        return features
    
    # =========================================================================
    # SEQUENTIAL FEATURES (from recent trade outcomes)
    # =========================================================================
    
    def _compute_sequential_features(self, recent_outcomes: List[Dict]) -> Dict[str, float]:
        """Compute features from recent trade outcomes."""
        features = {}
        
        if not recent_outcomes:
            # Default values when no history
            features["recent_win_rate"] = 0.5
            features["recent_avg_pnl"] = 0.0
            features["recent_streak"] = 0.5
            features["recent_volatility"] = 0.5
            features["recent_hold_time"] = 0.5
            return features
        
        # Get outcomes (limit to last 20)
        outcomes = recent_outcomes[-20:]
        
        # 1. Recent win rate
        wins = sum(1 for o in outcomes if o.get("is_win", False))
        features["recent_win_rate"] = wins / len(outcomes)
        
        # 2. Recent average P&L (normalized)
        pnls = [o.get("pnl", 0) for o in outcomes if "pnl" in o]
        if pnls:
            avg_pnl = np.mean(pnls)
            # Normalize to -1 to 1 (assume max expected P&L is $500)
            features["recent_avg_pnl"] = max(min(avg_pnl / 500, 1.0), -1.0)
        else:
            features["recent_avg_pnl"] = 0.0
        
        # 3. Win/loss streak
        streak = 0
        if outcomes:
            last_outcome = outcomes[-1].get("is_win", False)
            for o in reversed(outcomes):
                if o.get("is_win", False) == last_outcome:
                    streak += 1
                else:
                    break
            # Positive for win streak, negative for loss streak
            streak = streak if last_outcome else -streak
        features["recent_streak"] = (streak + 10) / 20  # Normalize to 0-1 (assumes max streak 10)
        
        # 4. P&L volatility (consistency)
        if len(pnls) >= 3:
            features["recent_volatility"] = min(np.std(pnls) / 200, 1.0)  # Normalize
        else:
            features["recent_volatility"] = 0.5
        
        # 5. Average hold time (normalized)
        hold_times = [o.get("hold_duration_minutes", 30) for o in outcomes if "hold_duration_minutes" in o]
        if hold_times:
            avg_hold = np.mean(hold_times)
            features["recent_hold_time"] = min(avg_hold / 120, 1.0)  # Normalize (2 hours = 1.0)
        else:
            features["recent_hold_time"] = 0.5
        
        # 6. Same signal type performance
        signal_types = [o.get("signal_type") for o in outcomes if o.get("signal_type")]
        if signal_types:
            # Count how many of same type won
            from collections import Counter
            type_counts = Counter(signal_types)
            most_common = type_counts.most_common(1)[0][0]
            same_type = [o for o in outcomes if o.get("signal_type") == most_common]
            same_type_wins = sum(1 for o in same_type if o.get("is_win", False))
            features["same_type_win_rate"] = same_type_wins / len(same_type) if same_type else 0.5
        else:
            features["same_type_win_rate"] = 0.5
        
        # 7. Recency-weighted win rate (recent trades count more)
        if outcomes:
            weights = np.exp(np.linspace(-2, 0, len(outcomes)))  # Exponential weights
            weighted_wins = sum(w * (1 if o.get("is_win", False) else 0) for w, o in zip(weights, outcomes))
            features["recency_weighted_wr"] = weighted_wins / sum(weights)
        else:
            features["recency_weighted_wr"] = 0.5
        
        # 8. Drawdown indicator
        if pnls:
            cumulative = np.cumsum(pnls)
            peak = np.maximum.accumulate(cumulative)
            drawdown = peak - cumulative
            max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
            features["in_drawdown"] = 1.0 if max_dd > 200 else max_dd / 200  # Normalize
        else:
            features["in_drawdown"] = 0.0
        
        return features
    
    # =========================================================================
    # CROSS-TIMEFRAME FEATURES
    # =========================================================================
    
    def _compute_cross_timeframe_features(self, df: pd.DataFrame, higher_tf: pd.DataFrame) -> Dict[str, float]:
        """Compute cross-timeframe alignment features."""
        features = {}
        
        if higher_tf is None or higher_tf.empty:
            features["htf_trend_alignment"] = 0.5
            features["htf_momentum_alignment"] = 0.5
            features["htf_volatility_ratio"] = 1.0
            return features
        
        higher_tf = self._normalize_columns(higher_tf)
        
        close_ltf = df["Close"].values
        close_htf = higher_tf["Close"].values
        
        # 1. Trend alignment
        ltf_trend = 1 if close_ltf[-1] > np.mean(close_ltf[-self.config.short_window:]) else -1
        htf_trend = 1 if close_htf[-1] > np.mean(close_htf[-self.config.short_window:]) else -1
        features["htf_trend_alignment"] = 1.0 if ltf_trend == htf_trend else 0.0
        
        # 2. Momentum alignment
        if len(close_ltf) >= self.config.short_window and len(close_htf) >= self.config.short_window:
            ltf_mom = (close_ltf[-1] - close_ltf[-self.config.short_window]) / close_ltf[-self.config.short_window]
            htf_mom = (close_htf[-1] - close_htf[-self.config.short_window]) / close_htf[-self.config.short_window]
            # Both positive or both negative = aligned
            features["htf_momentum_alignment"] = 1.0 if (ltf_mom * htf_mom > 0) else 0.0
        else:
            features["htf_momentum_alignment"] = 0.5
        
        # 3. Volatility ratio (LTF vs HTF)
        ltf_atr = self._compute_atr(df["High"].values, df["Low"].values, close_ltf, self.config.short_window)
        htf_atr = self._compute_atr(higher_tf["High"].values, higher_tf["Low"].values, close_htf, self.config.short_window)
        features["htf_volatility_ratio"] = ltf_atr / htf_atr if htf_atr > 0 else 1.0
        
        # 4. HTF RSI
        features["htf_rsi"] = self._compute_rsi(close_htf, 14)
        
        # 5. HTF price position
        if len(higher_tf) >= self.config.medium_window:
            hh = np.max(higher_tf["High"].values[-self.config.medium_window:])
            ll = np.min(higher_tf["Low"].values[-self.config.medium_window:])
            range_size = hh - ll
            if range_size > 0:
                features["htf_price_position"] = (close_htf[-1] - ll) / range_size
            else:
                features["htf_price_position"] = 0.5
        else:
            features["htf_price_position"] = 0.5
        
        return features
    
    # =========================================================================
    # NORMALIZATION
    # =========================================================================
    
    def _normalize_features(self, features: Dict[str, float]) -> Dict[str, float]:
        """Normalize features to 0-1 range."""
        normalized = {}
        
        for name, value in features.items():
            # Handle NaN/Inf
            if not np.isfinite(value):
                value = 0.0
            
            # Clip outliers if configured
            if self.config.clip_outliers:
                # Update running stats
                if name not in self._running_stats:
                    self._running_stats[name] = {"mean": value, "std": 1.0, "count": 1}
                else:
                    stats = self._running_stats[name]
                    stats["count"] += 1
                    # Online mean/std update
                    delta = value - stats["mean"]
                    stats["mean"] += delta / stats["count"]
                    stats["std"] = max(abs(delta), stats["std"] * 0.99)  # Slow decay
                
                # Clip to N standard deviations
                stats = self._running_stats[name]
                lower = stats["mean"] - self.config.outlier_std * stats["std"]
                upper = stats["mean"] + self.config.outlier_std * stats["std"]
                value = max(min(value, upper), lower)
            
            normalized[name] = value
        
        return normalized
    
    def get_feature_names(self) -> List[str]:
        """Get list of feature names (for ML model compatibility)."""
        return self._feature_names.copy()
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Placeholder for feature importance (requires trained model)."""
        # Return equal weights for now
        if not self._feature_names:
            return {}
        weight = 1.0 / len(self._feature_names)
        return {name: weight for name in self._feature_names}




