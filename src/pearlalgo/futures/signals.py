from __future__ import annotations

from typing import Any, Literal, Optional

import pandas as pd

from pearlalgo.futures.sr import Bar, calculate_support_resistance, sr_signal_from_levels

Side = Literal["long", "short", "flat"]


def ma_cross_signal(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> Side:
    prices = df["Close"]
    if len(prices) < max(fast, slow):
        return "flat"
    fast_ma = prices.rolling(fast).mean().iloc[-1]
    slow_ma = prices.rolling(slow).mean().iloc[-1]
    if pd.isna(fast_ma) or pd.isna(slow_ma):
        return "flat"
    if fast_ma > slow_ma:
        return "long"
    if fast_ma < slow_ma:
        return "short"
    return "flat"


def ema_filter(df: pd.DataFrame, period: int = 20) -> tuple[float | None, bool]:
    """
    Compute EMA and return (ema_value, price_above_ema).
    Returns (None, False) if insufficient data.
    """
    if len(df) < period:
        return None, False
    prices = df["Close"]
    ema = prices.ewm(span=period, adjust=False).mean().iloc[-1]
    if pd.isna(ema):
        return None, False
    close = float(prices.iloc[-1])
    return float(ema), close > ema


def sr_strategy(symbol: str, df: pd.DataFrame, *, fast: int = 20, slow: int = 50, tolerance: float = 0.002) -> dict[str, Any]:
    """
    Support/Resistance + VWAP strategy with EMA filter.
    - Long: close > vwap, near support1, and price > 20-EMA.
    - Short: close < vwap, near resistance1, and price < 20-EMA.
    """
    bars = [
        Bar(timestamp=idx, high=row["High"], low=row["Low"], close=row["Close"], volume=row.get("Volume", 0.0))
        for idx, row in df.iterrows()
    ]
    sr_levels = calculate_support_resistance(bars)
    close = float(df["Close"].iloc[-1])
    signal_obj = sr_signal_from_levels(close, sr_levels, tolerance=tolerance)
    side: Side = signal_obj.signal_type if signal_obj.signal_type in {"long", "short"} else "flat"
    
    # EMA filter (20-period by default, using fast parameter)
    ema_value, price_above_ema = ema_filter(df, period=fast)
    
    # Build trade_reason string
    trade_reason_parts = []
    if side == "long":
        if sr_levels.get("support1"):
            trade_reason_parts.append("Bullish pivot")
        if sr_levels.get("vwap") and close > sr_levels["vwap"]:
            trade_reason_parts.append("above VWAP")
        if ema_value and price_above_ema:
            trade_reason_parts.append(f"{fast}EMA")
        # Apply EMA filter: only take long if price above EMA
        if ema_value and not price_above_ema:
            side = "flat"
            trade_reason_parts = ["flat (below EMA filter)"]
    elif side == "short":
        if sr_levels.get("resistance1"):
            trade_reason_parts.append("Bearish pivot")
        if sr_levels.get("vwap") and close < sr_levels["vwap"]:
            trade_reason_parts.append("below VWAP")
        if ema_value and not price_above_ema:
            trade_reason_parts.append(f"below {fast}EMA")
        # Apply EMA filter: only take short if price below EMA
        if ema_value and price_above_ema:
            side = "flat"
            trade_reason_parts = ["flat (above EMA filter)"]
    
    trade_reason = " + ".join(trade_reason_parts) if trade_reason_parts else None

    return {
        "symbol": symbol,
        "strategy_name": "sr",
        "side": side,
        "fast_ma": ema_value,  # Actually EMA now
        "slow_ma": float(df["Close"].rolling(slow).mean().iloc[-1]) if len(df) >= slow else None,
        "support1": sr_levels.get("support1"),
        "resistance1": sr_levels.get("resistance1"),
        "vwap": sr_levels.get("vwap"),
        "entry_price": signal_obj.entry_price,
        "stop_price": signal_obj.stop_price,
        "target_price": signal_obj.target_price,
        "comment": trade_reason,
        "params": {"fast": fast, "slow": slow, "tolerance": tolerance},
    }


def generate_signal(
    symbol: str,
    df: pd.DataFrame,
    strategy_name: str = "ma_cross",
    **params: Any,
) -> dict[str, Any]:
    """
    Strategy-agnostic signal wrapper. Supports ma_cross and sr.
    Returns a dict with side, indicators, and metadata.
    """
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 50))
    if strategy_name == "ma_cross":
        side = ma_cross_signal(df, fast=fast, slow=slow)
        prices = df["Close"]
        fast_ma = float(prices.rolling(fast).mean().iloc[-1]) if len(prices) >= fast else None
        slow_ma = float(prices.rolling(slow).mean().iloc[-1]) if len(prices) >= slow else None
        return {
            "symbol": symbol,
            "strategy_name": strategy_name,
            "side": side,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "params": {"fast": fast, "slow": slow},
        }
    if strategy_name == "sr":
        return sr_strategy(symbol, df, fast=fast, slow=slow, tolerance=float(params.get("tolerance", 0.002)))

    raise ValueError(f"Unsupported strategy: {strategy_name}")
