"""Intraday Swing Strategy - Holds positions for hours, targets larger moves."""
from __future__ import annotations

import pandas as pd
from typing import Dict, Any
from pearlalgo.strategies.base import register_strategy

Side = str  # "long" | "short" | "flat"


@register_strategy(
    name="intraday_swing",
    description="Intraday swing trading - holds for hours, targets 1-3% moves",
    default_params={
        "trend_ema": 50,
        "entry_ema": 20,
        "adx_period": 14,
        "adx_threshold": 25,
        "min_move_target": 0.01,  # 1% minimum target
        "max_move_target": 0.03,  # 3% maximum target
        "stop_loss_pct": 0.005,   # 0.5% stop loss
        "min_hold_bars": 4,       # Hold at least 4 bars (1 hour on 15min)
        "max_hold_bars": 16,      # Max 4 hours
    }
)
def intraday_swing_strategy(symbol: str, df: pd.DataFrame, **params) -> Dict[str, Any]:
    """
    Intraday swing strategy:
    - Uses 50 EMA for trend direction
    - 20 EMA for entry timing
    - ADX for trend strength
    - Targets 1-3% moves
    - Holds for 1-4 hours
    
    Best for: 15-60 minute timeframes
    """
    if len(df) < max(params.get("trend_ema", 50), params.get("adx_period", 14)):
        return {
            "side": "flat",
            "confidence": 0.0,
            "comment": "Insufficient data",
            "strategy_name": "intraday_swing",
        }
    
    # Calculate EMAs
    trend_ema = df["Close"].ewm(span=params.get("trend_ema", 50), adjust=False).mean()
    entry_ema = df["Close"].ewm(span=params.get("entry_ema", 20), adjust=False).mean()
    
    # ADX for trend strength
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr1 = pd.DataFrame(high - low)
    tr2 = pd.DataFrame(abs(high - close.shift()))
    tr3 = pd.DataFrame(abs(low - close.shift()))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(window=params.get("adx_period", 14)).mean()
    plus_di = 100 * (plus_dm.rolling(window=params.get("adx_period", 14)).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=params.get("adx_period", 14)).mean() / atr)
    
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=params.get("adx_period", 14)).mean()
    
    # Current values
    price = float(df["Close"].iloc[-1])
    trend_ema_val = float(trend_ema.iloc[-1])
    entry_ema_val = float(entry_ema.iloc[-1])
    adx_val = float(adx.iloc[-1])
    plus_di_val = float(plus_di.iloc[-1])
    minus_di_val = float(minus_di.iloc[-1])
    
    # Entry logic
    side: Side = "flat"
    confidence = 0.0
    comment = ""
    
    # Long: Price above trend EMA, entry EMA crossing up, strong trend (ADX > 25), +DI > -DI
    if (price > trend_ema_val and
        entry_ema_val > trend_ema_val and
        adx_val > params.get("adx_threshold", 25) and
        plus_di_val > minus_di_val):
        side = "long"
        confidence = 0.75
        comment = f"Swing LONG: Trend up (ADX {adx_val:.1f}), +DI > -DI"
    
    # Short: Price below trend EMA, entry EMA crossing down, strong trend, -DI > +DI
    elif (price < trend_ema_val and
          entry_ema_val < trend_ema_val and
          adx_val > params.get("adx_threshold", 25) and
          minus_di_val > plus_di_val):
        side = "short"
        confidence = 0.75
        comment = f"Swing SHORT: Trend down (ADX {adx_val:.1f}), -DI > +DI"
    
    # Calculate targets
    stop_loss = None
    take_profit = None
    if side == "long":
        stop_loss = price * (1 - params.get("stop_loss_pct", 0.005))
        take_profit = price * (1 + params.get("min_move_target", 0.01))
    elif side == "short":
        stop_loss = price * (1 + params.get("stop_loss_pct", 0.005))
        take_profit = price * (1 - params.get("min_move_target", 0.01))
    
    return {
        "side": side,
        "confidence": confidence,
        "comment": comment,
        "trend_ema": trend_ema_val,
        "entry_ema": entry_ema_val,
        "adx": adx_val,
        "plus_di": plus_di_val,
        "minus_di": minus_di_val,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "min_hold_bars": params.get("min_hold_bars", 4),
        "max_hold_bars": params.get("max_hold_bars", 16),
        "strategy_name": "intraday_swing",
    }

