"""
Historical Data Buffer Manager - Maintains rolling buffers of OHLCV data per symbol.

Provides:
- Rolling buffers (last N bars per symbol)
- Automatic backfill on startup
- Incremental updates from live feed
- Buffer persistence (survive restarts)
"""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class BufferManager:
    """
    Manages rolling buffers of historical OHLCV data per symbol.
    
    Maintains a fixed-size buffer (e.g., 1000 bars) per symbol,
    automatically backfilling on startup and updating incrementally.
    """

    def __init__(
        self,
        max_bars: int = 1000,
        persistence_dir: Optional[Path] = None,
        data_provider=None,
    ):
        """
        Initialize buffer manager.

        Args:
            max_bars: Maximum number of bars to keep per symbol (default: 1000)
            persistence_dir: Directory to persist buffers (optional)
            data_provider: Data provider for backfilling (optional)
        """
        self.max_bars = max_bars
        self.persistence_dir = persistence_dir or Path("data/buffers")
        self.data_provider = data_provider
        
        # Buffers: symbol -> DataFrame with columns: timestamp, open, high, low, close, volume
        self.buffers: Dict[str, pd.DataFrame] = {}
        
        # Ensure persistence directory exists
        if self.persistence_dir:
            self.persistence_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(
            f"BufferManager initialized: max_bars={max_bars}, "
            f"persistence_dir={self.persistence_dir}"
        )

    def get_buffer(self, symbol: str) -> pd.DataFrame:
        """
        Get current buffer for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            DataFrame with OHLCV data (empty if no data)
        """
        return self.buffers.get(symbol, pd.DataFrame())

    def has_buffer(self, symbol: str) -> bool:
        """Check if buffer exists for symbol."""
        return symbol in self.buffers and len(self.buffers[symbol]) > 0

    def get_buffer_size(self, symbol: str) -> int:
        """Get current buffer size for symbol."""
        if symbol not in self.buffers:
            return 0
        return len(self.buffers[symbol])

    def add_bar(
        self,
        symbol: str,
        timestamp: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        """
        Add a new bar to the buffer (incremental update).

        Args:
            symbol: Trading symbol
            timestamp: Bar timestamp
            open: Open price
            high: High price
            low: Low price
            close: Close price
            volume: Volume
        """
        # Create new bar DataFrame
        new_bar = pd.DataFrame(
            {
                "timestamp": [timestamp],
                "open": [open],
                "high": [high],
                "low": [low],
                "close": [close],
                "volume": [volume],
            }
        )

        # Initialize buffer if needed
        if symbol not in self.buffers:
            self.buffers[symbol] = pd.DataFrame()

        # Append new bar
        self.buffers[symbol] = pd.concat(
            [self.buffers[symbol], new_bar], ignore_index=True
        )

        # Trim to max_bars (keep most recent)
        if len(self.buffers[symbol]) > self.max_bars:
            self.buffers[symbol] = self.buffers[symbol].tail(self.max_bars).reset_index(
                drop=True
            )

        logger.debug(
            f"Added bar to buffer for {symbol}: buffer_size={len(self.buffers[symbol])}"
        )

    def update_from_dataframe(self, symbol: str, df: pd.DataFrame) -> None:
        """
        Update buffer from a DataFrame (bulk update).

        Args:
            symbol: Trading symbol
            df: DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if df.empty:
            return

        # Ensure timestamp is datetime
        if "timestamp" in df.columns:
            df = df.copy()
            if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
                df["timestamp"] = pd.to_datetime(df["timestamp"])

        # Sort by timestamp
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Merge with existing buffer (if any)
        if symbol in self.buffers and len(self.buffers[symbol]) > 0:
            # Combine and deduplicate
            combined = pd.concat([self.buffers[symbol], df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)
        else:
            combined = df

        # Trim to max_bars (keep most recent)
        if len(combined) > self.max_bars:
            combined = combined.tail(self.max_bars).reset_index(drop=True)

        self.buffers[symbol] = combined

        logger.info(
            f"Updated buffer for {symbol}: {len(combined)} bars "
            f"(from {len(df)} new bars)"
        )

    async def backfill(
        self,
        symbol: str,
        timeframe: str = "15m",
        days: int = 30,
        data_provider=None,
    ) -> bool:
        """
        Backfill buffer with historical data.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe (e.g., '15m', '5m', '1h')
            days: Number of days to backfill (default: 30)
            data_provider: Data provider to use (uses self.data_provider if None)

        Returns:
            True if backfill succeeded, False otherwise
        """
        provider = data_provider or self.data_provider
        if not provider:
            logger.warning(f"No data provider available for backfilling {symbol}")
            return False

        try:
            # Calculate date range
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            logger.info(
                f"Backfilling {symbol} from {start.date()} to {end.date()} "
                f"({days} days, {timeframe})"
            )

            # Fetch historical data
            # In async context, prefer async method directly to avoid event loop conflicts
            if hasattr(provider, "_fetch_historical_async"):
                # Use async method directly (we're already in async context)
                df = await provider._fetch_historical_async(
                    symbol=symbol, start=start, end=end, timeframe=timeframe
                )
            elif hasattr(provider, "fetch_historical"):
                # Fall back to sync method only if async is not available
                # Note: This may fail if called from async context with running event loop
                try:
                    df = provider.fetch_historical(
                        symbol=symbol, start=start, end=end, timeframe=timeframe
                    )
                except RuntimeError as e:
                    if "event loop" in str(e).lower():
                        logger.warning(
                            f"Event loop conflict for {symbol}, skipping backfill. "
                            f"Buffer will populate from live data."
                        )
                        return False
                    raise
            else:
                logger.error(f"Data provider {provider} does not support historical data")
                return False

            if df.empty:
                logger.warning(f"No historical data returned for {symbol}")
                return False

            # Update buffer
            self.update_from_dataframe(symbol, df)

            logger.info(
                f"Backfilled {symbol}: {len(self.buffers[symbol])} bars "
                f"(requested {days} days)"
            )
            return True

        except Exception as e:
            logger.error(f"Error backfilling {symbol}: {e}", exc_info=True)
            return False

    async def backfill_multiple(
        self,
        symbols: list[str],
        timeframe: str = "15m",
        days: int = 30,
        data_provider=None,
    ) -> Dict[str, bool]:
        """
        Backfill multiple symbols.

        Args:
            symbols: List of symbols to backfill
            timeframe: Timeframe
            days: Number of days
            data_provider: Data provider

        Returns:
            Dictionary of symbol -> success status
        """
        results = {}
        for symbol in symbols:
            results[symbol] = await self.backfill(
                symbol, timeframe=timeframe, days=days, data_provider=data_provider
            )
        return results

    def save_buffer(self, symbol: str) -> bool:
        """
        Save buffer to disk (persistence).

        Args:
            symbol: Trading symbol

        Returns:
            True if saved successfully
        """
        if not self.persistence_dir:
            return False

        if symbol not in self.buffers or self.buffers[symbol].empty:
            return False

        try:
            file_path = self.persistence_dir / f"{symbol}_buffer.pkl"
            with open(file_path, "wb") as f:
                pickle.dump(self.buffers[symbol], f)
            logger.debug(f"Saved buffer for {symbol} to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving buffer for {symbol}: {e}")
            return False

    def load_buffer(self, symbol: str) -> bool:
        """
        Load buffer from disk (persistence).

        Args:
            symbol: Trading symbol

        Returns:
            True if loaded successfully
        """
        if not self.persistence_dir:
            return False

        file_path = self.persistence_dir / f"{symbol}_buffer.pkl"
        if not file_path.exists():
            return False

        try:
            with open(file_path, "rb") as f:
                df = pickle.load(f)
            self.buffers[symbol] = df
            logger.info(f"Loaded buffer for {symbol}: {len(df)} bars from {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error loading buffer for {symbol}: {e}")
            return False

    def save_all_buffers(self) -> Dict[str, bool]:
        """Save all buffers to disk."""
        results = {}
        for symbol in self.buffers:
            results[symbol] = self.save_buffer(symbol)
        return results

    def load_all_buffers(self, symbols: list[str]) -> Dict[str, bool]:
        """Load buffers for multiple symbols."""
        results = {}
        for symbol in symbols:
            results[symbol] = self.load_buffer(symbol)
        return results

    def clear_buffer(self, symbol: str) -> None:
        """Clear buffer for a symbol."""
        if symbol in self.buffers:
            del self.buffers[symbol]
            logger.debug(f"Cleared buffer for {symbol}")

    def clear_all_buffers(self) -> None:
        """Clear all buffers."""
        self.buffers.clear()
        logger.info("Cleared all buffers")

    def get_latest_bar(self, symbol: str) -> Optional[pd.Series]:
        """
        Get the latest bar for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Latest bar as Series, or None if no data
        """
        if symbol not in self.buffers or self.buffers[symbol].empty:
            return None
        return self.buffers[symbol].iloc[-1]

    def get_bars_since(
        self, symbol: str, timestamp: datetime, inclusive: bool = True
    ) -> pd.DataFrame:
        """
        Get all bars since a timestamp.

        Args:
            symbol: Trading symbol
            timestamp: Start timestamp
            inclusive: Include bars at exactly the timestamp

        Returns:
            DataFrame with bars since timestamp
        """
        if symbol not in self.buffers or self.buffers[symbol].empty:
            return pd.DataFrame()

        df = self.buffers[symbol]
        if "timestamp" not in df.columns:
            return pd.DataFrame()

        if inclusive:
            mask = df["timestamp"] >= timestamp
        else:
            mask = df["timestamp"] > timestamp

        return df[mask].copy()

    def get_statistics(self) -> Dict[str, Dict]:
        """
        Get statistics about all buffers.

        Returns:
            Dictionary of symbol -> statistics
        """
        stats = {}
        for symbol, df in self.buffers.items():
            if df.empty:
                stats[symbol] = {"bars": 0, "oldest": None, "newest": None}
            else:
                stats[symbol] = {
                    "bars": len(df),
                    "oldest": df["timestamp"].min() if "timestamp" in df.columns else None,
                    "newest": df["timestamp"].max() if "timestamp" in df.columns else None,
                }
        return stats
