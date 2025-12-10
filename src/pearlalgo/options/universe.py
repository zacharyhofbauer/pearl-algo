"""
Equity Universe Manager - Maintain scan target lists for options.

Provides:
- Maintain list of scan targets (SPY, QQQ, individual stocks)
- Dynamic universe updates
- Sector/industry filtering
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
    Manages equity universe for options scanning.

    Maintains lists of symbols to scan, with support for:
    - Index ETFs (SPY, QQQ, etc.)
    - Individual stocks
    - Sector/industry filtering
    """

    # Common index ETFs
    INDEX_ETFS = ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "XLI", "XLP"]

    # Common liquid stocks (top 20 by volume)
    LIQUID_STOCKS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
        "META", "TSLA", "BRK.B", "V", "JNJ",
        "WMT", "JPM", "MA", "PG", "UNH",
        "HD", "DIS", "BAC", "PYPL", "NFLX",
    ]

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        include_etfs: bool = True,
        include_stocks: bool = True,
        max_symbols: Optional[int] = None,
    ):
        """
        Initialize equity universe.

        Args:
            symbols: Custom list of symbols (optional)
            include_etfs: Include index ETFs (default: True)
            include_stocks: Include liquid stocks (default: True)
            max_symbols: Maximum number of symbols (optional)
        """
        self.symbols: List[str] = []

        if symbols:
            # Use custom symbols
            self.symbols = symbols
        else:
            # Build from defaults
            if include_etfs:
                self.symbols.extend(self.INDEX_ETFS)
            if include_stocks:
                self.symbols.extend(self.LIQUID_STOCKS)

        # Limit if specified
        if max_symbols:
            self.symbols = self.symbols[:max_symbols]

        # Remove duplicates
        self.symbols = list(dict.fromkeys(self.symbols))

        logger.info(
            f"EquityUniverse initialized: {len(self.symbols)} symbols "
            f"(ETFs={include_etfs}, stocks={include_stocks})"
        )

    def add_symbol(self, symbol: str) -> None:
        """Add a symbol to the universe."""
        if symbol not in self.symbols:
            self.symbols.append(symbol)
            logger.debug(f"Added symbol to universe: {symbol}")

    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from the universe."""
        if symbol in self.symbols:
            self.symbols.remove(symbol)
            logger.debug(f"Removed symbol from universe: {symbol}")

    def get_symbols(self) -> List[str]:
        """Get all symbols in the universe."""
        return self.symbols.copy()

    def get_count(self) -> int:
        """Get number of symbols in universe."""
        return len(self.symbols)

    def filter_by_sector(self, sectors: List[str]) -> List[str]:
        """
        Filter symbols by sector (placeholder - would need sector data).

        Args:
            sectors: List of sector names

        Returns:
            Filtered list of symbols
        """
        # Placeholder - in production, you'd have sector mapping
        logger.warning("Sector filtering not implemented, returning all symbols")
        return self.symbols

    def update_from_config(self, config: Dict) -> None:
        """
        Update universe from configuration.

        Args:
            config: Configuration dictionary with 'universe' key
        """
        universe_config = config.get("universe", [])
        if universe_config:
            self.symbols = universe_config
            logger.info(f"Updated universe from config: {len(self.symbols)} symbols")
