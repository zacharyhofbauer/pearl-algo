"""
Historical Futures Data Loader

Loads historical ES/NQ data from Massive API for backtesting purposes.
Handles contract rolls and timestamp alignment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class HistoricalFuturesDataLoader:
    """
    Loader for historical ES/NQ futures data from Massive API.
    
    Features:
    - Loads historical bars for ES and NQ
    - Handles contract rolls (ESU5 -> ESZ5, etc.)
    - Aligns timestamps across multiple symbols
    - Normalizes data to standard OHLCV format
    - Caches data locally in Parquet format
    """
    
    def __init__(
        self,
        data_provider,  # MassiveDataProvider
        cache_dir: str = "data/backtesting",
    ):
        """
        Initialize historical data loader.
        
        Args:
            data_provider: MassiveDataProvider instance
            cache_dir: Directory for caching historical data
        """
        self.data_provider = data_provider
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"HistoricalFuturesDataLoader initialized with cache_dir={cache_dir}")
    
    def load_es_data(
        self,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "15m",
    ) -> pd.DataFrame:
        """
        Load ES historical data.
        
        Args:
            start_date: Start date
            end_date: End date
            timeframe: Bar timeframe (1m, 5m, 15m, 1h, 1d)
            
        Returns:
            DataFrame with OHLCV data, handling contract rolls
        """
        logger.info(f"Loading ES data from {start_date.date()} to {end_date.date()}, timeframe={timeframe}")
        
        # Check cache first
        cache_file = self.cache_dir / f"ES_{timeframe}_{start_date.date()}_{end_date.date()}.parquet"
        if cache_file.exists():
            logger.info(f"Loading ES data from cache: {cache_file}")
            try:
                df = pd.read_parquet(cache_file)
                df.index = pd.to_datetime(df.index)
                return df
            except Exception as e:
                logger.warning(f"Error loading cache, fetching fresh data: {e}")
        
        # Fetch from Massive API
        df = self.data_provider.fetch_historical(
            symbol="ES",
            start=start_date,
            end=end_date,
            timeframe=timeframe,
        )
        
        if df.empty:
            logger.warning(f"No ES data returned for date range")
            return pd.DataFrame()
        
        # Handle contract rolls by detecting gaps and adjusting
        df = self._handle_contract_rolls(df, symbol="ES")
        
        # Normalize data
        df = self.normalize_data(df)
        
        # Cache the data
        try:
            df.to_parquet(cache_file)
            logger.info(f"Cached ES data to {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to cache ES data: {e}")
        
        return df
    
    def load_nq_data(
        self,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "15m",
    ) -> pd.DataFrame:
        """
        Load NQ historical data.
        
        Args:
            start_date: Start date
            end_date: End date
            timeframe: Bar timeframe (1m, 5m, 15m, 1h, 1d)
            
        Returns:
            DataFrame with OHLCV data, handling contract rolls
        """
        logger.info(f"Loading NQ data from {start_date.date()} to {end_date.date()}, timeframe={timeframe}")
        
        # Check cache first
        cache_file = self.cache_dir / f"NQ_{timeframe}_{start_date.date()}_{end_date.date()}.parquet"
        if cache_file.exists():
            logger.info(f"Loading NQ data from cache: {cache_file}")
            try:
                df = pd.read_parquet(cache_file)
                df.index = pd.to_datetime(df.index)
                return df
            except Exception as e:
                logger.warning(f"Error loading cache, fetching fresh data: {e}")
        
        # Fetch from Massive API
        df = self.data_provider.fetch_historical(
            symbol="NQ",
            start=start_date,
            end=end_date,
            timeframe=timeframe,
        )
        
        if df.empty:
            logger.warning(f"No NQ data returned for date range")
            return pd.DataFrame()
        
        # Handle contract rolls
        df = self._handle_contract_rolls(df, symbol="NQ")
        
        # Normalize data
        df = self.normalize_data(df)
        
        # Cache the data
        try:
            df.to_parquet(cache_file)
            logger.info(f"Cached NQ data to {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to cache NQ data: {e}")
        
        return df
    
    def _handle_contract_rolls(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Handle futures contract rolls by detecting gaps and adjusting prices.
        
        Args:
            df: DataFrame with OHLCV data
            symbol: Symbol (ES or NQ)
            
        Returns:
            DataFrame with adjusted prices for contract rolls
        """
        if df.empty:
            return df
        
        # Detect large gaps (potential contract roll)
        # Contract rolls typically happen on expiration dates
        # For now, we'll use a simple approach: detect price gaps > 5%
        
        df = df.copy()
        df['price_change_pct'] = df['close'].pct_change().abs()
        
        # Identify potential roll dates (large price changes)
        roll_threshold = 0.05  # 5% change suggests contract roll
        potential_rolls = df[df['price_change_pct'] > roll_threshold].index
        
        if len(potential_rolls) > 0:
            logger.info(f"Detected {len(potential_rolls)} potential contract rolls for {symbol}")
            
            # For each roll, adjust subsequent prices
            for roll_date in potential_rolls:
                roll_idx = df.index.get_loc(roll_date)
                if roll_idx > 0:
                    # Calculate price difference at roll
                    prev_close = df.iloc[roll_idx - 1]['close']
                    roll_close = df.iloc[roll_idx]['close']
                    price_diff = roll_close - prev_close
                    
                    # Adjust all prices after roll
                    df.loc[df.index >= roll_date, ['open', 'high', 'low', 'close']] -= price_diff
                    logger.debug(f"Adjusted prices after {roll_date} by ${price_diff:.2f}")
        
        # Drop the helper column
        df = df.drop(columns=['price_change_pct'], errors='ignore')
        
        return df
    
    def align_timestamps(
        self,
        dataframes: Dict[str, pd.DataFrame],
        method: str = "inner",
    ) -> Dict[str, pd.DataFrame]:
        """
        Align timestamps across multiple DataFrames.
        
        Args:
            dataframes: Dictionary of symbol -> DataFrame
            method: Alignment method ("inner", "outer", "left", "right")
            
        Returns:
            Dictionary of aligned DataFrames
        """
        if not dataframes:
            return {}
        
        if len(dataframes) == 1:
            return dataframes
        
        logger.info(f"Aligning timestamps for {len(dataframes)} symbols using {method} join")
        
        # Get all unique timestamps
        all_timestamps = set()
        for df in dataframes.values():
            all_timestamps.update(df.index)
        
        # Create aligned index
        aligned_index = pd.Index(sorted(all_timestamps))
        
        # Align each DataFrame
        aligned = {}
        for symbol, df in dataframes.items():
            # Reindex to aligned index
            aligned_df = df.reindex(aligned_index, method=method)
            
            # Forward fill missing values (within reason)
            aligned_df = aligned_df.fillna(method='ffill', limit=10)
            
            aligned[symbol] = aligned_df
            logger.debug(f"Aligned {symbol}: {len(df)} -> {len(aligned_df)} bars")
        
        return aligned
    
    def normalize_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize DataFrame to standard OHLCV format.
        
        Args:
            df: DataFrame with market data
            
        Returns:
            Normalized DataFrame with columns: open, high, low, close, volume
        """
        if df.empty:
            return df
        
        # Ensure required columns exist
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            logger.warning(f"Missing columns in data: {missing_cols}, attempting to infer...")
            # Try to infer from common column name variations
            col_mapping = {
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume',
                'O': 'open',
                'H': 'high',
                'L': 'low',
                'C': 'close',
                'V': 'volume',
            }
            for old_col, new_col in col_mapping.items():
                if old_col in df.columns and new_col not in df.columns:
                    df[new_col] = df[old_col]
        
        # Select only required columns
        available_cols = [col for col in required_cols if col in df.columns]
        df = df[available_cols].copy()
        
        # Ensure numeric types
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Remove rows with NaN in critical columns
        df = df.dropna(subset=['close'])
        
        # Sort by timestamp
        df = df.sort_index()
        
        # Remove duplicates
        df = df[~df.index.duplicated(keep='last')]
        
        logger.debug(f"Normalized data: {len(df)} bars, columns={list(df.columns)}")
        
        return df
    
    def load_multiple_symbols(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "15m",
        align: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """
        Load multiple symbols and optionally align timestamps.
        
        Args:
            symbols: List of symbols (e.g., ["ES", "NQ"])
            start_date: Start date
            end_date: End date
            timeframe: Bar timeframe
            align: Whether to align timestamps
            
        Returns:
            Dictionary of symbol -> DataFrame
        """
        logger.info(f"Loading {len(symbols)} symbols: {symbols}")
        
        dataframes = {}
        
        for symbol in symbols:
            if symbol == "ES":
                df = self.load_es_data(start_date, end_date, timeframe)
            elif symbol == "NQ":
                df = self.load_nq_data(start_date, end_date, timeframe)
            else:
                logger.warning(f"Unknown symbol: {symbol}, skipping...")
                continue
            
            if not df.empty:
                dataframes[symbol] = df
        
        # Align timestamps if requested
        if align and len(dataframes) > 1:
            dataframes = self.align_timestamps(dataframes)
        
        logger.info(f"Loaded {len(dataframes)} symbols successfully")
        
        return dataframes
