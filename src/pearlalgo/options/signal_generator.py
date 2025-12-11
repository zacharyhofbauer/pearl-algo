"""
Options Signal Generator

Generates trading signals from options chain analysis.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.options.strategy import OptionsStrategy, create_strategy
from pearlalgo.options.universe import EquityUniverse


class OptionsSignalGenerator:
    """
    Generates trading signals from options analysis.
    """
    
    def __init__(
        self,
        universe: EquityUniverse,
        strategy: OptionsStrategy,
        data_provider=None,  # MassiveDataProvider
    ):
        """
        Initialize signal generator.
        
        Args:
            universe: EquityUniverse instance
            strategy: OptionsStrategy instance
            data_provider: Data provider for fetching options chains
        """
        self.universe = universe
        self.strategy = strategy
        self.data_provider = data_provider
        
        logger.info(
            f"OptionsSignalGenerator initialized: "
            f"universe_size={universe.get_universe_size()}, "
            f"strategy={strategy.name}"
        )
    
    async def generate_signals(self) -> List[Dict]:
        """
        Generate signals for all symbols in universe.
        
        Returns:
            List of signal dictionaries
        """
        signals = []
        symbols = self.universe.get_optionable_symbols()
        
        for symbol in symbols:
            try:
                signal = await self._generate_signal_for_symbol(symbol)
                if signal and signal.get("side") != "flat":
                    signals.append(signal)
            except Exception as e:
                logger.warning(f"Error generating signal for {symbol}: {e}")
                continue
        
        logger.info(f"Generated {len(signals)} options signals")
        return signals
    
    async def _generate_signal_for_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Generate signal for a single symbol.
        
        Args:
            symbol: Equity symbol
            
        Returns:
            Signal dictionary or None
        """
        if not self.data_provider:
            logger.warning("No data provider available for options signal generation")
            return None
        
        try:
            # Fetch options chain
            options_chain = await self.data_provider.get_options_chain(symbol)
            
            if not options_chain:
                return None
            
            # Get underlying price
            latest_bar = await self.data_provider.get_latest_bar(symbol)
            if not latest_bar:
                return None
            
            underlying_price = latest_bar.get("close", 0)
            
            # Analyze with strategy
            signal = self.strategy.analyze(options_chain, underlying_price)
            
            # Add symbol and metadata
            if signal.get("side") != "flat":
                signal["symbol"] = symbol
                signal["underlying_price"] = underlying_price
                signal["strategy_name"] = self.strategy.name
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return None
