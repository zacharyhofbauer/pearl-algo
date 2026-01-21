"""
Market Regime Detection for Trading Bots

Classifies market conditions to enable regime-aware trading strategies:
- trending_bull: Strong upward trends
- trending_bear: Strong downward trends
- ranging: Sideways/consolidation markets
- volatile: High volatility regardless of direction
- mixed: Mixed signals or transitional periods
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any
from enum import Enum
import pandas as pd
import numpy as np

from pearlalgo.utils.logger import logger


class MarketRegime(Enum):
    """Market regime classifications."""

    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    RANGING = "ranging"
    VOLATILE = "volatile"
    MIXED = "mixed"


@dataclass
class RegimeMetrics:
    """Metrics used for regime classification."""

    adx: float  # Trend strength (0-100)
    trend_direction: int  # -1, 0, 1
    volatility_ratio: float  # Current vs historical volatility
    range_ratio: float  # Daily range vs ATR
    momentum_consistency: float  # How consistent momentum is
    volume_trend: float  # Volume trend direction
    confidence: float  # Classification confidence (0-1)


@dataclass
class MarketRegimeDetector:
    """
    Detects market regimes for regime-aware trading.

    Uses multiple technical indicators to classify market conditions:
    - ADX for trend strength
    - Volatility analysis
    - Momentum consistency
    - Volume patterns
    """

    # Configuration parameters
    adx_period: int = 14
    volatility_lookback: int = 20
    momentum_period: int = 10
    volume_period: int = 20

    # Thresholds for regime classification
    trend_strength_threshold: float = 25.0  # ADX threshold for trending markets
    volatility_threshold: float = 1.5  # Multiplier for high volatility detection
    momentum_consistency_threshold: float = 0.7  # Consistency required for trending
    volume_trend_threshold: float = 0.1  # Volume trend significance

    def detect_regime(self, df: pd.DataFrame) -> tuple[MarketRegime, RegimeMetrics, float]:
        """
        Detect the current market regime.

        Returns:
            tuple: (regime, metrics, confidence)
        """
        if len(df) < max(self.adx_period, self.volatility_lookback, self.momentum_period):
            return MarketRegime.MIXED, self._empty_metrics(), 0.0

        try:
            metrics = self._calculate_regime_metrics(df)
            regime, confidence = self._classify_regime(metrics)
            return regime, metrics, confidence
        except Exception as e:
            logger.warning(f"Error detecting market regime: {e}")
            return MarketRegime.MIXED, self._empty_metrics(), 0.0

    def _calculate_regime_metrics(self, df: pd.DataFrame) -> RegimeMetrics:
        """Calculate all metrics needed for regime classification."""
        # ADX calculation (trend strength)
        adx = self._calculate_adx(df)

        # Trend direction from moving averages
        fast_ma = df["close"].rolling(20).mean()
        slow_ma = df["close"].rolling(50).mean()
        trend_direction = (
            1
            if fast_ma.iloc[-1] > slow_ma.iloc[-1]
            else -1
            if fast_ma.iloc[-1] < slow_ma.iloc[-1]
            else 0
        )

        # Volatility analysis
        current_volatility = (
            df["close"].pct_change().rolling(self.volatility_lookback).std().iloc[-1]
        )
        historical_volatility = (
            df["close"]
            .pct_change()
            .rolling(self.volatility_lookback * 4)
            .std()
            .iloc[-1]
        )
        volatility_ratio = (
            current_volatility / historical_volatility if historical_volatility > 0 else 1.0
        )

        # Range vs ATR analysis
        daily_range = (df["high"] - df["low"]).rolling(20).mean().iloc[-1]
        atr = self._calculate_atr(df)
        range_ratio = daily_range / atr if atr > 0 else 1.0

        # Momentum consistency
        momentum = df["close"].pct_change(self.momentum_period)
        mom_std = momentum.rolling(20).std().iloc[-1]
        momentum_consistency = (
            abs(momentum.rolling(20).mean().iloc[-1]) / mom_std if mom_std > 0 else 0.0
        )

        # Volume trend (if volume data available)
        volume_trend = 0.0
        if "volume" in df.columns:
            volume_ma_short = df["volume"].rolling(10).mean()
            volume_ma_long = df["volume"].rolling(30).mean()
            denom = volume_ma_long.iloc[-1]
            volume_trend = (
                (volume_ma_short.iloc[-1] - volume_ma_long.iloc[-1]) / denom if denom > 0 else 0.0
            )

        return RegimeMetrics(
            adx=adx,
            trend_direction=trend_direction,
            volatility_ratio=volatility_ratio,
            range_ratio=range_ratio,
            momentum_consistency=momentum_consistency,
            volume_trend=volume_trend,
            confidence=0.0,  # Will be set by classifier
        )

    def _calculate_adx(self, df: pd.DataFrame) -> float:
        """Calculate Average Directional Index (ADX)."""
        # True Range
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # Directional Movement
        plus_dm = np.where(
            (df["high"] - df["high"].shift(1)) > (df["low"].shift(1) - df["low"]),
            np.maximum(df["high"] - df["high"].shift(1), 0),
            0,
        )
        minus_dm = np.where(
            (df["low"].shift(1) - df["low"]) > (df["high"] - df["high"].shift(1)),
            np.maximum(df["low"].shift(1) - df["low"], 0),
            0,
        )

        # Smoothed calculations
        atr = tr.rolling(self.adx_period).mean()
        plus_di_smooth = pd.Series(plus_dm).rolling(self.adx_period).mean()
        minus_di_smooth = pd.Series(minus_dm).rolling(self.adx_period).mean()

        plus_di = 100 * plus_di_smooth / atr
        minus_di = 100 * minus_di_smooth / atr

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(self.adx_period).mean()

        return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return float(atr.iloc[-1]) if not pd.isna(atr.iloc[-1]) else 0.0

    def _classify_regime(self, metrics: RegimeMetrics) -> tuple[MarketRegime, float]:
        """
        Classify market regime based on calculated metrics.

        Returns regime and confidence score.
        """
        scores = {
            MarketRegime.TRENDING_BULL: 0.0,
            MarketRegime.TRENDING_BEAR: 0.0,
            MarketRegime.RANGING: 0.0,
            MarketRegime.VOLATILE: 0.0,
        }

        # Trending Bull conditions
        if (
            metrics.adx > self.trend_strength_threshold
            and metrics.trend_direction > 0
            and metrics.momentum_consistency > self.momentum_consistency_threshold
        ):
            scores[MarketRegime.TRENDING_BULL] = (
                0.4 * min(metrics.adx / 50.0, 1.0)  # ADX strength
                + 0.3 * metrics.momentum_consistency  # Momentum consistency
                + 0.3 * (1.0 - metrics.volatility_ratio)  # Lower volatility bonus
            )

        # Trending Bear conditions
        if (
            metrics.adx > self.trend_strength_threshold
            and metrics.trend_direction < 0
            and metrics.momentum_consistency > self.momentum_consistency_threshold
        ):
            scores[MarketRegime.TRENDING_BEAR] = (
                0.4 * min(metrics.adx / 50.0, 1.0)
                + 0.3 * metrics.momentum_consistency
                + 0.3 * (1.0 - metrics.volatility_ratio)
            )

        # Volatile conditions (high volatility regardless of trend)
        if metrics.volatility_ratio > self.volatility_threshold:
            scores[MarketRegime.VOLATILE] = min(metrics.volatility_ratio / 2.0, 1.0)

        # Ranging conditions (low trend strength, low volatility)
        if (
            metrics.adx < self.trend_strength_threshold * 0.5
            and metrics.volatility_ratio < 1.2
            and metrics.range_ratio < 1.5
        ):
            scores[MarketRegime.RANGING] = (
                0.4 * (1.0 - metrics.adx / 50.0)  # Low ADX
                + 0.3 * (1.0 - metrics.volatility_ratio)  # Low volatility
                + 0.3 * (1.0 - metrics.momentum_consistency)  # Inconsistent momentum
            )

        best_regime = max(scores.items(), key=lambda x: x[1])
        confidence = float(best_regime[1])

        if confidence < 0.3:
            return MarketRegime.MIXED, confidence

        return best_regime[0], confidence

    def _empty_metrics(self) -> RegimeMetrics:
        """Return empty metrics for error cases."""
        return RegimeMetrics(
            adx=0.0,
            trend_direction=0,
            volatility_ratio=1.0,
            range_ratio=1.0,
            momentum_consistency=0.0,
            volume_trend=0.0,
            confidence=0.0,
        )

    def get_regime_filter(self, regime: MarketRegime) -> Dict[str, Any]:
        """
        Get recommended trading parameters for a specific regime.

        This allows bots to adapt their behavior based on market conditions.
        """
        filters = {
            MarketRegime.TRENDING_BULL: {
                "trend_following_bias": 1.0,
                "breakout_bias": 0.3,
                "mean_reversion_bias": 0.1,
                "max_positions": 2,
                "risk_multiplier": 1.2,  # Increase risk in strong trends
                "confidence_boost": 0.1,
            },
            MarketRegime.TRENDING_BEAR: {
                "trend_following_bias": 1.0,
                "breakout_bias": 0.3,
                "mean_reversion_bias": 0.1,
                "max_positions": 2,
                "risk_multiplier": 1.2,
                "confidence_boost": 0.1,
            },
            MarketRegime.RANGING: {
                "trend_following_bias": 0.2,
                "breakout_bias": 1.0,  # Favor breakouts in ranging markets
                "mean_reversion_bias": 0.8,
                "max_positions": 1,
                "risk_multiplier": 0.8,  # Reduce risk in ranging markets
                "confidence_boost": 0.0,
            },
            MarketRegime.VOLATILE: {
                "trend_following_bias": 0.5,
                "breakout_bias": 0.8,
                "mean_reversion_bias": 0.2,
                "max_positions": 1,
                "risk_multiplier": 0.6,  # Significantly reduce risk
                "confidence_boost": -0.1,  # Require higher confidence
            },
            MarketRegime.MIXED: {
                "trend_following_bias": 0.5,
                "breakout_bias": 0.5,
                "mean_reversion_bias": 0.5,
                "max_positions": 1,
                "risk_multiplier": 0.7,
                "confidence_boost": 0.0,
            },
        }

        return filters.get(regime, filters[MarketRegime.MIXED])


# Global instance for reuse
market_regime_detector = MarketRegimeDetector()

