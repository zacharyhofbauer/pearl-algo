from __future__ import annotations

from typing import Any, Literal, Optional

import pandas as pd

from pearlalgo.futures.sr import Bar, calculate_support_resistance

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


def sr_strategy(symbol: str, df: pd.DataFrame, *, fast: int = 20, slow: int = 50, tolerance: float = 0.002) -> dict[str, Any]:
    """
    Support/Resistance + VWAP strategy with optional MA filter.
    - Long: close > vwap and within tolerance of support1.
    - Short: close < vwap and within tolerance of resistance1.
    """
    bars = [
        Bar(timestamp=idx, high=row["High"], low=row["Low"], close=row["Close"], volume=row.get("Volume", 0.0))
        for idx, row in df.iterrows()
    ]
    sr_levels = calculate_support_resistance(bars)
    close = float(df["Close"].iloc[-1])
    vwap = sr_levels.get("vwap")
    support = sr_levels.get("support1")
    resistance = sr_levels.get("resistance1")
    side: Side = "flat"
    comment = "flat"

    def near(level: Optional[float]) -> bool:
        if level is None:
            return False
        return abs(close - level) <= level * tolerance

    if vwap:
        if close > vwap and near(support):
            side = "long"
            comment = "long above vwap near support1"
        elif close < vwap and near(resistance):
            side = "short"
            comment = "short below vwap near resistance1"

    # Optional MA trend filter
    trend = ma_cross_signal(df, fast=fast, slow=slow)
    if side == "long" and trend == "short":
        side = "flat"
        comment = "flat (MA filter)"
    if side == "short" and trend == "long":
        side = "flat"
        comment = "flat (MA filter)"

    return {
        "symbol": symbol,
        "strategy_name": "sr",
        "side": side,
        "fast_ma": float(df["Close"].rolling(fast).mean().iloc[-1]) if len(df) >= fast else None,
        "slow_ma": float(df["Close"].rolling(slow).mean().iloc[-1]) if len(df) >= slow else None,
        "support1": support,
        "resistance1": resistance,
        "vwap": vwap,
        "comment": comment,
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
