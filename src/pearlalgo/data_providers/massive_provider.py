"""
Massive.com Data Provider for US equities, futures, and options.

Enhanced with options chains, historical data, and improved error handling.
Uses Massive.com API for historical and real-time data.
Uses official massive Python client for API access.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from massive import RESTClient
except ImportError:
    RESTClient = None
    logger.warning("massive package not installed. Install with: pip install massive")

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.data_providers.massive_config import MassiveConfig
from pearlalgo.utils.retry import CircuitBreaker, async_retry_with_backoff

logger = logging.getLogger(__name__)


class TokenBucket:
    """Token bucket rate limiter."""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket.
        
        Args:
            capacity: Maximum tokens (requests)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens, waiting if necessary."""
        async with self._lock:
            now = time.time()
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            
            # Wait if not enough tokens
            if self.tokens < tokens:
                wait_time = (tokens - self.tokens) / self.refill_rate
                await asyncio.sleep(wait_time)
                # Refill again after wait
                now = time.time()
                elapsed = now - self.last_refill
                self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
                self.last_refill = now
            
            self.tokens -= tokens


class MassiveDataProvider(DataProvider):
    """
    Enhanced Massive.com data provider for US equities, futures, and options.

    Supports:
    - Historical OHLCV data
    - Real-time quotes
    - Options chains
    - Futures contract discovery
    - Rate limit handling with token bucket
    """

    def __init__(
        self, 
        api_key: str, 
        rate_limit_delay: float = 0.25,
        config: Optional[MassiveConfig] = None,
    ):
        """
        Initialize Massive.com data provider.

        Args:
            api_key: Massive.com API key
            rate_limit_delay: Delay between API calls in seconds (default 0.25 for 4 calls/sec)
            config: Optional MassiveConfig (if None, creates from api_key)
        """
        if RESTClient is None:
            raise ImportError(
                "massive package is required. Install with: pip install massive"
            )
        
        if config:
            self.config = config
        else:
            self.config = MassiveConfig(api_key=api_key, rate_limit_delay=rate_limit_delay)
        
        self.api_key = self.config.api_key
        self.base_url = self.config.base_url
        self.rate_limit_delay = self.config.rate_limit_delay
        
        # Initialize Massive REST client
        self.client = RESTClient(api_key=self.api_key)
        
        # Token bucket rate limiter (200 requests per minute = ~3.33 per second)
        self.rate_limiter = TokenBucket(
            capacity=10,  # Burst capacity
            refill_rate=self.config.requests_per_minute / 60.0  # Tokens per second
        )
        
        # Simple rate limiter for backward compatibility
        self._last_request_time: float = 0.0
        
        # Circuit breaker for API calls
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_failure_threshold,
            recovery_timeout=self.config.circuit_breaker_recovery_timeout,
            expected_exception=Exception,
        )
        
        # Contract cache for futures
        self._contract_cache: Dict[str, tuple[str, datetime]] = {}  # symbol -> (contract_code, expiration)
        self._contract_cache_ttl = timedelta(hours=4)

    async def _rate_limit(self) -> None:
        """Enforce rate limiting using token bucket."""
        await self.rate_limiter.acquire(1)
        # Also maintain simple delay for backward compatibility
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    async def close(self) -> None:
        """Close client connections."""
        # RESTClient doesn't have explicit close, but we can clear cache
        self._contract_cache.clear()

    async def _resolve_contract(self, symbol: str) -> str:
        """
        Resolve base symbol (ES, NQ) to active contract (ESU5, NQU5).
        
        Args:
            symbol: Base futures symbol (e.g., 'ES', 'NQ')
            
        Returns:
            Active contract code (e.g., 'ESU5', 'NQU5')
        """
        # Check cache first
        if symbol in self._contract_cache:
            contract_code, expiration = self._contract_cache[symbol]
            if datetime.now(timezone.utc) < expiration:
                return contract_code
        
        # Query Massive API for active contracts
        try:
            await self._rate_limit()
            
            # Use futures contracts endpoint
            # Note: The exact API method may vary - this is based on the plan's specification
            # GET /futures/vX/contracts?product_code=ES&active=true
            response = self.client.futures.get_contracts(
                product_code=symbol,
                active=True
            )
            
            if response and response.get("status") == "OK":
                results = response.get("results", [])
                if results:
                    # Find contract with nearest expiration
                    contracts = sorted(
                        results,
                        key=lambda x: x.get("expiration_date", ""),
                    )
                    active_contract = contracts[0]
                    contract_code = active_contract.get("ticker", symbol)
                    expiration_str = active_contract.get("expiration_date", "")
                    
                    # Parse expiration and cache
                    try:
                        expiration_date = datetime.fromisoformat(expiration_str.replace("Z", "+00:00"))
                        # Cache until 4 hours before expiration
                        cache_expiration = expiration_date - timedelta(hours=4)
                        self._contract_cache[symbol] = (contract_code, cache_expiration)
                        logger.debug(f"Resolved {symbol} to contract {contract_code}")
                        return contract_code
                    except Exception as e:
                        logger.warning(f"Could not parse expiration for {contract_code}: {e}")
                        return contract_code
            
            # Fallback: return symbol as-is if contract discovery fails
            logger.warning(f"Could not resolve contract for {symbol}, using symbol as-is")
            return symbol
            
        except Exception as e:
            logger.warning(f"Error resolving contract for {symbol}: {e}, using symbol as-is")
            return symbol

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

        # Convert timeframe to Massive format
        resolution_map = {
            "1m": "1min",
            "5m": "5mins",
            "15m": "15mins",
            "30m": "30mins",
            "1h": "1hour",
            "1d": "1day",
        }
        
        resolution = resolution_map.get(timeframe.lower() if timeframe else "1d", "1day")

        # For futures, resolve to active contract
        if symbol in ["ES", "NQ", "MES", "MNQ", "YM", "RTY"]:
            symbol = await self._resolve_contract(symbol)

        all_results = []
        
        # Massive API uses futures/vX/aggs/{ticker} for futures
        # For stocks, use v2/aggs/ticker/{ticker}/range
        is_futures = any(symbol.startswith(prefix) for prefix in ["ES", "NQ", "MES", "MNQ", "YM", "RTY"])
        
        # Chunk requests for large date ranges
        chunk_days = 30
        current_start = start
        total_days = (end - start).days
        
        logger.debug(f"Fetching {symbol} from {start.date()} to {end.date()} ({total_days} days)")

        while current_start < end:
            chunk_end = min(current_start + timedelta(days=chunk_days), end)
            
            try:
                await self._rate_limit()
                
                if is_futures:
                    # Use futures aggregates endpoint
                    response = self.client.futures.get_aggregates(
                        ticker=symbol,
                        resolution=resolution,
                        window_start=current_start.isoformat(),
                        limit=50000  # Max limit
                    )
                else:
                    # Use stocks aggregates endpoint
                    response = self.client.stocks.get_aggregates(
                        ticker=symbol,
                        resolution=resolution,
                        window_start=current_start.isoformat(),
                        limit=50000
                    )
                
                if response and response.get("status") == "OK":
                    results = response.get("results", [])
                    if results:
                        chunk_count = len(results)
                        logger.debug(
                            f"Retrieved {chunk_count} bars for {symbol} "
                            f"({current_start.date()} to {chunk_end.date()})"
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
                    
                    # Handle pagination via next_url
                    next_url = response.get("next_url")
                    if next_url:
                        logger.debug(f"More data available via next_url for {symbol}")
                        # For simplicity, we'll fetch in chunks - could implement full pagination
                
            except Exception as e:
                logger.error(
                    f"Error fetching data for {symbol} ({current_start.date()} to {chunk_end.date()}): {e}"
                )
                # Continue with next chunk
                current_start = chunk_end
                continue

            # Move to next chunk
            current_start = chunk_end
            
            # Delay between chunks
            if current_start < end:
                await asyncio.sleep(2.0)

        if not all_results:
            logger.warning(
                f"No data retrieved for {symbol} in date range. "
                f"⚠️  Massive.com FREE TIER may not include futures data. "
                f"Futures data requires a paid subscription."
            )
            return pd.DataFrame()

        df = pd.DataFrame(all_results)
        df = df.drop_duplicates(subset=['timestamp'])
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        
        logger.info(
            f"Retrieved {len(df)} total bars for {symbol} "
            f"({df.index.min().date()} to {df.index.max().date()})"
        )
        return df

    @async_retry_with_backoff(
        max_attempts=5,
        initial_delay=2.0,
        max_delay=120.0,
        exponential_base=2.0,
        exceptions=(Exception,),
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
            # For futures, resolve to active contract
            original_symbol = symbol
            if symbol in ["ES", "NQ", "MES", "MNQ", "YM", "RTY"]:
                symbol = await self._resolve_contract(symbol)

            await self._rate_limit()
            
            # Use appropriate endpoint based on symbol type
            is_futures = any(symbol.startswith(prefix) for prefix in ["ES", "NQ", "MES", "MNQ", "YM", "RTY"])
            
            if is_futures:
                # Get latest futures aggregates
                response = self.client.futures.get_aggregates(
                    ticker=symbol,
                    resolution="1min",
                    limit=1
                )
            else:
                # Get latest stock aggregates
                response = self.client.stocks.get_aggregates(
                    ticker=symbol,
                    resolution="1min",
                    limit=1
                )
            
            if response and response.get("status") == "OK":
                results = response.get("results", [])
                if results and len(results) > 0:
                    result = results[-1]  # Get most recent
                    price = result.get("c", 0)
                    
                    # Validate price for futures
                    if original_symbol in ["ES", "MES"] and not (3000 <= price <= 7000):
                        logger.warning(
                            f"Massive returned invalid price ${price:.2f} for {original_symbol} "
                            f"(expected $3000-7000). Rejecting - likely free tier limitation."
                        )
                        return None
                    elif original_symbol in ["NQ", "MNQ"] and not (10000 <= price <= 25000):
                        logger.warning(
                            f"Massive returned invalid price ${price:.2f} for {original_symbol} "
                            f"(expected $10000-25000). Rejecting - likely free tier limitation."
                        )
                        return None
                    
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
            
            return None

        except Exception as e:
            logger.error(f"Error fetching Massive data for {symbol}: {e}")
            raise

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
            await self._rate_limit()
            
            # Use Massive options snapshot endpoint
            response = self.client.options.get_snapshot(
                underlying=underlying_symbol,
                expiration_date=expiration_date
            )
            
            if response and response.get("status") == "OK":
                results = response.get("results", [])
                options = []
                for result in results:
                    options.append(
                        {
                            "symbol": result.get("details", {}).get("ticker"),
                            "strike": result.get("details", {}).get("strike_price"),
                            "expiration": result.get("details", {}).get("expiration_date"),
                            "option_type": result.get("details", {}).get("contract_type"),
                            "bid": result.get("last_quote", {}).get("bid"),
                            "ask": result.get("last_quote", {}).get("ask"),
                            "last_price": result.get("last_trade", {}).get("price"),
                            "volume": result.get("session", {}).get("volume"),
                            "open_interest": result.get("session", {}).get("open_interest"),
                        }
                    )
                return options

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
            await self._rate_limit()
            
            # Use Massive last trade endpoint
            response = self.client.stocks.get_last_trade(ticker=symbol)
            
            if response and response.get("status") == "OK":
                result = response.get("results", {})
                return {
                    "last_price": result.get("p"),
                    "timestamp": datetime.fromtimestamp(
                        result.get("t", 0) / 1000000, tz=timezone.utc
                    ),
                }

            # Get quote (bid/ask)
            response = self.client.stocks.get_last_quote(ticker=symbol)
            if response and response.get("status") == "OK":
                result = response.get("results", {})
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
