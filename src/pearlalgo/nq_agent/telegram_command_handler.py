"""
Telegram Command Handler for NQ Agent

Handles incoming Telegram commands and provides interactive bot functionality.
This can run as a separate service or be integrated into the main service.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from pearlalgo.utils.logger import logger

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        ContextTypes,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, command handler disabled")

from pearlalgo.nq_agent.state_manager import NQAgentStateManager
from pearlalgo.nq_agent.performance_tracker import PerformanceTracker
from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.utils.paths import get_signals_file, get_state_file, ensure_state_dir


class TelegramCommandHandler:
    """
    Handles Telegram bot commands and callbacks.
    
    This class processes incoming Telegram commands and provides
    interactive functionality for the NQ Agent bot.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        state_dir: Optional[Path] = None,
    ):
        """
        Initialize command handler.
        
        Args:
            bot_token: Telegram bot token
            chat_id: Authorized chat ID
            state_dir: State directory for reading agent data
        """
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot required for command handler")
        
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.state_dir = ensure_state_dir(state_dir)
        self.state_manager = NQAgentStateManager(state_dir=state_dir)
        self.performance_tracker = PerformanceTracker(
            state_dir=state_dir,
            state_manager=self.state_manager,
        )
        self.telegram_notifier = NQAgentTelegramNotifier(
            bot_token=bot_token,
            chat_id=chat_id,
        )
        
        # Build application
        self.application = Application.builder().token(bot_token).build()
        
        # Register handlers
        self._register_handlers()
        
    def _register_handlers(self):
        """Register command and callback handlers."""
        # Command handlers
        # Note: We'll add logging directly in each handler
        self.application.add_handler(CommandHandler("start", self._handle_start))
        self.application.add_handler(CommandHandler("help", self._handle_help))
        self.application.add_handler(CommandHandler("status", self._handle_status))
        self.application.add_handler(CommandHandler("pause", self._handle_pause))
        self.application.add_handler(CommandHandler("resume", self._handle_resume))
        self.application.add_handler(CommandHandler("signals", self._handle_signals))
        self.application.add_handler(CommandHandler("performance", self._handle_performance))
        
        # Callback query handler (for inline buttons)
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))
    
    async def _check_authorized(self, update: Update) -> bool:
        """Check if update is from authorized chat."""
        if not update.effective_chat:
            return False
        return str(update.effective_chat.id) == str(self.chat_id)
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        logger.info(f"Received /start command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        message = (
            "🤖 *NQ Agent Bot*\n\n"
            "Available commands:\n"
            "• /status - Get current status\n"
            "• /pause - Pause agent\n"
            "• /resume - Resume agent\n"
            "• /signals - Show recent signals\n"
            "• /performance - Show performance\n"
            "• /help - Show help\n"
        )
        await update.message.reply_text(message, parse_mode="Markdown")
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        message = (
            "📚 *NQ Agent Bot Help*\n\n"
            "*/status* - Get current agent status and metrics\n"
            "*/pause* - Pause the trading agent (stops processing)\n"
            "*/resume* - Resume the paused trading agent\n"
            "*/signals* - Show recent trading signals (last 10)\n"
            "*/performance* - Show performance metrics (7-day)\n"
        )
        await update.message.reply_text(message, parse_mode="Markdown")
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        logger.info(f"Received /status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            # Load state
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                await update.message.reply_text(
                    "❌ *Agent state not found*\n\n"
                    "The agent may not be running or state file doesn't exist.\n"
                    "Make sure the NQ Agent service is started.",
                    parse_mode="Markdown"
                )
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Build status message
            running = state.get("running", False)
            paused = state.get("paused", False)
            status_emoji = "🟢" if running and not paused else "⏸️" if paused else "🔴"
            
            message = f"{status_emoji} *Agent Status*\n\n"
            message += f"*Status:* {'RUNNING' if running else 'STOPPED'}\n"
            if paused:
                message += "⏸️ *Paused*\n"
            
            if "cycle_count" in state:
                message += f"🔄 Cycles: {state.get('cycle_count', 0):,}\n"
            if "signal_count" in state:
                message += f"🔔 Signals: {state.get('signal_count', 0)}\n"
            if "buffer_size" in state:
                message += f"📊 Buffer: {state.get('buffer_size', 0)} bars\n"
            
            # Add inline buttons
            keyboard = []
            if running and not paused:
                keyboard.append([InlineKeyboardButton("⏸️ Pause", callback_data='pause')])
            elif paused:
                keyboard.append([InlineKeyboardButton("▶️ Resume", callback_data='resume')])
            keyboard.append([
                InlineKeyboardButton("📊 Performance", callback_data='performance'),
                InlineKeyboardButton("🔔 Signals", callback_data='signals'),
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(message, parse_mode="Markdown", reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling status command: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pause command."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        # Note: This requires integration with the running service
        # For now, just acknowledge the command
        await update.message.reply_text(
            "⏸️ *Pause command received*\n\n"
            "Note: Direct pause/resume requires service integration.\n"
            "Currently, you need to pause via service management scripts.",
            parse_mode="Markdown"
        )
    
    async def _handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resume command."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        await update.message.reply_text(
            "▶️ *Resume command received*\n\n"
            "Note: Direct pause/resume requires service integration.\n"
            "Currently, you need to resume via service management scripts.",
            parse_mode="Markdown"
        )
    
    async def _handle_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /signals command."""
        logger.info(f"Received /signals command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await update.message.reply_text("📭 No signals found")
                return
            
            # Read last 10 signals
            signals = []
            with open(signals_file) as f:
                for line in f:
                    try:
                        signal_data = json.loads(line.strip())
                        signals.append(signal_data)
                    except json.JSONDecodeError:
                        continue
            
            if not signals:
                await update.message.reply_text("📭 No signals found")
                return
            
            # Get last 10
            recent_signals = signals[-10:]
            recent_signals.reverse()  # Show newest first
            
            message = f"🔔 *Recent Signals ({len(recent_signals)})*\n\n"
            
            for i, sig_data in enumerate(recent_signals, 1):
                signal = sig_data.get("signal", {})
                signal_type = signal.get("type", "unknown")
                direction = signal.get("direction", "long").upper()
                entry_price = signal.get("entry_price", 0)
                status = sig_data.get("status", "unknown")
                
                status_emoji = {
                    "generated": "🆕",
                    "entered": "✅",
                    "exited": "🏁",
                    "expired": "⏰",
                }.get(status, "⚪")
                
                message += f"{i}. {status_emoji} {signal_type} {direction}\n"
                message += f"   Entry: ${entry_price:.2f} | Status: {status}\n\n"
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling signals command: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _handle_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /performance command."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            performance = self.performance_tracker.get_performance_metrics(days=7)
            
            message = "📈 *Performance (7-day)*\n\n"
            
            total_signals = performance.get("total_signals", 0)
            exited_signals = performance.get("exited_signals", 0)
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            win_rate = performance.get("win_rate", 0) * 100
            total_pnl = performance.get("total_pnl", 0)
            avg_pnl = performance.get("avg_pnl", 0)
            
            message += f"*Signals:* {total_signals} total, {exited_signals} exited\n"
            
            if exited_signals > 0:
                message += f"✅ {wins}W  ❌ {losses}L\n"
                message += f"📊 Win Rate: {win_rate:.1f}%\n"
                message += f"💰 Total P&L: ${total_pnl:,.2f}\n"
                message += f"📊 Avg P&L: ${avg_pnl:,.2f}\n"
            else:
                message += "⏳ No completed trades yet\n"
            
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error handling performance command: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()
        
        if not await self._check_authorized(update):
            await query.edit_message_text("❌ Unauthorized access")
            return
        
        callback_data = query.data
        
        if callback_data == 'status':
            # Trigger status handler
            # Create a fake update for status command
            await self._handle_status(update, context)
        elif callback_data == 'performance':
            await self._handle_performance(update, context)
        elif callback_data == 'signals':
            await self._handle_signals(update, context)
        elif callback_data in ('pause', 'resume'):
            await query.edit_message_text(
                f"⚠️ {callback_data.title()} requires service integration.\n"
                "Use service management scripts for now."
            )
    
    async def start(self):
        """Start the command handler (polling for updates)."""
        logger.info("Starting Telegram command handler...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Telegram command handler started (polling)")
    
    async def stop(self):
        """Stop the command handler."""
        logger.info("Stopping Telegram command handler...")
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()
        logger.info("Telegram command handler stopped")
    
    def run(self):
        """Run the command handler (blocking)."""
        logger.info("Starting Telegram command handler...")
        logger.info(f"Listening for commands from chat ID: {self.chat_id}")
        logger.info("Press Ctrl+C to stop")
        try:
            self.application.run_polling(
                drop_pending_updates=True,  # Ignore old messages when starting
                allowed_updates=["message", "callback_query"]  # Only listen to these update types
            )
        except KeyboardInterrupt:
            logger.info("Command handler stopped by user")
        except Exception as e:
            logger.error(f"Command handler error: {e}", exc_info=True)
            raise


def main():
    """Main entry point for running command handler as standalone service."""
    import os
    import sys
    from pathlib import Path
    
    # Try loading from .env
    try:
        from dotenv import load_dotenv
        project_root = Path(__file__).parent.parent.parent.parent
        load_dotenv(project_root / ".env")
    except ImportError:
        pass
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
        print("Set them in .env file or environment variables")
        sys.exit(1)
    
    handler = TelegramCommandHandler(
        bot_token=bot_token,
        chat_id=chat_id,
    )
    
    try:
        handler.run()
    except KeyboardInterrupt:
        print("\nShutting down command handler...")
    except Exception as e:
        logger.error(f"Command handler error: {e}", exc_info=True)


if __name__ == "__main__":
    main()


