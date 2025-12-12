"""
Interactive Telegram Bot for NQ Agent

Provides interactive commands to control and monitor the NQ agent service.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger as loguru_logger
    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, interactive bot disabled")


class NQAgentTelegramBot:
    """
    Interactive Telegram bot for NQ agent control.
    
    Provides commands:
    - /start - Start bot
    - /status - Get service status
    - /signals - Get recent signals
    - /performance - Get performance metrics
    - /config - Get configuration
    - /pause - Pause service (if running)
    - /resume - Resume service (if paused)
    """
    
    def __init__(
        self,
        bot_token: str,
        service_instance: Optional[object] = None,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize Telegram bot.
        
        Args:
            bot_token: Telegram bot token
            service_instance: Optional NQAgentService instance (for control commands)
            state_dir: State directory for reading data
        """
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot is required for interactive bot")
        
        self.bot_token = bot_token
        self.service = service_instance
        self.state_dir = state_dir or Path("data/nq_agent_state")
        
        self.application = None
        
        logger.info("NQAgentTelegramBot initialized")
    
    async def start(self) -> None:
        """Start the bot."""
        if not self.application:
            self.application = Application.builder().token(self.bot_token).build()
            
            # Register command handlers
            self.application.add_handler(CommandHandler("start", self._cmd_start))
            self.application.add_handler(CommandHandler("status", self._cmd_status))
            self.application.add_handler(CommandHandler("signals", self._cmd_signals))
            self.application.add_handler(CommandHandler("performance", self._cmd_performance))
            self.application.add_handler(CommandHandler("config", self._cmd_config))
            self.application.add_handler(CommandHandler("pause", self._cmd_pause))
            self.application.add_handler(CommandHandler("resume", self._cmd_resume))
            
            logger.info("Telegram bot commands registered")
        
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Telegram bot started and polling")
    
    async def stop(self) -> None:
        """Stop the bot."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Telegram bot stopped")
    
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        await update.message.reply_text(
            "🤖 *NQ Agent Bot*\n\n"
            "Available commands:\n"
            "/status - Get service status\n"
            "/signals - Get recent signals\n"
            "/performance - Get performance metrics\n"
            "/config - Get configuration\n"
            "/pause - Pause service\n"
            "/resume - Resume service",
            parse_mode="Markdown",
        )
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if self.service:
            status = self.service.get_status()
            
            # Format status message
            message = "📊 *Service Status*\n\n"
            
            status_emoji = "🟢" if status.get("running") else "🔴"
            pause_status = " ⏸️ PAUSED" if status.get("paused") else ""
            message += f"{status_emoji} Status: {'RUNNING' if status.get('running') else 'STOPPED'}{pause_status}\n"
            
            if status.get("uptime"):
                uptime = status["uptime"]
                message += f"⏱️ Uptime: {uptime.get('hours', 0)}h {uptime.get('minutes', 0)}m\n"
            
            message += f"🔄 Cycles: {status.get('cycle_count', 0)}\n"
            message += f"🔔 Signals: {status.get('signal_count', 0)}\n"
            message += f"⚠️ Errors: {status.get('error_count', 0)}\n"
            
            await update.message.reply_text(message, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Service instance not available")
    
    async def _cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /signals command."""
        try:
            from pearlalgo.nq_agent.state_manager import NQAgentStateManager
            
            state_manager = NQAgentStateManager(state_dir=self.state_dir)
            recent_signals = state_manager.get_recent_signals(limit=10)
            
            if not recent_signals:
                await update.message.reply_text("No signals found")
                return
            
            message = "🔔 *Recent Signals*\n\n"
            for i, signal in enumerate(recent_signals[-10:], 1):
                signal_type = signal.get("type", "unknown")
                direction = signal.get("direction", "").upper()
                confidence = signal.get("confidence", 0)
                entry_price = signal.get("entry_price", 0)
                
                message += (
                    f"{i}. {signal_type} {direction}\n"
                    f"   Entry: ${entry_price:.2f}\n"
                    f"   Confidence: {confidence:.0%}\n\n"
                )
            
            await update.message.reply_text(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error getting signals: {e}")
            await update.message.reply_text(f"Error: {e}")
    
    async def _cmd_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /performance command."""
        try:
            from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
            
            tracker = PerformanceTracker(state_dir=self.state_dir)
            metrics = tracker.get_performance_metrics(days=7)
            
            message = "📈 *Performance Metrics (7 days)*\n\n"
            message += f"Total Signals: {metrics.get('total_signals', 0)}\n"
            message += f"Exited Signals: {metrics.get('exited_signals', 0)}\n"
            
            if metrics.get("exited_signals", 0) > 0:
                message += f"✅ Wins: {metrics.get('wins', 0)}\n"
                message += f"❌ Losses: {metrics.get('losses', 0)}\n"
                message += f"📊 Win Rate: {metrics.get('win_rate', 0) * 100:.1f}%\n"
                message += f"💰 Total P&L: ${metrics.get('total_pnl', 0):,.2f}\n"
                message += f"📊 Avg P&L: ${metrics.get('avg_pnl', 0):,.2f}\n"
                message += f"⏱️ Avg Hold: {metrics.get('avg_hold_minutes', 0):.1f} min\n"
            else:
                message += "No completed trades yet"
            
            await update.message.reply_text(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error getting performance: {e}")
            await update.message.reply_text(f"Error: {e}")
    
    async def _cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /config command."""
        if self.service:
            config = self.service.config
            message = "⚙️ *Configuration*\n\n"
            message += f"Symbol: {config.symbol}\n"
            message += f"Timeframe: {config.timeframe}\n"
            message += f"Scan Interval: {config.scan_interval}s\n"
            message += f"Stop Loss ATR: {config.stop_loss_atr_multiplier}x\n"
            message += f"Risk/Reward: {config.take_profit_risk_reward}:1\n"
            message += f"Max Risk: {config.max_risk_per_trade * 100:.1f}%\n"
            
            await update.message.reply_text(message, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Service instance not available")
    
    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pause command."""
        if self.service:
            self.service.pause()
            await update.message.reply_text("⏸️ Service paused")
        else:
            await update.message.reply_text("❌ Service instance not available")
    
    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /resume command."""
        if self.service:
            self.service.resume()
            await update.message.reply_text("▶️ Service resumed")
        else:
            await update.message.reply_text("❌ Service instance not available")


async def run_bot(bot_token: str, service_instance: Optional[object] = None) -> None:
    """
    Run the Telegram bot (for standalone usage).
    
    Args:
        bot_token: Telegram bot token
        service_instance: Optional NQAgentService instance
    """
    bot = NQAgentTelegramBot(bot_token=bot_token, service_instance=service_instance)
    
    try:
        await bot.start()
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
    finally:
        await bot.stop()


if __name__ == "__main__":
    import sys
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)
    
    asyncio.run(run_bot(bot_token))

