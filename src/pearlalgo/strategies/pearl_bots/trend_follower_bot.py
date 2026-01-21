"""
Trend Follower Bot - PEARL Automated Trading System

A complete automated trading bot that follows trends using multiple timeframe analysis,
optimized for PEARLalgo's technical analysis framework.

Strategy Logic:
- Identifies strong trends using moving averages and trend strength indicators
- Enters on pullbacks within trending markets
- Uses volatility-adjusted stops and targets
- Filters signals based on market structure and momentum
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np
from functools import lru_cache
import hashlib

from .bot_template import BotConfig, TradeSignal, IndicatorSuite, TradingBot, register_bot


@dataclass
class CachedTrendFollowerIndicators(IndicatorSuite):
    """Optimized indicator suite with caching for trend following strategies."""

    # Configuration
    fast_ma_period: int = 20
    slow_ma_period: int = 50
    trend_strength_period: int = 14
    volatility_period: int = 20
    momentum_period: int = 10

    def __post_init__(self):
        # Cache for computed indicators
        self._indicator_cache: Dict[str, Dict[str, Any]] = {}
        self._dataframe_cache: Dict[str, pd.DataFrame] = {}

    def _get_cache_key(self, df: pd.DataFrame) -> str:
        """Generate cache key based on dataframe content and parameters."""
        # Use last 100 bars + parameter hash for cache key
        recent_data = df.tail(100) if len(df) > 100 else df
        data_hash = hashlib.md5(str(recent_data.values.tobytes()).encode()).hexdigest()[:16]
        param_hash = hashlib.md5(f"{self.fast_ma_period}_{self.slow_ma_period}_{self.trend_strength_period}_{self.volatility_period}_{self.momentum_period}".encode()).hexdigest()[:8]
        return f"{data_hash}_{param_hash}"

    def _calculate_base_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate all indicators efficiently with vectorized operations."""
        # Work on a copy to avoid modifying original
        df_calc = df.copy()

        # Vectorized moving averages
        df_calc['fast_ma'] = df_calc['close'].rolling(self.fast_ma_period, min_periods=1).mean()
        df_calc['slow_ma'] = df_calc['close'].rolling(self.slow_ma_period, min_periods=1).mean()

        # Trend direction (vectorized)
        df_calc['trend_direction'] = np.where(
            df_calc['fast_ma'] > df_calc['slow_ma'], 1,
            np.where(df_calc['fast_ma'] < df_calc['slow_ma'], -1, 0)
        )

        # Pre-calculate components for ADX (True Range and Directional Movement)
        high_low = df_calc['high'] - df_calc['low']
        high_close = (df_calc['high'] - df_calc['close'].shift(1)).abs()
        low_close = (df_calc['low'] - df_calc['close'].shift(1)).abs()

        # True Range (vectorized max)
        df_calc['tr'] = np.maximum.reduce([high_low, high_close, low_close])

        # Directional Movement (vectorized)
        df_calc['plus_dm'] = np.where(
            (df_calc['high'] - df_calc['high'].shift(1)) > (df_calc['low'].shift(1) - df_calc['low']),
            np.maximum(df_calc['high'] - df_calc['high'].shift(1), 0), 0
        )
        df_calc['minus_dm'] = np.where(
            (df_calc['low'].shift(1) - df_calc['low']) > (df_calc['high'] - df_calc['high'].shift(1)),
            np.maximum(df_calc['low'].shift(1) - df_calc['low'], 0), 0
        )

        # Smoothed calculations (ATR and DI values)
        df_calc['atr'] = df_calc['tr'].rolling(self.trend_strength_period, min_periods=1).mean()
        df_calc['plus_di_smooth'] = df_calc['plus_dm'].rolling(self.trend_strength_period, min_periods=1).mean()
        df_calc['minus_di_smooth'] = df_calc['minus_dm'].rolling(self.trend_strength_period, min_periods=1).mean()

        # Directional Indicators
        df_calc['plus_di'] = 100 * df_calc['plus_di_smooth'] / df_calc['atr']
        df_calc['minus_di'] = 100 * df_calc['minus_di_smooth'] / df_calc['atr']

        # ADX components
        df_calc['dx'] = 100 * np.abs(df_calc['plus_di'] - df_calc['minus_di']) / (df_calc['plus_di'] + df_calc['minus_di'])
        df_calc['trend_strength'] = df_calc['dx'].rolling(self.trend_strength_period, min_periods=1).mean()

        # Momentum indicators (vectorized)
        df_calc['roc'] = df_calc['close'].pct_change(self.momentum_period)
        df_calc['momentum'] = df_calc['close'] / df_calc['close'].shift(self.momentum_period) - 1

        # Volatility for position sizing
        df_calc['returns'] = df_calc['close'].pct_change()
        df_calc['volatility'] = df_calc['returns'].rolling(self.volatility_period, min_periods=1).std()

        # Pullback detection (price deviation from trend)
        df_calc['trend_price'] = (df_calc['fast_ma'] + df_calc['slow_ma']) / 2
        df_calc['pullback_pct'] = (df_calc['close'] - df_calc['trend_price']) / df_calc['trend_price']

        return df_calc

    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate trend-following indicators with intelligent caching."""
        if df.empty:
            return {}

        cache_key = self._get_cache_key(df)

        # Check if we have cached results
        if cache_key in self._indicator_cache:
            cached_result = self._indicator_cache[cache_key]
            # Verify cache is still valid (dataframe hasn't changed significantly)
            if len(df) >= len(self._dataframe_cache.get(cache_key, pd.DataFrame())):
                # Try incremental update if just one bar added
                cached_df = self._dataframe_cache[cache_key]
                if len(df) == len(cached_df) + 1 and df.iloc[:-1].equals(cached_df):
                    # Incremental update for single bar addition
                    updated_df = self._incremental_update(cached_df, df.iloc[-1])
                    self._dataframe_cache[cache_key] = updated_df
                    result = self._extract_signals(updated_df)
                    self._indicator_cache[cache_key] = result
                    return result
                else:
                    # Full recalculation needed
                    pass
            else:
                # Cache hit - return cached result
                return cached_result

        # Calculate indicators
        df_calc = self._calculate_base_indicators(df)

        # Cache the dataframe and extract signals
        self._dataframe_cache[cache_key] = df_calc
        result = self._extract_signals(df_calc)
        self._indicator_cache[cache_key] = result

        return result

    def _incremental_update(self, cached_df: pd.DataFrame, new_bar: pd.Series) -> pd.DataFrame:
        """Incrementally update indicators when only one bar is added."""
        # This is a simplified incremental update - in practice you'd need
        # more sophisticated logic for rolling window updates
        updated_df = cached_df.copy()
        updated_df = pd.concat([updated_df, new_bar.to_frame().T], ignore_index=True)

        # Recalculate only the indicators that need updating
        # For now, do a full recalculation but this could be optimized further
        return self._calculate_base_indicators(updated_df)

    def _extract_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Extract final signals from calculated dataframe."""
        return {
            'fast_ma': df['fast_ma'].iloc[-1],
            'slow_ma': df['slow_ma'].iloc[-1],
            'trend_direction': df['trend_direction'].iloc[-1],
            'trend_strength': df['trend_strength'].iloc[-1],
            'momentum': df['momentum'].iloc[-1],
            'pullback_pct': df['pullback_pct'].iloc[-1],
            'volatility': df['volatility'].iloc[-1],
            'current_price': df['close'].iloc[-1],
            # Don't return full dataframe to save memory
        }

    def get_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Extract numeric features for ML models."""
        signals = self.calculate_signals(df)

        return {
            'trend_direction': float(signals.get('trend_direction', 0)),
            'trend_strength': float(signals.get('trend_strength', 0)),
            'momentum': float(signals.get('momentum', 0)),
            'pullback_pct': float(signals.get('pullback_pct', 0)),
            'volatility': float(signals.get('volatility', 0)),
        }


class TrendFollowerBot(TradingBot):
    """
    Trend Follower Bot - Complete automated trading system with performance optimizations.

    This bot implements a trend-following strategy optimized for PEARLalgo:
    - Identifies strong trending markets using technical indicators
    - Enters on pullbacks within established trends
    - Uses volatility-adjusted risk management
    - Filters based on trend strength and momentum
    - Features cached indicator calculations for real-time performance
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        # Use cached indicators for performance
        self.indicators = CachedTrendFollowerIndicators()

        # Bot-specific parameters
        self.min_trend_strength = self.config.parameters.get('min_trend_strength', 25.0)
        self.max_pullback_pct = self.config.parameters.get('max_pullback_pct', 0.02)
        self.momentum_threshold = self.config.parameters.get('momentum_threshold', 0.005)

    @property
    def name(self) -> str:
        return "TrendFollowerBot"

    @property
    def description(self) -> str:
        return ("Lux Algo Chart Prime style trend-following bot. Identifies strong trends "
                "and enters on pullbacks with volatility-adjusted stops.")

    @property
    def strategy_type(self) -> str:
        return "trend_following"

    def get_indicator_suite(self) -> IndicatorSuite:
        return self.indicators

    def generate_signal_logic(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Optional[TradeSignal]:
        """
        Core signal generation logic for trend following.

        Strategy rules (similar to Lux Algo AI-generated strategies):
        1. Trend must be strong enough (ADX > threshold)
        2. Price must be in a pullback within the trend
        3. Momentum must align with trend direction
        4. Enter counter to pullback direction
        """
        trend_direction = indicators.get('trend_direction', 0)
        trend_strength = indicators.get('trend_strength', 0)
        pullback_pct = indicators.get('pullback_pct', 0)
        momentum = indicators.get('momentum', 0)
        current_price = indicators.get('current_price', 0)
        volatility = indicators.get('volatility', 0)

        # Must have a strong trend
        if trend_strength < self.min_trend_strength:
            return None

        # Must be in a trending market
        if trend_direction == 0:
            return None

        # Check for pullback opportunity
        max_pullback = self.max_pullback_pct
        if abs(pullback_pct) < max_pullback:
            return None

        # Momentum must align with trend (but not be extreme)
        momentum_aligned = (
            (trend_direction > 0 and momentum > self.momentum_threshold) or
            (trend_direction < 0 and momentum < -self.momentum_threshold)
        )

        if not momentum_aligned:
            return None

        # Determine entry direction (counter to pullback)
        if trend_direction > 0 and pullback_pct < -max_pullback:
            # Bull trend with pullback - go long
            direction = "long"
            confidence = min(trend_strength / 50.0, 1.0)  # Scale confidence with trend strength

        elif trend_direction < 0 and pullback_pct > max_pullback:
            # Bear trend with pullback - go short
            direction = "short"
            confidence = min(trend_strength / 50.0, 1.0)

        else:
            return None

        # Calculate entry, stop, and target prices
        entry_price = current_price

        # Volatility-adjusted stop loss
        vol_adjustment = max(volatility * current_price, current_price * 0.005)  # Min 0.5%
        if direction == "long":
            stop_loss = entry_price - vol_adjustment
            take_profit = entry_price + (vol_adjustment * 2)  # 2:1 reward
        else:  # short
            stop_loss = entry_price + vol_adjustment
            take_profit = entry_price - (vol_adjustment * 2)

        # Create signal with reasoning
        reason = (f"Strong {direction} trend (strength: {trend_strength:.1f}) "
                 f"with pullback opportunity. Momentum: {momentum:.4f}")

        return TradeSignal(
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            bot_name=self.name,
            bot_version=self.config.version,
            reason=reason,
            indicators_used=['trend_strength', 'momentum', 'pullback_pct', 'volatility'],
            features={
                'trend_strength': trend_strength,
                'momentum': momentum,
                'pullback_pct': pullback_pct,
                'volatility': volatility,
            }
        )


# Register the bot for creation by name
register_bot(TrendFollowerBot)