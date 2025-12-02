"""Scalping Strategy - Fast entries/exits on 1-5 minute timeframes."""

from __future__ import annotations

import pandas as pd
from typing import Dict, Any
from pearlalgo.strategies.base import register_strategy

Side = str  # "long" | "short" | "flat"


@register_strategy(
    name="scalping",
    description="Fast scalping strategy for 1-5min timeframes with quick exits",
    default_params={
        "fast_ema": 9,
        "slow_ema": 21,
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "atr_period": 14,
        "atr_multiplier": 1.5,
        "min_volume_spike": 1.5,
        "max_hold_bars": 5,  # Exit after 5 bars max
        "take_profit_multiplier": 2.0,
    },
)
def scalping_strategy(symbol: str, df: pd.DataFrame, **params) -> Dict[str, Any]:
    """
    Scalping strategy:
    - Uses fast EMAs (9/21) for trend
    - RSI for overbought/oversold
    - ATR for stop loss and take profit
    - Volume spike confirmation
    - Quick exits (max 5 bars hold)

    Best for: 1-5 minute timeframes
    """
    if len(df) < max(
        params.get("slow_ema", 21),
        params.get("rsi_period", 14),
        params.get("atr_period", 14),
    ):
        return {
            "side": "flat",
            "confidence": 0.0,
            "comment": "Insufficient data",
            "strategy_name": "scalping",
        }

    # Calculate indicators
    fast_ema = df["Close"].ewm(span=params.get("fast_ema", 9), adjust=False).mean()
    slow_ema = df["Close"].ewm(span=params.get("slow_ema", 21), adjust=False).mean()

    # RSI
    delta = df["Close"].diff()
    gain = (
        (delta.where(delta > 0, 0)).rolling(window=params.get("rsi_period", 14)).mean()
    )
    loss = (
        (-delta.where(delta < 0, 0)).rolling(window=params.get("rsi_period", 14)).mean()
    )
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # ATR for stops
    high_low = df["High"] - df["Low"]
    high_close = abs(df["High"] - df["Close"].shift())
    low_close = abs(df["Low"] - df["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=params.get("atr_period", 14)).mean()

    # Volume analysis
    if "Volume" in df.columns:
        avg_volume = df["Volume"].rolling(20).mean()
        volume_spike = df["Volume"].iloc[-1] > (
            avg_volume.iloc[-1] * params.get("min_volume_spike", 1.5)
        )
    else:
        volume_spike = True  # Assume volume spike if no volume data

    # Current values
    price = float(df["Close"].iloc[-1])
    fast_ema_val = float(fast_ema.iloc[-1])
    slow_ema_val = float(slow_ema.iloc[-1])
    rsi_val = float(rsi.iloc[-1])
    atr_val = float(atr.iloc[-1])

    # Entry logic
    side: Side = "flat"
    confidence = 0.0
    comment = ""

    # Long setup: Fast EMA > Slow EMA, RSI oversold bounce, volume spike
    if (
        fast_ema_val > slow_ema_val
        and rsi_val < params.get("rsi_oversold", 30)
        and rsi_val > 20  # Not too oversold (avoid falling knife)
        and volume_spike
    ):
        side = "long"
        confidence = 0.7
        comment = f"Scalp LONG: RSI bounce {rsi_val:.1f}, EMA trend up, volume spike"

    # Short setup: Fast EMA < Slow EMA, RSI overbought rejection, volume spike
    elif (
        fast_ema_val < slow_ema_val
        and rsi_val > params.get("rsi_overbought", 70)
        and rsi_val < 80  # Not too overbought
        and volume_spike
    ):
        side = "short"
        confidence = 0.7
        comment = (
            f"Scalp SHORT: RSI rejection {rsi_val:.1f}, EMA trend down, volume spike"
        )

    # Calculate stop loss and take profit
    stop_loss = None
    take_profit = None

    if side == "long":
        stop_loss = price - (atr_val * params.get("atr_multiplier", 1.5))
        take_profit = price + (
            atr_val
            * params.get("atr_multiplier", 1.5)
            * params.get("take_profit_multiplier", 2.0)
        )
    elif side == "short":
        stop_loss = price + (atr_val * params.get("atr_multiplier", 1.5))
        take_profit = price - (
            atr_val
            * params.get("atr_multiplier", 1.5)
            * params.get("take_profit_multiplier", 2.0)
        )

    return {
        "side": side,
        "confidence": confidence,
        "comment": comment,
        "fast_ema": fast_ema_val,
        "slow_ema": slow_ema_val,
        "rsi": rsi_val,
        "atr": atr_val,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "max_hold_bars": params.get("max_hold_bars", 5),
        "strategy_name": "scalping",
    }
