"""
Dummy Data Provider - Generates synthetic market data for paper trading.

Used as a fallback when all real data sources fail, allowing the system
to continue running and demonstrating the workflow.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from pearlalgo.data_providers.base import DataProvider


class DummyDataProvider(DataProvider):
    """
    Generates synthetic market data for paper trading.
    
    Uses realistic price movements based on symbol type and maintains
    price history for consistency.
    """

    # Base prices for common futures (approximate as of 2024)
    BASE_PRICES: Dict[str, float] = {
        "MES": 5500.0,  # Micro E-mini S&P 500
        "MNQ": 18000.0,  # Micro E-mini Nasdaq
        "MYM": 38000.0,  # Micro E-mini Dow
        "M2K": 2000.0,  # Micro E-mini Russell 2000
        "ES": 5500.0,  # E-mini S&P 500
        "NQ": 18000.0,  # E-mini Nasdaq
    }

    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.price_history: Dict[str, float] = {}
        
        # Initialize prices
        for symbol in symbols:
            # Extract base symbol (remove month/year suffix if present)
            base_symbol = symbol.split()[0] if " " in symbol else symbol
            self.price_history[symbol] = self.BASE_PRICES.get(
                base_symbol, 1000.0
            ) + random.uniform(-50, 50)  # Add some randomness

    def fetch_historical(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """Generate synthetic historical OHLCV data."""
        if end is None:
            end = datetime.now(timezone.utc)
        if start is None:
            from datetime import timedelta
            start = end - timedelta(days=1)

        # Generate minute bars
        current = start
        bars = []
        base_price = self.price_history.get(symbol, 1000.0)

        while current <= end:
            # Random walk with slight upward bias
            change_pct = random.uniform(-0.001, 0.0015)  # -0.1% to +0.15%
            base_price *= (1 + change_pct)

            # Generate OHLC
            high = base_price * (1 + abs(random.uniform(0, 0.0005)))
            low = base_price * (1 - abs(random.uniform(0, 0.0005)))
            open_price = base_price * (1 + random.uniform(-0.0003, 0.0003))
            close_price = base_price
            volume = random.randint(100, 10000)

            bars.append({
                "timestamp": current,
                "Open": open_price,
                "High": high,
                "Low": low,
                "Close": close_price,
                "Volume": volume,
            })

            # Move to next minute
            from datetime import timedelta
            current += timedelta(minutes=1)

        df = pd.DataFrame(bars)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
            # Update price history
            self.price_history[symbol] = close_price

        return df

    def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """
        Get latest synthetic bar data.
        
        Returns a dict with OHLCV data similar to real providers.
        """
        base_price = self.price_history.get(symbol, 1000.0)
        
        # Small random walk
        change_pct = random.uniform(-0.0005, 0.0005)  # -0.05% to +0.05%
        new_price = base_price * (1 + change_pct)
        
        # Generate OHLC around new price
        high = new_price * (1 + abs(random.uniform(0, 0.0003)))
        low = new_price * (1 - abs(random.uniform(0, 0.0003)))
        open_price = base_price  # Previous close
        close_price = new_price
        volume = random.randint(500, 5000)

        # Update price history
        self.price_history[symbol] = close_price

        return {
            "timestamp": datetime.now(timezone.utc),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close_price,
            "volume": volume,
            "vwap": (high + low + close_price) / 3,
        }

