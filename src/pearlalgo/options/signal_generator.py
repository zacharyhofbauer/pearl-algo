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
        
        # Delta targeting parameters (from config)
        self.delta_target = None  # Will be set from config if provided
        self.max_delta_exposure = 100  # Max delta exposure per position
        
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
            # Fetch latest underlying price
            latest_bar = await self.data_provider.get_latest_bar(symbol)
            if not latest_bar:
                return None
            
            underlying_price = latest_bar.get("close", 0)
            if underlying_price <= 0:
                return None
            
            # Fetch options chain
            options_chain = await self.data_provider.get_options_chain(symbol)
            
            if not options_chain:
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
                
                # Add delta targeting if option contract is specified
                signal = self._add_delta_targeting(signal, options_chain)
                
                # Apply risk controls
                signal = self._apply_risk_controls(signal)
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return None
    
    def _add_delta_targeting(self, signal: Dict, options_chain: List[Dict]) -> Dict:
        """
        Add delta targeting to signal.
        
        Args:
            signal: Signal dictionary
            options_chain: Options chain for delta calculation
            
        Returns:
            Signal with delta information added
        """
        option_symbol = signal.get("option_symbol")
        if not option_symbol:
            return signal
        
        # Find the option in the chain
        option = None
        for opt in options_chain:
            if opt.get("symbol") == option_symbol:
                option = opt
                break
        
        if not option:
            return signal
        
        # Calculate approximate delta based on option type and moneyness
        strike = option.get("strike", 0)
        underlying_price = signal.get("underlying_price", 0)
        option_type = option.get("option_type", "").lower()
        
        if strike > 0 and underlying_price > 0:
            # Simple delta approximation: moneyness-based
            moneyness = underlying_price / strike if strike > 0 else 1.0
            
            if option_type == "call":
                # Call delta: higher for ITM, lower for OTM
                # Rough approximation: 0.5 at ATM, approaches 1.0 deep ITM, 0.0 deep OTM
                if moneyness >= 1.0:
                    delta = min(0.95, 0.5 + (moneyness - 1.0) * 0.5)
                else:
                    delta = max(0.05, 0.5 - (1.0 - moneyness) * 0.5)
            else:  # put
                # Put delta: negative, higher magnitude for ITM
                if moneyness <= 1.0:
                    delta = max(-0.95, -0.5 - (1.0 - moneyness) * 0.5)
                else:
                    delta = min(-0.05, -0.5 + (moneyness - 1.0) * 0.5)
            
            signal["delta"] = delta
            signal["moneyness"] = moneyness
        
        return signal
    
    def _apply_risk_controls(self, signal: Dict) -> Dict:
        """
        Apply risk controls to signal.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Signal with risk controls applied (may be modified or filtered)
        """
        # Check max delta exposure
        delta = signal.get("delta", 0)
        position_size = signal.get("position_size", 1)
        delta_exposure = abs(delta * position_size)
        
        if delta_exposure > self.max_delta_exposure:
            # Reduce position size to meet delta exposure limit
            max_size = int(self.max_delta_exposure / abs(delta)) if delta != 0 else position_size
            signal["position_size"] = max(1, max_size)
            signal["delta_exposure"] = abs(delta * signal["position_size"])
            logger.debug(f"Reduced position size to meet delta exposure limit: {delta_exposure} -> {signal['delta_exposure']}")
        else:
            signal["delta_exposure"] = delta_exposure
        
        return signal
