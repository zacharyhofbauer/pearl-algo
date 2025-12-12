"""
Options Data Ingestion - Separates data fetching from strategy logic.

This module handles all data fetching operations, allowing strategies
to focus on signal generation without knowing data provider details.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.market_data_provider import MarketDataProvider


class OptionsDataIngestion:
    """
    Handles options data ingestion for strategies.
    
    Separates data fetching from strategy logic, allowing strategies
    to work with any data provider.
    """

    def __init__(self, data_provider: MarketDataProvider):
        """
        Initialize data ingestion.
        
        Args:
            data_provider: Market data provider instance (must implement MarketDataProvider)
        """
        self.data_provider = data_provider
        logger.info("OptionsDataIngestion initialized")

    async def get_underlier_data(
        self,
        symbol: str,
    ) -> Optional[Dict]:
        """
        Get current data for an underlying symbol.
        
        Args:
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            
        Returns:
            Dictionary with:
                - symbol: Symbol name
                - price: Current price
                - timestamp: Update timestamp
                - bid: Bid price (if available)
                - ask: Ask price (if available)
                - volume: Volume (if available)
            None if data unavailable
        """
        try:
            price = await self.data_provider.get_underlier_price(symbol)
            return {
                "symbol": symbol,
                "price": price,
                "timestamp": datetime.now(timezone.utc),
            }
        except Exception as e:
            logger.error(f"Error fetching underlier data for {symbol}: {e}")
            return None

    async def get_options_chain(
        self,
        symbol: str,
        mode: str = "intraday",
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Get filtered options chain for an underlying symbol.
        
        Args:
            symbol: Underlying symbol
            mode: 'intraday' or 'swing' (uses default filters)
            filters: Optional custom filters (overrides mode defaults)
            
        Returns:
            List of option contracts (see MarketDataProvider interface)
        """
        try:
            # Use mode-based defaults if no custom filters
            if filters is None:
                if mode == "intraday":
                    filters = {
                        "min_dte": 0,
                        "max_dte": 7,
                        "strike_proximity_pct": 0.10,
                        "min_volume": 100,
                        "min_open_interest": 500,
                    }
                elif mode == "swing":
                    filters = {
                        "min_dte": 7,
                        "max_dte": 45,
                        "strike_proximity_pct": 0.15,
                        "min_volume": 50,
                        "min_open_interest": 200,
                    }
                else:
                    filters = {}

            options = await self.data_provider.get_option_chain(symbol, filters=filters)
            logger.debug(f"Retrieved {len(options)} options for {symbol} (mode: {mode})")
            return options

        except Exception as e:
            logger.error(f"Error fetching options chain for {symbol}: {e}")
            return []

    async def get_options_quotes(
        self,
        contracts: List[str],
    ) -> List[Dict]:
        """
        Get real-time quotes for specific option contracts.
        
        Args:
            contracts: List of option contract identifiers
            
        Returns:
            List of quote dictionaries
        """
        try:
            quotes = await self.data_provider.get_option_quotes(contracts)
            return quotes
        except Exception as e:
            logger.error(f"Error fetching option quotes: {e}")
            return []

    async def get_batch_underlier_data(
        self,
        symbols: List[str],
    ) -> Dict[str, Optional[Dict]]:
        """
        Get data for multiple underlying symbols in parallel.
        
        Args:
            symbols: List of underlying symbols
            
        Returns:
            Dictionary mapping symbol to data (or None if unavailable)
        """
        tasks = [self.get_underlier_data(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.error(f"Error fetching data for {symbol}: {result}")
                data[symbol] = None
            else:
                data[symbol] = result

        return data

    async def validate_data_availability(
        self,
        symbols: List[str],
    ) -> Dict[str, bool]:
        """
        Validate that data is available for symbols.
        
        Args:
            symbols: List of symbols to validate
            
        Returns:
            Dictionary mapping symbol to availability status
        """
        availability = {}
        for symbol in symbols:
            try:
                price = await self.data_provider.get_underlier_price(symbol)
                availability[symbol] = price > 0
            except Exception:
                availability[symbol] = False

        return availability
