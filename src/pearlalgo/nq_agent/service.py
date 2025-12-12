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
        self.telegram_notifier = NQAgentTelegramNotifier(
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
        )
        
        self.running = False
        self.shutdown_requested = False
        self.start_time: Optional[datetime] = None
        self.cycle_count = 0
        self.signal_count = 0
        
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
                # Fetch latest data
                market_data = await self.data_fetcher.fetch_latest_data()
                
                if market_data["df"].empty:
                    logger.debug("No market data available, waiting...")
                    await asyncio.sleep(self.config.scan_interval)
                    continue
                
                # Generate signals
                signals = self.strategy.analyze(market_data)
                
                # Process signals
                for signal in signals:
                    await self._process_signal(signal)
                
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
                await asyncio.sleep(self.config.scan_interval)
    
    async def _process_signal(self, signal: Dict) -> None:
        """
        Process a trading signal.
        
        Args:
            signal: Signal dictionary
        """
        try:
            # Save signal to state
            self.state_manager.save_signal(signal)
            
            # Send to Telegram
            success = self.telegram_notifier.send_signal(signal)
            
            if success:
                logger.info(f"Signal sent to Telegram: {signal.get('type')} {signal.get('direction')}")
            else:
                logger.warning("Failed to send signal to Telegram")
            
            self.signal_count += 1
            
        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
    
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
