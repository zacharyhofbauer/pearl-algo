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

from .bot_template import PearlBot, BotConfig, TradeSignal, IndicatorSuite, register_bot


@dataclass
class TrendFollowerIndicators(IndicatorSuite):
    """Indicator suite for trend following strategies (equivalent to Lux Algo S&O)."""

    # Configuration
    fast_ma_period: int = 20
    slow_ma_period: int = 50
    trend_strength_period: int = 14
    volatility_period: int = 20
    momentum_period: int = 10

    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate trend-following indicators and signals."""
        if df.empty:
            return {}

        # Moving averages
        df = df.copy()
        df['fast_ma'] = df['close'].rolling(self.fast_ma_period).mean()
        df['slow_ma'] = df['close'].rolling(self.slow_ma_period).mean()

        # Trend direction and strength
        df['trend_direction'] = np.where(df['fast_ma'] > df['slow_ma'], 1,
                                       np.where(df['fast_ma'] < df['slow_ma'], -1, 0))

        # Trend strength (ADX-like calculation)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift(1)).abs()
        low_close = (df['low'] - df['close'].shift(1)).abs()

        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['tr'] = tr

        df['plus_dm'] = np.where(
            (df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']),
            np.maximum(df['high'] - df['high'].shift(1), 0), 0
        )
        df['minus_dm'] = np.where(
            (df['low'].shift(1) - df['low']) > (df['high'] - df['high'].shift(1)),
            np.maximum(df['low'].shift(1) - df['low'], 0), 0
        )

        # Smoothed calculations
        df['atr'] = df['tr'].rolling(self.trend_strength_period).mean()
        df['plus_di'] = 100 * (df['plus_dm'].rolling(self.trend_strength_period).mean() /
                              df['atr'].rolling(self.trend_strength_period).mean())
        df['minus_di'] = 100 * (df['minus_dm'].rolling(self.trend_strength_period).mean() /
                               df['atr'].rolling(self.trend_strength_period).mean())

        df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
        df['trend_strength'] = df['dx'].rolling(self.trend_strength_period).mean()

        # Momentum and pullback detection
        df['roc'] = df['close'].pct_change(self.momentum_period)
        df['momentum'] = df['close'] / df['close'].shift(self.momentum_period) - 1

        # Volatility for position sizing
        df['volatility'] = df['close'].pct_change().rolling(self.volatility_period).std()

        # Pullback detection (price deviation from trend)
        df['trend_price'] = (df['fast_ma'] + df['slow_ma']) / 2
        df['pullback_pct'] = (df['close'] - df['trend_price']) / df['trend_price']

        return {
            'fast_ma': df['fast_ma'].iloc[-1],
            'slow_ma': df['slow_ma'].iloc[-1],
            'trend_direction': df['trend_direction'].iloc[-1],
            'trend_strength': df['trend_strength'].iloc[-1],
            'momentum': df['momentum'].iloc[-1],
            'pullback_pct': df['pullback_pct'].iloc[-1],
            'volatility': df['volatility'].iloc[-1],
            'current_price': df['close'].iloc[-1],
            'df': df,  # Keep full dataframe for additional analysis
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


class TrendFollowerBot(PearlBot):
    """
    Trend Follower Bot - Complete automated trading system.

    This bot implements a trend-following strategy optimized for PEARLalgo:
    - Identifies strong trending markets using technical indicators
    - Enters on pullbacks within established trends
    - Uses volatility-adjusted risk management
    - Filters based on trend strength and momentum
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        self.indicators = TrendFollowerIndicators()

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