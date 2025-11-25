from __future__ import annotations

import pandas as pd


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV to a new timeframe."""
    ohlc = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    return df.resample(rule).agg(ohlc).dropna()
