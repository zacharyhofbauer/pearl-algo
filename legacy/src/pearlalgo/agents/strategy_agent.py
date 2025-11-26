from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.strategies.base import BaseStrategy


class StrategyAgent:
    """
    Coordinates data retrieval and strategy execution.

    Intended for backtest/paper/live reuse; downstream execution/risk agents
    consume the resulting signal dataframe.
    """

    def __init__(
        self,
        provider: DataProvider,
        strategy: BaseStrategy,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ):
        self.provider = provider
        self.strategy = strategy
        self.symbol = symbol
        self.start = start
        self.end = end
        self.timeframe = timeframe

    def run(self) -> pd.DataFrame:
        data = self.provider.fetch_historical(
            self.symbol,
            start=self.start,
            end=self.end,
            timeframe=self.timeframe,
        )
        return self.strategy.run(data)
