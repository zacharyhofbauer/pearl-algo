"""
Options Strategies - Swing-trade strategies for equity options.

Provides:
- Momentum breakout strategies
- Volatility expansion plays
- Options-specific indicators (IV rank, Greeks)
"""

from __future__ import annotations

import logging
import pandas as pd
from typing import Dict, Any, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.strategies.base import register_strategy

Side = str  # "long" | "short" | "flat"


@register_strategy(
    name="swing_momentum",
    description="Swing momentum strategy for options - targets 2-5% moves",
    default_params={
        "lookback": 20,
        "volume_multiplier": 1.5,
        "min_move": 0.02,  # 2% minimum move
        "max_move": 0.05,  # 5% maximum move
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
    },
)
def swing_momentum_strategy(
    symbol: str, df: pd.DataFrame, **params
) -> Dict[str, Any]:
    """
    Swing momentum strategy for options:
    - Momentum breakout with volume confirmation
    - RSI for overbought/oversold
    - Targets 2-5% moves
    - Best for: 15-60 minute timeframes

    Args:
        symbol: Trading symbol
        df: DataFrame with OHLCV data
        **params: Strategy parameters

    Returns:
        Strategy signal dictionary
    """
    lookback = params.get("lookback", 20)
    volume_multiplier = params.get("volume_multiplier", 1.5)
    min_move = params.get("min_move", 0.02)
    rsi_period = params.get("rsi_period", 14)

    if len(df) < max(lookback, rsi_period) + 1:
        return {
            "side": "flat",
            "confidence": 0.0,
            "comment": "Insufficient data",
            "strategy_name": "swing_momentum",
        }

    prices = df["Close"]
    volumes = df.get("Volume", pd.Series([1.0] * len(df)))

    current_price = float(prices.iloc[-1])
    recent_high = float(prices.iloc[-lookback:-1].max())
    recent_low = float(prices.iloc[-lookback:-1].min())

    current_volume = float(volumes.iloc[-1])
    avg_volume = float(volumes.iloc[-lookback:-1].mean())

    # Calculate RSI
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    current_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

    side: Side = "flat"
    confidence = 0.0
    comment = ""

    # Long: Breakout above recent high with volume, RSI not overbought
    if (
        current_price > recent_high * (1 + min_move)
        and current_volume >= avg_volume * volume_multiplier
        and current_rsi < 70
    ):
        side = "long"
        confidence = 0.7
        if current_volume >= avg_volume * (volume_multiplier * 1.5):
            confidence = 0.85
        comment = (
            f"Momentum LONG: Breakout above {recent_high:.2f} "
            f"with {current_volume / avg_volume:.1f}x volume, RSI={current_rsi:.1f}"
        )

    # Short: Breakdown below recent low with volume, RSI not oversold
    elif (
        current_price < recent_low * (1 - min_move)
        and current_volume >= avg_volume * volume_multiplier
        and current_rsi > 30
    ):
        side = "short"
        confidence = 0.7
        if current_volume >= avg_volume * (volume_multiplier * 1.5):
            confidence = 0.85
        comment = (
            f"Momentum SHORT: Breakdown below {recent_low:.2f} "
            f"with {current_volume / avg_volume:.1f}x volume, RSI={current_rsi:.1f}"
        )

    # Calculate targets
    stop_loss = None
    take_profit = None
    if side == "long":
        stop_loss = current_price * (1 - min_move)
        take_profit = current_price * (1 + min_move * 1.5)  # 1.5x risk/reward
    elif side == "short":
        stop_loss = current_price * (1 + min_move)
        take_profit = current_price * (1 - min_move * 1.5)

    return {
        "side": side,
        "confidence": confidence,
        "comment": comment,
        "rsi": current_rsi,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "volume_ratio": current_volume / avg_volume if avg_volume > 0 else 1.0,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "strategy_name": "swing_momentum",
    }


def volatility_expansion_strategy(
    symbol: str, df: pd.DataFrame, iv_rank: Optional[float] = None, **params
) -> Dict[str, Any]:
    """
    Volatility expansion strategy for options.

    Enters when volatility expands (IV rank increases).

    Args:
        symbol: Trading symbol
        df: DataFrame with OHLCV data
        iv_rank: Current IV rank (0-100)
        **params: Strategy parameters

    Returns:
        Strategy signal dictionary
    """
    # Placeholder - would need IV data from options chain
    # For now, return flat
    return {
        "side": "flat",
        "confidence": 0.0,
        "comment": "Volatility expansion strategy requires IV data",
        "strategy_name": "volatility_expansion",
    }
