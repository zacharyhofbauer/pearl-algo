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
from pearlalgo.utils.telegram_alerts import TelegramAlerts


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
        
        # Status update task
        self.status_update_task: Optional[asyncio.Task] = None
        
        # Telegram alerts (for status updates)
        self.telegram_alerts: Optional[TelegramAlerts] = None
        self._initialize_telegram()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("ContinuousService initialized")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True
    
    def _initialize_telegram(self):
        """Initialize Telegram alerts for status updates."""
        import os
        alerts_config = self.config.get("alerts", {})
        telegram_config = alerts_config.get("telegram", {})
        
        bot_token = (
            telegram_config.get("bot_token") or 
            os.getenv("TELEGRAM_BOT_TOKEN", "")
        )
        chat_id_raw = (
            telegram_config.get("chat_id") or 
            os.getenv("TELEGRAM_CHAT_ID", "")
        )
        
        # Ensure chat_id is a string (Telegram API requires string)
        # Also handle template variables like "${TELEGRAM_CHAT_ID}"
        chat_id = str(chat_id_raw) if chat_id_raw else ""
        if chat_id.startswith("${") and chat_id.endswith("}"):
            # Template variable not resolved, try env var directly
            var_name = chat_id[2:-1]
            chat_id = str(os.getenv(var_name, ""))
        
        # Handle bot_token template variables too
        if bot_token and bot_token.startswith("${") and bot_token.endswith("}"):
            var_name = bot_token[2:-1]
            bot_token = os.getenv(var_name, "")
        
        enabled = telegram_config.get("enabled", False) or (bool(bot_token and chat_id))
        
        if enabled and bot_token and chat_id:
            try:
                # Log for debugging (mask sensitive data)
                logger.debug(
                    f"Initializing Telegram: bot_token={bot_token[:10]}..., "
                    f"chat_id={chat_id}, enabled={enabled}"
                )
                self.telegram_alerts = TelegramAlerts(
                    bot_token=str(bot_token),
                    chat_id=str(chat_id),
                    enabled=True,
                )
                if self.telegram_alerts.enabled:
                    logger.info(
                        f"Telegram alerts initialized for status updates "
                        f"(chat_id: {self.telegram_alerts.chat_id})"
                    )
                    # Test connection by sending a silent test (we'll catch errors in send methods)
                else:
                    logger.warning("Telegram alerts initialized but not enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize Telegram alerts: {e}", exc_info=True)
                self.telegram_alerts = None
        else:
            logger.debug(
                f"Telegram not enabled: bot_token={'set' if bot_token else 'missing'}, "
                f"chat_id={'set' if chat_id else 'missing'}"
            )
    
    async def _send_startup_notification(self):
        """Send startup notification to Telegram."""
        if not self.telegram_alerts:
            logger.debug("Telegram alerts not available, skipping startup notification")
            return
        
        try:
            logger.debug(f"Sending startup notification to chat_id: {self.telegram_alerts.chat_id}")
            workers_config = self.config.get("monitoring", {}).get("workers", {})
            futures_config = workers_config.get("futures", {})
            symbols = futures_config.get("symbols", ["NQ", "ES"])
            strategy = futures_config.get("strategy", "intraday_swing")
            interval = futures_config.get("interval", 60)
            
            message = (
                f"🚀 *Service Started*\n\n"
                f"*Status:* Monitoring Active\n"
                f"*Symbols:* {', '.join(symbols)}\n"
                f"*Strategy:* {strategy}\n"
                f"*Scan Interval:* {interval}s\n"
                f"*Health Check:* http://localhost:{self.health_port}/healthz\n\n"
                f"System is now monitoring markets 24/7. "
                f"You'll receive alerts for entry and exit signals."
            )
            success = await self.telegram_alerts.send_message(message)
            if success:
                logger.info("Startup notification sent to Telegram")
            else:
                logger.warning(
                    "Failed to send startup notification to Telegram. "
                    "Make sure you've started the bot by sending /start to it first."
                )
        except Exception as e:
            logger.warning(
                f"Failed to send startup notification: {e}. "
                "If you see 'Not Found', make sure you've sent /start to your bot first."
            )
    
    async def _send_status_update(self):
        """Send periodic status update to Telegram."""
        if not self.telegram_alerts:
            return
        
        try:
            uptime = datetime.now(timezone.utc) - self.start_time
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)
            uptime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            
            # Get buffer status
            buffer_status = {}
            if self.buffer_manager:
                for symbol in ["NQ", "ES"]:
                    if self.buffer_manager.has_buffer(symbol):
                        buffer_size = len(self.buffer_manager.get_buffer(symbol))
                        buffer_status[symbol] = buffer_size
            
            # Get worker status
            worker_status = "Running"
            if self.worker_pool:
                health = self.worker_pool.get_health_status()
                worker_status = health.get("status", "Unknown")
            
            buffer_info = "\n".join([f"  • {sym}: {size} bars" for sym, size in buffer_status.items()])
            if not buffer_info:
                buffer_info = "  • Buffers initializing..."
            
            message = (
                f"📊 *Status Update*\n\n"
                f"*Uptime:* {uptime_str}\n"
                f"*Cycles Run:* {self.cycle_count}\n"
                f"*Worker Status:* {worker_status}\n\n"
                f"*Buffer Status:*\n{buffer_info}\n\n"
                f"System is running normally. Monitoring for signals..."
            )
            await self.telegram_alerts.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to send status update: {e}")
    
    async def _status_update_loop(self, interval: int = 600):
        """
        Periodic status update loop.
        
        Args:
            interval: Update interval in seconds (default: 600 = 10 minutes)
        """
        # Wait a bit before first update (let system initialize)
        await asyncio.sleep(60)  # Wait 1 minute after startup
        
        while not self.shutdown_requested:
            try:
                await self._send_status_update()
                # Wait for next update
                for _ in range(interval):
                    if self.shutdown_requested:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Error in status update loop: {e}")
                await asyncio.sleep(interval)
    
    async def _send_shutdown_notification(self, uptime: timedelta):
        """Send shutdown notification to Telegram."""
        if not self.telegram_alerts:
            return
        
        try:
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)
            uptime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            
            message = (
                f"🛑 *Service Stopped*\n\n"
                f"*Uptime:* {uptime_str}\n"
                f"*Total Cycles:* {self.cycle_count}\n\n"
                f"Service has been shut down gracefully."
            )
            await self.telegram_alerts.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to send shutdown notification: {e}")

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

        # Send startup notification
        await self._send_startup_notification()
        
        # Start periodic status updates (every 10 minutes)
        status_update_interval = self.config.get("monitoring", {}).get("status_update_interval", 600)
        self.status_update_task = asyncio.create_task(
            self._status_update_loop(interval=status_update_interval)
        )

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

        # Stop status update task
        if self.status_update_task:
            self.status_update_task.cancel()
            try:
                await self.status_update_task
            except asyncio.CancelledError:
                pass

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
        
        # Send shutdown notification
        await self._send_shutdown_notification(uptime)
        
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
