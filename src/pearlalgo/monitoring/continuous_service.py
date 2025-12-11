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

# Load .env file early so environment variables are available
try:
    from dotenv import load_dotenv
    from pathlib import Path
    # Try to find .env file in project root (works when run as module)
    project_root = Path(__file__).parent.parent.parent.parent
    env_path = project_root / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        # Fallback to default behavior (current directory)
        load_dotenv()
except ImportError:
    pass  # dotenv not required, but helpful
except Exception as e:
    logger.warning(f"Could not load .env file: {e}")


class ContinuousService:
    """
    Enhanced 24/7 continuous service for options trading.
    
    Manages:
    - Options workers for continuous QQQ/SPY monitoring
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

        # Options signal tracker
        from pearlalgo.options.signal_tracker import OptionsSignalTracker
        self.options_signal_tracker = OptionsSignalTracker()
        
        # Health checker (will be updated with scanner references after workers start)
        self.health_checker = HealthChecker(
            worker_pool=self.worker_pool,
            data_feed_manager=self.data_feed_manager,
            options_signal_tracker=self.options_signal_tracker,
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
            options_config = workers_config.get("options", {})
            universe = options_config.get("universe", ["QQQ", "SPY"])
            strategy = options_config.get("strategy", "swing_momentum")
            interval = options_config.get("interval", 900)
            
            # Format message - use simple formatting to avoid Markdown parsing issues
            symbols_str = ', '.join(universe)
            message = (
                "🚀 *Service Started*\n\n"
                "*Status:* Monitoring Active\n"
                f"*Symbols:* {symbols_str}\n"
                f"*Strategy:* {strategy}\n"
                f"*Scan Interval:* {interval}s\n"
                f"*Health Check:* localhost:{self.health_port}/healthz\n\n"
                "System is now monitoring markets 24/7. "
                "You'll receive alerts for entry and exit signals."
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
                # Get symbols from options config
                workers_config = self.config.get("monitoring", {}).get("workers", {})
                options_config = workers_config.get("options", {})
                symbols = options_config.get("universe", ["QQQ", "SPY"])
                for symbol in symbols:
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
                "📊 *Status Update*\n\n"
                f"*Uptime:* {uptime_str}\n"
                f"*Cycles Run:* {self.cycle_count}\n"
                f"*Worker Status:* {worker_status}\n\n"
                f"*Buffer Status:*\n{buffer_info}\n\n"
                "System is running normally. Monitoring for signals..."
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
                "🛑 *Service Stopped*\n\n"
                f"*Uptime:* {uptime_str}\n"
                f"*Total Cycles:* {self.cycle_count}\n\n"
                "Service has been shut down gracefully."
            )
            await self.telegram_alerts.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to send shutdown notification: {e}")

    async def _initialize_data_provider(self):
        """Initialize data provider and feed manager."""
        try:
            from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider
            from pearlalgo.config.settings import get_settings

            # Get IBKR settings from config or environment
            settings = get_settings()
            
            # Get IBKR connection settings from config if available
            ibkr_config = self.config.get("data", {}).get("fallback", {}).get("ibkr", {})
            host = ibkr_config.get("host") or settings.ib_host
            port = ibkr_config.get("port") or settings.ib_port
            client_id = ibkr_config.get("client_id") or settings.ib_data_client_id or settings.ib_client_id

            logger.info(
                f"Initializing IBKR data provider: host={host}, port={port}, client_id={client_id}"
            )

            # Initialize IBKR provider
            try:
                provider = IBKRDataProvider(
                    settings=settings,
                    host=host,
                    port=port,
                    client_id=client_id,
                )
                logger.info("IBKR provider initialized (will connect on first request)")
            except Exception as e:
                logger.error(f"Failed to initialize IBKR provider: {e}")
                raise ValueError(
                    f"Cannot initialize IBKR data provider: {e}. "
                    f"Please check your IBKR Gateway connection settings and ensure IB Gateway/TWS is running."
                ) from e

            # Get IBKR config for rate limits
            data_feeds_config = self.config.get("monitoring", {}).get("data_feeds", {})
            ibkr_config = data_feeds_config.get("ibkr", {})
            
            self.data_feed_manager = DataFeedManager(
                data_provider=provider,
                rate_limit=ibkr_config.get("rate_limit", 10),  # IBKR allows more requests
                reconnect_delay=ibkr_config.get("reconnect_delay", 5.0),
            )
            self.buffer_manager.data_provider = provider
            self.health_checker.data_feed_manager = self.data_feed_manager
            logger.info("Data provider initialized successfully")
        except Exception as e:
            logger.error(f"CRITICAL: Failed to initialize data provider: {e}", exc_info=True)
            raise RuntimeError(
                f"Cannot start service without a working data provider. "
                f"Error: {e}. Please check your IBKR Gateway connection settings."
            ) from e

    # Futures worker removed - system now focuses on options trading only

    async def _options_worker(
        self, universe: List[str], strategy: str, interval: int
    ) -> None:
        """
        Worker for options swing scanning.

        Args:
            universe: List of equity symbols (e.g., ["SPY", "QQQ"])
            strategy: Strategy name
            interval: Scan interval in seconds
        """
        logger.info(
            f"Options swing worker started: universe_size={len(universe)}, strategy={strategy}, "
            f"interval={interval}s"
        )

        from pearlalgo.options.universe import EquityUniverse
        from pearlalgo.options.swing_scanner import OptionsSwingScanner
        from pearlalgo.utils.telegram_alerts import TelegramAlerts

        # Initialize options universe
        options_universe = EquityUniverse(symbols=universe)

        # Initialize options scanner with buffer manager for historical context
        scanner = OptionsSwingScanner(
            universe=options_universe,
            strategy=strategy,
            config=self.config,
            data_provider=self.data_feed_manager.data_provider if self.data_feed_manager else None,
            buffer_manager=self.buffer_manager,
        )
        
        # Update health checker with scanner reference
        self.health_checker.options_swing_scanner = scanner

        while not self.shutdown_requested:
            try:
                # Check market hours
                if not is_market_open():
                    logger.debug("Market closed, waiting...")
                    await asyncio.sleep(60)  # Check every minute
                    continue

                # Run options scan
                logger.info(f"Running options swing scan for {len(universe)} symbols")
                results = await scanner.scan()
                
                if results.get("status") == "success":
                    signals = results.get("signals", [])
                    if signals:
                        logger.info(f"Generated {len(signals)} options swing signals")
                        
                        # Process signals: track and send Telegram alerts
                        for signal in signals:
                            try:
                                # Add to options signal tracker
                                if signal.get("option_symbol") and signal.get("expiration"):
                                    from datetime import datetime
                                    expiration = datetime.fromisoformat(
                                        signal["expiration"].replace("Z", "+00:00")
                                    )
                                    self.options_signal_tracker.add_signal(
                                        underlying_symbol=signal.get("symbol"),
                                        option_symbol=signal.get("option_symbol"),
                                        strike=signal.get("strike", 0),
                                        expiration=expiration,
                                        option_type=signal.get("option_type", "call"),
                                        direction=signal.get("side", "long"),
                                        entry_premium=signal.get("entry_price", 0),
                                        quantity=1,
                                        strategy_name=signal.get("strategy_name", strategy),
                                        reasoning=signal.get("reasoning"),
                                    )
                                
                                # Send Telegram alert
                                if self.telegram_alerts:
                                    await self.telegram_alerts.notify_signal(
                                        symbol=signal.get("symbol"),
                                        side=signal.get("side", "long"),
                                        price=signal.get("entry_price", 0),
                                        strategy=signal.get("strategy_name", strategy),
                                        confidence=signal.get("confidence"),
                                        entry_price=signal.get("entry_price"),
                                        option_symbol=signal.get("option_symbol"),
                                        strike=signal.get("strike"),
                                        expiration=signal.get("expiration"),
                                        option_type=signal.get("option_type"),
                                        underlying_price=signal.get("underlying_price"),
                                        dte=signal.get("dte"),
                                        reasoning=signal.get("reasoning"),
                                    )
                            except Exception as e:
                                logger.error(f"Error processing signal: {e}", exc_info=True)
                
                self.cycle_count += 1

                # Wait for next cycle
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"Error in options worker: {e}", exc_info=True)
                await asyncio.sleep(interval)  # Wait before retry
    
    async def _options_intraday_worker(
        self, symbols: List[str], strategy: str, interval: int
    ) -> None:
        """
        Worker for options intraday scanning.

        Args:
            symbols: List of underlying symbols (e.g., ["QQQ", "SPY"])
            strategy: Strategy name
            interval: Scan interval in seconds
        """
        logger.info(
            f"Options intraday worker started: symbols={symbols}, strategy={strategy}, "
            f"interval={interval}s"
        )

        from pearlalgo.options.intraday_scanner import OptionsIntradayScanner

        # Initialize intraday scanner
        scanner = OptionsIntradayScanner(
            symbols=symbols,
            strategy=strategy,
            config=self.config,
            data_feed_manager=self.data_feed_manager,
            buffer_manager=self.buffer_manager,
            data_provider=self.data_feed_manager.data_provider if self.data_feed_manager else None,
        )
        
        # Update health checker with scanner reference
        self.health_checker.options_intraday_scanner = scanner

        while not self.shutdown_requested:
            try:
                # Check market hours
                if not is_market_open():
                    logger.debug("Market closed, waiting...")
                    await asyncio.sleep(60)  # Check every minute
                    continue

                # Run intraday scan
                logger.info(f"Running options intraday scan for {symbols}")
                results = await scanner.scan()
                
                if results.get("status") == "success":
                    signals = results.get("signals", [])
                    if signals:
                        logger.info(f"Generated {len(signals)} intraday options signals")
                        
                        # Process signals: track and send Telegram alerts
                        for signal in signals:
                            try:
                                # Add to options signal tracker
                                if signal.get("option_symbol") and signal.get("expiration"):
                                    from datetime import datetime
                                    expiration = datetime.fromisoformat(
                                        signal["expiration"].replace("Z", "+00:00")
                                    )
                                    self.options_signal_tracker.add_signal(
                                        underlying_symbol=signal.get("symbol"),
                                        option_symbol=signal.get("option_symbol"),
                                        strike=signal.get("strike", 0),
                                        expiration=expiration,
                                        option_type=signal.get("option_type", "call"),
                                        direction=signal.get("side", "long"),
                                        entry_premium=signal.get("entry_price", 0),
                                        quantity=signal.get("position_size", 1),
                                        strategy_name=signal.get("strategy_name", strategy),
                                        reasoning=signal.get("reasoning"),
                                    )
                                
                                # Send Telegram alert
                                if self.telegram_alerts:
                                    await self.telegram_alerts.notify_signal(
                                        symbol=signal.get("symbol"),
                                        side=signal.get("side", "long"),
                                        price=signal.get("entry_price", 0),
                                        strategy=signal.get("strategy_name", strategy),
                                        confidence=signal.get("confidence"),
                                        entry_price=signal.get("entry_price"),
                                        stop_loss=signal.get("stop_loss"),
                                        take_profit=signal.get("take_profit"),
                                        option_symbol=signal.get("option_symbol"),
                                        strike=signal.get("strike"),
                                        expiration=signal.get("expiration"),
                                        option_type=signal.get("option_type"),
                                        underlying_price=signal.get("underlying_price"),
                                        delta=signal.get("delta"),
                                        dte=signal.get("dte"),
                                        reasoning=signal.get("reasoning"),
                                    )
                            except Exception as e:
                                logger.error(f"Error processing signal: {e}", exc_info=True)
                
                self.cycle_count += 1

                # Wait for next cycle
                await asyncio.sleep(interval)

            except Exception as e:
                logger.error(f"Error in options intraday worker: {e}", exc_info=True)
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

        # Register workers from config
        workers_config = self.config.get("monitoring", {}).get("workers", {})

        # Options swing worker
        options_config = workers_config.get("options", {})
        if options_config.get("enabled", False):
            universe = options_config.get("universe", ["SPY", "QQQ"])
            strategy = options_config.get("strategy", "swing_momentum")
            interval = options_config.get("interval", 900)  # Default 15 minutes

            self.worker_pool.register_worker(
                "options_swing_scanner",
                "options",
                self._options_worker,
                universe=universe,
                strategy=strategy,
                interval=interval,
            )
            
            # Add small delay before starting next worker to avoid API burst
            await asyncio.sleep(2.0)
        
        # Options intraday worker
        options_intraday_config = workers_config.get("options_intraday", {})
        if options_intraday_config.get("enabled", False):
            symbols = options_intraday_config.get("symbols", ["QQQ", "SPY"])
            strategy = options_intraday_config.get("strategy", "momentum")
            interval = options_intraday_config.get("interval", 60)  # Default 1 minute

            self.worker_pool.register_worker(
                "options_intraday_scanner",
                "options",
                self._options_intraday_worker,
                symbols=symbols,
                strategy=strategy,
                interval=interval,
            )
        
        # Update health checker with scanner references after workers are registered
        # (scanners are created inside workers, so we'll update health checker dynamically)

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
    
    # .env file is now loaded at module level (see imports above)

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
