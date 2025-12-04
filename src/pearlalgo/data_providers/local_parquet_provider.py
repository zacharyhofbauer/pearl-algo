"""
Local Parquet Data Provider for deterministic historical data storage.

Provides fast, efficient storage and retrieval of historical market data
using Parquet format. Essential for deterministic backtesting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pearlalgo.data_providers.base import DataProvider

logger = logging.getLogger(__name__)


class LocalParquetProvider(DataProvider):
    """
    Local Parquet-based historical data provider.

    Features:
    - Fast read/write with Parquet format
    - Deterministic data for backtesting
    - Efficient compression
    - Support for multiple timeframes
    - Metadata storage
    """

    def __init__(self, root_dir: str | Path):
        """
        Initialize local Parquet provider.

        Args:
            root_dir: Root directory for storing Parquet files
        """
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(
        self, symbol: str, timeframe: Optional[str] = None
    ) -> Path:
        """
        Get file path for a symbol and timeframe.

        Args:
            symbol: Ticker symbol
            timeframe: Timeframe (e.g., '1m', '5m', '15m', '1d')

        Returns:
            Path to Parquet file
        """
        if timeframe:
            filename = f"{symbol}_{timeframe}.parquet"
        else:
            filename = f"{symbol}.parquet"

        return self.root_dir / filename

    def save_historical(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: Optional[str] = None,
        overwrite: bool = False,
    ) -> bool:
        """
        Save historical data to Parquet file.

        Args:
            df: DataFrame with OHLCV data (must have timestamp index)
            symbol: Ticker symbol
            timeframe: Timeframe identifier
            overwrite: Whether to overwrite existing file

        Returns:
            True if successful, False otherwise
        """
        if df.empty:
            logger.warning(f"Empty DataFrame provided for {symbol}")
            return False

        if not isinstance(df.index, pd.DatetimeIndex):
            logger.error(f"DataFrame index must be DatetimeIndex for {symbol}")
            return False

        file_path = self._get_file_path(symbol, timeframe)

        if file_path.exists() and not overwrite:
            logger.warning(
                f"File already exists: {file_path}. Use overwrite=True to replace."
            )
            return False

        try:
            # Ensure timestamp column is stored properly
            df_to_save = df.copy()
            df_to_save.index.name = "timestamp"

            # Convert to PyArrow table
            table = pa.Table.from_pandas(df_to_save)

            # Write to Parquet with compression
            pq.write_table(
                table,
                file_path,
                compression="snappy",  # Good balance of speed and compression
                write_statistics=True,
                metadata={
                    "symbol": symbol,
                    "timeframe": timeframe or "default",
                    "created_at": datetime.now().isoformat(),
                    "row_count": str(len(df)),
                },
            )

            logger.info(
                f"Saved {len(df)} rows for {symbol} to {file_path}"
            )
            return True

        except Exception as e:
            logger.error(f"Error saving data for {symbol} to {file_path}: {e}")
            return False

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch historical data from Parquet file.

        Args:
            symbol: Ticker symbol
            start: Start datetime (inclusive)
            end: End datetime (inclusive)
            timeframe: Timeframe identifier

        Returns:
            DataFrame with OHLCV data indexed by timestamp
        """
        file_path = self._get_file_path(symbol, timeframe)

        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return pd.DataFrame()

        try:
            # Read Parquet file
            table = pq.read_table(file_path)
            df = table.to_pandas()

            # Set timestamp as index if it's a column
            if "timestamp" in df.columns:
                df.set_index("timestamp", inplace=True)
            elif df.index.name != "timestamp":
                df.index.name = "timestamp"

            # Filter by date range
            if start is not None:
                df = df[df.index >= start]
            if end is not None:
                df = df[df.index <= end]

            if df.empty:
                logger.warning(
                    f"No data found for {symbol} in range {start} to {end}"
                )
                return pd.DataFrame()

            logger.info(
                f"Loaded {len(df)} rows for {symbol} from {file_path}"
            )
            return df

        except Exception as e:
            logger.error(
                f"Error loading data for {symbol} from {file_path}: {e}"
            )
            return pd.DataFrame()

    def list_symbols(self, timeframe: Optional[str] = None) -> list[str]:
        """
        List all symbols with available data.

        Args:
            timeframe: Optional timeframe filter

        Returns:
            List of symbol names
        """
        pattern = "*.parquet" if not timeframe else f"*_{timeframe}.parquet"
        files = list(self.root_dir.glob(pattern))

        symbols = []
        for file in files:
            name = file.stem  # Remove .parquet extension
            if timeframe:
                # Remove timeframe suffix
                symbol = name.replace(f"_{timeframe}", "")
            else:
                symbol = name

            # Remove timeframe if present (in case of default files)
            if "_" in symbol:
                parts = symbol.split("_")
                # Check if last part looks like a timeframe
                if len(parts[-1]) <= 4 and parts[-1].replace("mhd", "").isdigit():
                    symbol = "_".join(parts[:-1])

            if symbol not in symbols:
                symbols.append(symbol)

        return sorted(symbols)

    def get_metadata(self, symbol: str, timeframe: Optional[str] = None) -> dict:
        """
        Get metadata for a stored file.

        Args:
            symbol: Ticker symbol
            timeframe: Timeframe identifier

        Returns:
            Dict with metadata (row_count, created_at, etc.)
        """
        file_path = self._get_file_path(symbol, timeframe)

        if not file_path.exists():
            return {}

        try:
            parquet_file = pq.ParquetFile(file_path)
            metadata = parquet_file.metadata.metadata

            if metadata:
                return {
                    k.decode() if isinstance(k, bytes) else k: (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in metadata.items()
                }

            return {}

        except Exception as e:
            logger.error(f"Error reading metadata for {symbol}: {e}")
            return {}

    def file_exists(self, symbol: str, timeframe: Optional[str] = None) -> bool:
        """
        Check if a file exists for a symbol.

        Args:
            symbol: Ticker symbol
            timeframe: Timeframe identifier

        Returns:
            True if file exists
        """
        return self._get_file_path(symbol, timeframe).exists()




