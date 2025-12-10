"""
Continuous Service - Enhanced 24/7 service with worker pool orchestration.

Replaces scripts/signal_generation_service.py with:
- Worker pool architecture
- Health check endpoints
- Graceful degradation
- State persistence
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.live.langgraph_trader import LangGraphTrader
from pearlalgo.monitoring.worker_pool import WorkerPool, WorkerStatus
from pearlalgo.monitoring.data_feed_manager import DataFeedManager
from pearlalgo.monitoring.health import HealthChecker, run_health_server
from pearlalgo.data_providers.buffer_manager import BufferManager
from pearlalgo.utils.market_hours import is_market_open


class ContinuousService:
    """
    Enhanced 24/7 continuous service for futures trading.

    Manages:
    - Futures worker for continuous NQ/ES monitoring
    - Data feed management
    - Health monitoring
    - Graceful shutdown
    - Telegram alerts for entry and exit signals
    """

    def __init__(
        self,
        config: Dict,
        log_file: Optional[str] = None,
        health_port: int = 8080,
    ):
        """
        Initialize continuous service.

        Args:
            config: Configuration dictionary
            log_file: Log file path (optional)
            health_port: Health check server port
        """
        self.config = config
        self.log_file = log_file
        self.health_port = health_port

        # Service state
        self.shutdown_requested = False
        self.start_time = datetime.now(timezone.utc)
        self.cycle_count = 0

        # Initialize components
        self.worker_pool = WorkerPool(
            max_workers=config.get("monitoring", {}).get("max_workers", 10),
            max_restarts=config.get("monitoring", {}).get("max_restarts", 10),
        )

        # Data feed manager (will be initialized with data provider)
        self.data_feed_manager: Optional[DataFeedManager] = None

        # Buffer manager
        self.buffer_manager = BufferManager(
            max_bars=config.get("monitoring", {}).get("buffer_size", 1000),
            persistence_dir=Path("data/buffers"),
        )

        # Health checker
        self.health_checker = HealthChecker(
            worker_pool=self.worker_pool,
            data_feed_manager=self.data_feed_manager,
        )

        # Health server task
        self.health_server_task: Optional[asyncio.Task] = None

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("ContinuousService initialized")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True

    async def _initialize_data_provider(self):
        """Initialize data provider and feed manager."""
        try:
            from pearlalgo.data_providers.polygon_provider import PolygonDataProvider
            from pearlalgo.data_providers.dummy_provider import DummyDataProvider
            import os

            polygon_api_key = (
                self.config.get("data", {})
                .get("fallback", {})
                .get("polygon", {})
                .get("api_key")
            ) or os.getenv("POLYGON_API_KEY")

            provider = None
            use_dummy = False

            if polygon_api_key:
                try:
                    # Initialize Polygon provider
                    provider = PolygonDataProvider(api_key=polygon_api_key)
                    logger.info("Polygon provider initialized (will validate on first request)")
                except Exception as e:
                    logger.warning(f"Failed to initialize Polygon provider: {e}, using dummy provider")
                    use_dummy = True
            else:
                logger.info("No Polygon API key found, using dummy data provider")
                use_dummy = True

            # Fall back to dummy provider if needed
            if use_dummy:
                # Get symbols from config for dummy provider
                futures_symbols = (
                    self.config.get("monitoring", {})
                    .get("workers", {})
                    .get("futures", {})
                    .get("symbols", [])
                )
                all_symbols = futures_symbols or ["NQ"]
                provider = DummyDataProvider(symbols=all_symbols)
                logger.info("Using DummyDataProvider (for testing/development)")

            if provider:
                self.data_feed_manager = DataFeedManager(
                    data_provider=provider,
                    rate_limit=self.config.get("monitoring", {})
                    .get("data_feeds", {})
                    .get("polygon", {})
                    .get("rate_limit", 5),
                    reconnect_delay=self.config.get("monitoring", {})
                    .get("data_feeds", {})
                    .get("polygon", {})
                    .get("reconnect_delay", 5.0),
                )
                self.buffer_manager.data_provider = provider
                self.health_checker.data_feed_manager = self.data_feed_manager
                logger.info("Data provider initialized")
            else:
                logger.error("Failed to initialize any data provider")
        except Exception as e:
            logger.error(f"Error initializing data provider: {e}", exc_info=True)
            # Last resort: use dummy provider
            try:
                from pearlalgo.data_providers.dummy_provider import DummyDataProvider
                futures_symbols = (
                    self.config.get("monitoring", {})
                    .get("workers", {})
                    .get("futures", {})
                    .get("symbols", [])
                )
                all_symbols = futures_symbols or ["NQ"]
                provider = DummyDataProvider(symbols=all_symbols)
                self.data_feed_manager = DataFeedManager(
                    data_provider=provider,
                    rate_limit=5,
                    reconnect_delay=5.0,
                )
                self.buffer_manager.data_provider = provider
                logger.warning("Using DummyDataProvider as fallback")
            except Exception as fallback_error:
                logger.error(f"Even fallback provider failed: {fallback_error}")

    async def _futures_worker(
        self, symbols: List[str], strategy: str, interval: int
    ) -> None:
        """
        Worker for futures intraday scanning.

        Args:
            symbols: List of futures symbols (e.g., ["NQ", "ES"])
            strategy: Strategy name
            interval: Scan interval in seconds
        """
        logger.info(
            f"Futures worker started: symbols={symbols}, strategy={strategy}, "
            f"interval={interval}s"
        )

        # Initialize trader for futures
        trader = LangGraphTrader(
            symbols=symbols,
            strategy=strategy,
            mode="paper",
            config_path=None,
        )
        trader.config = self.config

        # Pass buffer manager to agents
        if self.buffer_manager:
            trader.workflow.market_data_agent.buffer_manager = self.buffer_manager
            trader.workflow.quant_research_agent.buffer_manager = self.buffer_manager

        # Backfill buffers on startup
        if self.data_feed_manager and self.buffer_manager:
            logger.info(f"Backfilling buffers for {symbols}...")
            await self.buffer_manager.backfill_multiple(
                symbols,
                timeframe="15m",
                days=30,
                data_provider=self.data_feed_manager.data_provider,
            )

        while not self.shutdown_requested:
            try:
                # Check market hours
                if not is_market_open():
                    logger.debug("Market closed, waiting...")
                    await asyncio.sleep(60)  # Check every minute
                    continue

                # Run trading cycle
                logger.info(f"Running futures cycle for {symbols}")
                await trader.workflow.run_cycle()
                self.cycle_count += 1

                # Wait for next cycle
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"Error in futures worker: {e}", exc_info=True)
                await asyncio.sleep(interval)  # Wait before retry

    async def start(self) -> None:
        """Start the continuous service."""
        logger.info("=" * 60)
        logger.info("Starting Continuous Service")
        logger.info("=" * 60)

        # Initialize data provider
        await self._initialize_data_provider()

        # Start health check server
        if self.config.get("monitoring", {}).get("health", {}).get("enabled", True):
            self.health_server_task = asyncio.create_task(
                run_health_server(
                    self.health_checker,
                    port=self.health_port,
                )
            )

        # Start worker pool health checks
        await self.worker_pool.start_health_checks()

        # Register futures worker from config
        workers_config = self.config.get("monitoring", {}).get("workers", {})

        # Futures worker
        futures_config = workers_config.get("futures", {})
        if futures_config.get("enabled", False):
            symbols = futures_config.get("symbols", ["NQ", "ES"])
            strategy = futures_config.get("strategy", "intraday_swing")
            interval = futures_config.get("interval", 60)

            self.worker_pool.register_worker(
                "futures_scanner",
                "futures",
                self._futures_worker,
                symbols=symbols,
                strategy=strategy,
                interval=interval,
            )

        logger.info(f"Registered {len(self.worker_pool.workers)} workers")

        # Wait for shutdown
        try:
            while not self.shutdown_requested:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Service interrupted by user")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("=" * 60)
        logger.info("Shutting down Continuous Service")
        logger.info("=" * 60)

        # Stop health server
        if self.health_server_task:
            self.health_server_task.cancel()
            try:
                await self.health_server_task
            except asyncio.CancelledError:
                pass

        # Stop all workers
        await self.worker_pool.stop_all_workers()

        # Disconnect data feed (this should close provider sessions)
        if self.data_feed_manager:
            await self.data_feed_manager.disconnect()
            # Explicitly ensure provider session is closed
            if hasattr(self.data_feed_manager, 'data_provider') and self.data_feed_manager.data_provider:
                if hasattr(self.data_feed_manager.data_provider, 'close'):
                    try:
                        await self.data_feed_manager.data_provider.close()
                    except Exception as e:
                        logger.debug(f"Error closing data provider session: {e}")

        # Save buffers
        self.buffer_manager.save_all_buffers()

        uptime = datetime.now(timezone.utc) - self.start_time
        logger.info(f"Service stopped: uptime={uptime}, cycles={self.cycle_count}")


def main():
    """CLI entry point for continuous service."""
    import argparse
    import yaml
    from pathlib import Path
    
    # Load .env file to get environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv not required, but helpful

    parser = argparse.ArgumentParser(
        description="24/7 Continuous Trading Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config/config.yaml",
        help="Path to config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Path to log file (default: logs/continuous_service.log)",
    )
    parser.add_argument(
        "--health-port",
        type=int,
        default=8080,
        help="Health check server port (default: 8080)",
    )

    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return

    with open(config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    # Default log file
    if not args.log_file:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        args.log_file = str(log_dir / "continuous_service.log")

    # Create and start service
    service = ContinuousService(
        config=config,
        log_file=args.log_file,
        health_port=args.health_port,
    )

    try:
        asyncio.run(service.start())
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
