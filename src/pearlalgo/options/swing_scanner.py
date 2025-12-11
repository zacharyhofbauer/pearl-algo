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
        data_provider=None,  # MassiveDataProvider
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
