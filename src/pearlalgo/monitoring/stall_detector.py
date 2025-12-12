"""
Stall Detector - Detects when data feeds have stalled or frozen.

Monitors for:
- No data updates for extended periods
- Same price for extended periods
- Connection issues that cause data flow to stop
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class StallDetector:
    """
    Detects when data feeds have stalled or frozen.
    
    Tracks:
    - Last update time per symbol
    - Price stability (frozen prices)
    - Connection health
    """

    def __init__(
        self,
        stall_threshold: float = 60.0,  # 1 minute
        frozen_price_threshold: float = 300.0,  # 5 minutes
    ):
        """
        Initialize stall detector.
        
        Args:
            stall_threshold: Time in seconds before feed is considered stalled
            frozen_price_threshold: Time in seconds before price is considered frozen
        """
        self.stall_threshold = stall_threshold
        self.frozen_price_threshold = frozen_price_threshold

        # Track last update times and prices
        self._last_updates: Dict[str, float] = {}
        self._last_prices: Dict[str, float] = {}
        self._price_frozen_since: Dict[str, float] = {}
        self._stall_alerts_sent: Dict[str, bool] = {}

        logger.info(
            f"StallDetector initialized: stall_threshold={stall_threshold}s, "
            f"frozen_price_threshold={frozen_price_threshold}s"
        )

    def update(self, symbol: str, price: Optional[float], timestamp: Optional[float] = None) -> Dict[str, bool]:
        """
        Update detector with new data point.
        
        Args:
            symbol: Symbol name
            price: Current price (None if no data)
            timestamp: Update timestamp (default: now)
            
        Returns:
            Dictionary with detection results:
                - is_stalled: True if feed is stalled
                - is_frozen: True if price is frozen
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).timestamp()

        results = {
            "is_stalled": False,
            "is_frozen": False,
        }

        # Update last update time
        if price is not None:
            self._last_updates[symbol] = timestamp

            # Check for frozen price
            if symbol in self._last_prices:
                last_price = self._last_prices[symbol]
                if abs(price - last_price) < 0.001:  # Price unchanged
                    if symbol not in self._price_frozen_since:
                        self._price_frozen_since[symbol] = timestamp
                    else:
                        frozen_duration = timestamp - self._price_frozen_since[symbol]
                        if frozen_duration > self.frozen_price_threshold:
                            results["is_frozen"] = True
                            if not self._stall_alerts_sent.get(f"{symbol}_frozen", False):
                                logger.error(
                                    f"Frozen price detected for {symbol}: "
                                    f"price unchanged for {frozen_duration:.1f}s"
                                )
                                self._stall_alerts_sent[f"{symbol}_frozen"] = True
                else:
                    # Price changed, reset frozen tracking
                    self._price_frozen_since.pop(symbol, None)
                    self._stall_alerts_sent.pop(f"{symbol}_frozen", None)

            self._last_prices[symbol] = price
        else:
            # No price data - check if we've had data recently
            if symbol in self._last_updates:
                elapsed = timestamp - self._last_updates[symbol]
                if elapsed > self.stall_threshold:
                    results["is_stalled"] = True
                    if not self._stall_alerts_sent.get(f"{symbol}_stalled", False):
                        logger.error(
                            f"Stalled feed detected for {symbol}: "
                            f"no updates for {elapsed:.1f}s"
                        )
                        self._stall_alerts_sent[f"{symbol}_stalled"] = True

        return results

    def check_stalled(self, symbol: str) -> bool:
        """
        Check if a symbol's feed is stalled.
        
        Args:
            symbol: Symbol to check
            
        Returns:
            True if stalled, False otherwise
        """
        if symbol not in self._last_updates:
            return True  # Never received data

        elapsed = datetime.now(timezone.utc).timestamp() - self._last_updates[symbol]
        return elapsed > self.stall_threshold

    def get_stalled_symbols(self, symbols: List[str]) -> List[str]:
        """
        Get list of stalled symbols.
        
        Args:
            symbols: List of symbols to check
            
        Returns:
            List of stalled symbol names
        """
        stalled = []
        for symbol in symbols:
            if self.check_stalled(symbol):
                stalled.append(symbol)
        return stalled

    def reset_symbol(self, symbol: str) -> None:
        """Reset tracking for a symbol."""
        self._last_updates.pop(symbol, None)
        self._last_prices.pop(symbol, None)
        self._price_frozen_since.pop(symbol, None)
        self._stall_alerts_sent.pop(f"{symbol}_stalled", None)
        self._stall_alerts_sent.pop(f"{symbol}_frozen", None)
        logger.debug(f"Reset stall tracking for {symbol}")

    def reset_all(self) -> None:
        """Reset all tracking."""
        self._last_updates.clear()
        self._last_prices.clear()
        self._price_frozen_since.clear()
        self._stall_alerts_sent.clear()
        logger.debug("Reset all stall tracking")
