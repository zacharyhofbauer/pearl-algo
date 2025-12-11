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
        
        # Contract cache removed - no longer needed for futures

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
        # RESTClient doesn't have explicit close
        pass

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

        # Futures contract resolution removed - system now focuses on stocks/options

        all_results = []
        
        # System now focuses on stocks/options only
        # Use stocks endpoint for all symbols
        
        # Chunk requests for large date ranges
        chunk_days = 30
        current_start = start
        total_days = (end - start).days
        
        logger.debug(f"Fetching {symbol} from {start.date()} to {end.date()} ({total_days} days)")

        while current_start < end:
            chunk_end = min(current_start + timedelta(days=chunk_days), end)
            
            try:
                await self._rate_limit()
                
                # Use list_aggs for stocks/options (returns iterator, sync call)
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
                f"Please check your API key and symbol validity."
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
            # #region agent log
            import json
            with open('/home/pearlalgo/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"massive_provider.py:545","message":"get_latest_bar entry","data":{"original_symbol":symbol},"timestamp":int(__import__('time').time()*1000)}) + '\n')
            # #endregion
            # Futures contract resolution removed - system now focuses on stocks/options
            original_symbol = symbol

            await self._rate_limit()
            
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
            underlying_symbol: Underlying ticker (e.g., 'AAPL', 'QQQ')
            expiration_date: Expiration date in YYYY-MM-DD format (optional)
            min_dte: Minimum days to expiration (optional)
            max_dte: Maximum days to expiration (optional)
            strike_proximity_pct: Filter strikes within X% of current price (optional, e.g., 0.10 for 10%)
            min_volume: Minimum volume threshold (optional)
            min_open_interest: Minimum open interest threshold (optional)
            underlying_price: Current underlying price for strike proximity filtering (optional)

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
                
                # Get current date for DTE calculation
                from datetime import date
                today = date.today()
                
                for option in options_iter:
                    # Option is an object with attributes
                    details = getattr(option, 'details', None) or option
                    last_quote = getattr(option, 'last_quote', None) or {}
                    last_trade = getattr(option, 'last_trade', None) or {}
                    session = getattr(option, 'session', None) or {}
                    
                    # Extract option data
                    strike = getattr(details, 'strike_price', None) if hasattr(details, 'strike_price') else getattr(option, 'strike_price', None)
                    expiration_str = getattr(details, 'expiration_date', None) if hasattr(details, 'expiration_date') else getattr(option, 'expiration_date', None)
                    volume = getattr(session, 'volume', None) if hasattr(session, 'volume', None) else None
                    open_interest = getattr(session, 'open_interest', None) if hasattr(session, 'open_interest', None) else None
                    
                    # Filter by volume
                    if min_volume is not None and (volume is None or volume < min_volume):
                        continue
                    
                    # Filter by open interest
                    if min_open_interest is not None and (open_interest is None or open_interest < min_open_interest):
                        continue
                    
                    # Filter by expiration date
                    if expiration_str:
                        try:
                            if isinstance(expiration_str, str):
                                exp_date = datetime.fromisoformat(expiration_str.replace("Z", "+00:00")).date()
                            else:
                                exp_date = expiration_str.date() if hasattr(expiration_str, 'date') else expiration_str
                            
                            dte = (exp_date - today).days
                            
                            # Filter by DTE range
                            if min_dte is not None and dte < min_dte:
                                continue
                            if max_dte is not None and dte > max_dte:
                                continue
                            
                            # Filter by expiration date if specified
                            if expiration_date:
                                exp_date_str = exp_date.strftime("%Y-%m-%d")
                                if exp_date_str != expiration_date:
                                    continue
                        except Exception as e:
                            logger.debug(f"Error parsing expiration date {expiration_str}: {e}")
                            continue
                    
                    # Filter by strike proximity
                    if strike_proximity_pct is not None and underlying_price is not None and strike is not None:
                        strike_diff_pct = abs(strike - underlying_price) / underlying_price
                        if strike_diff_pct > strike_proximity_pct:
                            continue
                    
                    option_dict = {
                        "symbol": getattr(details, 'ticker', None) if hasattr(details, 'ticker') else getattr(option, 'ticker', None),
                        "strike": strike,
                        "expiration": expiration_str,
                        "option_type": getattr(details, 'contract_type', None) if hasattr(details, 'contract_type') else getattr(option, 'contract_type', None),
                        "bid": getattr(last_quote, 'bid', None) if hasattr(last_quote, 'bid') else None,
                        "ask": getattr(last_quote, 'ask', None) if hasattr(last_quote, 'ask') else None,
                        "last_price": getattr(last_trade, 'price', None) if hasattr(last_trade, 'price', None) else None,
                        "volume": volume,
                        "open_interest": open_interest,
                    }
                    
                    # Add DTE if we calculated it
                    if expiration_str:
                        try:
                            if isinstance(expiration_str, str):
                                exp_date = datetime.fromisoformat(expiration_str.replace("Z", "+00:00")).date()
                            else:
                                exp_date = expiration_str.date() if hasattr(expiration_str, 'date') else expiration_str
                            dte = (exp_date - today).days
                            option_dict["dte"] = dte
                        except:
                            pass
                    
                    options.append(option_dict)
                    
                    # Limit results
                    if len(options) >= 1000:
                        break
                
                logger.debug(
                    f"Retrieved {len(options)} options for {underlying_symbol} "
                    f"(filters: min_dte={min_dte}, max_dte={max_dte}, "
                    f"min_volume={min_volume}, min_oi={min_open_interest})"
                )
                
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
