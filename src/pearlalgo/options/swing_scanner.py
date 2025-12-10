"""
Options Swing Scanner - Broad-market equity scanning for options.

Provides:
- Broad-market equity scanning (S&P 500, NASDAQ 100)
- Lower frequency (15-60 minute intervals)
- Options chain fetching via Polygon
- Strategy execution: swing-specific strategies
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

from pearlalgo.live.langgraph_trader import LangGraphTrader
from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.chain_filter import OptionsChainFilter
from pearlalgo.data_providers.buffer_manager import BufferManager
from pearlalgo.monitoring.data_feed_manager import DataFeedManager
from pearlalgo.utils.market_hours import is_market_open


class OptionsSwingScanner:
    """
    Scanner for options swing trading.

    Designed for lower-frequency scanning (15-60 minute intervals)
    with broad-market equity coverage.
    """

    def __init__(
        self,
        universe: EquityUniverse,
        strategy: str = "swing_momentum",
        config: Optional[Dict] = None,
        data_feed_manager: Optional[DataFeedManager] = None,
        buffer_manager: Optional[BufferManager] = None,
        chain_filter: Optional[OptionsChainFilter] = None,
    ):
        """
        Initialize options swing scanner.

        Args:
            universe: EquityUniverse instance
            strategy: Strategy name (default: "swing_momentum")
            config: Configuration dictionary
            data_feed_manager: DataFeedManager instance (optional)
            buffer_manager: BufferManager instance (optional)
            chain_filter: OptionsChainFilter instance (optional)
        """
        self.universe = universe
        self.strategy = strategy
        self.config = config or {}
        self.data_feed_manager = data_feed_manager
        self.buffer_manager = buffer_manager
        self.chain_filter = chain_filter or OptionsChainFilter()

        # Get symbols from universe
        symbols = universe.get_symbols()

        # Initialize trader
        self.trader = LangGraphTrader(
            symbols=symbols,
            strategy=strategy,
            mode="paper",
            config_path=None,
        )
        self.trader.config = config

        # Pass buffer manager to agents if available
        if self.buffer_manager:
            if hasattr(self.trader.workflow.market_data_agent, "buffer_manager"):
                self.trader.workflow.market_data_agent.buffer_manager = self.buffer_manager
            if hasattr(self.trader.workflow.quant_research_agent, "buffer_manager"):
                self.trader.workflow.quant_research_agent.buffer_manager = self.buffer_manager

        logger.info(
            f"OptionsSwingScanner initialized: {len(symbols)} symbols, "
            f"strategy={strategy}"
        )

    async def fetch_options_chain(
        self, underlying_symbol: str
    ) -> Optional[List[Dict]]:
        """
        Fetch options chain for an underlying symbol.

        Args:
            underlying_symbol: Underlying stock symbol

        Returns:
            List of option contracts or None on error
        """
        if not self.data_feed_manager:
            return None

        try:
            # Use Polygon provider to fetch options chain
            provider = self.data_feed_manager.data_provider
            if hasattr(provider, "get_options_chain"):
                chain = await provider.get_options_chain(underlying_symbol)
                return chain
        except Exception as e:
            logger.error(f"Error fetching options chain for {underlying_symbol}: {e}")

        return None

    async def scan(self) -> Dict:
        """
        Run a single scan cycle.

        Returns:
            Dictionary with scan results
        """
        if not is_market_open():
            logger.debug("Market closed, skipping scan")
            return {"status": "skipped", "reason": "market_closed"}

        try:
            symbols = self.universe.get_symbols()
            logger.info(f"Running options scan for {len(symbols)} symbols")

            # Run trading cycle
            state = await self.trader.workflow.run_cycle()

            # Extract results
            results = {
                "status": "success",
                "symbols_scanned": len(symbols),
                "signals_generated": len(state.signals),
                "signals": {},
                "exits": {},
            }

            # Collect signals
            for symbol, signal in state.signals.items():
                if signal.side != "flat":
                    results["signals"][symbol] = {
                        "side": signal.side,
                        "confidence": signal.confidence,
                        "entry_price": signal.entry_price,
                        "stop_loss": signal.stop_loss,
                        "take_profit": signal.take_profit,
                    }

            # Check for exit signals
            for symbol, signal in state.signals.items():
                if signal.side == "flat" and "exit_type" in signal.indicators:
                    results["exits"][symbol] = {
                        "exit_type": signal.indicators.get("exit_type"),
                        "exit_reason": signal.reasoning,
                        "unrealized_pnl": signal.indicators.get("unrealized_pnl"),
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
            f"{self.universe.get_count()} symbols, interval={interval}s"
        )

        # Backfill buffers on startup
        if self.buffer_manager and self.data_feed_manager:
            symbols = self.universe.get_symbols()
            logger.info(f"Backfilling buffers for {len(symbols)} symbols...")
            await self.buffer_manager.backfill_multiple(
                symbols,
                timeframe="15m",
                days=30,
                data_provider=self.data_feed_manager.data_provider,
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
