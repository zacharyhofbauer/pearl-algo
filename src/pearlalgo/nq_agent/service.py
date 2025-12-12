"""
NQ Agent Service

Main 24/7 service for running NQ intraday strategy.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
from pearlalgo.nq_agent.state_manager import NQAgentStateManager
from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy


class NQAgentService:
    """
    24/7 service for NQ intraday trading strategy.
    
    Runs independently, fetches data, generates signals, and sends to Telegram.
    """
    
    def __init__(
        self,
        data_provider: DataProvider,
        config: Optional[NQIntradayConfig] = None,
        state_dir: Optional[Path] = None,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
    ):
        """
        Initialize NQ agent service.
        
        Args:
            data_provider: Data provider instance
            config: Strategy configuration (optional)
            state_dir: State directory (optional)
            telegram_bot_token: Telegram bot token (optional)
            telegram_chat_id: Telegram chat ID (optional)
        """
        self.config = config or NQIntradayConfig()
        self.strategy = NQIntradayStrategy(config=self.config)
        self.data_fetcher = NQAgentDataFetcher(data_provider, config=self.config)
        self.state_manager = NQAgentStateManager(state_dir=state_dir)
        self.performance_tracker = PerformanceTracker(state_dir=state_dir)
        self.telegram_notifier = NQAgentTelegramNotifier(
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
        )
        
        self.running = False
        self.shutdown_requested = False
        self.paused = False
        self.start_time: Optional[datetime] = None
        self.cycle_count = 0
        self.signal_count = 0
        self.error_count = 0
        self.last_status_update: Optional[datetime] = None
        self.status_update_interval = 1800  # 30 minutes in seconds
        self.consecutive_errors = 0
        self.max_consecutive_errors = 10  # Circuit breaker threshold
        self.data_fetch_errors = 0
        self.max_data_fetch_errors = 5
        
        logger.info("NQAgentService initialized")
    
    async def start(self) -> None:
        """Start the service."""
        if self.running:
            logger.warning("Service already running")
            return
        
        self.running = True
        self.shutdown_requested = False
        self.start_time = datetime.now(timezone.utc)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("NQ Agent Service starting...")
        
        try:
            await self._run_loop()
        except Exception as e:
            logger.error(f"Service error: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the service."""
        if not self.running:
            return
        
        logger.info("Stopping NQ Agent Service...")
        self.shutdown_requested = True
        
        # Save final state
        self._save_state()
        
        self.running = False
        logger.info("NQ Agent Service stopped")
    
    async def _run_loop(self) -> None:
        """Main service loop."""
        logger.info(f"Starting main loop (scan_interval={self.config.scan_interval}s)")
        
        while not self.shutdown_requested:
            try:
                # Skip if paused
                if self.paused:
                    await asyncio.sleep(self.config.scan_interval)
                    continue
                
                # Fetch latest data with error handling
                try:
                    market_data = await self.data_fetcher.fetch_latest_data()
                    self.data_fetch_errors = 0  # Reset on success
                except Exception as e:
                    logger.error(f"Error fetching market data: {e}", exc_info=True)
                    self.data_fetch_errors += 1
                    self.error_count += 1
                    
                    # Circuit breaker: if too many data fetch errors, wait longer
                    if self.data_fetch_errors >= self.max_data_fetch_errors:
                        logger.warning(
                            f"Too many data fetch errors ({self.data_fetch_errors}), "
                            f"waiting {self.config.scan_interval * 2}s before retry"
                        )
                        await self._notify_error("Data fetch failures", f"{self.data_fetch_errors} consecutive errors")
                        await asyncio.sleep(self.config.scan_interval * 2)
                    else:
                        await asyncio.sleep(self.config.scan_interval)
                    continue
                
                if market_data["df"].empty:
                    logger.debug("No market data available, waiting...")
                    await asyncio.sleep(self.config.scan_interval)
                    continue
                
                # Generate signals
                signals = self.strategy.analyze(market_data)
                
                # Process signals
                for signal in signals:
                    await self._process_signal(signal)
                
                # Send periodic status updates
                await self._check_status_update()
                
                # Save state periodically
                if self.cycle_count % 10 == 0:
                    self._save_state()
                
                self.cycle_count += 1
                
                # Wait for next cycle
                await asyncio.sleep(self.config.scan_interval)
                
            except asyncio.CancelledError:
                logger.info("Service loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in service loop: {e}", exc_info=True)
                self.error_count += 1
                self.consecutive_errors += 1
                
                # Circuit breaker: if too many consecutive errors, pause service
                if self.consecutive_errors >= self.max_consecutive_errors:
                    logger.error(
                        f"Too many consecutive errors ({self.consecutive_errors}), "
                        "pausing service. Manual intervention required."
                    )
                    await self._notify_error(
                        "Service paused due to errors",
                        f"{self.consecutive_errors} consecutive errors detected"
                    )
                    self.paused = True
                
                await asyncio.sleep(self.config.scan_interval)
            else:
                # Reset consecutive errors on successful cycle
                self.consecutive_errors = 0
    
    async def _process_signal(self, signal: Dict) -> None:
        """
        Process a trading signal.
        
        Args:
            signal: Signal dictionary
        """
        try:
            # Track signal generation
            signal_id = self.performance_tracker.track_signal_generated(signal)
            signal["signal_id"] = signal_id
            
            # Save signal to state
            self.state_manager.save_signal(signal)
            
            # Send to Telegram (await async call)
            success = await self.telegram_notifier.send_signal(signal)
            
            if success:
                logger.info(f"Signal sent to Telegram: {signal.get('type')} {signal.get('direction')}")
            else:
                logger.warning("Failed to send signal to Telegram")
            
            self.signal_count += 1
            
        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            self.error_count += 1
    
    async def _check_status_update(self) -> None:
        """Send periodic status updates to Telegram."""
        now = datetime.now(timezone.utc)
        
        # Check if it's time for a status update
        if (
            self.last_status_update is None
            or (now - self.last_status_update).total_seconds() >= self.status_update_interval
        ):
            await self._send_status_update()
            self.last_status_update = now
    
    async def _send_status_update(self) -> None:
        """Send status update to Telegram."""
        try:
            # Use enhanced status with performance metrics
            status = self.get_status()
            await self.telegram_notifier.send_enhanced_status(status)
        except Exception as e:
            logger.error(f"Error sending status update: {e}", exc_info=True)
    
    def pause(self) -> None:
        """Pause the service."""
        self.paused = True
        logger.info("Service paused")
    
    def resume(self) -> None:
        """Resume the service."""
        self.paused = False
        logger.info("Service resumed")
    
    async def _notify_error(self, title: str, message: str) -> None:
        """Notify about errors via Telegram."""
        try:
            if self.telegram_notifier.enabled and self.telegram_notifier.telegram:
                await self.telegram_notifier.telegram.notify_risk_warning(
                    f"{title}\n\n{message}",
                    risk_status="ERROR",
                )
        except Exception as e:
            logger.error(f"Error sending error notification: {e}")
    
    def get_status(self) -> Dict:
        """Get current service status."""
        uptime = None
        if self.start_time:
            uptime_delta = datetime.now(timezone.utc) - self.start_time
            uptime = {
                "hours": int(uptime_delta.total_seconds() / 3600),
                "minutes": int((uptime_delta.total_seconds() % 3600) / 60),
            }
        
        # Get performance metrics
        performance = self.performance_tracker.get_performance_metrics(days=7)
        
        return {
            "running": self.running,
            "paused": self.paused,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime": uptime,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "error_count": self.error_count,
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "performance": performance,
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
            },
        }
    
    def _save_state(self) -> None:
        """Save current service state."""
        state = {
            "running": self.running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "cycle_count": self.cycle_count,
            "signal_count": self.signal_count,
            "buffer_size": self.data_fetcher.get_buffer_size(),
            "config": {
                "symbol": self.config.symbol,
                "timeframe": self.config.timeframe,
                "scan_interval": self.config.scan_interval,
            },
        }
        self.state_manager.save_state(state)
    
    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown_requested = True
