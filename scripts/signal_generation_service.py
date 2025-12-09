#!/usr/bin/env python
"""
24/7 Signal Generation Service

Long-running service for continuous signal generation with:
- Automatic error recovery
- Graceful shutdown handling
- Health monitoring
- Log rotation
- Signal deduplication
- Market hours awareness
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from loguru import logger
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

from pearlalgo.live.langgraph_trader import LangGraphTrader
from pearlalgo.futures.signal_deduplicator import SignalDeduplicator
from pearlalgo.utils.market_hours import is_market_open


class SignalGenerationService:
    """24/7 signal generation service with error recovery."""

    def __init__(
        self,
        symbols: list[str],
        strategy: str = "sr",
        interval: int = 300,
        config_path: Optional[str] = None,
        log_file: Optional[str] = None,
        max_retries: int = 3,
        retry_backoff: float = 60.0,
    ):
        self.symbols = symbols
        self.strategy = strategy
        self.interval = interval
        self.config_path = config_path
        self.log_file = log_file
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

        # Load config first
        self.config = {}
        if self.config_path and Path(self.config_path).exists():
            import yaml
            with open(self.config_path, "r") as f:
                self.config = yaml.safe_load(f) or {}

        # Service state
        self.shutdown_requested = False
        self.cycle_count = 0
        self.consecutive_errors = 0
        self.last_successful_cycle = None
        self.start_time = datetime.now(timezone.utc)
        self.skipped_cycles = 0

        # Signal deduplication
        dedup_config = self.config.get("signal_generation", {}).get("deduplication", {})
        if dedup_config.get("enabled", True):
            window_minutes = dedup_config.get("window_minutes", 15)
            self.deduplicator = SignalDeduplicator(window_minutes=window_minutes)
        else:
            self.deduplicator = None

        # Market hours awareness
        market_hours_config = self.config.get("signal_generation", {}).get("market_hours", {})
        self.check_market_hours = market_hours_config.get("enabled", True)
        self.skip_during_close = market_hours_config.get("skip_during_close", True)

        # Setup logging
        self._setup_logging()

        # Initialize trader
        self.trader = None
        self._initialize_trader()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            f"SignalGenerationService initialized: symbols={symbols}, "
            f"strategy={strategy}, interval={interval}s"
        )

    def _setup_logging(self):
        """Setup logging with file rotation if log_file is specified."""
        if self.log_file:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Configure loguru with rotation
            try:
                from loguru import logger as loguru_logger

                loguru_logger.add(
                    self.log_file,
                    rotation="00:00",  # Rotate at midnight
                    retention="30 days",  # Keep 30 days of logs
                    compression="zip",  # Compress old logs
                    level="INFO",
                    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                )
                logger.info(f"Logging to file: {self.log_file}")
            except ImportError:
                # Fallback to standard logging
                file_handler = logging.FileHandler(self.log_file)
                file_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    )
                )
                logging.getLogger().addHandler(file_handler)
                logger.info(f"Logging to file: {self.log_file} (standard logging)")

    def _initialize_trader(self):
        """Initialize the LangGraph trader."""
        try:
            self.trader = LangGraphTrader(
                config_path=self.config_path,
                symbols=self.symbols,
                strategy=self.strategy,
            )
            logger.info("Trader initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize trader: {e}", exc_info=True)
            raise

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True

    async def _run_cycle_with_retry(self) -> bool:
        """
        Run a single cycle with retry logic.

        Returns:
            True if cycle succeeded, False otherwise
        """
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Running cycle #{self.cycle_count + 1} (attempt {attempt + 1})")

                # Run a single cycle
                await self.trader.workflow.run_cycle()

                # Success
                self.consecutive_errors = 0
                self.last_successful_cycle = datetime.now(timezone.utc)
                self.cycle_count += 1
                logger.info(f"Cycle #{self.cycle_count} completed successfully")
                return True

            except KeyboardInterrupt:
                logger.info("Cycle interrupted by user")
                raise
            except Exception as e:
                self.consecutive_errors += 1
                logger.error(
                    f"Cycle failed (attempt {attempt + 1}/{self.max_retries}): {e}",
                    exc_info=True,
                )

                if attempt < self.max_retries - 1:
                    backoff_time = self.retry_backoff * (2 ** attempt)
                    logger.info(f"Retrying in {backoff_time}s...")
                    await asyncio.sleep(backoff_time)
                else:
                    logger.error(f"Cycle failed after {self.max_retries} attempts")
                    return False

        return False

    async def run(self):
        """Main service loop."""
        logger.info("=" * 60)
        logger.info("Starting 24/7 Signal Generation Service")
        logger.info(f"Symbols: {self.symbols}")
        logger.info(f"Strategy: {self.strategy}")
        logger.info(f"Interval: {self.interval}s ({self.interval / 60:.1f} minutes)")
        logger.info("=" * 60)

        try:
            while not self.shutdown_requested:
                # Check market hours
                if self.check_market_hours and self.skip_during_close:
                    if not is_market_open():
                        self.skipped_cycles += 1
                        logger.info(
                            f"Market is closed, skipping cycle. "
                            f"Total skipped: {self.skipped_cycles}"
                        )
                        # Wait shorter interval during market close
                        await asyncio.sleep(60)  # Check every minute
                        continue

                # Run cycle with retry
                success = await self._run_cycle_with_retry()

                # Check for too many consecutive errors
                if self.consecutive_errors >= self.max_retries * 2:
                    logger.critical(
                        f"Too many consecutive errors ({self.consecutive_errors}), "
                        "stopping service. Check logs for details."
                    )
                    break

                # Wait for next cycle (check shutdown during sleep)
                if not self.shutdown_requested:
                    logger.info(f"Waiting {self.interval}s until next cycle...")
                    sleep_chunks = max(1, self.interval // 10)  # Check every 10% of interval
                    for _ in range(10):
                        await asyncio.sleep(sleep_chunks)
                        if self.shutdown_requested:
                            break

        except KeyboardInterrupt:
            logger.info("Service interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in service: {e}", exc_info=True)
            raise
        finally:
            self._shutdown()

    def _shutdown(self):
        """Cleanup and shutdown."""
        uptime = datetime.now(timezone.utc) - self.start_time
        logger.info("=" * 60)
        logger.info("Shutting down Signal Generation Service")
        logger.info(f"Total cycles: {self.cycle_count}")
        logger.info(f"Uptime: {uptime}")
        logger.info(f"Last successful cycle: {self.last_successful_cycle}")
        logger.info("=" * 60)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="24/7 Signal Generation Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="Trading symbols (e.g., ES NQ MES MNQ)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="sr",
        help="Trading strategy (default: sr)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Cycle interval in seconds (default: 300 = 5 minutes)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Path to log file (default: logs/signal_generation.log)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries per cycle (default: 3)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=60.0,
        help="Retry backoff time in seconds (default: 60.0)",
    )

    args = parser.parse_args()

    # Default log file
    if not args.log_file:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        args.log_file = str(log_dir / "signal_generation.log")

    # Default config path
    if not args.config:
        args.config = str(PROJECT_ROOT / "config" / "config.yaml")

    # Create and run service
    service = SignalGenerationService(
        symbols=args.symbols,
        strategy=args.strategy,
        interval=args.interval,
        config_path=args.config,
        log_file=args.log_file,
        max_retries=args.max_retries,
        retry_backoff=args.retry_backoff,
    )

    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

