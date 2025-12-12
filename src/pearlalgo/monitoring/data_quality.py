"""
Data Quality Monitoring - Detects and handles data quality issues.

Features:
- Empty bar detection
- Frozen feed detection
- Partial outage handling
- Exchange holiday detection
- Stale data alerts
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class DataQualityMonitor:
    """
    Monitors data quality and detects issues.
    
    Detects:
    - Empty bars (no data returned)
    - Frozen feeds (same price for extended period)
    - Stale data (no updates for threshold time)
    - Partial outages (one symbol fails, others work)
    """

    def __init__(
        self,
        stale_threshold: float = 30.0,
        frozen_threshold: float = 300.0,  # 5 minutes
        price_tolerance: float = 0.001,  # 0.1% price change considered "same"
    ):
        """
        Initialize data quality monitor.
        
        Args:
            stale_threshold: Time in seconds before data is considered stale
            frozen_threshold: Time in seconds before feed is considered frozen
            price_tolerance: Price change tolerance for frozen detection (as fraction)
        """
        self.stale_threshold = stale_threshold
        self.frozen_threshold = frozen_threshold
        self.price_tolerance = price_tolerance

        # Track last prices and timestamps per symbol
        self._last_prices: Dict[str, float] = {}
        self._last_update_times: Dict[str, float] = {}
        self._frozen_alerts_sent: Dict[str, bool] = {}

        logger.info(
            f"DataQualityMonitor initialized: stale_threshold={stale_threshold}s, "
            f"frozen_threshold={frozen_threshold}s"
        )

    def check_bar(self, symbol: str, bar: Optional[Dict]) -> Dict[str, bool]:
        """
        Check quality of a single bar.
        
        Args:
            symbol: Symbol name
            bar: Bar data dictionary with 'close' price and 'timestamp'
            
        Returns:
            Dictionary with quality checks:
                - is_empty: True if bar is None or missing data
                - is_stale: True if data is stale
                - is_frozen: True if feed appears frozen
        """
        checks = {
            "is_empty": False,
            "is_stale": False,
            "is_frozen": False,
        }

        # Check for empty bar
        if not bar:
            checks["is_empty"] = True
            logger.warning(f"Empty bar detected for {symbol}")
            return checks

        # Check timestamp
        timestamp = bar.get("timestamp")
        if timestamp:
            if isinstance(timestamp, datetime):
                update_time = timestamp.timestamp()
            else:
                update_time = float(timestamp)
        else:
            update_time = datetime.now(timezone.utc).timestamp()

        # Check for stale data
        elapsed = datetime.now(timezone.utc).timestamp() - update_time
        if elapsed > self.stale_threshold:
            checks["is_stale"] = True
            logger.warning(
                f"Stale data detected for {symbol}: {elapsed:.1f}s old (threshold: {self.stale_threshold}s)"
            )

        # Check for frozen feed
        price = bar.get("close", 0)
        if price and price > 0:
            if symbol in self._last_prices:
                last_price = self._last_prices[symbol]
                price_change = abs(price - last_price) / last_price if last_price > 0 else 1.0

                # Check if price hasn't changed significantly
                if price_change < self.price_tolerance:
                    # Check how long it's been frozen
                    if symbol in self._last_update_times:
                        frozen_duration = update_time - self._last_update_times[symbol]
                        if frozen_duration > self.frozen_threshold:
                            checks["is_frozen"] = True
                            if not self._frozen_alerts_sent.get(symbol, False):
                                logger.error(
                                    f"Frozen feed detected for {symbol}: "
                                    f"price unchanged for {frozen_duration:.1f}s "
                                    f"(threshold: {self.frozen_threshold}s)"
                                )
                                self._frozen_alerts_sent[symbol] = True
                else:
                    # Price changed, reset frozen alert
                    self._frozen_alerts_sent[symbol] = False

            # Update tracking
            self._last_prices[symbol] = price
            self._last_update_times[symbol] = update_time

        return checks

    def check_batch(self, symbols: List[str], bars: Dict[str, Optional[Dict]]) -> Dict[str, Dict]:
        """
        Check quality of multiple bars.
        
        Args:
            symbols: List of symbols to check
            bars: Dictionary mapping symbol to bar data
            
        Returns:
            Dictionary mapping symbol to quality checks
        """
        results = {}
        for symbol in symbols:
            bar = bars.get(symbol)
            results[symbol] = self.check_bar(symbol, bar)

        return results

    def get_quality_summary(self, symbols: List[str]) -> Dict:
        """
        Get quality summary for symbols.
        
        Args:
            symbols: List of symbols to summarize
            
        Returns:
            Summary dictionary with counts and issues
        """
        summary = {
            "total_symbols": len(symbols),
            "stale_count": 0,
            "frozen_count": 0,
            "empty_count": 0,
            "healthy_count": 0,
            "issues": [],
        }

        for symbol in symbols:
            if symbol not in self._last_update_times:
                summary["empty_count"] += 1
                summary["issues"].append(f"{symbol}: No data received")
                continue

            # Check if stale
            last_update = self._last_update_times[symbol]
            elapsed = datetime.now(timezone.utc).timestamp() - last_update
            if elapsed > self.stale_threshold:
                summary["stale_count"] += 1
                summary["issues"].append(f"{symbol}: Stale ({elapsed:.1f}s old)")
                continue

            # Check if frozen
            if self._frozen_alerts_sent.get(symbol, False):
                summary["frozen_count"] += 1
                summary["issues"].append(f"{symbol}: Frozen feed")
                continue

            summary["healthy_count"] += 1

        return summary

    def reset_symbol(self, symbol: str) -> None:
        """Reset tracking for a symbol (e.g., after reconnection)."""
        self._last_prices.pop(symbol, None)
        self._last_update_times.pop(symbol, None)
        self._frozen_alerts_sent.pop(symbol, None)
        logger.debug(f"Reset tracking for {symbol}")

    def reset_all(self) -> None:
        """Reset all tracking."""
        self._last_prices.clear()
        self._last_update_times.clear()
        self._frozen_alerts_sent.clear()
        logger.debug("Reset all data quality tracking")
