"""
IBKR Data Provider for stocks, futures, and options.

Uses IB Gateway via ib_insync for live and historical data.
Supports:
- Historical OHLCV data for stocks and futures
- Real-time quotes
- Full options chains with filtering
- Connection management and reconnection
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd
from ib_insync import util

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.data_providers.ibkr_executor import (
    GetHistoricalDataTask,
    GetLatestBarTask,
    GetOptionsChainTask,
    IBKRExecutor,
)
from pearlalgo.utils.retry import async_retry_with_backoff

logger = logging.getLogger(__name__)


class IBKRDataProvider(DataProvider):
    """
    IBKR data provider using IB Gateway via ib_insync.
    
    Supports:
    - Historical OHLCV data (stocks and futures)
    - Real-time quotes
    - Options chains with filtering
    - Automatic connection management
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        """
        Initialize IBKR data provider.
        
        Args:
            settings: Settings instance (optional, uses get_settings() if not provided)
            host: IB Gateway host (default: from settings)
            port: IB Gateway port (default: from settings)
            client_id: Client ID for data connections (default: IBKR_DATA_CLIENT_ID from settings)
        """
        self.settings = settings or get_settings()
        self.host = host or self.settings.ib_host
        self.port = port or self.settings.ib_port
        self.client_id = client_id or self.settings.ib_data_client_id or self.settings.ib_client_id
        
        # Futures symbols for contract type detection
        self.futures_symbols = {"ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "NG", "ZB", "ZN", "ZF", "ZT"}
        
        # Initialize executor (dedicated thread for IBKR calls)
        self._executor = IBKRExecutor(
            host=self.host,
            port=self.port,
            client_id=self.client_id,
        )
        self._executor.start()
        
        logger.info(
            f"IBKRDataProvider initialized: host={self.host}, port={self.port}, client_id={self.client_id}"
        )

    async def close(self) -> None:
        """Close IB connection and stop executor."""
        logger.info("Closing IBKRDataProvider...")
        self._executor.stop(timeout=10.0)
        logger.info("IBKRDataProvider closed")


    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data synchronously.
        
        Args:
            symbol: Ticker symbol (e.g., 'AAPL', 'ES' for futures)
            start: Start datetime (default: 1 year ago)
            end: End datetime (default: now)
            timeframe: Timeframe (e.g., '1m', '5m', '15m', '1h', '1d')
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(
            self._fetch_historical_async(symbol, start, end, timeframe)
        )

    async def _fetch_historical_async(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        """Async implementation of fetch_historical using executor."""
        if start is None:
            start = datetime.now(timezone.utc) - timedelta(days=365)
        if end is None:
            end = datetime.now(timezone.utc)
        
        # Determine if symbol is futures or stock
        is_futures = symbol.upper() in self.futures_symbols
        
        try:
            # Submit task to executor
            task_id = str(uuid.uuid4())
            task = GetHistoricalDataTask(
                task_id=task_id,
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
                is_futures=is_futures,
            )
            
            future = self._executor.submit_task(task)
            bars = await asyncio.wrap_future(future)
            
            if not bars:
                logger.warning(f"No historical data returned for {symbol}")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = util.df(bars)
            if df.empty:
                return pd.DataFrame()
            
            # Rename columns to standard format
            df = df.rename(columns={
                "date": "timestamp",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            })
            
            # Ensure timestamp is datetime and set as index
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp")
            
            # Filter by start/end if needed (IB may return more data)
            if start:
                df = df[df.index >= start]
            if end:
                df = df[df.index <= end]
            
            logger.info(f"Retrieved {len(df)} bars for {symbol} ({df.index.min()} to {df.index.max()})")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}", exc_info=True)
            return pd.DataFrame()

    @async_retry_with_backoff(
        max_retries=3,
        initial_delay=1.0,
        max_delay=5.0,
        exponential_base=2.0,
    )
    async def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """
        Get latest bar/quote for a symbol.
        
        Args:
            symbol: Ticker symbol
            
        Returns:
            Dict with timestamp, open, high, low, close, volume, or None if unavailable
        """
        try:
            # Determine if futures or stock
            is_futures = symbol.upper() in self.futures_symbols
            
            # Submit task to executor
            task_id = str(uuid.uuid4())
            task = GetLatestBarTask(
                task_id=task_id,
                symbol=symbol,
                is_futures=is_futures,
            )
            
            future = self._executor.submit_task(task)
            result = await asyncio.wrap_future(future)
            
            return result
            
        except Exception as e:
            logger.error(f"Error fetching latest bar for {symbol}: {e}")
            return None

    async def get_options_chain(
        self,
        underlying_symbol: str,
        expiration_date: Optional[str] = None,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        strike_proximity_pct: Optional[float] = None,
        min_volume: Optional[int] = None,
        min_open_interest: Optional[int] = None,
        underlying_price: Optional[float] = None,
    ) -> List[Dict]:
        """
        Get options chain for an underlying symbol with filtering.
        
        Args:
            underlying_symbol: Underlying ticker (e.g., 'QQQ', 'SPY')
            expiration_date: Expiration date in YYYYMMDD format (optional)
            min_dte: Minimum days to expiration (optional)
            max_dte: Maximum days to expiration (optional)
            strike_proximity_pct: Filter strikes within X% of current price (optional)
            min_volume: Minimum volume threshold (optional)
            min_open_interest: Minimum open interest threshold (optional)
            underlying_price: Current underlying price for strike filtering (optional)
            
        Returns:
            List of option contracts with strike, expiration, type (call/put)
        """
        try:
            # Get underlying price if not provided
            if underlying_price is None:
                latest_bar = await self.get_latest_bar(underlying_symbol)
                if latest_bar:
                    underlying_price = latest_bar.get("close", 0)
                else:
                    logger.warning(f"Cannot get underlying price for {underlying_symbol}")
                    return []
            
            if underlying_price <= 0:
                logger.warning(f"Invalid underlying price for {underlying_symbol}: {underlying_price}")
                return []
            
            # Submit task to executor
            task_id = str(uuid.uuid4())
            task = GetOptionsChainTask(
                task_id=task_id,
                underlying_symbol=underlying_symbol,
                expiration_date=expiration_date,
                min_dte=min_dte,
                max_dte=max_dte,
                strike_proximity_pct=strike_proximity_pct,
                min_volume=min_volume,
                min_open_interest=min_open_interest,
                underlying_price=underlying_price,
            )
            
            future = self._executor.submit_task(task)
            all_options = await asyncio.wrap_future(future)
            
            logger.info(f"Retrieved {len(all_options)} options for {underlying_symbol}")
            return all_options
            
        except Exception as e:
            logger.error(f"Error fetching options chain for {underlying_symbol}: {e}", exc_info=True)
            return []

    async def get_options_chain_filtered(
        self,
        underlying_symbol: str,
        mode: str = "intraday",  # "intraday" or "swing"
        underlying_price: Optional[float] = None,
    ) -> List[Dict]:
        """
        Get filtered options chain based on trading mode.
        
        Args:
            underlying_symbol: Underlying ticker
            mode: "intraday" (0-7 DTE) or "swing" (7-45 DTE)
            underlying_price: Current underlying price for strike filtering
            
        Returns:
            Filtered list of option contracts
        """
        if mode == "intraday":
            return await self.get_options_chain(
                underlying_symbol=underlying_symbol,
                min_dte=0,
                max_dte=7,
                strike_proximity_pct=0.10,  # Within 10% of current price
                min_volume=100,
                min_open_interest=500,
                underlying_price=underlying_price,
            )
        elif mode == "swing":
            return await self.get_options_chain(
                underlying_symbol=underlying_symbol,
                min_dte=7,
                max_dte=45,
                strike_proximity_pct=0.15,  # Within 15% of current price
                min_volume=50,
                min_open_interest=200,
                underlying_price=underlying_price,
            )
        else:
            logger.warning(f"Unknown mode: {mode}, using default filtering")
            return await self.get_options_chain(
                underlying_symbol=underlying_symbol,
                underlying_price=underlying_price,
            )
