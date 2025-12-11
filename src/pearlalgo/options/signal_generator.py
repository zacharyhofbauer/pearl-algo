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
        buffer_manager=None,  # BufferManager for historical data
    ):
        """
        Initialize signal generator.
        
        Args:
            universe: EquityUniverse instance
            strategy: OptionsStrategy instance
            data_provider: Data provider for fetching options chains
            buffer_manager: BufferManager for historical price data (optional)
        """
        self.universe = universe
        self.strategy = strategy
        self.data_provider = data_provider
        self.buffer_manager = buffer_manager
        
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
            
            # Underlying price already fetched above
            if not latest_bar or underlying_price <= 0:
                return None
            
            # Get historical data for multi-day pattern detection
            historical_data = None
            if self.buffer_manager and self.buffer_manager.has_buffer(symbol):
                buffer = self.buffer_manager.get_buffer(symbol)
                # Convert buffer to list of dicts for strategy
                historical_data = [
                    {
                        "timestamp": bar.get("timestamp"),
                        "open": bar.get("open", 0),
                        "high": bar.get("high", 0),
                        "low": bar.get("low", 0),
                        "close": bar.get("close", 0),
                        "volume": bar.get("volume", 0),
                    }
                    for bar in buffer
                ]
            
            # Analyze with strategy (pass historical data if strategy supports it)
            if hasattr(self.strategy, 'analyze') and 'historical_data' in self.strategy.analyze.__code__.co_varnames:
                signal = self.strategy.analyze(options_chain, underlying_price, historical_data=historical_data)
            else:
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
