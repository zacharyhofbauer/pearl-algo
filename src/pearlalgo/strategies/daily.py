from __future__ import annotations

import pandas as pd

from pearlalgo.strategies.base import BaseStrategy


class MovingAverageCross(BaseStrategy):
    """
    Simple moving-average cross. Generates BUY when fast > slow, SELL when fast < slow.
    """

    name = "ma_cross"

    def __init__(self, fast: int = 10, slow: int = 20):
        self.fast = fast
        self.slow = slow

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["fast"] = df["Close"].rolling(self.fast).mean()
        df["slow"] = df["Close"].rolling(self.slow).mean()
        df["entry"] = 0
        df.loc[df["fast"] > df["slow"], "entry"] = 1
        df.loc[df["fast"] < df["slow"], "entry"] = -1
        df["size"] = 1
        return df[["entry", "size"]]


class Breakout(BaseStrategy):
    """
    Simple channel breakout: BUY above recent high, SELL below recent low.
    """

    name = "breakout"

    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["recent_high"] = df["High"].rolling(self.lookback).max()
        df["recent_low"] = df["Low"].rolling(self.lookback).min()
        df["entry"] = 0
        df.loc[df["Close"] > df["recent_high"], "entry"] = 1
        df.loc[df["Close"] < df["recent_low"], "entry"] = -1
        df["size"] = 1
        return df[["entry", "size"]]
