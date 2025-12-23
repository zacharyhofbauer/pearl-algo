"""
NQ Agent Data Fetcher

Fetches market data from data providers for NQ strategy.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import parse_utc_timestamp

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.utils.data_quality import DataQualityChecker
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.retry import async_retry_with_backoff


class NQAgentDataFetcher:
    """
    Data fetcher for NQ agent.
    
    Fetches market data from data providers for strategy analysis.
    """

    def __init__(
        self,
        data_provider: DataProvider,
        config: Optional[NQIntradayConfig] = None,
    ):
        """
        Initialize data fetcher.
        
        Args:
            data_provider: Data provider instance
            config: Configuration instance (optional)
        """
        self.data_provider = data_provider
        self.config = config or NQIntradayConfig()

        # Load data configuration
        service_config = load_service_config()
        data_settings = service_config.get("data", {})

        # Buffer for historical data
        self._data_buffer: Optional[pd.DataFrame] = None
        self._buffer_size = data_settings.get("buffer_size", 100)
        self._buffer_size_5m = data_settings.get("buffer_size_5m", 50)
        self._buffer_size_15m = data_settings.get("buffer_size_15m", 50)
        self._historical_hours = data_settings.get("historical_hours", 2)
        self._multitimeframe_5m_hours = data_settings.get("multitimeframe_5m_hours", 4)
        self._multitimeframe_15m_hours = data_settings.get("multitimeframe_15m_hours", 12)

        # Base historical fetch caching (default OFF).
        # When enabled, 1m history is refreshed on a TTL rather than every 30s cycle.
        # This reduces IBKR request volume while keeping Level 1 real-time data fresh.
        self._enable_base_cache: bool = bool(data_settings.get("enable_base_cache", False))
        self._base_refresh_seconds: int = int(data_settings.get("base_refresh_seconds", 60) or 60)
        self._base_last_refresh: Optional[datetime] = None
        self._base_cache_hits: int = 0
        self._base_cache_misses: int = 0
        self._base_request_count: int = 0  # Total historical fetch requests

        # MTF caching (default OFF) - reduces repeated 5m/15m historical fetches when scan_interval is fast.
        self._enable_mtf_cache: bool = bool(data_settings.get("enable_mtf_cache", False))
        self._mtf_refresh_seconds_5m: int = int(data_settings.get("mtf_refresh_seconds_5m", 300) or 300)
        self._mtf_refresh_seconds_15m: int = int(data_settings.get("mtf_refresh_seconds_15m", 900) or 900)
        self._mtf_last_refresh_5m: Optional[datetime] = None
        self._mtf_last_refresh_15m: Optional[datetime] = None
        self._mtf_cache_hits_5m: int = 0
        self._mtf_cache_hits_15m: int = 0
        self._mtf_cache_misses_5m: int = 0
        self._mtf_cache_misses_15m: int = 0
        
        # Initialize data quality checker
        stale_threshold_minutes = data_settings.get("stale_data_threshold_minutes", 10)
        self.stale_data_threshold_minutes = stale_threshold_minutes  # Store for use in logging
        self.data_quality_checker = DataQualityChecker(
            stale_data_threshold_minutes=stale_threshold_minutes
        )

        # Multi-timeframe buffers
        self._data_buffer_5m: Optional[pd.DataFrame] = None
        self._data_buffer_15m: Optional[pd.DataFrame] = None
        
        # Store last market data for status updates
        self._last_market_data: Optional[Dict] = None

        logger.info(
            f"NQAgentDataFetcher initialized with provider={type(data_provider).__name__}, "
            f"base_cache_enabled={self._enable_base_cache}, mtf_cache_enabled={self._enable_mtf_cache}"
        )

    @async_retry_with_backoff(
        max_retries=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(ConnectionError, TimeoutError, Exception),
    )
    async def fetch_latest_data(self) -> Dict:
        """
        Fetch latest market data for analysis.
        
        Returns:
            Dictionary with 'df' (DataFrame) and 'latest_bar' (Dict)
        """
        try:
            # Fetch historical data to populate/update buffer
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=self._historical_hours)

            # Check if we can use cached base historical data
            df = await self._fetch_base_historical_data(start, end)

            if df.empty:
                logger.warning(f"No historical data available for {self.config.symbol} (Error 162 may be blocking historical data)")
                # Don't return early - still try to get latest bar (Level 1 real-time data might work)
                # Set df to empty DataFrame but continue to try get_latest_bar
                df = pd.DataFrame()

            # Data quality checks
            # Check for missing values
            if df.isnull().any().any():
                missing = df.isnull().sum()
                missing_dict = {col: missing[col] for col in missing.index if missing[col] > 0}
                logger.warning(f"Data contains missing values: {missing_dict}")

            # Check for stale data using DataQualityChecker
            freshness_check = self.data_quality_checker.check_data_freshness(None, df)
            data_freshness_warning = not freshness_check["is_fresh"]
            if data_freshness_warning:
                age_minutes = freshness_check["age_minutes"]
                logger.warning(f"Data may be stale: latest historical bar is {age_minutes:.1f} minutes old (market may be closed or data subscription issue)")

            # Update buffer if we have data
            if not df.empty:
                # Log data freshness status
                if not data_freshness_warning:
                    logger.debug(f"Data is fresh: {len(df)} bars retrieved for {self.config.symbol}")
                    # Preserve timestamps for downstream charting/HUD context (sessions, key levels, etc).
                    # IBKRProvider returns a DatetimeIndex named "timestamp"; reset_index keeps it as a column.
                    self._data_buffer = df.tail(self._buffer_size).reset_index()
                
                # Log data freshness at INFO level for observability
                if "timestamp" in df.columns:
                    latest_timestamp = df["timestamp"].max()
                    if isinstance(latest_timestamp, pd.Timestamp):
                        age_minutes = (datetime.now(timezone.utc) - latest_timestamp.to_pydatetime().replace(tzinfo=timezone.utc)).total_seconds() / 60
                        logger.info(f"Data freshness: latest_bar_age={age_minutes:.1f} minutes")
                
                # Log buffer status
                buffer_size = len(self._data_buffer) if self._data_buffer is not None else 0
                if self._data_buffer is not None and not self._data_buffer.empty and "timestamp" in self._data_buffer.columns:
                    latest_buffer_time = self._data_buffer["timestamp"].max()
                    logger.info(f"Buffer: {buffer_size} bars, latest_timestamp={latest_buffer_time}")
                else:
                    logger.info(f"Buffer: {buffer_size} bars")
            else:
                # No historical data, but we'll still try real-time Level 1
                logger.info(f"Buffer: 0 bars (historical data unavailable, will try Level 1 real-time data)")

            # Fetch latest bar if method available
            latest_bar = None
            data_source = "unknown"
            if hasattr(self.data_provider, 'get_latest_bar'):
                try:
                    if asyncio.iscoroutinefunction(self.data_provider.get_latest_bar):
                        latest_bar = await self.data_provider.get_latest_bar(self.config.symbol)
                    else:
                        # Run sync method in executor
                        loop = asyncio.get_event_loop()
                        latest_bar = await loop.run_in_executor(
                            None,
                            lambda: self.data_provider.get_latest_bar(self.config.symbol)
                        )
                    
                    if latest_bar:
                        # Determine data source based on timestamp freshness
                        bar_timestamp = latest_bar.get("timestamp")
                        if bar_timestamp:
                            if isinstance(bar_timestamp, str):
                                bar_timestamp = parse_utc_timestamp(bar_timestamp)
                            if isinstance(bar_timestamp, pd.Timestamp):
                                bar_timestamp = bar_timestamp.to_pydatetime()
                            if bar_timestamp.tzinfo is None:
                                bar_timestamp = bar_timestamp.replace(tzinfo=timezone.utc)
                            
                            now = datetime.now(timezone.utc)
                            age_seconds = (now - bar_timestamp).total_seconds()
                            age_minutes = age_seconds / 60
                            
                            # If data is very fresh (< 30 seconds), likely real-time
                            if age_seconds < 30:
                                data_source = "real-time"
                                logger.debug(f"Latest bar for {self.config.symbol} from real-time data (age: {age_seconds:.1f}s)")
                            else:
                                data_source = "historical"
                                logger.info(
                                    f"Latest bar for {self.config.symbol} from historical data "
                                    f"(age: {age_minutes:.1f} minutes, price: ${latest_bar.get('close', 0):.2f})"
                                )
                                
                                # Warn if data is stale
                                if age_minutes > self.stale_data_threshold_minutes:
                                    logger.warning(
                                        f"⚠️  Stale data detected for {self.config.symbol}: "
                                        f"{age_minutes:.1f} minutes old (threshold: {self.stale_data_threshold_minutes} min). "
                                        f"Price may not match current market."
                                    )
                        else:
                            data_source = "provider"
                            logger.debug(f"Latest bar for {self.config.symbol} from provider (timestamp not available)")
                except Exception as e:
                    logger.error(f"❌ Could not fetch latest bar from provider: {e}. Will use historical data fallback.", exc_info=True)
                    data_source = "fallback"

            # If no latest_bar from provider, use last row from historical data (if available)
            if latest_bar is None:
                if not df.empty:
                    data_source = "historical_fallback"
                    logger.info(f"Using historical data fallback for latest bar (real-time subscription may not be available)")
                    latest_row = df.iloc[-1]
                    timestamp = latest_row.name if hasattr(latest_row, 'name') else datetime.now(timezone.utc)
                    if hasattr(timestamp, 'to_pydatetime'):
                        timestamp = timestamp.to_pydatetime()
                    elif isinstance(timestamp, pd.Timestamp):
                        timestamp = timestamp.to_pydatetime()
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)

                    # Extract values from Series/DataFrame row
                    if hasattr(latest_row, 'get'):
                        open_val = latest_row.get("open", 0)
                        high_val = latest_row.get("high", 0)
                        low_val = latest_row.get("low", 0)
                        close_val = latest_row.get("close", 0)
                        volume_val = latest_row.get("volume", 0)
                    else:
                        # DataFrame row access
                        open_val = latest_row["open"] if "open" in latest_row.index else 0
                        high_val = latest_row["high"] if "high" in latest_row.index else 0
                        low_val = latest_row["low"] if "low" in latest_row.index else 0
                        close_val = latest_row["close"] if "close" in latest_row.index else 0
                        volume_val = latest_row["volume"] if "volume" in latest_row.index else 0

                    latest_bar = {
                        "timestamp": timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc),
                        "open": float(open_val),
                        "high": float(high_val),
                        "low": float(low_val),
                        "close": float(close_val),
                        "volume": int(volume_val),
                    }
                    
                    # Check age of historical fallback data
                    if isinstance(timestamp, datetime):
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=timezone.utc)
                        now = datetime.now(timezone.utc)
                        age_seconds = (now - timestamp).total_seconds()
                        age_minutes = age_seconds / 60
                        
                        logger.debug(
                            f"Using last bar from historical data as latest_bar for {self.config.symbol} "
                            f"(age: {age_minutes:.1f} minutes, price: ${close_val:.2f})"
                        )
                        
                        # Warn if historical fallback is stale
                        if age_minutes > self.stale_data_threshold_minutes:
                            logger.warning(
                                f"⚠️  Historical fallback data for {self.config.symbol} is stale: "
                                f"{age_minutes:.1f} minutes old (threshold: {self.stale_data_threshold_minutes} min). "
                                f"Price ${close_val:.2f} may not match current market."
                            )
                else:
                    # No historical data AND no real-time data - this is a problem
                    logger.error(
                        f"❌ CRITICAL: No data available for {self.config.symbol}\n"
                        f"   - Historical data blocked by Error 162 (TWS conflict)\n"
                        f"   - Level 1 real-time data not available (Error 354 or subscription issue)\n"
                        f"   \n"
                        f"   📋 Actions:\n"
                        f"   1. Resolve Error 162: Close any TWS sessions, wait 60s, restart Gateway\n"
                        f"   2. Verify Level 1 subscription is active and paid\n"
                        f"   3. Ensure 'Market Data API Acknowledgement' is signed in Client Portal\n"
                        f"   4. Check if market is open (CME futures: ETH Sun 6PM ET - Fri 5PM ET)"
                    )
                    latest_bar = None

            if latest_bar is None:
                logger.warning(f"No latest bar available for {self.config.symbol}")
                market_data = {"df": pd.DataFrame(), "latest_bar": None}
                self._last_market_data = market_data
                return market_data
            
            # Add data source metadata to latest_bar for tracking
            latest_bar["_data_source"] = data_source

            # Update buffer if we have new data
            if self._data_buffer is None or self._data_buffer.empty:
                # Preserve timestamps for downstream charting/HUD context (sessions, key levels, etc).
                self._data_buffer = df.tail(self._buffer_size).reset_index()
            else:
                # Append latest bar to buffer
                timestamp = latest_bar.get("timestamp")
                if timestamp and isinstance(timestamp, str):
                    timestamp = parse_utc_timestamp(timestamp)

                new_row = pd.DataFrame([{
                    "timestamp": timestamp or datetime.now(timezone.utc),
                    "open": latest_bar.get("open"),
                    "high": latest_bar.get("high"),
                    "low": latest_bar.get("low"),
                    "close": latest_bar.get("close"),
                    "volume": latest_bar.get("volume", 0),
                }])

                self._data_buffer = pd.concat([self._data_buffer, new_row], ignore_index=True)

                # Trim buffer to max size
                if len(self._data_buffer) > self._buffer_size:
                    self._data_buffer = self._data_buffer.tail(self._buffer_size).reset_index(drop=True)

            # Fetch multi-timeframe data (optionally cached)
            df_5m, df_15m = await self._fetch_multitimeframe_data(end)

            # Store market data for status updates
            market_data = {
                "df": self._data_buffer.copy(),
                "latest_bar": latest_bar,
                "df_5m": df_5m,
                "df_15m": df_15m,
            }
            self._last_market_data = market_data

            return market_data

        except Exception as e:
            # Use ErrorHandler for standardized error handling
            ErrorHandler.handle_data_fetch_error(
                e,
                context={"symbol": self.config.symbol, "timeframe": self.config.timeframe},
            )
            # Return empty data instead of raising to allow graceful degradation
            market_data = {
                "df": pd.DataFrame(),
                "latest_bar": None,
                "df_5m": pd.DataFrame(),
                "df_15m": pd.DataFrame(),
            }
            self._last_market_data = market_data
            return market_data

    async def _fetch_base_historical_data(
        self, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """
        Fetch base historical data with optional TTL caching.
        
        When caching is enabled, historical data is only refreshed when the TTL
        expires, reducing IBKR request volume. The latest bar (Level 1 real-time)
        is still fetched every cycle for freshness.
        
        Args:
            start: Start datetime for data fetch
            end: End datetime for data fetch
            
        Returns:
            DataFrame with historical OHLCV data
        """
        now = end
        
        # Check if cache is enabled and valid
        if self._enable_base_cache and self._data_buffer is not None and not self._data_buffer.empty:
            if self._base_last_refresh is not None:
                elapsed = (now - self._base_last_refresh).total_seconds()
                if elapsed < self._base_refresh_seconds:
                    # Cache hit - return existing buffer
                    self._base_cache_hits += 1
                    logger.debug(
                        "Base historical cache hit",
                        extra={
                            "cache_age_seconds": round(elapsed, 1),
                            "ttl_seconds": self._base_refresh_seconds,
                            "hits": self._base_cache_hits,
                            "misses": self._base_cache_misses,
                        },
                    )
                    return self._data_buffer.copy()
        
        # Cache miss (or caching disabled) - fetch fresh data
        self._base_cache_misses += 1
        self._base_request_count += 1
        
        if self._enable_base_cache:
            logger.debug(
                "Base historical cache miss - fetching fresh data",
                extra={
                    "hits": self._base_cache_hits,
                    "misses": self._base_cache_misses,
                    "total_requests": self._base_request_count,
                },
            )
        
        # Use sync method (data providers use sync interface)
        # Run in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: self.data_provider.fetch_historical(
                self.config.symbol,
                start=start,
                end=end,
                timeframe=self.config.timeframe,
            )
        )
        
        # Update cache timestamp on successful fetch
        if not df.empty and self._enable_base_cache:
            self._base_last_refresh = now
        
        return df

    async def _fetch_multitimeframe_data(self, end: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Fetch 5m and 15m timeframe data for multi-timeframe analysis.
        
        Args:
            end: End datetime for data fetch
            
        Returns:
            Tuple of (df_5m, df_15m)
        """
        if self._enable_mtf_cache:
            return await self._fetch_multitimeframe_data_cached(end)
        return await self._fetch_multitimeframe_data_uncached(end)

    async def _fetch_multitimeframe_data_cached(self, end: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch 5m/15m data using TTL caching (default OFF)."""
        now = end

        def _expired(last: Optional[datetime], ttl_s: int) -> bool:
            if last is None:
                return True
            try:
                return (now - last).total_seconds() >= float(ttl_s)
            except Exception:
                return True

        need_5m = _expired(self._mtf_last_refresh_5m, self._mtf_refresh_seconds_5m) or self._data_buffer_5m is None
        need_15m = _expired(self._mtf_last_refresh_15m, self._mtf_refresh_seconds_15m) or self._data_buffer_15m is None

        if not need_5m:
            self._mtf_cache_hits_5m += 1
        else:
            self._mtf_cache_misses_5m += 1
        if not need_15m:
            self._mtf_cache_hits_15m += 1
        else:
            self._mtf_cache_misses_15m += 1

        # If neither needs refresh, return cached copies.
        if (not need_5m) and (not need_15m):
            return (
                self._data_buffer_5m.copy() if self._data_buffer_5m is not None else pd.DataFrame(),
                self._data_buffer_15m.copy() if self._data_buffer_15m is not None else pd.DataFrame(),
            )

        # Otherwise refresh whichever is stale, leaving the other intact.
        df_5m_new = pd.DataFrame()
        df_15m_new = pd.DataFrame()
        if need_5m or need_15m:
            logger.debug(
                "Refreshing MTF cache",
                extra={
                    "need_5m": need_5m,
                    "need_15m": need_15m,
                    "hits_5m": self._mtf_cache_hits_5m,
                    "hits_15m": self._mtf_cache_hits_15m,
                    "misses_5m": self._mtf_cache_misses_5m,
                    "misses_15m": self._mtf_cache_misses_15m,
                },
            )

        # Refresh 5m
        if need_5m:
            df_5m_new, _ = await self._fetch_multitimeframe_data_uncached(end, fetch_5m=True, fetch_15m=False)
            if not df_5m_new.empty:
                self._mtf_last_refresh_5m = now

        # Refresh 15m
        if need_15m:
            _, df_15m_new = await self._fetch_multitimeframe_data_uncached(end, fetch_5m=False, fetch_15m=True)
            if not df_15m_new.empty:
                self._mtf_last_refresh_15m = now

        # Return current cached buffers (updated where refreshed).
        return (
            self._data_buffer_5m.copy() if self._data_buffer_5m is not None else pd.DataFrame(),
            self._data_buffer_15m.copy() if self._data_buffer_15m is not None else pd.DataFrame(),
        )

    async def _fetch_multitimeframe_data_uncached(
        self,
        end: datetime,
        fetch_5m: bool = True,
        fetch_15m: bool = True,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Fetch 5m/15m timeframe data directly from the provider."""
        try:
            # Calculate start time (need more history for higher timeframes)
            start_5m = end - timedelta(hours=self._multitimeframe_5m_hours)
            start_15m = end - timedelta(hours=self._multitimeframe_15m_hours)

            loop = asyncio.get_event_loop()

            # Fetch 5m data
            if fetch_5m:
                df_5m = await loop.run_in_executor(
                    None,
                    lambda: self.data_provider.fetch_historical(
                        self.config.symbol,
                        start=start_5m,
                        end=end,
                        timeframe="5m",
                    )
                )
            else:
                df_5m = pd.DataFrame()

            # Fetch 15m data
            if fetch_15m:
                df_15m = await loop.run_in_executor(
                    None,
                    lambda: self.data_provider.fetch_historical(
                        self.config.symbol,
                        start=start_15m,
                        end=end,
                        timeframe="15m",
                    )
                )
            else:
                df_15m = pd.DataFrame()

            # Update buffers
            if not df_5m.empty:
                # Preserve timestamp for downstream charting/overlays and better operator debugging.
                self._data_buffer_5m = df_5m.tail(self._buffer_size_5m).reset_index()
            if not df_15m.empty:
                # Preserve timestamp for downstream charting/overlays and better operator debugging.
                self._data_buffer_15m = df_15m.tail(self._buffer_size_15m).reset_index()

            return (
                self._data_buffer_5m.copy() if self._data_buffer_5m is not None else pd.DataFrame(),
                self._data_buffer_15m.copy() if self._data_buffer_15m is not None else pd.DataFrame(),
            )

        except Exception as e:
            logger.warning(f"Error fetching multi-timeframe data: {e}")
            return (pd.DataFrame(), pd.DataFrame())

    def get_buffer_size(self) -> int:
        """Get current buffer size."""
        if self._data_buffer is None:
            return 0
        return len(self._data_buffer)

    def get_cache_stats(self) -> Dict:
        """
        Get cache statistics for observability/dashboard.
        
        Returns:
            Dictionary with cache hit/miss counts and hit rates.
        """
        # Base historical cache stats
        base_total = self._base_cache_hits + self._base_cache_misses
        base_hit_rate = (
            self._base_cache_hits / base_total if base_total > 0 else 0.0
        )
        
        # MTF cache stats (5m)
        mtf_5m_total = self._mtf_cache_hits_5m + self._mtf_cache_misses_5m
        mtf_5m_hit_rate = (
            self._mtf_cache_hits_5m / mtf_5m_total if mtf_5m_total > 0 else 0.0
        )
        
        # MTF cache stats (15m)
        mtf_15m_total = self._mtf_cache_hits_15m + self._mtf_cache_misses_15m
        mtf_15m_hit_rate = (
            self._mtf_cache_hits_15m / mtf_15m_total if mtf_15m_total > 0 else 0.0
        )
        
        return {
            "base_cache_enabled": self._enable_base_cache,
            "base_ttl_seconds": self._base_refresh_seconds,
            "base_hits": self._base_cache_hits,
            "base_misses": self._base_cache_misses,
            "base_hit_rate": round(base_hit_rate, 3),
            "base_request_count": self._base_request_count,
            "mtf_cache_enabled": self._enable_mtf_cache,
            "mtf_5m_ttl_seconds": self._mtf_refresh_seconds_5m,
            "mtf_5m_hits": self._mtf_cache_hits_5m,
            "mtf_5m_misses": self._mtf_cache_misses_5m,
            "mtf_5m_hit_rate": round(mtf_5m_hit_rate, 3),
            "mtf_15m_ttl_seconds": self._mtf_refresh_seconds_15m,
            "mtf_15m_hits": self._mtf_cache_hits_15m,
            "mtf_15m_misses": self._mtf_cache_misses_15m,
            "mtf_15m_hit_rate": round(mtf_15m_hit_rate, 3),
        }
