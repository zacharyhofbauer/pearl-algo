from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

import pandas as pd


class DataProvider(ABC):
    """Abstract data provider for historical and live data."""

    @abstractmethod
    def fetch_historical(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV data indexed by timestamp."""

    def stream_live(self, symbols: list[str]) -> Iterable[pd.DataFrame]:
        """
        Optional live data stream.
        Should yield data frames or rows containing latest bars/ticks.
        """
        raise NotImplementedError("Live streaming not implemented for this provider")
