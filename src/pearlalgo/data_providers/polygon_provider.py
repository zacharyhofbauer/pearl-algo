"""
Polygon.io Data Provider for US equities, futures, and options.

Enhanced with options chains, historical data, and improved error handling.
Uses Polygon.io API for historical and real-time data.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import aiohttp
import pandas as pd

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.data_providers.polygon_config import PolygonConfig
from pearlalgo.utils.retry import CircuitBreaker, async_retry_with_backoff

logger = logging.getLogger(__name__)


def _convert_futures_symbol_to_polygon(symbol: str) -> str:
    """
    Convert futures symbol (e.g., 'ES', 'NQ') to Polygon.io format.
    
    Polygon requires futures symbols in format: ROOT + MONTH_CODE + YEAR_DIGIT
    Example: ES -> ESZ5 (ES + December + 2025)
    
    Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, 
                 N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
    
    Args:
        symbol: Futures symbol (e.g., 'ES', 'NQ')
        
    Returns:
        Polygon-formatted symbol (e.g., 'ESZ5')
    """
    # Common futures symbols
    futures_symbols = {'ES', 'NQ', 'YM', 'RTY', 'MES', 'MNQ', 'MYM', 'M2K', 
                       'CL', 'GC', 'SI', 'HG', 'NG', 'ZC', 'ZS', 'ZW'}
    
    # Check if it's a futures symbol (not already formatted)
    root = symbol.upper().split()[0]  # Get root, remove any suffix
    
    if root not in futures_symbols:
        # Not a futures symbol or already formatted, return as-is
        return symbol
    
    # Get current month and year
    now = datetime.now(timezone.utc)
    current_month = now.month
    current_year = now.year
    
    # Month codes
    month_codes = {
        1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
        7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
    }
    
    month_code = month_codes[current_month]
    year_digit = str(current_year)[-1]  # Last digit of year
    
    # Format: ROOT + MONTH + YEAR
    polygon_symbol = f"{root}{month_code}{year_digit}"
    
    logger.debug(f"Converted futures symbol {symbol} -> {polygon_symbol}")
    return polygon_symbol


class PolygonDataProvider(DataProvider):
    """
    Enhanced Polygon.io data provider for US equities, futures, and options.

    Supports:
    - Historical OHLCV data
    - Real-time quotes
    - Options chains
    - Rate limit handling
    """

    def __init__(
        self, 
        api_key: str, 
        rate_limit_delay: float = 0.25,
        config: Optional[PolygonConfig] = None,
    ):
        """
        Initialize Polygon.io data provider.

        Args:
            api_key: Polygon.io API key
            rate_limit_delay: Delay between API calls in seconds (default 0.25 for 4 calls/sec)
            config: Optional PolygonConfig (if None, creates from api_key)
        """
        if config:
            self.config = config
        else:
            self.config = PolygonConfig(api_key=api_key, rate_limit_delay=rate_limit_delay)
        
        self.api_key = self.config.api_key
        self.base_url = self.config.base_url
        self.rate_limit_delay = self.config.rate_limit_delay
        self.session: Optional[aiohttp.ClientSession] = None
        self._last_request_time: float = 0.0
        
        # Circuit breaker for API calls
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_failure_threshold,
            recovery_timeout=self.config.circuit_breaker_recovery_timeout,
            expected_exception=Exception,
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with timeout."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    async def close(self) -> None:
        """Close aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()

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
        """Async implementation of fetch_historical."""
        if start is None:
            start = datetime.now(timezone.utc).replace(
                year=datetime.now(timezone.utc).year - 1
            )
        if end is None:
            end = datetime.now(timezone.utc)

        # Convert timeframe to Polygon format
        timespan_map = {
            "1m": ("minute", 1),
            "5m": ("minute", 5),
            "15m": ("minute", 15),
            "30m": ("minute", 30),
            "1h": ("hour", 1),
            "1d": ("day", 1),
        }

        if timeframe:
            timespan, multiplier = timespan_map.get(
                timeframe.lower(), ("day", 1)
            )
        else:
            timespan, multiplier = ("day", 1)

        all_results = []
        session = await self._get_session()

        # Polygon API has limits on results per request (~50000 bars)
        # For large date ranges, we need to chunk the requests
        # Free/starter tier may have stricter limits, so use smaller chunks
        # Estimate: 15m bars = ~390 per day
        # Use 30 days chunks to be safe and avoid rate limits
        chunk_days = 30
        current_start = start
        total_days = (end - start).days
        
        logger.debug(f"Fetching {symbol} from {start.date()} to {end.date()} ({total_days} days)")

        while current_start < end:
            # Calculate chunk end date
            chunk_end = min(
                current_start + timedelta(days=chunk_days),
                end
            )
            
            date_from = current_start.strftime("%Y-%m-%d")
            date_to = chunk_end.strftime("%Y-%m-%d")

            # Convert futures symbols to Polygon format
            polygon_symbol = _convert_futures_symbol_to_polygon(symbol)

            url = f"{self.base_url}/v2/aggs/ticker/{polygon_symbol}/range/{multiplier}/{timespan}/{date_from}/{date_to}"
            params = {"adjusted": "true", "sort": "asc", "apikey": self.api_key}

            try:
                await self._rate_limit()
                timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
                async with session.get(url, params=params, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "OK":
                            results = data.get("results", [])
                            if results:
                                chunk_count = len(results)
                                logger.debug(
                                    f"Retrieved {chunk_count} bars for {symbol} "
                                    f"({date_from} to {date_to})"
                                )
                                for result in results:
                                    all_results.append(
                                        {
                                            "timestamp": datetime.fromtimestamp(
                                                result["t"] / 1000, tz=timezone.utc
                                            ),
                                            "open": result["o"],
                                            "high": result["h"],
                                            "low": result["l"],
                                            "close": result["c"],
                                            "volume": result.get("v", 0),
                                        }
                                    )
                            else:
                                logger.debug(
                                    f"No results for {symbol} ({date_from} to {date_to})"
                                )
                    elif response.status == 401:
                        # Only log once per symbol to reduce noise
                        if not hasattr(self, '_unauthorized_logged'):
                            self._unauthorized_logged = set()
                        if symbol not in self._unauthorized_logged:
                            logger.error(
                                f"Polygon API unauthorized - API key is invalid or expired. "
                                f"Please check your POLYGON_API_KEY in .env file. "
                                f"API key invalid or expired for {symbol}. Service will fail without valid API key."
                            )
                            self._unauthorized_logged.add(symbol)
                        return pd.DataFrame()
                    elif response.status == 429:
                        logger.warning(
                            f"Polygon API rate limit exceeded for {symbol} "
                            f"({date_from} to {date_to}). Applying exponential backoff..."
                        )
                        # Exponential backoff for rate limits
                        backoff_delay = min(
                            self.config.initial_backoff * (self.config.backoff_multiplier ** 2),
                            self.config.max_backoff
                        )
                        await asyncio.sleep(backoff_delay)
                        # Retry this chunk
                        continue
                    else:
                        logger.warning(
                            f"Polygon API error for {symbol}: {response.status} "
                            f"({date_from} to {date_to})"
                        )
                        # Continue with next chunk instead of failing completely
                        current_start = chunk_end
                        continue

            except Exception as e:
                logger.error(
                    f"Error fetching data for {symbol} ({date_from} to {date_to}): {e}"
                )
                # Continue with next chunk
                current_start = chunk_end
                continue

            # Move to next chunk
            current_start = chunk_end
            
            # Longer delay between chunks to respect rate limits
            # Free/starter tier needs more time between requests
            if current_start < end:
                await asyncio.sleep(2.0)  # 2 second delay between chunks

        if not all_results:
            logger.warning(f"No data retrieved for {symbol} in date range")
            return pd.DataFrame()

        df = pd.DataFrame(all_results)
        # Remove duplicates (in case of overlapping chunks)
        df = df.drop_duplicates(subset=['timestamp'])
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        
        logger.info(
            f"Retrieved {len(df)} total bars for {symbol} "
            f"({df.index.min().date()} to {df.index.max().date()})"
        )
        return df

    @async_retry_with_backoff(
        max_attempts=5,  # Increased attempts for rate limit scenarios
        initial_delay=2.0,  # Start with 2s delay for rate limits
        max_delay=120.0,  # Allow up to 2 minutes for rate limit recovery
        exponential_base=2.0,
        exceptions=(aiohttp.ClientError, aiohttp.ClientResponseError, asyncio.TimeoutError, Exception),
    )
    async def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """
        Get latest bar for a symbol with retry and circuit breaker.

        Args:
            symbol: Ticker symbol

        Returns:
            Dict with timestamp, open, high, low, close, volume, vwap
        """
        try:
            return await self.circuit_breaker.acall(self._get_latest_bar_impl, symbol)
        except Exception as e:
            logger.error(f"Error fetching latest bar for {symbol}: {e}")
            return None
    
    async def _get_latest_bar_impl(self, symbol: str) -> Optional[Dict]:
        """Internal implementation of get_latest_bar."""
        try:
            session = await self._get_session()
            
            # Convert futures symbols to Polygon format
            polygon_symbol = _convert_futures_symbol_to_polygon(symbol)

            url = f"{self.base_url}/v2/aggs/ticker/{polygon_symbol}/prev"
            params = {"adjusted": "true", "apikey": self.api_key}

            await self._rate_limit()
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            async with session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    if (
                        data.get("status") == "OK"
                        and data.get("resultsCount", 0) > 0
                    ):
                        result = data["results"][0]
                        return {
                            "timestamp": datetime.fromtimestamp(
                                result["t"] / 1000, tz=timezone.utc
                            ),
                            "open": result["o"],
                            "high": result["h"],
                            "low": result["l"],
                            "close": result["c"],
                            "volume": result.get("v", 0),
                            "vwap": result.get("vw"),
                        }
                elif response.status == 401:
                    # Only log once per symbol to reduce noise
                    if not hasattr(self, '_unauthorized_logged_live'):
                        self._unauthorized_logged_live = set()
                    if symbol not in self._unauthorized_logged_live:
                        logger.error(
                            f"Polygon API unauthorized for {symbol} (tried as {polygon_symbol}) - "
                            f"API key is invalid or expired. Please check your POLYGON_API_KEY in .env file. "
                            f"Service will fail without valid API key."
                        )
                        self._unauthorized_logged_live.add(symbol)
                    # Return None - caller should handle the error explicitly
                    return None
                elif response.status == 403:
                    logger.debug(
                        f"Polygon API forbidden for {symbol} (may need paid tier)"
                    )
                elif response.status == 429:
                    # Rate limit hit - raise exception to trigger exponential backoff
                    error_msg = f"Polygon API rate limit for {symbol}"
                    logger.warning(error_msg)
                    # Raise exception to trigger retry with exponential backoff
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=429,
                        message=error_msg,
                    )
                else:
                    logger.debug(
                        f"Polygon API error for {symbol}: {response.status}"
                    )
                    # Raise exception for non-200 responses to trigger retry
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message=f"Polygon API error: {response.status}",
                    )

        except aiohttp.ClientResponseError as e:
            # Re-raise HTTP errors to trigger retry
            logger.error(f"Polygon API HTTP error for {symbol}: {e.status} - {e.message}")
            raise
        except Exception as e:
            logger.error(f"Error fetching Polygon data for {symbol}: {e}")
            raise

        return None

    async def get_options_chain(
        self, underlying_symbol: str, expiration_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Get options chain for an underlying symbol.

        Args:
            underlying_symbol: Underlying ticker (e.g., 'AAPL', 'QQQ')
            expiration_date: Expiration date in YYYY-MM-DD format (optional)

        Returns:
            List of option contracts with strike, expiration, type (call/put)
        """
        try:
            session = await self._get_session()

            # Polygon uses O: prefix for options
            url = f"{self.base_url}/v3/snapshot/options/{underlying_symbol}"
            if expiration_date:
                url += f"/{expiration_date}"

            params = {"apikey": self.api_key}

            await self._rate_limit()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK":
                        results = data.get("results", [])
                        options = []
                        for result in results:
                            options.append(
                                {
                                    "symbol": result.get("details", {}).get(
                                        "ticker"
                                    ),
                                    "strike": result.get("details", {}).get(
                                        "strike_price"
                                    ),
                                    "expiration": result.get("details", {}).get(
                                        "expiration_date"
                                    ),
                                    "option_type": result.get("details", {}).get(
                                        "contract_type"
                                    ),  # 'call' or 'put'
                                    "bid": result.get("last_quote", {}).get(
                                        "bid"
                                    ),
                                    "ask": result.get("last_quote", {}).get(
                                        "ask"
                                    ),
                                    "last_price": result.get("last_trade", {}).get(
                                        "price"
                                    ),
                                    "volume": result.get("session", {}).get(
                                        "volume"
                                    ),
                                    "open_interest": result.get("session", {}).get(
                                        "open_interest"
                                    ),
                                }
                            )
                        return options
                elif response.status == 401:
                    logger.debug(
                        f"Polygon API unauthorized for options on {underlying_symbol}"
                    )
                elif response.status == 403:
                    logger.debug(
                        f"Polygon API forbidden for options on {underlying_symbol} (may need paid tier)"
                    )
                elif response.status == 429:
                    logger.warning(
                        f"Polygon API rate limit for options on {underlying_symbol}"
                    )

        except Exception as e:
            logger.error(
                f"Error fetching options chain for {underlying_symbol}: {e}"
            )

        return []

    async def get_real_time_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get real-time quote (last trade and current bid/ask).

        Args:
            symbol: Ticker symbol

        Returns:
            Dict with last_price, bid, ask, bid_size, ask_size, timestamp
        """
        try:
            session = await self._get_session()

            url = f"{self.base_url}/v2/last/trade/{symbol}"
            params = {"apikey": self.api_key}

            await self._rate_limit()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK":
                        result = data.get("results", {})
                        return {
                            "last_price": result.get("p"),
                            "timestamp": datetime.fromtimestamp(
                                result.get("t", 0) / 1000000, tz=timezone.utc
                            ),
                        }

            # Get quote (bid/ask)
            url = f"{self.base_url}/v2/last/nbbo/{symbol}"
            await self._rate_limit()
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "OK":
                        result = data.get("results", {})
                        return {
                            "bid": result.get("b"),
                            "ask": result.get("a"),
                            "bid_size": result.get("x"),
                            "ask_size": result.get("y"),
                            "timestamp": datetime.fromtimestamp(
                                result.get("t", 0) / 1000000, tz=timezone.utc
                            ),
                        }

        except Exception as e:
            logger.error(f"Error fetching real-time quote for {symbol}: {e}")

        return None
