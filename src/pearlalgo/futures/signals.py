from __future__ import annotations

from typing import Any, Literal

import pandas as pd

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


def generate_signal(
    symbol: str,
    df: pd.DataFrame,
    strategy_name: str = "ma_cross",
    **params: Any,
) -> dict[str, Any]:
    """
    Strategy-agnostic signal wrapper. Currently supports ma_cross.
    Returns a dict with side, indicators, and metadata.
    """
    fast = int(params.get("fast", 20))
    slow = int(params.get("slow", 50))
    side: Side
    if strategy_name == "ma_cross":
        side = ma_cross_signal(df, fast=fast, slow=slow)
    else:
        raise ValueError(f"Unsupported strategy: {strategy_name}")

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
