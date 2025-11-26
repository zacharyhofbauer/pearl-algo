from __future__ import annotations

from typing import Any

import pandas as pd


def ma_cross_signal(prices: pd.Series, fast: int, slow: int) -> str:
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
    prices = df["Close"]
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 20))
    side = ma_cross_signal(prices, fast=fast, slow=slow)
    return {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "side": side,
        "fast_ma": float(prices.rolling(fast).mean().iloc[-1]) if len(prices) >= fast else None,
        "slow_ma": float(prices.rolling(slow).mean().iloc[-1]) if len(prices) >= slow else None,
        "params": {"fast": fast, "slow": slow},
    }
