from __future__ import annotations

from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return signals/positions given OHLCV data."""
