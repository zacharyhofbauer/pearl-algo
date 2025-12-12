"""
NQ Agent Data Fetcher

Fetches market data from data providers for NQ strategy.
"""

from __future__ import annotations

import asyncio
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig


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
        
        # Buffer for historical data
        self._data_buffer: Optional[pd.DataFrame] = None
        self._buffer_size = 100  # Keep last 100 bars
        
        logger.info(f"NQAgentDataFetcher initialized with provider={type(data_provider).__name__}")
    
    async def fetch_latest_data(self) -> Dict:
        """
        Fetch latest market data for analysis.
        
        Returns:
            Dictionary with 'df' (DataFrame) and 'latest_bar' (Dict)
        """
        try:
            # Fetch historical data to populate/update buffer
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=2)  # Last 2 hours for intraday
            
            if hasattr(self.data_provider, 'fetch_historical_async'):
                df = await self.data_provider.fetch_historical_async(
                    self.config.symbol,
                    start=start,
                    end=end,
                    timeframe=self.config.timeframe,
                )
            else:
                # Fallback to sync method
                df = self.data_provider.fetch_historical(
                    self.config.symbol,
                    start=start,
                    end=end,
                    timeframe=self.config.timeframe,
                )
            
            if not df.empty:
                self._data_buffer = df.tail(self._buffer_size).reset_index(drop=True)
            
            # Fetch latest bar if method available
            latest_bar = None
            if hasattr(self.data_provider, 'get_latest_bar'):
                if asyncio.iscoroutinefunction(self.data_provider.get_latest_bar):
                    latest_bar = await self.data_provider.get_latest_bar(self.config.symbol)
                else:
                    latest_bar = self.data_provider.get_latest_bar(self.config.symbol)
            
            # If no latest_bar from provider, use last row from historical data
            if latest_bar is None and not df.empty:
                latest_row = df.iloc[-1]
                timestamp = latest_row.name if hasattr(latest_row, 'name') and hasattr(latest_row.name, 'to_pydatetime') else datetime.now(timezone.utc)
                if hasattr(timestamp, 'to_pydatetime'):
                    timestamp = timestamp.to_pydatetime()
                latest_bar = {
                    "timestamp": timestamp,
                    "open": float(latest_row.get("open", 0)),
                    "high": float(latest_row.get("high", 0)),
                    "low": float(latest_row.get("low", 0)),
                    "close": float(latest_row.get("close", 0)),
                    "volume": int(latest_row.get("volume", 0)),
                }
            
            if latest_bar is None:
                logger.warning(f"No latest bar available for {self.config.symbol}")
                return {"df": pd.DataFrame(), "latest_bar": None}
            
            # Update buffer if we have new data
            if self._data_buffer is None or self._data_buffer.empty:
                self._data_buffer = df.tail(self._buffer_size).reset_index(drop=True)
            else:
                # Append latest bar to buffer
                timestamp = latest_bar.get("timestamp")
                if timestamp and isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                
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
            
            return {
                "df": self._data_buffer.copy(),
                "latest_bar": latest_bar,
            }
            
        except Exception as e:
            logger.error(f"Error fetching latest data: {e}", exc_info=True)
            return {"df": pd.DataFrame(), "latest_bar": None}
    
    def get_buffer_size(self) -> int:
        """Get current buffer size."""
        if self._data_buffer is None:
            return 0
        return len(self._data_buffer)
