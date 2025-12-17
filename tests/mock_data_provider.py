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
    Also simulates IBKR quirks: delayed data, occasional timeouts, connection issues.
    """
    
    def __init__(
        self,
        base_price: float = 17500.0,  # Realistic NQ futures price (typical range: ~17,000-20,000)
        volatility: float = 25.0,  # Realistic intraday volatility for NQ (points per bar)
        trend: float = 0.0,  # Price trend per bar (positive = uptrend, negative = downtrend)
        simulate_delayed_data: bool = True,  # Simulate IBKR delayed data (5-15 second delay)
        simulate_timeouts: bool = True,  # Simulate occasional timeouts (5% chance)
        simulate_connection_issues: bool = True,  # Simulate connection issues (2% chance)
    ):
        """
        Initialize mock data provider.
        
        NOTE: This generates SYNTHETIC data for testing strategy LOGIC only.
        Prices are not real market data and should not be used for actual trading decisions.
        
        Args:
            base_price: Starting price for generated data (default ~17,500 for NQ futures)
            volatility: Price volatility in points per bar (default 25 points for realistic NQ movement)
            trend: Price trend per bar (positive = uptrend, negative = downtrend)
            simulate_delayed_data: If True, simulates IBKR delayed data (5-15 second delay)
            simulate_timeouts: If True, simulates occasional timeouts (5% chance per call)
            simulate_connection_issues: If True, simulates connection issues (2% chance per call)
        """
        self.base_price = base_price
        self.volatility = volatility
        self.trend = trend
        self.current_price = base_price
        self._historical_data: List[Dict] = []
        self.simulate_delayed_data = simulate_delayed_data
        self.simulate_timeouts = simulate_timeouts
        self.simulate_connection_issues = simulate_connection_issues
        self._call_count = 0
        
    def fetch_historical(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1m",
    ) -> pd.DataFrame:
        """
        Generate fake historical data with optional IBKR quirks simulation.
        
        Simulates:
        - Occasional timeouts (5% chance)
        - Connection issues (2% chance)
        - Delayed data (timestamp offset)
        """
        self._call_count += 1
        
        # Simulate occasional timeouts (IBKR quirk)
        if self.simulate_timeouts and random.random() < 0.05:
            raise TimeoutError("IBKR Gateway timeout (simulated)")
        
        # Simulate occasional connection issues (IBKR quirk)
        if self.simulate_connection_issues and random.random() < 0.02:
            raise ConnectionError("IBKR Gateway connection refused (simulated)")
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
            
            # Simulate delayed data (IBKR quirk: data is 5-15 seconds old)
            if self.simulate_delayed_data:
                delay_seconds = random.randint(5, 15)
                timestamp = current_time - timedelta(seconds=delay_seconds)
            else:
                timestamp = current_time
            
            bars.append({
                "timestamp": timestamp,
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
        Get fake latest bar with optional IBKR quirks simulation.
        
        Simulates:
        - Occasional timeouts (5% chance)
        - Connection issues (2% chance)
        - Delayed data (5-15 second delay in timestamp)
        
        Args:
            symbol: Trading symbol (ignored)
            
        Returns:
            Latest bar dictionary
        """
        # Simulate occasional timeouts (IBKR quirk)
        if self.simulate_timeouts and random.random() < 0.05:
            raise TimeoutError("IBKR Gateway timeout (simulated)")
        
        # Simulate occasional connection issues (IBKR quirk)
        if self.simulate_connection_issues and random.random() < 0.02:
            raise ConnectionError("IBKR Gateway connection refused (simulated)")
        
        # Generate a new bar
        change = random.gauss(self.trend, self.volatility)
        self.current_price = max(self.current_price + change, 1000.0)
        
        high = self.current_price + abs(random.gauss(0, self.volatility * 0.3))
        low = self.current_price - abs(random.gauss(0, self.volatility * 0.3))
        open_price = self.current_price - random.gauss(0, self.volatility * 0.2)
        
        # Simulate delayed data (IBKR quirk: data is 5-15 seconds old)
        if self.simulate_delayed_data:
            delay_seconds = random.randint(5, 15)
            timestamp = datetime.now(timezone.utc) - timedelta(seconds=delay_seconds)
        else:
            timestamp = datetime.now(timezone.utc)
        
        return {
            "timestamp": timestamp,
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




