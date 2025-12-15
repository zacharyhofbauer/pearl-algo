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
            self.application.add_handler(CommandHandler("history", self._cmd_history))
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
            "/signals - Get recent signals (last 10)\n"
            "/history - Get signal history (last 20)\n"
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
        """Handle /signals command - shows last 10 signals."""
        try:
            from pearlalgo.nq_agent.state_manager import NQAgentStateManager
            from datetime import datetime
            
            state_manager = NQAgentStateManager(state_dir=self.state_dir)
            recent_signals = state_manager.get_recent_signals(limit=10)
            
            if not recent_signals:
                await update.message.reply_text("📭 No signals found yet")
                return
            
            message = "🔔 *Recent Signals (Last 10)*\n\n"
            for i, signal in enumerate(recent_signals[-10:], 1):
                signal_type = signal.get("type", "unknown").replace("_", " ").title()
                direction = signal.get("direction", "").upper()
                direction_emoji = "📈" if direction == "LONG" else "📉"
                confidence = signal.get("confidence", 0)
                entry_price = signal.get("entry_price", 0)
                timestamp = signal.get("timestamp", "")
                
                # Format timestamp
                time_str = ""
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        time_str = dt.strftime("%H:%M:%S")
                    except:
                        pass
                
                message += (
                    f"{i}. {direction_emoji} *{signal_type} {direction}*\n"
                    f"   💰 Entry: ${entry_price:.2f}\n"
                    f"   🎯 Confidence: {confidence:.0%}\n"
                )
                if time_str:
                    message += f"   🕐 Time: {time_str}\n"
                message += "\n"
            
            await update.message.reply_text(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error getting signals: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
    
    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /history command - shows last 20 signals with timestamps."""
        try:
            from pearlalgo.nq_agent.state_manager import NQAgentStateManager
            from datetime import datetime
            
            state_manager = NQAgentStateManager(state_dir=self.state_dir)
            recent_signals = state_manager.get_recent_signals(limit=20)
            
            if not recent_signals:
                await update.message.reply_text("📭 No signal history found yet")
                return
            
            message = "📜 *Signal History (Last 20)*\n\n"
            for i, signal in enumerate(recent_signals[-20:], 1):
                signal_type = signal.get("type", "unknown").replace("_", " ").title()
                direction = signal.get("direction", "").upper()
                direction_emoji = "📈" if direction == "LONG" else "📉"
                confidence = signal.get("confidence", 0)
                entry_price = signal.get("entry_price", 0)
                timestamp = signal.get("timestamp", "")
                
                # Format timestamp
                date_time_str = ""
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        date_time_str = dt.strftime("%m/%d %H:%M")
                    except:
                        date_time_str = timestamp[:16] if len(timestamp) > 16 else timestamp
                
                message += (
                    f"{i}. {direction_emoji} {signal_type} {direction}\n"
                    f"   💰 ${entry_price:.2f} | 🎯 {confidence:.0%}"
                )
                if date_time_str:
                    message += f" | 🕐 {date_time_str}"
                message += "\n"
            
            await update.message.reply_text(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
    
    async def _cmd_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /performance command - shows formatted performance metrics."""
        try:
            from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
            
            tracker = PerformanceTracker(state_dir=self.state_dir)
            metrics = tracker.get_performance_metrics(days=7)
            
            message = "📈 *Performance Metrics (Last 7 Days)*\n\n"
            
            # Signal Statistics
            total_signals = metrics.get('total_signals', 0)
            exited_signals = metrics.get('exited_signals', 0)
            
            message += "📊 *Signal Statistics*\n"
            message += f"Total Signals: {total_signals}\n"
            message += f"Exited Signals: {exited_signals}\n"
            if total_signals > 0:
                exit_rate = (exited_signals / total_signals) * 100
                message += f"Exit Rate: {exit_rate:.1f}%\n"
            message += "\n"
            
            # Trade Performance (if any completed trades)
            if exited_signals > 0:
                wins = metrics.get('wins', 0)
                losses = metrics.get('losses', 0)
                win_rate = metrics.get('win_rate', 0) * 100
                total_pnl = metrics.get('total_pnl', 0)
                avg_pnl = metrics.get('avg_pnl', 0)
                avg_hold = metrics.get('avg_hold_minutes', 0)
                
                message += "💰 *Trade Performance*\n"
                message += f"✅ Wins: {wins}\n"
                message += f"❌ Losses: {losses}\n"
                message += f"📊 Win Rate: {win_rate:.1f}%\n\n"
                
                message += "💵 *P&L Summary*\n"
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                message += f"{pnl_emoji} Total P&L: ${total_pnl:,.2f}\n"
                avg_emoji = "🟢" if avg_pnl >= 0 else "🔴"
                message += f"{avg_emoji} Avg P&L: ${avg_pnl:,.2f}\n"
                message += f"⏱️ Avg Hold Time: {avg_hold:.1f} min\n"
            else:
                message += "⏳ *No completed trades yet*\n"
                message += "Waiting for signal exits..."
            
            await update.message.reply_text(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error getting performance: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
    
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

