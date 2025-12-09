"""
Signal Deduplication - Prevent duplicate signals within a time window.

Tracks recent signals and skips duplicates to avoid notification spam.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass
class SignalKey:
    """Key for signal deduplication."""

    symbol: str
    direction: str  # "long" or "short"
    price_range: str  # Price range bucket (e.g., "4500-4510")
    strategy: str

    def to_hash(self) -> str:
        """Generate hash for this signal key."""
        key_str = f"{self.symbol}:{self.direction}:{self.price_range}:{self.strategy}"
        return hashlib.md5(key_str.encode()).hexdigest()


class SignalDeduplicator:
    """
    Deduplicate signals within a time window.

    Prevents sending duplicate signals for the same symbol/direction/price
    within a configurable time window.
    """

    def __init__(self, window_minutes: int = 15):
        """
        Initialize signal deduplicator.

        Args:
            window_minutes: Time window in minutes (default: 15)
        """
        self.window_minutes = window_minutes
        self.window_seconds = window_minutes * 60
        self.signal_cache: Dict[str, float] = {}  # hash -> timestamp
        self._last_cleanup = time.time()

    def _cleanup_old_signals(self):
        """Remove expired signals from cache."""
        current_time = time.time()
        # Cleanup every 5 minutes
        if current_time - self._last_cleanup < 300:
            return

        expired_keys = [
            key
            for key, timestamp in self.signal_cache.items()
            if current_time - timestamp > self.window_seconds
        ]

        for key in expired_keys:
            del self.signal_cache[key]

        self._last_cleanup = current_time
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired signals")

    def _get_price_range(self, price: float, bucket_size: float = 10.0) -> str:
        """
        Get price range bucket for deduplication.

        Args:
            price: Signal price
            bucket_size: Size of price bucket (default: $10)

        Returns:
            Price range string (e.g., "4500-4510")
        """
        bucket = int(price / bucket_size) * bucket_size
        return f"{bucket:.0f}-{bucket + bucket_size:.0f}"

    def is_duplicate(
        self,
        symbol: str,
        direction: str,
        price: float,
        strategy: str,
        price_bucket_size: float = 10.0,
    ) -> bool:
        """
        Check if signal is a duplicate.

        Args:
            symbol: Trading symbol
            direction: "long" or "short"
            price: Signal price
            strategy: Strategy name
            price_bucket_size: Size of price bucket for deduplication

        Returns:
            True if duplicate, False otherwise
        """
        self._cleanup_old_signals()

        price_range = self._get_price_range(price, price_bucket_size)
        signal_key = SignalKey(
            symbol=symbol,
            direction=direction.lower(),
            price_range=price_range,
            strategy=strategy,
        )

        signal_hash = signal_key.to_hash()
        current_time = time.time()

        # Check if signal exists in cache
        if signal_hash in self.signal_cache:
            signal_time = self.signal_cache[signal_hash]
            age_seconds = current_time - signal_time

            if age_seconds < self.window_seconds:
                logger.debug(
                    f"Duplicate signal detected: {symbol} {direction} "
                    f"at {price} (age: {age_seconds:.0f}s)"
                )
                return True

        # Not a duplicate - add to cache
        self.signal_cache[signal_hash] = current_time
        return False

    def clear(self):
        """Clear all cached signals."""
        self.signal_cache.clear()
        logger.info("Signal deduplication cache cleared")

    def get_cache_size(self) -> int:
        """Get number of signals in cache."""
        return len(self.signal_cache)


