"""
IBKR Provider - Production-ready IBKR data provider.

Uses IB Gateway via ib_insync for live and historical data.
Implements the DataProvider interface for provider-agnostic strategy code.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import pandas as pd
from ib_insync import util

from pearlalgo.utils.logger import logger

from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.data_providers.ibkr_data_executor import (
    GetHistoricalDataTask,
    GetLatestBarTask,
    IBKRExecutor,
)
from pearlalgo.utils.retry import async_retry_with_backoff


# ---------------------------------------------------------------------------
# Connection-level Circuit Breaker
# ---------------------------------------------------------------------------

class ConnectionCircuitBreaker:
    """Tracks IBKR connection failures and opens the circuit after threshold.

    States:
    - **closed** (healthy): requests pass through normally.
    - **open**: too many consecutive failures; requests are short-circuited
      with cached / empty data until ``recovery_seconds`` elapses.
    - **half-open**: one probe request is allowed through to test recovery.

    This protects the system from hammering a dead IBKR Gateway and enables
    graceful degradation (serve cached data, suppress stale-data signals).
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds

        self._consecutive_failures: int = 0
        self._state: str = "closed"  # "closed" | "open" | "half_open"
        self._opened_at: float = 0.0
        self._last_cached_bar: Optional[Dict] = None
        self._last_cached_df: Optional[pd.DataFrame] = None

    # -- public API --

    @property
    def state(self) -> str:
        """Return current circuit state, promoting open -> half_open if due."""
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.recovery_seconds:
                self._state = "half_open"
                logger.info("IBKR connection circuit breaker: open -> half_open (probe allowed)")
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    def record_success(self) -> None:
        if self._consecutive_failures > 0 or self._state != "closed":
            logger.info(
                f"IBKR connection circuit breaker: {self._state} -> closed "
                f"(was {self._consecutive_failures} failures)"
            )
        self._consecutive_failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold and self._state == "closed":
            self._state = "open"
            self._opened_at = time.monotonic()
            logger.warning(
                f"IBKR connection circuit breaker OPENED after "
                f"{self._consecutive_failures} consecutive failures.  "
                f"Entering read-only degraded mode for {self.recovery_seconds}s."
            )
        elif self._state == "half_open":
            # Probe failed — re-open the circuit
            self._state = "open"
            self._opened_at = time.monotonic()
            logger.warning("IBKR connection circuit breaker: half_open probe failed -> re-opened")

    def cache_bar(self, bar: Optional[Dict]) -> None:
        if bar is not None:
            self._last_cached_bar = bar

    def cache_df(self, df: Optional[pd.DataFrame]) -> None:
        if df is not None and not df.empty:
            self._last_cached_df = df

    def get_cached_bar(self) -> Optional[Dict]:
        return self._last_cached_bar

    def get_cached_df(self) -> pd.DataFrame:
        return self._last_cached_df if self._last_cached_df is not None else pd.DataFrame()


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
            connect_on_startup=False,  # Keep process startup fast; connect on demand
        )
        self._executor.start()

        # Connection-level circuit breaker: opens after 5 consecutive
        # failures and serves cached data until a recovery probe succeeds.
        self._circuit_breaker = ConnectionCircuitBreaker(
            failure_threshold=5,
            recovery_seconds=60.0,
        )

        # Entitlements checker (will be initialized after connection)
        self.entitlements_checker: Optional[object] = None
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
            symbol: Underlying symbol (e.g., 'MNQ', 'MES')
            
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

    async def validate_connection(self) -> bool:
        """
        Validate that the provider is connected and ready.
        
        Returns:
            True if connected and ready, False otherwise
        """
        # The executor manages its own connection
        # Submit a connect task to ensure connection
        from pearlalgo.data_providers.ibkr_data_executor import ConnectTask

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
        # Circuit breaker: if open, return cached data immediately
        if self._circuit_breaker.is_open:
            logger.warning(
                f"IBKR circuit breaker OPEN — returning cached historical data for {symbol}"
            )
            return self._circuit_breaker.get_cached_df()

        if not await self.validate_connection():
            self._circuit_breaker.record_failure()
            logger.error("Not connected to IB Gateway")
            return self._circuit_breaker.get_cached_df()

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
            try:
                bars = await asyncio.wrap_future(future)
            except Exception as e:
                error_str = str(e).lower()
                # Check for Error 162: TWS session conflict
                if "162" in str(e) or "tws session" in error_str or "different ip" in error_str:
                    logger.error(
                        f"❌ IBKR Error 162: TWS session conflict detected for {symbol}\n"
                        f"   This error occurs when Trader Workstation (TWS) is connected from a different IP address.\n"
                        f"   You cannot use both TWS and Gateway simultaneously from different IPs.\n"
                        f"   \n"
                        f"   📋 Solution:\n"
                        f"   1. Close TWS or disconnect it completely (check all devices)\n"
                        f"   2. Wait 30-60 seconds for session to clear\n"
                        f"   3. Restart Gateway: ./scripts/gateway/gateway.sh stop && ./scripts/gateway/gateway.sh start\n"
                        f"   4. Restart service\n"
                        f"   \n"
                        f"   Note: This error blocks historical data. Level 1 real-time data may still work.\n"
                        f"   Original error: {e}"
                    )
                    # Don't raise - return empty DataFrame so service can continue
                    # Level 1 real-time data might still work even if historical fails
                    return pd.DataFrame()
                raise
            
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
            self._circuit_breaker.record_success()
            self._circuit_breaker.cache_df(df)
            return df

        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error(f"Error fetching historical data for {symbol}: {e}", exc_info=True)
            return self._circuit_breaker.get_cached_df()

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
        # Circuit breaker: if open, return cached bar immediately
        if self._circuit_breaker.is_open:
            logger.warning(
                f"IBKR circuit breaker OPEN — returning cached latest bar for {symbol}"
            )
            return self._circuit_breaker.get_cached_bar()

        if not await self.validate_connection():
            self._circuit_breaker.record_failure()
            logger.error("Not connected to IB Gateway")
            return self._circuit_breaker.get_cached_bar()

        try:
            # Determine if futures or stock
            is_futures = symbol.upper() in self.futures_symbols

            logger.info(f"Submitting GetLatestBarTask for {symbol} (requesting Level 1 real-time data)")
            
            # Submit task to executor
            task_id = str(uuid.uuid4())
            task = GetLatestBarTask(
                task_id=task_id,
                symbol=symbol,
                is_futures=is_futures,
            )

            future = self._executor.submit_task(task)
            result = await asyncio.wrap_future(future)
            
            if result:
                data_level = result.get('_data_level', 'unknown')
                market_open = result.get('_market_open_assumption')
                market_str = f", market_open={market_open}" if market_open is not None else ""
                logger.info(f"✅ GetLatestBarTask completed for {symbol}: data_level={data_level}{market_str}")
                self._circuit_breaker.record_success()
                self._circuit_breaker.cache_bar(result)
            else:
                logger.warning(f"⚠️  GetLatestBarTask returned None for {symbol} (check docs/MARKET_DATA_SUBSCRIPTION.md if Error 354)")

            return result

        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error(
                f"❌ Error fetching latest bar for {symbol}: {e} "
                f"(if Error 354, see docs/MARKET_DATA_SUBSCRIPTION.md)",
                exc_info=True,
            )
            return self._circuit_breaker.get_cached_bar()
