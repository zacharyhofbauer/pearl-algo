"""
Market Data Provider Interface - Provider-agnostic abstraction for market data.

This interface allows strategies to work with any data provider (IBKR, Massive, DataBento)
without knowing implementation details. All providers must implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional


class MarketDataProvider(ABC):
    """
    Provider-agnostic interface for market data access.
    
    All data providers (IBKR, Massive, DataBento) must implement this interface.
    Strategies should only depend on this interface, never on provider-specific code.
    """

    @abstractmethod
    async def get_underlier_price(self, symbol: str) -> float:
        """
        Get current price for an underlying symbol (e.g., SPY, QQQ).
        
        Args:
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            
        Returns:
            Current price as float
            
        Raises:
            ConnectionError: If provider is not connected
            ValueError: If symbol is invalid or not found
        """
        pass

    @abstractmethod
    async def get_option_chain(
        self,
        symbol: str,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Get options chain for an underlying symbol with optional filtering.
        
        Args:
            symbol: Underlying symbol (e.g., 'SPY', 'QQQ')
            filters: Optional filter dictionary with keys:
                - min_dte: Minimum days to expiration
                - max_dte: Maximum days to expiration
                - strike_proximity_pct: Filter strikes within X% of current price
                - min_volume: Minimum volume threshold
                - min_open_interest: Minimum open interest threshold
                - delta_range: Tuple of (min_delta, max_delta)
                - min_iv: Minimum implied volatility
                
        Returns:
            List of option contracts, each with:
                - symbol: Option symbol string
                - underlying_symbol: Underlying ticker
                - strike: Strike price
                - expiration: Expiration date (YYYYMMDD format)
                - expiration_date: ISO format date string
                - dte: Days to expiration
                - option_type: 'call' or 'put'
                - bid: Bid price
                - ask: Ask price
                - last_price: Last trade price
                - volume: Volume
                - open_interest: Open interest
                - iv: Implied volatility (if available)
                - delta: Delta (if available)
                - gamma: Gamma (if available)
                - theta: Theta (if available)
                - vega: Vega (if available)
                
        Raises:
            ConnectionError: If provider is not connected
            ValueError: If symbol is invalid or not found
        """
        pass

    @abstractmethod
    async def get_option_quotes(self, contracts: List[str]) -> List[Dict]:
        """
        Get real-time quotes for specific option contracts.
        
        Args:
            contracts: List of option contract identifiers (provider-specific format)
            
        Returns:
            List of quote dictionaries with bid, ask, last, volume, etc.
            
        Raises:
            ConnectionError: If provider is not connected
        """
        pass

    @abstractmethod
    async def subscribe_realtime(
        self,
        symbols: List[str],
    ) -> AsyncIterator[Dict]:
        """
        Subscribe to real-time market data updates.
        
        Args:
            symbols: List of symbols to subscribe to (underliers or options)
            
        Yields:
            Dictionary with market data updates:
                - symbol: Symbol string
                - timestamp: Update timestamp
                - price: Current price
                - bid: Bid price (if available)
                - ask: Ask price (if available)
                - volume: Volume (if available)
                - other fields as available
                
        Raises:
            ConnectionError: If provider is not connected
        """
        pass

    @abstractmethod
    async def validate_connection(self) -> bool:
        """
        Validate that the provider is connected and ready.
        
        Returns:
            True if connected and ready, False otherwise
        """
        pass

    @abstractmethod
    async def validate_market_data_entitlements(self) -> Dict[str, bool]:
        """
        Validate market data entitlements for the account.
        
        Returns:
            Dictionary with entitlement status:
                - options_data: True if options data is available
                - realtime_quotes: True if real-time quotes are enabled
                - historical_data: True if historical data is accessible
                - account_type: 'paper' or 'live'
                
        Raises:
            ConnectionError: If provider is not connected
        """
        pass

    async def close(self) -> None:
        """
        Close connection and cleanup resources.
        
        This is a default implementation that does nothing.
        Providers can override if they need cleanup.
        """
        pass
