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
            
            # Use list_futures_contracts method (returns iterator, sync call)
            # GET /futures/vX/contracts?product_code=ES&active=true
            contracts = []
            try:
                # Run sync call in executor to avoid blocking
                loop = asyncio.get_event_loop()
                contract_iter = await loop.run_in_executor(
                    None,
                    lambda: self.client.list_futures_contracts(
                        product_code=symbol,
                        active="true",  # String "true" not boolean
                        limit=100,
                        sort="expiration_date"
                    )
                )
                # Iterate over results
                for contract in contract_iter:
                    contracts.append(contract)
                    # Only need first few, break after getting some
                    if len(contracts) >= 10:
                        break
            except Exception as e:
                logger.warning(f"Error iterating contracts for {symbol}: {e}")
            
            if contracts:
                # Find contract with nearest expiration (first one since sorted)
                active_contract = contracts[0]
                # Contract object has attributes, not dict keys
                contract_code = getattr(active_contract, 'ticker', symbol)
                expiration_str = getattr(active_contract, 'expiration_date', None)
                
                # Parse expiration and cache
                if expiration_str:
                    try:
                        if isinstance(expiration_str, str):
                            expiration_date = datetime.fromisoformat(expiration_str.replace("Z", "+00:00"))
                        else:
                            expiration_date = expiration_str
                        # Cache until 4 hours before expiration
                        cache_expiration = expiration_date - timedelta(hours=4)
                        self._contract_cache[symbol] = (contract_code, cache_expiration)
                        logger.debug(f"Resolved {symbol} to contract {contract_code}")
                        return contract_code
                    except Exception as e:
                        logger.warning(f"Could not parse expiration for {contract_code}: {e}")
                        return contract_code
                else:
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
                    # Use list_futures_aggregates (returns iterator, sync call)
                    bars = []
                    try:
                        # Run sync call in executor
                        loop = asyncio.get_event_loop()
                        bars_iter = await loop.run_in_executor(
                            None,
                            lambda: self.client.list_futures_aggregates(
                                ticker=symbol,
                                resolution=resolution,
                                window_start=current_start.isoformat(),
                                limit=50000
                            )
                        )
                        for bar in bars_iter:
                            bars.append(bar)
                            # Limit to reasonable size
                            if len(bars) >= 50000:
                                break
                        
                        if bars:
                            chunk_count = len(bars)
                            logger.debug(
                                f"Retrieved {chunk_count} bars for {symbol} "
                                f"({current_start.date()} to {chunk_end.date()})"
                            )
                            for bar in bars:
                                # Bar is an object with attributes
                                timestamp_ms = getattr(bar, 'timestamp', None) or getattr(bar, 't', 0)
                                all_results.append(
                                    {
                                        "timestamp": datetime.fromtimestamp(
                                            timestamp_ms / 1000, tz=timezone.utc
                                        ),
                                        "open": getattr(bar, 'open', 0) or getattr(bar, 'o', 0),
                                        "high": getattr(bar, 'high', 0) or getattr(bar, 'h', 0),
                                        "low": getattr(bar, 'low', 0) or getattr(bar, 'l', 0),
                                        "close": getattr(bar, 'close', 0) or getattr(bar, 'c', 0),
                                        "volume": getattr(bar, 'volume', 0) or getattr(bar, 'v', 0),
                                    }
                                )
                    except Exception as e:
                        logger.warning(f"Error fetching futures aggregates for {symbol}: {e}")
                else:
                    # Use list_aggs for stocks (returns iterator, sync call)
                    bars = []
                    try:
                        # Convert resolution to multiplier and timespan
                        resolution_parts = resolution.replace("min", "").replace("s", "").replace("hour", "h")
                        if "min" in resolution:
                            multiplier = int(resolution_parts.replace("min", ""))
                            timespan = "minute"
                        elif "hour" in resolution or "h" in resolution:
                            multiplier = int(resolution_parts.replace("h", "").replace("hour", ""))
                            timespan = "hour"
                        else:
                            multiplier = 1
                            timespan = "day"
                        
                        # Run sync call in executor
                        loop = asyncio.get_event_loop()
                        bars_iter = await loop.run_in_executor(
                            None,
                            lambda: self.client.list_aggs(
                                ticker=symbol,
                                multiplier=multiplier,
                                timespan=timespan,
                                from_=current_start.strftime("%Y-%m-%d"),
                                to=chunk_end.strftime("%Y-%m-%d"),
                                limit=50000
                            )
                        )
                        for bar in bars_iter:
                            bars.append(bar)
                            if len(bars) >= 50000:
                                break
                        
                        if bars:
                            chunk_count = len(bars)
                            logger.debug(
                                f"Retrieved {chunk_count} bars for {symbol} "
                                f"({current_start.date()} to {chunk_end.date()})"
                            )
                            for bar in bars:
                                timestamp_ms = getattr(bar, 'timestamp', None) or getattr(bar, 't', 0)
                                all_results.append(
                                    {
                                        "timestamp": datetime.fromtimestamp(
                                            timestamp_ms / 1000, tz=timezone.utc
                                        ),
                                        "open": getattr(bar, 'open', 0) or getattr(bar, 'o', 0),
                                        "high": getattr(bar, 'high', 0) or getattr(bar, 'h', 0),
                                        "low": getattr(bar, 'low', 0) or getattr(bar, 'l', 0),
                                        "close": getattr(bar, 'close', 0) or getattr(bar, 'c', 0),
                                        "volume": getattr(bar, 'volume', 0) or getattr(bar, 'v', 0),
                                    }
                                )
                    except Exception as e:
                        logger.warning(f"Error fetching stock aggregates for {symbol}: {e}")
                
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
                # Get latest futures aggregates (returns iterator, sync call)
                bars = []
                try:
                    # Run sync call in executor
                    loop = asyncio.get_event_loop()
                    bars_iter = await loop.run_in_executor(
                        None,
                        lambda: self.client.list_futures_aggregates(
                            ticker=symbol,
                            resolution="1min",
                            limit=1
                        )
                    )
                    for bar in bars_iter:
                        bars.append(bar)
                        break  # Only need one
                    
                    if bars:
                        bar = bars[0]
                        price = getattr(bar, 'close', 0) or getattr(bar, 'c', 0)
                        
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
                        
                        timestamp_ms = getattr(bar, 'timestamp', None) or getattr(bar, 't', 0)
                        return {
                            "timestamp": datetime.fromtimestamp(
                                timestamp_ms / 1000, tz=timezone.utc
                            ),
                            "open": getattr(bar, 'open', 0) or getattr(bar, 'o', 0),
                            "high": getattr(bar, 'high', 0) or getattr(bar, 'h', 0),
                            "low": getattr(bar, 'low', 0) or getattr(bar, 'l', 0),
                            "close": getattr(bar, 'close', 0) or getattr(bar, 'c', 0),
                            "volume": getattr(bar, 'volume', 0) or getattr(bar, 'v', 0),
                            "vwap": getattr(bar, 'vwap', None) or getattr(bar, 'vw', None),
                        }
                except Exception as e:
                    logger.warning(f"Error fetching latest futures bar for {symbol}: {e}")
            else:
                # Get latest stock aggregates using get_previous_close_agg or list_aggs
                try:
                    # Try get_previous_close_agg first (simpler for latest, sync call)
                    loop = asyncio.get_event_loop()
                    bar = await loop.run_in_executor(
                        None,
                        lambda: self.client.get_previous_close_agg(ticker=symbol)
                    )
                    if bar:
                        price = getattr(bar, 'close', 0) or getattr(bar, 'c', 0)
                        timestamp_ms = getattr(bar, 'timestamp', None) or getattr(bar, 't', 0)
                        return {
                            "timestamp": datetime.fromtimestamp(
                                timestamp_ms / 1000, tz=timezone.utc
                            ),
                            "open": getattr(bar, 'open', 0) or getattr(bar, 'o', 0),
                            "high": getattr(bar, 'high', 0) or getattr(bar, 'h', 0),
                            "low": getattr(bar, 'low', 0) or getattr(bar, 'l', 0),
                            "close": getattr(bar, 'close', 0) or getattr(bar, 'c', 0),
                            "volume": getattr(bar, 'volume', 0) or getattr(bar, 'v', 0),
                            "vwap": getattr(bar, 'vwap', None) or getattr(bar, 'vw', None),
                        }
                except Exception as e:
                    logger.debug(f"get_previous_close_agg failed for {symbol}, trying list_aggs: {e}")
                    # Fallback to list_aggs (sync call)
                    bars = []
                    loop = asyncio.get_event_loop()
                    bars_iter = await loop.run_in_executor(
                        None,
                        lambda: self.client.list_aggs(
                            ticker=symbol,
                            multiplier=1,
                            timespan="minute",
                            from_=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            to=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            limit=1
                        )
                    )
                    for bar in bars_iter:
                        bars.append(bar)
                        break
                    
                    if bars:
                        bar = bars[0]
                        timestamp_ms = getattr(bar, 'timestamp', None) or getattr(bar, 't', 0)
                        return {
                            "timestamp": datetime.fromtimestamp(
                                timestamp_ms / 1000, tz=timezone.utc
                            ),
                            "open": getattr(bar, 'open', 0) or getattr(bar, 'o', 0),
                            "high": getattr(bar, 'high', 0) or getattr(bar, 'h', 0),
                            "low": getattr(bar, 'low', 0) or getattr(bar, 'l', 0),
                            "close": getattr(bar, 'close', 0) or getattr(bar, 'c', 0),
                            "volume": getattr(bar, 'volume', 0) or getattr(bar, 'v', 0),
                            "vwap": getattr(bar, 'vwap', None) or getattr(bar, 'vw', None),
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
            
            # Use list_snapshot_options_chain (returns iterator, sync call)
            options = []
            try:
                # Run sync call in executor
                loop = asyncio.get_event_loop()
                options_iter = await loop.run_in_executor(
                    None,
                    lambda: self.client.list_snapshot_options_chain(underlying_asset=underlying_symbol)
                )
                for option in options_iter:
                    # Option is an object with attributes
                    details = getattr(option, 'details', None) or option
                    last_quote = getattr(option, 'last_quote', None) or {}
                    last_trade = getattr(option, 'last_trade', None) or {}
                    session = getattr(option, 'session', None) or {}
                    
                    options.append(
                        {
                            "symbol": getattr(details, 'ticker', None) if hasattr(details, 'ticker') else getattr(option, 'ticker', None),
                            "strike": getattr(details, 'strike_price', None) if hasattr(details, 'strike_price') else getattr(option, 'strike_price', None),
                            "expiration": getattr(details, 'expiration_date', None) if hasattr(details, 'expiration_date') else getattr(option, 'expiration_date', None),
                            "option_type": getattr(details, 'contract_type', None) if hasattr(details, 'contract_type') else getattr(option, 'contract_type', None),
                            "bid": getattr(last_quote, 'bid', None) if hasattr(last_quote, 'bid') else None,
                            "ask": getattr(last_quote, 'ask', None) if hasattr(last_quote, 'ask') else None,
                            "last_price": getattr(last_trade, 'price', None) if hasattr(last_trade, 'price') else None,
                            "volume": getattr(session, 'volume', None) if hasattr(session, 'volume') else None,
                            "open_interest": getattr(session, 'open_interest', None) if hasattr(session, 'open_interest') else None,
                        }
                    )
                    # Limit results
                    if len(options) >= 1000:
                        break
                
                return options
            except Exception as e:
                logger.error(
                    f"Error fetching options chain for {underlying_symbol}: {e}"
                )

        except Exception as e:
            logger.error(
                f"Error in options chain fetch for {underlying_symbol}: {e}"
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
            
            # Use get_last_trade (returns LastTrade object, sync call)
            try:
                loop = asyncio.get_event_loop()
                trade = await loop.run_in_executor(
                    None,
                    lambda: self.client.get_last_trade(ticker=symbol)
                )
                if trade:
                    price = getattr(trade, 'price', None) or getattr(trade, 'p', 0)
                    timestamp_ns = getattr(trade, 'timestamp', None) or getattr(trade, 't', 0)
                    return {
                        "last_price": price,
                        "timestamp": datetime.fromtimestamp(
                            timestamp_ns / 1000000, tz=timezone.utc
                        ) if timestamp_ns else datetime.now(timezone.utc),
                    }
            except Exception as e:
                logger.debug(f"get_last_trade failed for {symbol}: {e}")

            # Get quote (bid/ask) using get_last_quote (sync call)
            try:
                loop = asyncio.get_event_loop()
                quote = await loop.run_in_executor(
                    None,
                    lambda: self.client.get_last_quote(ticker=symbol)
                )
                if quote:
                    timestamp_ns = getattr(quote, 'timestamp', None) or getattr(quote, 't', 0)
                    return {
                        "bid": getattr(quote, 'bid', None) or getattr(quote, 'b', None),
                        "ask": getattr(quote, 'ask', None) or getattr(quote, 'a', None),
                        "bid_size": getattr(quote, 'bid_size', None) or getattr(quote, 'x', None),
                        "ask_size": getattr(quote, 'ask_size', None) or getattr(quote, 'y', None),
                        "timestamp": datetime.fromtimestamp(
                            timestamp_ns / 1000000, tz=timezone.utc
                        ) if timestamp_ns else datetime.now(timezone.utc),
                    }
            except Exception as e:
                logger.debug(f"get_last_quote failed for {symbol}: {e}")

        except Exception as e:
            logger.error(f"Error fetching real-time quote for {symbol}: {e}")

        return None
