"""
Options Swing Scanner

High-level scanner for options swing trading setups.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.strategy import create_strategy
from pearlalgo.options.signal_generator import OptionsSignalGenerator
from pearlalgo.utils.market_hours import is_market_open
from pearlalgo.options.features import OptionsFeatureComputer


class OptionsSwingScanner:
    """
    Scanner for options swing trading setups.
    
    Scans equity options for swing trade opportunities using
    volatility compression, breakouts, and other patterns.
    """
    
    def __init__(
        self,
        universe: EquityUniverse,
        strategy: str = "swing_momentum",
        config: Optional[Dict] = None,
        data_provider=None,  # IBKRDataProvider
        buffer_manager=None,  # BufferManager for historical data
    ):
        """
        Initialize options swing scanner.
        
        Args:
            universe: EquityUniverse instance
            strategy: Strategy name (default: "swing_momentum")
            config: Configuration dictionary
            data_provider: Data provider for fetching options chains
            buffer_manager: BufferManager for historical price data (optional)
        """
        self.universe = universe
        self.strategy_name = strategy
        self.config = config or {}
        self.data_provider = data_provider
        self.buffer_manager = buffer_manager
        
        # Initialize feature computer for entry criteria
        self.feature_computer = OptionsFeatureComputer(config=self.config.get("features", {}))
        
        # Load entry criteria parameters from config
        entry_config = self.config.get("entry_criteria", {})
        self.entry_params = {
            "min_confidence": entry_config.get("min_confidence", 0.6),
            "volatility_compression_threshold": entry_config.get("volatility_compression_threshold", 0.20),
            "breakout_volume_multiplier": entry_config.get("breakout_volume_multiplier", 1.5),
            "support_resistance_tolerance": entry_config.get("support_resistance_tolerance", 0.02),
        }
        
        # Position sizing parameters
        position_config = self.config.get("position_sizing", {})
        self.position_params = {
            "max_position_size": position_config.get("max_position_size", 5),  # Max contracts for swing
            "base_position_size": position_config.get("base_position_size", 1),
            "risk_per_trade": position_config.get("risk_per_trade", 0.015),  # 1.5% for swing trades
        }
        
        # Risk control parameters
        risk_config = self.config.get("risk_controls", {})
        self.risk_params = {
            "max_delta_exposure": risk_config.get("max_delta_exposure", 100),  # Max delta exposure
            "max_position_value": risk_config.get("max_position_value", 10000),  # Max $ per position
            "max_total_exposure": risk_config.get("max_total_exposure", 50000),  # Max total exposure
        }
        
        # Create strategy instance
        strategy_params = self.config.get("strategy_params", {})
        self.strategy = create_strategy(strategy, strategy_params)
        
        # Create signal generator with buffer manager for historical context
        self.signal_generator = OptionsSignalGenerator(
            universe=universe,
            strategy=self.strategy,
            data_provider=data_provider,
            buffer_manager=buffer_manager,
        )
        
        logger.info(
            f"OptionsSwingScanner initialized: "
            f"universe_size={universe.get_universe_size()}, "
            f"strategy={strategy}"
        )
    
    async def scan(self) -> Dict:
        """
        Run a single scan cycle.
        
        Returns:
            Dictionary with scan results
        """
        if not is_market_open():
            logger.debug("Market closed, skipping options scan")
            return {"status": "skipped", "reason": "market_closed"}
        
        try:
            logger.info(f"Running options scan for {self.universe.get_universe_size()} symbols")
            
            # Generate signals
            signals = await self.signal_generator.generate_signals()
            
            # Format results
            results = {
                "status": "success",
                "signals_generated": len(signals),
                "signals": signals,
            }
            
            return results
            
        except Exception as e:
            logger.error(f"Error in options scan: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
    
    def _apply_entry_criteria(self, signals: List[Dict]) -> List[Dict]:
        """
        Apply entry criteria filters to signals.
        
        Args:
            signals: List of raw signals
            
        Returns:
            Filtered signals that meet entry criteria
        """
        filtered = []
        min_confidence = self.entry_params.get("min_confidence", 0.6)
        
        for signal in signals:
            # Filter by minimum confidence
            if signal.get("confidence", 0) < min_confidence:
                continue
            
            # Additional entry criteria can be added here:
            # - Volatility compression check
            # - Breakout confirmation
            # - Support/resistance levels
            
            filtered.append(signal)
        
        logger.debug(f"Entry criteria: {len(signals)} -> {len(filtered)} signals")
        return filtered
    
    def _add_position_sizing(self, signal: Dict) -> Dict:
        """
        Add position sizing to signal based on risk parameters.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Signal with position_size added
        """
        entry_price = signal.get("entry_price", 0)
        if entry_price <= 0:
            signal["position_size"] = self.position_params.get("base_position_size", 1)
            return signal
        
        # Calculate position size based on risk per trade
        base_size = self.position_params.get("base_position_size", 1)
        max_size = self.position_params.get("max_position_size", 5)
        
        # Adjust size based on confidence
        confidence = signal.get("confidence", 0.5)
        size_multiplier = 0.5 + (confidence - 0.5) * 1.5  # 0.5 conf = 0.5x, 1.0 conf = 1.5x
        
        position_size = int(base_size * size_multiplier)
        position_size = min(position_size, max_size)
        position_size = max(position_size, 1)
        
        signal["position_size"] = position_size
        signal["risk_amount"] = entry_price * position_size * self.position_params.get("risk_per_trade", 0.015)
        
        return signal
    
    def _check_risk_controls(self, signal: Dict, current_total_exposure: float) -> bool:
        """
        Check if signal passes risk controls.
        
        Args:
            signal: Signal dictionary
            current_total_exposure: Current total exposure across all positions
            
        Returns:
            True if signal passes risk controls, False otherwise
        """
        entry_price = signal.get("entry_price", 0)
        position_size = signal.get("position_size", 0)
        position_value = entry_price * position_size
        
        # Check max position value
        max_position_value = self.risk_params.get("max_position_value", 10000)
        if position_value > max_position_value:
            logger.debug(f"Position value ${position_value:.2f} exceeds max ${max_position_value:.2f}")
            return False
        
        # Check max total exposure
        max_total_exposure = self.risk_params.get("max_total_exposure", 50000)
        new_total_exposure = current_total_exposure + position_value
        if new_total_exposure > max_total_exposure:
            logger.debug(f"Total exposure ${new_total_exposure:.2f} would exceed max ${max_total_exposure:.2f}")
            return False
        
        # Check delta exposure (if delta is provided)
        delta = signal.get("delta", 0)
        if delta != 0:
            max_delta_exposure = self.risk_params.get("max_delta_exposure", 100)
            delta_exposure = abs(delta * position_size)
            if delta_exposure > max_delta_exposure:
                logger.debug(f"Delta exposure {delta_exposure:.2f} exceeds max {max_delta_exposure:.2f}")
                return False
        
        return True
    
    async def scan_continuous(
        self, interval: int = 900, shutdown_check: Optional[callable] = None
    ) -> None:
        """
        Run continuous scanning with specified interval.
        
        Args:
            interval: Scan interval in seconds (default: 900 = 15 minutes)
            shutdown_check: Optional callable that returns True to stop
        """
        logger.info(
            f"Starting continuous options scanning: "
            f"universe_size={self.universe.get_universe_size()}, "
            f"interval={interval}s"
        )
        
        # Backfill buffers on startup for historical context
        if self.buffer_manager and self.data_provider:
            symbols = self.universe.get_optionable_symbols()
            logger.info(f"Backfilling buffers for {len(symbols)} symbols...")
            await self.buffer_manager.backfill_multiple(
                symbols,
                timeframe="15m",
                days=30,
                data_provider=self.data_provider,
            )
        
        cycle_count = 0
        
        try:
            while True:
                if shutdown_check and shutdown_check():
                    logger.info("Shutdown requested, stopping scanner")
                    break
                
                cycle_count += 1
                logger.info(f"Options scan cycle #{cycle_count}")
                
                # Run scan
                results = await self.scan()
                logger.debug(f"Scan results: {results}")
                
                # Wait for next cycle
                await asyncio.sleep(interval)
                
        except KeyboardInterrupt:
            logger.info("Scanner interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in scanner: {e}", exc_info=True)
            raise
        finally:
            logger.info(f"Options scanner stopped after {cycle_count} cycles")
