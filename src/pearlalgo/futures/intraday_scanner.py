"""
Futures Intraday Scanner - High-frequency scanning for NQ and ES futures.

Provides:
- Dedicated scanner for NQ and ES
- High-frequency scanning (1-5 minute intervals)
- Real-time data ingestion from Massive
- Strategy execution: intraday_swing, sr, ma_cross
- Signal generation with entry/exit logic
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
from pearlalgo.data_providers.buffer_manager import BufferManager
from pearlalgo.monitoring.data_feed_manager import DataFeedManager
from pearlalgo.utils.market_hours import is_market_open


class FuturesIntradayScanner:
    """
    Scanner for futures intraday trading (NQ, ES).

    Designed for high-frequency scanning with 1-5 minute intervals.
    """

    def __init__(
        self,
        symbols: List[str],
        strategy: str = "intraday_swing",
        config: Optional[Dict] = None,
        data_feed_manager: Optional[DataFeedManager] = None,
        buffer_manager: Optional[BufferManager] = None,
    ):
        """
        Initialize futures intraday scanner.

        Args:
            symbols: List of futures symbols (e.g., ["NQ", "ES"])
            strategy: Strategy name (default: "intraday_swing")
            config: Configuration dictionary
            data_feed_manager: DataFeedManager instance (optional)
            buffer_manager: BufferManager instance (optional)
        """
        self.symbols = symbols
        self.strategy = strategy
        self.config = config or {}
        self.data_feed_manager = data_feed_manager
        self.buffer_manager = buffer_manager

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
            f"FuturesIntradayScanner initialized: symbols={symbols}, "
            f"strategy={strategy}"
        )

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
            logger.info(f"Running futures scan for {self.symbols}")

            # Run trading cycle
            state = await self.trader.workflow.run_cycle()

            # Extract results
            results = {
                "status": "success",
                "symbols": self.symbols,
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
            logger.error(f"Error in futures scan: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def scan_continuous(
        self, interval: int = 60, shutdown_check: Optional[callable] = None
    ) -> None:
        """
        Run continuous scanning with specified interval.

        Args:
            interval: Scan interval in seconds (default: 60)
            shutdown_check: Optional callable that returns True to stop
        """
        logger.info(
            f"Starting continuous futures scanning: "
            f"symbols={self.symbols}, interval={interval}s"
        )

        # Backfill buffers on startup
        if self.buffer_manager and self.data_feed_manager:
            logger.info(f"Backfilling buffers for {self.symbols}...")
            await self.buffer_manager.backfill_multiple(
                self.symbols,
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
                logger.info(f"Futures scan cycle #{cycle_count}")

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
            logger.info(f"Futures scanner stopped after {cycle_count} cycles")
