from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from pearlalgo.strategies.base import BaseStrategy


class ESBreakoutStrategy(BaseStrategy):
    name = "es_breakout"

    def __init__(self, lookback: int = 50, atr_len: int = 14, atr_k: float = 1.5):
        self.lookback = lookback
        self.atr_len = atr_len
        self.atr_k = atr_k

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["hh"] = df["High"].rolling(self.lookback).max()
        df["ll"] = df["Low"].rolling(self.lookback).min()
        df["atr"] = ta.atr(df["High"], df["Low"], df["Close"], length=self.atr_len)
        df["long"] = (df["Close"] > df["hh"].shift(1)).astype(int)
        df["short"] = (df["Close"] < df["ll"].shift(1)).astype(int)
        df["entry"] = df["long"] - df["short"]
        df["stop_long"] = df["Close"] - self.atr_k * df["atr"]
        df["stop_short"] = df["Close"] + self.atr_k * df["atr"]
        df["stop"] = pd.NA
        df.loc[df["entry"] > 0, "stop"] = df["stop_long"]
        df.loc[df["entry"] < 0, "stop"] = df["stop_short"]
        df["target"] = pd.NA
        df.loc[df["entry"] > 0, "target"] = df["Close"] + self.atr_k * df["atr"]
        df.loc[df["entry"] < 0, "target"] = df["Close"] - self.atr_k * df["atr"]
        df["size"] = 1  # placeholder; agents can override with risk-based sizing
        return df


class EquityMomentumStrategy(BaseStrategy):
    name = "equity_momentum"

    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast = fast
        self.slow = slow

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["fast_ma"] = df["Close"].rolling(self.fast).mean()
        df["slow_ma"] = df["Close"].rolling(self.slow).mean()
        df["entry"] = 0
        df.loc[df["fast_ma"] > df["slow_ma"], "entry"] = 1
        df.loc[df["fast_ma"] < df["slow_ma"], "entry"] = -1
        df["stop"] = pd.NA
        df["target"] = pd.NA
        df["size"] = 1
        return df


class FuturesTrendStrategy(BaseStrategy):
    name = "futures_trend"

    def __init__(self, atr_len: int = 14, atr_k: float = 2.0):
        self.atr_len = atr_len
        self.atr_k = atr_k

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["atr"] = ta.atr(df["High"], df["Low"], df["Close"], length=self.atr_len)
        df["trend"] = df["Close"].diff().rolling(10).mean()
        df["entry"] = 0
        df.loc[df["trend"] > 0, "entry"] = 1
        df.loc[df["trend"] < 0, "entry"] = -1
        df["stop"] = df["Close"] - self.atr_k * df["atr"]
        df["target"] = pd.NA
        df["size"] = 1
        return df


class OptionsPremiumSellStrategy(BaseStrategy):
    name = "options_premium_sell"

    def __init__(self, delta_threshold: float = 0.2):
        self.delta_threshold = delta_threshold

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Educational placeholder: flags entries when realized vol is low and trend is flat.
        Actual options greeks/pricing must be supplied by a real options data feed.
        """
        df = data.copy()
        df["rv"] = df["Close"].pct_change().rolling(20).std()
        df["trend"] = df["Close"].diff().rolling(10).mean()
        df["entry"] = 0
        df.loc[(df["rv"] < df["rv"].median()) & (abs(df["trend"]) < df["Close"].pct_change().std()), "entry"] = 1
        df["stop"] = pd.NA
        df["target"] = pd.NA
        df["size"] = 1
        return df
