"""
Mock Data Provider for Testing

Provides fake market data for testing without requiring live IBKR connection.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import pandas as pd

from pearlalgo.data_providers.base import DataProvider


class MockDataProvider(DataProvider):
    """
    Mock data provider that generates fake market data for testing.
    
    Simulates realistic NQ futures data with trends, volatility, and patterns.
    """
    
    def __init__(
        self,
        base_price: float = 15000.0,
        volatility: float = 50.0,
        trend: float = 0.0,  # Price trend per bar
    ):
        """
        Initialize mock data provider.
        
        Args:
            base_price: Starting price for generated data
            volatility: Price volatility (standard deviation)
            trend: Price trend per bar (positive = uptrend, negative = downtrend)
        """
        self.base_price = base_price
        self.volatility = volatility
        self.trend = trend
        self.current_price = base_price
        self._historical_data: List[Dict] = []
        
    def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        """
        Generate fake historical data.
        
        Args:
            symbol: Trading symbol (ignored, always generates NQ data)
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe (e.g., "1m", "5m")
            
        Returns:
            DataFrame with OHLCV data
        """
        # Parse timeframe
        if timeframe.endswith("m"):
            minutes = int(timeframe[:-1])
        elif timeframe.endswith("h"):
            minutes = int(timeframe[:-1]) * 60
        else:
            minutes = 1
        
        # Generate bars
        bars = []
        current_time = start
        price = self.current_price
        
        while current_time <= end:
            # Generate price movement
            change = random.gauss(self.trend, self.volatility)
            price = max(price + change, 1000.0)  # Prevent negative prices
            
            # Generate OHLC
            high = price + abs(random.gauss(0, self.volatility * 0.3))
            low = price - abs(random.gauss(0, self.volatility * 0.3))
            open_price = price - random.gauss(0, self.volatility * 0.2)
            close_price = price
            volume = random.randint(1000, 10000)
            
            bars.append({
                "timestamp": current_time,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close_price, 2),
                "volume": volume,
            })
            
            current_time += timedelta(minutes=minutes)
            self.current_price = close_price
        
        df = pd.DataFrame(bars)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
        
        return df
    
    async def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """
        Get fake latest bar.
        
        Args:
            symbol: Trading symbol (ignored)
            
        Returns:
            Latest bar dictionary
        """
        # Generate a new bar
        change = random.gauss(self.trend, self.volatility)
        self.current_price = max(self.current_price + change, 1000.0)
        
        high = self.current_price + abs(random.gauss(0, self.volatility * 0.3))
        low = self.current_price - abs(random.gauss(0, self.volatility * 0.3))
        open_price = self.current_price - random.gauss(0, self.volatility * 0.2)
        
        return {
            "timestamp": datetime.now(timezone.utc),
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(self.current_price, 2),
            "volume": random.randint(1000, 10000),
        }
    
    async def validate_connection(self) -> bool:
        """Always returns True for mock provider."""
        return True
    
    async def close(self) -> None:
        """No-op for mock provider."""
        pass



