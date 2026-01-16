"""
Mean Reversion Bot - PEARL Automated Trading System

A complete automated trading bot that trades mean reversion opportunities,
optimized for PEARLalgo's oscillator-based analysis.

Strategy Logic:
- Identifies overbought/oversold conditions using multiple oscillators
- Detects divergence patterns between price and momentum
- Enters on exhaustion signals with timing filters
- Uses volatility-based stops and reversion targets
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import pandas as pd
import numpy as np

from .bot_template import PearlBot, BotConfig, TradeSignal, IndicatorSuite, register_bot


@dataclass
class MeanReversionIndicators(IndicatorSuite):
    """Indicator suite for mean reversion strategies (equivalent to Lux Algo OSC)."""

    # Configuration
    rsi_period: int = 14
    stoch_k: int = 14
    stoch_d: int = 3
    cci_period: int = 20
    bb_period: int = 20
    bb_std: float = 2.0
    divergence_window: int = 10

    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate mean reversion indicators and signals."""
        if df.empty:
            return {}

        df = df.copy()

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Stochastic Oscillator
        lowest_low = df['low'].rolling(self.stoch_k).min()
        highest_high = df['high'].rolling(self.stoch_k).max()
        df['stoch_k'] = 100 * ((df['close'] - lowest_low) / (highest_high - lowest_low))
        df['stoch_d'] = df['stoch_k'].rolling(self.stoch_d).mean()

        # CCI (Commodity Channel Index)
        tp = (df['high'] + df['low'] + df['close']) / 3
        sma_tp = tp.rolling(self.cci_period).mean()
        mad_tp = tp.rolling(self.cci_period).apply(lambda x: np.mean(np.abs(x - x.mean())))
        df['cci'] = (tp - sma_tp) / (0.015 * mad_tp)

        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(self.bb_period).mean()
        df['bb_std'] = df['close'].rolling(self.bb_period).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * self.bb_std)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * self.bb_std)
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # Divergence detection (simplified)
        df['price_change'] = df['close'].pct_change(self.divergence_window)
        df['rsi_change'] = df['rsi'].pct_change(self.divergence_window)

        # Bullish divergence: price down, RSI up
        df['bullish_divergence'] = (
            (df['price_change'] < -0.02) & (df['rsi_change'] > 0.05) &
            (df['rsi'] < 35)  # RSI oversold
        )

        # Bearish divergence: price up, RSI down
        df['bearish_divergence'] = (
            (df['price_change'] > 0.02) & (df['rsi_change'] < -0.05) &
            (df['rsi'] > 65)  # RSI overbought
        )

        # Combined exhaustion signal
        df['oversold_signal'] = (
            (df['rsi'] < 30) &
            (df['stoch_k'] < 20) &
            (df['cci'] < -100) &
            (df['bb_position'] < 0.2)
        )

        df['overbought_signal'] = (
            (df['rsi'] > 70) &
            (df['stoch_k'] > 80) &
            (df['cci'] > 100) &
            (df['bb_position'] > 0.8)
        )

        # Mean reversion strength
        df['mr_strength'] = (
            (1 - df['bb_position']) * (df['rsi'] < 50) +
            (df['bb_position']) * (df['rsi'] > 50)
        ).clip(0, 1)

        return {
            'rsi': df['rsi'].iloc[-1],
            'stoch_k': df['stoch_k'].iloc[-1],
            'stoch_d': df['stoch_d'].iloc[-1],
            'cci': df['cci'].iloc[-1],
            'bb_position': df['bb_position'].iloc[-1],
            'bullish_divergence': df['bullish_divergence'].iloc[-1],
            'bearish_divergence': df['bearish_divergence'].iloc[-1],
            'oversold_signal': df['oversold_signal'].iloc[-1],
            'overbought_signal': df['overbought_signal'].iloc[-1],
            'mr_strength': df['mr_strength'].iloc[-1],
            'current_price': df['close'].iloc[-1],
            'bb_middle': df['bb_middle'].iloc[-1],
            'bb_upper': df['bb_upper'].iloc[-1],
            'bb_lower': df['bb_lower'].iloc[-1],
            'df': df,
        }

    def get_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Extract numeric features for ML models."""
        signals = self.calculate_signals(df)

        return {
            'rsi': float(signals.get('rsi', 50)),
            'stoch_k': float(signals.get('stoch_k', 50)),
            'stoch_d': float(signals.get('stoch_d', 50)),
            'cci': float(signals.get('cci', 0)),
            'bb_position': float(signals.get('bb_position', 0.5)),
            'mr_strength': float(signals.get('mr_strength', 0.5)),
        }


class MeanReversionBot(PearlBot):
    """
    Mean Reversion Bot - Complete automated trading system.

    This bot implements a mean reversion strategy optimized for PEARLalgo:
    - Identifies overbought/oversold conditions using multiple oscillators
    - Detects divergence patterns for higher-probability entries
    - Enters on exhaustion with confirmation across indicators
    - Uses volatility-based targets and time-based exits
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        self.indicators = MeanReversionIndicators()

        # Bot-specific parameters
        self.min_mr_strength = self.config.parameters.get('min_mr_strength', 0.7)
        self.require_divergence = self.config.parameters.get('require_divergence', False)
        self.max_hold_bars = self.config.parameters.get('max_hold_bars', 10)

    @property
    def name(self) -> str:
        return "MeanReversionBot"

    @property
    def description(self) -> str:
        return ("Lux Algo Chart Prime style mean reversion bot. Identifies "
                "overbought/oversold conditions and trades reversions to the mean.")

    @property
    def strategy_type(self) -> str:
        return "mean_reversion"

    def get_indicator_suite(self) -> IndicatorSuite:
        return self.indicators

    def generate_signal_logic(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Optional[TradeSignal]:
        """
        Core signal generation logic for mean reversion.

        Strategy rules (similar to Lux Algo AI-generated strategies):
        1. Multiple oscillators must agree on overbought/oversold
        2. Divergence patterns add confirmation if required
        3. Mean reversion strength must be sufficient
        4. Enter counter to current momentum
        """
        oversold_signal = indicators.get('oversold_signal', False)
        overbought_signal = indicators.get('overbought_signal', False)
        bullish_divergence = indicators.get('bullish_divergence', False)
        bearish_divergence = indicators.get('bearish_divergence', False)
        mr_strength = indicators.get('mr_strength', 0)
        current_price = indicators.get('current_price', 0)
        bb_middle = indicators.get('bb_middle', current_price)
        bb_upper = indicators.get('bb_upper', current_price)
        bb_lower = indicators.get('bb_lower', current_price)

        # Must have sufficient mean reversion strength
        if mr_strength < self.min_mr_strength:
            return None

        # Determine direction based on signals
        if oversold_signal and (not self.require_divergence or bullish_divergence):
            direction = "long"
            confidence_base = 0.75
            # Additional confirmation from divergence
            if bullish_divergence:
                confidence_base += 0.15

        elif overbought_signal and (not self.require_divergence or bearish_divergence):
            direction = "short"
            confidence_base = 0.75
            # Additional confirmation from divergence
            if bearish_divergence:
                confidence_base += 0.15

        else:
            return None

        # Scale confidence by mean reversion strength
        confidence = min(confidence_base + (mr_strength * 0.2), 1.0)

        # Calculate entry, stop, and target prices
        entry_price = current_price

        if direction == "long":
            # Target is middle of Bollinger Bands (mean reversion target)
            take_profit = bb_middle
            # Stop below recent low or BB lower
            # Cap the stop so it is not *more* than ~2% away (closer stop wins).
            stop_loss = max(bb_lower, current_price * 0.98)

        else:  # short
            take_profit = bb_middle
            # Cap the stop so it is not *more* than ~2% away (closer stop wins).
            stop_loss = min(bb_upper, current_price * 1.02)

        # Ensure minimum risk-reward ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)

        if reward / risk < 1.0:
            return None

        # Create signal with reasoning
        divergence_text = " with bullish divergence" if (direction == "long" and bullish_divergence) else \
                         " with bearish divergence" if (direction == "short" and bearish_divergence) else ""

        reason = (f"MR strength {mr_strength:.2f} indicating strong {direction} reversion opportunity{divergence_text}")

        return TradeSignal(
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            bot_name=self.name,
            bot_version=self.config.version,
            reason=reason,
            indicators_used=['mr_strength', 'rsi', 'stoch_k', 'cci', 'bb_position'],
            features={
                'mr_strength': mr_strength,
                'rsi': indicators.get('rsi', 50),
                'stoch_k': indicators.get('stoch_k', 50),
                'cci': indicators.get('cci', 0),
                'bb_position': indicators.get('bb_position', 0.5),
                'bullish_divergence': 1.0 if bullish_divergence else 0.0,
                'bearish_divergence': 1.0 if bearish_divergence else 0.0,
            }
        )


# Register the bot for creation by name
register_bot(MeanReversionBot)