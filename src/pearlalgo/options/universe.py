"""
Equity Universe Management

Manages list of optionable equities and filters by market cap, volume, liquidity.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class EquityUniverse:
    """
    Manages universe of optionable equities.
    
    Filters symbols by:
    - Market cap
    - Volume
    - Liquidity
    - Option availability
    """
    
    def __init__(
        self,
        symbols: List[str],
        filters: Optional[Dict] = None,
    ):
        """
        Initialize equity universe.
        
        Args:
            symbols: List of equity symbols (e.g., ['SPY', 'QQQ', 'AAPL'])
            filters: Optional filters dict with:
                - min_market_cap: Minimum market cap (default: None)
                - min_volume: Minimum daily volume (default: None)
                - min_liquidity: Minimum liquidity score (default: None)
        """
        self.symbols = symbols
        self.filters = filters or {}
        
        # Cache for optionable symbols
        self._optionable_cache: Optional[List[str]] = None
        
        logger.info(f"EquityUniverse initialized with {len(symbols)} symbols")
    
    def get_optionable_symbols(self) -> List[str]:
        """
        Get list of optionable symbols.
        
        Returns:
            List of symbols that have options available
        """
        if self._optionable_cache is not None:
            return self._optionable_cache
        
        # For now, assume all provided symbols are optionable
        # In production, this would query the data provider to verify
        self._optionable_cache = self.symbols.copy()
        
        return self._optionable_cache
    
    def update_universe(self, new_symbols: Optional[List[str]] = None) -> None:
        """
        Update universe with new symbols.
        
        Args:
            new_symbols: New list of symbols (if None, refreshes current)
        """
        if new_symbols is not None:
            self.symbols = new_symbols
        
        # Clear cache to force refresh
        self._optionable_cache = None
        
        logger.info(f"Universe updated: {len(self.symbols)} symbols")
    
    def add_symbol(self, symbol: str) -> None:
        """
        Add a symbol to the universe.
        
        Args:
            symbol: Symbol to add
        """
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            self._optionable_cache = None  # Clear cache
            logger.debug(f"Added symbol to universe: {symbol}")
    
    def remove_symbol(self, symbol: str) -> None:
        """
        Remove a symbol from the universe.
        
        Args:
            symbol: Symbol to remove
        """
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            self._optionable_cache = None  # Clear cache
            logger.debug(f"Removed symbol from universe: {symbol}")
    
    def filter_by_volume(self, min_volume: int) -> List[str]:
        """
        Filter symbols by minimum volume.
        
        Args:
            min_volume: Minimum daily volume
            
        Returns:
            Filtered list of symbols
        """
        # In production, this would query volume data
        # For now, return all symbols
        return self.symbols
    
    def filter_by_market_cap(self, min_market_cap: float) -> List[str]:
        """
        Filter symbols by minimum market cap.
        
        Args:
            min_market_cap: Minimum market cap in dollars
            
        Returns:
            Filtered list of symbols
        """
        # In production, this would query market cap data
        # For now, return all symbols
        return self.symbols
    
    def get_universe_size(self) -> int:
        """Get current universe size."""
        return len(self.symbols)
