"""
Data Feed Manager - Manages data feed connections with reconnection logic.

Provides:
- WebSocket connection management
- Automatic reconnection with exponential backoff
- Rate-limit queuing (respect Polygon limits: 5 calls/sec free tier)
- Data buffer management
- Health monitoring per data source
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Deque, Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter with queuing support."""

    def __init__(self, max_calls: int, time_window: float = 1.0):
        """
        Initialize rate limiter.

        Args:
            max_calls: Maximum calls per time window
            time_window: Time window in seconds (default: 1.0)
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.call_times: Deque[float] = deque()

    async def acquire(self) -> None:
        """Acquire permission to make a call (waits if needed)."""
        now = time.time()

        # Remove old call times outside the window
        while self.call_times and self.call_times[0] < now - self.time_window:
            self.call_times.popleft()

        # If at limit, wait until oldest call expires
        if len(self.call_times) >= self.max_calls:
            wait_time = self.time_window - (now - self.call_times[0])
            if wait_time > 0:
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                # Re-check after wait
                return await self.acquire()

        # Record this call
        self.call_times.append(time.time())


class DataFeedManager:
    """
    Manages data feed connections with automatic reconnection.

    Handles:
    - WebSocket connections (future)
    - REST API calls with rate limiting
    - Automatic reconnection on failure
    - Health monitoring
    """

    def __init__(
        self,
        data_provider,
        rate_limit: int = 5,
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 10,
        exponential_backoff: bool = True,
    ):
        """
        Initialize data feed manager.

        Args:
            data_provider: Data provider instance (Polygon, etc.)
            rate_limit: Maximum API calls per second
            reconnect_delay: Initial delay before reconnection (seconds)
            max_reconnect_attempts: Maximum reconnection attempts
            exponential_backoff: Use exponential backoff for reconnection
        """
        self.data_provider = data_provider
        self.rate_limit = rate_limit
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self.exponential_backoff = exponential_backoff

        # Rate limiter
        self.rate_limiter = RateLimiter(max_calls=rate_limit, time_window=1.0)

        # Connection state
        self.connected = False
        self.reconnect_attempts = 0
        self.last_connection_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_success_time: Optional[datetime] = None

        # Health monitoring
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0

        logger.info(
            f"DataFeedManager initialized: rate_limit={rate_limit}/s, "
            f"reconnect_delay={reconnect_delay}s"
        )

    async def connect(self) -> bool:
        """
        Connect to data feed.

        Returns:
            True if connected successfully
        """
        if self.connected:
            return True

        logger.info("Connecting to data feed...")

        for attempt in range(self.max_reconnect_attempts):
            try:
                # Test connection (provider-specific)
                if hasattr(self.data_provider, "test_connection"):
                    await self.data_provider.test_connection()
                elif hasattr(self.data_provider, "_get_session"):
                    # Test by getting session
                    await self.data_provider._get_session()

                self.connected = True
                self.reconnect_attempts = 0
                self.last_connection_time = datetime.now(timezone.utc)
                logger.info("Data feed connected successfully")
                return True

            except Exception as e:
                self.reconnect_attempts += 1
                self.last_error = str(e)
                logger.warning(
                    f"Connection attempt {attempt + 1}/{self.max_reconnect_attempts} "
                    f"failed: {e}"
                )

                if attempt < self.max_reconnect_attempts - 1:
                    # Calculate backoff delay
                    if self.exponential_backoff:
                        delay = self.reconnect_delay * (2 ** attempt)
                    else:
                        delay = self.reconnect_delay

                    delay = min(delay, 300)  # Cap at 5 minutes
                    logger.info(f"Retrying connection in {delay:.1f}s...")
                    await asyncio.sleep(delay)

        logger.error("Failed to connect to data feed after all attempts")
        self.connected = False
        return False

    async def disconnect(self) -> None:
        """Disconnect from data feed."""
        if not self.connected:
            return

        try:
            if hasattr(self.data_provider, "close"):
                await self.data_provider.close()
        except Exception as e:
            logger.warning(f"Error disconnecting: {e}")

        self.connected = False
        logger.info("Data feed disconnected")

    async def fetch_data(
        self, symbol: str, method: str = "get_latest_bar", *args, **kwargs
    ) -> Optional[Dict]:
        """
        Fetch data with rate limiting and error handling.

        Args:
            symbol: Trading symbol
            method: Method name to call on data provider
            *args: Arguments for method
            **kwargs: Keyword arguments for method

        Returns:
            Data dict or None on error
        """
        # Ensure connected
        if not self.connected:
            if not await self.connect():
                return None

        # Rate limit
        await self.rate_limiter.acquire()

        # Fetch data
        self.total_requests += 1
        try:
            provider_method = getattr(self.data_provider, method)
            if asyncio.iscoroutinefunction(provider_method):
                result = await provider_method(symbol, *args, **kwargs)
            else:
                result = provider_method(symbol, *args, **kwargs)

            self.successful_requests += 1
            self.last_success_time = datetime.now(timezone.utc)
            self.last_error = None

            return result

        except Exception as e:
            self.failed_requests += 1
            self.last_error = str(e)
            logger.error(f"Error fetching data for {symbol}: {e}", exc_info=True)

            # Check if connection lost
            if "connection" in str(e).lower() or "timeout" in str(e).lower():
                self.connected = False
                logger.warning("Connection lost, will reconnect on next request")

            return None

    async def fetch_multiple(
        self, symbols: list[str], method: str = "get_latest_bar", *args, **kwargs
    ) -> Dict[str, Optional[Dict]]:
        """
        Fetch data for multiple symbols (sequential with rate limiting).

        Args:
            symbols: List of symbols
            method: Method name
            *args: Arguments
            **kwargs: Keyword arguments

        Returns:
            Dictionary of symbol -> data
        """
        results = {}
        for symbol in symbols:
            results[symbol] = await self.fetch_data(symbol, method, *args, **kwargs)
        return results

    def get_health_status(self) -> Dict:
        """Get health status of data feed."""
        success_rate = (
            self.successful_requests / self.total_requests
            if self.total_requests > 0
            else 0.0
        )

        return {
            "connected": self.connected,
            "reconnect_attempts": self.reconnect_attempts,
            "last_connection_time": (
                self.last_connection_time.isoformat()
                if self.last_connection_time
                else None
            ),
            "last_success_time": (
                self.last_success_time.isoformat()
                if self.last_success_time
                else None
            ),
            "last_error": self.last_error,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": success_rate,
        }

    def reset_statistics(self) -> None:
        """Reset health statistics."""
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        logger.info("Reset data feed statistics")
