"""
Breakout Bot (variant)

Complete automated trading bot that trades breakouts from consolidation patterns.

Strategy Logic:
- Identifies consolidation ranges using volatility contraction
- Detects breakouts with volume confirmation
- Enters on breakout continuation with momentum filters
- Uses pattern-based stops and measured targets
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any
import pandas as pd

from .bot_template import BotConfig, TradeSignal, IndicatorSuite, TradingBot, register_bot


@dataclass
class BreakoutIndicators(IndicatorSuite):
    """Indicator suite for breakout strategies."""

    consolidation_period: int = 20
    breakout_volume_mult: float = 1.5
    volatility_lookback: int = 50
    pattern_recognition_window: int = 10

    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty:
            return {}

        df = df.copy()

        df["returns"] = df["close"].pct_change()
        df["volatility"] = df["returns"].rolling(self.volatility_lookback).std()
        df["volatility_sma"] = df["volatility"].rolling(self.consolidation_period).mean()
        df["volatility_ratio"] = df["volatility"] / df["volatility_sma"]

        df["high_max"] = df["high"].rolling(self.consolidation_period).max()
        df["low_min"] = df["low"].rolling(self.consolidation_period).min()
        df["range_size"] = df["high_max"] - df["low_min"]
        df["range_midpoint"] = (df["high_max"] + df["low_min"]) / 2

        df["volume_sma"] = df["volume"].rolling(self.consolidation_period).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma"]

        df["range_position"] = (df["close"] - df["low_min"]) / (df["high_max"] - df["low_min"])

        df["upper_breakout"] = df["close"] > df["high_max"].shift(1)
        df["lower_breakout"] = df["close"] < df["low_min"].shift(1)

        df["momentum"] = df["close"] / df["close"].shift(5) - 1
        df["momentum_acceleration"] = df["momentum"] - df["momentum"].shift(1)

        df["range_tightness"] = 1 - (df["range_size"] / df["range_midpoint"])
        df["pattern_strength"] = df["range_tightness"] * (1 / df["volatility_ratio"])

        return {
            "in_consolidation": df["volatility_ratio"].iloc[-1] < 0.7,
            "upper_breakout": df["upper_breakout"].iloc[-1],
            "lower_breakout": df["lower_breakout"].iloc[-1],
            "volume_confirmed": df["volume_ratio"].iloc[-1] > self.breakout_volume_mult,
            "momentum": df["momentum"].iloc[-1],
            "momentum_acceleration": df["momentum_acceleration"].iloc[-1],
            "pattern_strength": df["pattern_strength"].iloc[-1],
            "range_size_pct": df["range_size"].iloc[-1] / df["range_midpoint"].iloc[-1],
            "current_price": df["close"].iloc[-1],
            "range_high": df["high_max"].iloc[-1],
            "range_low": df["low_min"].iloc[-1],
            "df": df,
        }

    def get_features(self, df: pd.DataFrame) -> Dict[str, float]:
        signals = self.calculate_signals(df)
        return {
            "in_consolidation": 1.0 if signals.get("in_consolidation", False) else 0.0,
            "volume_confirmed": 1.0 if signals.get("volume_confirmed", False) else 0.0,
            "momentum": float(signals.get("momentum", 0)),
            "momentum_acceleration": float(signals.get("momentum_acceleration", 0)),
            "pattern_strength": float(signals.get("pattern_strength", 0)),
            "range_size_pct": float(signals.get("range_size_pct", 0)),
        }


class BreakoutBot(TradingBot):
    """
    Breakout Bot - Complete automated trading system.

    - Identifies consolidation patterns with volatility contraction
    - Confirms breakouts with volume and momentum analysis
    - Enters on breakout continuation with risk management
    - Uses pattern-based targets and stops
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        self.indicators = BreakoutIndicators()

        self.min_pattern_strength = self.config.parameters.get("min_pattern_strength", 0.6)
        self.require_volume_confirmation = self.config.parameters.get(
            "require_volume_confirmation", True
        )
        self.min_momentum_acceleration = self.config.parameters.get("min_momentum_acceleration", 0.001)

    @property
    def name(self) -> str:
        return "BreakoutBot"

    @property
    def description(self) -> str:
        return (
            "Breakout bot. Identifies consolidation patterns and trades breakouts with "
            "volume and momentum confirmation."
        )

    @property
    def strategy_type(self) -> str:
        return "breakout"

    def get_indicator_suite(self) -> IndicatorSuite:
        return self.indicators

    def generate_signal_logic(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Optional[TradeSignal]:
        in_consolidation = indicators.get("in_consolidation", False)
        upper_breakout = indicators.get("upper_breakout", False)
        lower_breakout = indicators.get("lower_breakout", False)
        volume_confirmed = indicators.get("volume_confirmed", False)
        momentum = indicators.get("momentum", 0)
        momentum_acceleration = indicators.get("momentum_acceleration", 0)
        pattern_strength = indicators.get("pattern_strength", 0)
        current_price = indicators.get("current_price", 0)
        range_high = indicators.get("range_high", 0)
        range_low = indicators.get("range_low", 0)
        range_size_pct = indicators.get("range_size_pct", 0)

        if not in_consolidation or pattern_strength < self.min_pattern_strength:
            return None

        if not (upper_breakout or lower_breakout):
            return None

        if self.require_volume_confirmation and not volume_confirmed:
            return None

        if upper_breakout:
            direction = "long"
            if momentum < 0 or momentum_acceleration < self.min_momentum_acceleration:
                return None
            confidence_base = 0.7
        elif lower_breakout:
            direction = "short"
            if momentum > 0 or momentum_acceleration > -self.min_momentum_acceleration:
                return None
            confidence_base = 0.7
        else:
            return None

        confidence = min(confidence_base + (pattern_strength * 0.3) + (abs(momentum_acceleration) * 100), 1.0)

        entry_price = current_price

        range_size = range_high - range_low
        if direction == "long":
            stop_loss = range_low - (range_size * 0.1)
            take_profit = entry_price + (range_size * 2)
        else:
            stop_loss = range_high + (range_size * 0.1)
            take_profit = entry_price - (range_size * 2)

        reason = (
            f"Pattern strength {pattern_strength:.2f} with "
            f"{'volume confirmed ' if volume_confirmed else ''}breakout. "
            f"Momentum acceleration: {momentum_acceleration:.4f}"
        )

        return TradeSignal(
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            bot_name=self.name,
            bot_version=self.config.version,
            reason=reason,
            indicators_used=["pattern_strength", "volume_confirmed", "momentum_acceleration", "range_size_pct"],
            features={
                "pattern_strength": pattern_strength,
                "volume_confirmed": 1.0 if volume_confirmed else 0.0,
                "momentum_acceleration": momentum_acceleration,
                "range_size_pct": range_size_pct,
                "momentum": momentum,
            },
        )


register_bot(BreakoutBot)

