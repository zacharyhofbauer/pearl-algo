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

        logger.info(f"NQAgentDataFetcher initialized with provider={type(data_provider).__name__}")

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

            # Use sync method (data providers use sync interface)
            # Run in executor to avoid blocking the event loop
            import asyncio
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
                    self._data_buffer = df.tail(self._buffer_size).reset_index(drop=True)
                
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
                self._data_buffer = df.tail(self._buffer_size).reset_index(drop=True)
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

            # Fetch multi-timeframe data
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

    async def _fetch_multitimeframe_data(self, end: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Fetch 5m and 15m timeframe data for multi-timeframe analysis.
        
        Args:
            end: End datetime for data fetch
            
        Returns:
            Tuple of (df_5m, df_15m)
        """
        try:
            # Calculate start time (need more history for higher timeframes)
            start_5m = end - timedelta(hours=self._multitimeframe_5m_hours)
            start_15m = end - timedelta(hours=self._multitimeframe_15m_hours)

            loop = asyncio.get_event_loop()

            # Fetch 5m data
            df_5m = await loop.run_in_executor(
                None,
                lambda: self.data_provider.fetch_historical(
                    self.config.symbol,
                    start=start_5m,
                    end=end,
                    timeframe="5m",
                )
            )

            # Fetch 15m data
            df_15m = await loop.run_in_executor(
                None,
                lambda: self.data_provider.fetch_historical(
                    self.config.symbol,
                    start=start_15m,
                    end=end,
                    timeframe="15m",
                )
            )

            # Update buffers
            if not df_5m.empty:
                self._data_buffer_5m = df_5m.tail(self._buffer_size_5m).reset_index(drop=True)
            if not df_15m.empty:
                self._data_buffer_15m = df_15m.tail(self._buffer_size_15m).reset_index(drop=True)

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
