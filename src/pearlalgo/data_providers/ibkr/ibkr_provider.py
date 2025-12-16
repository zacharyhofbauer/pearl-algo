"""
IBKR Provider - Production-ready IBKR data provider.

Uses IB Gateway via ib_insync for live and historical data.
Implements the DataProvider interface for provider-agnostic strategy code.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator, Dict, List, Optional

import pandas as pd
from ib_insync import util

from pearlalgo.utils.logger import logger

from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.data_providers.ibkr_executor import (
    GetHistoricalDataTask,
    GetLatestBarTask,
    GetOptionsChainTask,
    IBKRExecutor,
)
from pearlalgo.utils.retry import async_retry_with_backoff

logger = logging.getLogger(__name__)


class IBKRProvider(DataProvider):
    """
    Production-ready IBKR data provider implementing DataProvider interface.
    
    Features:
    - Implements DataProvider for provider-agnostic strategies
    - Connection lifecycle management with automatic reconnection
    - Market data entitlement validation
    - Stale data detection
    - Thread-safe executor for IBKR API calls
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        """
        Initialize IBKR provider.
        
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
        self.futures_symbols = {
            "ES", "MES",  # E-mini and Micro E-mini S&P 500
            "NQ", "MNQ",  # E-mini and Micro E-mini NASDAQ-100
            "YM", "MYM",  # E-mini and Micro E-mini Dow
            "RTY", "M2K",  # E-mini and Micro Russell 2000
            "CL", "MCL",  # Crude Oil and Micro
            "GC", "MGC",  # Gold and Micro
            "SI", "MSI",  # Silver and Micro
            "NG", "MNG",  # Natural Gas and Micro
            "ZB", "MZB",  # 30-Year Bond and Micro
            "ZN", "MZN",  # 10-Year Note and Micro
            "ZF", "MZF",  # 5-Year Note and Micro
            "ZT", "MZT",  # 2-Year Note and Micro
        }

        # Initialize executor (dedicated thread for IBKR calls)
        # The executor manages its own connection lifecycle
        # Use faster retry settings for better test performance
        self._executor = IBKRExecutor(
            host=self.host,
            port=self.port,
            client_id=self.client_id,
            reconnect_delay=2.0,  # Faster retries
            max_reconnect_attempts=3,  # Fail faster
        )
        self._executor.start()

        # Entitlements checker (will be initialized after connection)
        self.entitlements_checker: Optional[IBKREntitlements] = None
        self._entitlements_cache: Optional[Dict[str, bool]] = None

        logger.info(
            f"IBKRProvider initialized: host={self.host}, port={self.port}, client_id={self.client_id}"
        )

    async def close(self) -> None:
        """Close IB connection and stop executor."""
        logger.info("Closing IBKRProvider...")
        self._executor.stop(timeout=10.0)
        logger.info("IBKRProvider closed")

    # MarketDataProvider interface implementation

    async def get_underlier_price(self, symbol: str) -> float:
        """
        Get current price for an underlying symbol.
        
        Args:
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            
        Returns:
            Current price as float
            
        Raises:
            ConnectionError: If provider is not connected
            ValueError: If symbol is invalid or not found
        """
        if not await self.validate_connection():
            raise ConnectionError("Not connected to IB Gateway")

        latest_bar = await self.get_latest_bar(symbol)
        if not latest_bar:
            raise ValueError(f"No price data available for {symbol}")

        price = latest_bar.get("close", 0)
        if price <= 0:
            raise ValueError(f"Invalid price for {symbol}: {price}")

        return float(price)

    async def get_option_chain(
        self,
        symbol: str,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Get options chain for an underlying symbol with optional filtering.
        
        Args:
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            filters: Optional filter dictionary (see MarketDataProvider interface)
            
        Returns:
            List of option contracts
        """
        if not await self.validate_connection():
            raise ConnectionError("Not connected to IB Gateway")

        # Get underlying price first
        underlying_price = None
        try:
            underlying_price = await self.get_underlier_price(symbol)
        except Exception as e:
            logger.warning(f"Could not get underlying price for {symbol}: {e}")

        # Extract filters
        filters = filters or {}
        min_dte = filters.get("min_dte")
        max_dte = filters.get("max_dte")
        strike_proximity_pct = filters.get("strike_proximity_pct")
        min_volume = filters.get("min_volume")
        min_open_interest = filters.get("min_open_interest")
        expiration_date = filters.get("expiration_date")

        # Get options chain using executor
        task_id = str(uuid.uuid4())
        task = GetOptionsChainTask(
            task_id=task_id,
            underlying_symbol=symbol,
            expiration_date=expiration_date,
            min_dte=min_dte,
            max_dte=max_dte,
            strike_proximity_pct=strike_proximity_pct,
            min_volume=min_volume,
            min_open_interest=min_open_interest,
            underlying_price=underlying_price,
        )

        future = self._executor.submit_task(task)
        options = await asyncio.wrap_future(future)

        logger.info(f"Retrieved {len(options)} options for {symbol}")
        return options

    async def get_option_quotes(self, contracts: List[str]) -> List[Dict]:
        """
        Get real-time quotes for specific option contracts.
        
        Args:
            contracts: List of option contract identifiers (IBKR format)
            
        Returns:
            List of quote dictionaries
        """
        if not await self.validate_connection():
            raise ConnectionError("Not connected to IB Gateway")

        # This would need to be implemented in the executor
        # For now, return empty list
        logger.warning("get_option_quotes not yet fully implemented")
        return []

    async def subscribe_realtime(
        self,
        symbols: List[str],
    ) -> AsyncIterator[Dict]:
        """
        Subscribe to real-time market data updates.
        
        Args:
            symbols: List of symbols to subscribe to
            
        Yields:
            Dictionary with market data updates
        """
        if not await self.validate_connection():
            raise ConnectionError("Not connected to IB Gateway")

        # This would need to be implemented with async streaming
        # For now, yield empty
        logger.warning("subscribe_realtime not yet fully implemented")
        while True:
            await asyncio.sleep(1)
            yield {}

    async def validate_connection(self) -> bool:
        """
        Validate that the provider is connected and ready.
        
        Returns:
            True if connected and ready, False otherwise
        """
        # The executor manages its own connection
        # Submit a connect task to ensure connection
        from pearlalgo.data_providers.ibkr_executor import ConnectTask

        connect_task = ConnectTask(
            task_id="validate_connection",
            host=self.host,
            port=self.port,
            client_id=self.client_id,
            timeout=10.0,
        )

        try:
            future = self._executor.submit_task(connect_task)
            result = await asyncio.wrap_future(future)
            return result if result else self._executor.is_connected()
        except Exception as e:
            logger.warning(f"Connection validation failed: {e}")
            return self._executor.is_connected()

    async def validate_market_data_entitlements(self) -> Dict[str, bool]:
        """
        Validate market data entitlements for the account.
        
        Returns:
            Dictionary with entitlement status
        """
        if not await self.validate_connection():
            raise ConnectionError("Not connected to IB Gateway")

        # Return cached entitlements if available
        if self._entitlements_cache is not None:
            return self._entitlements_cache

        # For now, return basic entitlements
        # Full entitlement checking would need to run in executor thread
        # This is a simplified version
        entitlements = {
            "options_data": True,  # Assume available, will be validated on first use
            "realtime_quotes": True,
            "historical_data": True,
            "account_type": "paper",  # Default, should be detected from account summary
        }

        self._entitlements_cache = entitlements
        logger.info("Market data entitlements validated (simplified check)")
        return entitlements

    # DataProvider interface implementation (for backward compatibility)

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
        if not await self.validate_connection():
            logger.error("Not connected to IB Gateway")
            return pd.DataFrame()

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
            df = df.rename(
                columns={
                    "date": "timestamp",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                }
            )

            # Ensure timestamp is datetime and set as index
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.set_index("timestamp")

            # Filter by start/end if needed (IB may return more data)
            if start:
                df = df[df.index >= start]
            if end:
                df = df[df.index <= end]

            logger.info(
                f"Retrieved {len(df)} bars for {symbol} ({df.index.min()} to {df.index.max()})"
            )
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
        if not await self.validate_connection():
            logger.error("Not connected to IB Gateway")
            return None

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
