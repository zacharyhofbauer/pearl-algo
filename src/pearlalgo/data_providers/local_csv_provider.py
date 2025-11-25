from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from pearlalgo.data.loaders import load_csv
from pearlalgo.data.pipelines import resample_ohlcv
from pearlalgo.data_providers.base import DataProvider


class LocalCSVProvider(DataProvider):
    """
    Simple CSV-based historical provider.

    Uses either a provided file path or resolves `{root_dir}/{symbol}.csv`.
    Intended for backtesting/research and sample data ingestion.
    """

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)

    def _resolve_path(self, symbol: str, file_name: str | Path | None) -> Path:
        if file_name:
            return Path(file_name)
        direct = self.root_dir / f"{symbol}.csv"
        if direct.exists():
            return direct
        # fallback: try to find a file containing the symbol name
        candidates = sorted(self.root_dir.glob(f"*{symbol}*.csv"))
        if candidates:
            return candidates[0]
        return direct

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: str | None = None,
        file_name: str | Path | None = None,
    ) -> pd.DataFrame:
        path = self._resolve_path(symbol, file_name)
        df = load_csv(path)

        if start is not None:
            df = df[df.index >= start]
        if end is not None:
            df = df[df.index <= end]

        if timeframe:
            df = resample_ohlcv(df, timeframe)

        return df
