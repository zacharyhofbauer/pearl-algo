"""
Telegram Command Handler for NQ Agent

Handles incoming Telegram commands and provides interactive bot functionality.
This can run as a separate service or be integrated into the main service.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

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
from pearlalgo.utils.service_controller import ServiceController

try:
    from pearlalgo.nq_agent.chart_generator import ChartGenerator
    CHART_GENERATOR_AVAILABLE = True
except ImportError:
    CHART_GENERATOR_AVAILABLE = False
    ChartGenerator = None


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
        
        # Initialize service controller for remote control
        self.service_controller = ServiceController()
        
        # Initialize chart generator if available
        self.chart_generator = None
        if CHART_GENERATOR_AVAILABLE:
            try:
                self.chart_generator = ChartGenerator()
            except Exception as e:
                logger.warning(f"Could not initialize ChartGenerator: {e}")
        
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
        self.application.add_handler(CommandHandler("quick_status", self._handle_quick_status))
        self.application.add_handler(CommandHandler("pause", self._handle_pause))
        self.application.add_handler(CommandHandler("resume", self._handle_resume))
        self.application.add_handler(CommandHandler("signals", self._handle_signals))
        self.application.add_handler(CommandHandler("last_signal", self._handle_last_signal))
        self.application.add_handler(CommandHandler("active_trades", self._handle_active_trades))
        self.application.add_handler(CommandHandler("performance", self._handle_performance))
        # Read-only operational helpers
        self.application.add_handler(CommandHandler("config", self._handle_config))
        self.application.add_handler(CommandHandler("health", self._handle_health))
        
        # Service control commands (start/stop gateway and agent)
        self.application.add_handler(CommandHandler("start_gateway", self._handle_start_gateway))
        self.application.add_handler(CommandHandler("stop_gateway", self._handle_stop_gateway))
        self.application.add_handler(CommandHandler("gateway_status", self._handle_gateway_status))
        self.application.add_handler(CommandHandler("start_agent", self._handle_start_agent))
        self.application.add_handler(CommandHandler("stop_agent", self._handle_stop_agent))
        self.application.add_handler(CommandHandler("restart_agent", self._handle_restart_agent))
        
        # Callback query handler (for inline buttons)
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))
    
    def _is_agent_process_running(self) -> bool:
        """
        Best-effort check to see if the NQ Agent service process is running.
        
        Uses the PID file created by lifecycle scripts, and falls back to a
        lightweight /proc scan if needed.
        """
        try:
            project_root = Path(__file__).parent.parent.parent.parent
            pid_file = project_root / "logs" / "nq_agent.pid"
            
            # Prefer PID file (matches lifecycle scripts + service runner)
            if pid_file.exists():
                try:
                    pid_text = pid_file.read_text().strip()
                    if not pid_text:
                        return False
                    pid = int(pid_text)
                except Exception:
                    return False
                
                try:
                    # os.kill(pid, 0) checks if process exists without sending a signal
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False
            
            # Fallback: scan /proc for pearlalgo.nq_agent.main
            proc_root = Path("/proc")
            if not proc_root.exists():
                return False
            
            for entry in proc_root.iterdir():
                if not entry.is_dir() or not entry.name.isdigit():
                    continue
                cmdline_path = entry / "cmdline"
                try:
                    cmd = cmdline_path.read_text(errors="ignore")
                    if "pearlalgo.nq_agent.main" in cmd:
                        return True
                except Exception:
                    continue
        except Exception:
            # Fail closed: if we can't verify, treat as not running
            return False
        
        return False
    
    async def _check_authorized(self, update: Update) -> bool:
        """Check if update is from authorized chat."""
        if not update.effective_chat:
            return False
        authorized = str(update.effective_chat.id) == str(self.chat_id)
        if not authorized:
            logger.warning(
                "Unauthorized Telegram access",
                extra={"chat_id": update.effective_chat.id, "username": getattr(update.effective_user, 'username', None)},
            )
        return authorized
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        logger.info(f"Received /start command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        message = (
            "🤖 *NQ Agent Bot*\n\n"
            "*Service Control:*\n"
            "• /start_gateway - Start IBKR Gateway\n"
            "• /stop_gateway - Stop IBKR Gateway\n"
            "• /gateway_status - Check Gateway status\n"
            "• /start_agent - Start NQ Agent Service\n"
            "• /stop_agent - Stop NQ Agent Service\n"
            "• /restart_agent - Restart NQ Agent Service\n\n"
            "*Monitoring:*\n"
            "• /status - Get current agent status\n"
            "• /quick_status - Ultra-compact status\n"
            "• /signals - Show recent signals\n"
            "• /last_signal - Show most recent signal with chart\n"
            "• /active_trades - Show currently open positions\n"
            "• /performance - Show performance\n"
            "• /config - Show configuration\n"
            "• /health - Check agent health\n\n"
            "• /help - Show detailed help\n"
        )
        await update.message.reply_text(message, parse_mode="Markdown")
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        message = (
            "📚 *NQ Agent Bot Help*\n\n"
            "*Service Control:*\n"
            "*/start_gateway* - Start IBKR Gateway\n"
            "*/stop_gateway* - Stop IBKR Gateway\n"
            "*/gateway_status* - Check Gateway status\n"
            "*/start_agent* - Start NQ Agent Service\n"
            "*/stop_agent* - Stop NQ Agent Service\n"
            "*/restart_agent* - Restart NQ Agent Service\n\n"
            "*Monitoring:*\n"
            "*/status* - Get current agent status and metrics\n"
            "*/signals* - Show recent trading signals (last 10)\n"
            "*/performance* - Show performance metrics (7-day)\n"
            "*/config* - Show key configuration values\n"
            "*/health* - Check agent health status\n\n"
            "*/pause* - Pause the trading agent (informational)\n"
            "*/resume* - Resume the paused trading agent (informational)\n"
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
            
            # Determine if the actual service process is running
            process_running = self._is_agent_process_running()
            
            # Build status message - trust live process check over stale state
            state_running = state.get("running", False)
            running = process_running and state_running
            paused = state.get("paused", False)
            pause_reason = state.get("pause_reason") or "n/a"
            status_emoji = "🟢" if running and not paused else "⏸️" if paused else "🔴"
            
            message = f"{status_emoji} *Agent Status*\n\n"
            message += f"*Status:* {'RUNNING' if running else 'STOPPED'}\n"
            
            # If the bash status script would say NOT RUNNING, surface that clearly
            if not process_running:
                message += "⚠️ *Note:* Service process is not running. Showing last saved state only.\n"
            if paused:
                message += f"⏸️ *Paused* (reason: `{pause_reason}`)\n"
            
            if "cycle_count" in state:
                message += f"🔄 Cycles: {state.get('cycle_count', 0):,}\n"
            if "signal_count" in state:
                message += f"🔔 Signals: {state.get('signal_count', 0)}\n"
            if "buffer_size" in state:
                message += f"📊 Buffer: {state.get('buffer_size', 0)} bars\n"

            # Add a compact 7d performance summary
            try:
                perf = self.performance_tracker.get_performance_metrics(days=7)
                exited = perf.get("exited_signals", 0)
                if exited > 0:
                    wins = perf.get("wins", 0)
                    losses = perf.get("losses", 0)
                    win_rate = perf.get("win_rate", 0.0) * 100
                    total_pnl = perf.get("total_pnl", 0.0)
                    message += "\n📈 *Performance (7d):*\n"
                    message += f"   {wins}W / {losses}L • {win_rate:.1f}% WR • ${total_pnl:,.2f}\n"
            except Exception as e:
                logger.warning(f"Could not include performance in /status: {e}", exc_info=True)
            
            # Add inline buttons
            keyboard = []
            
            # Service control buttons (first row)
            if not running:
                keyboard.append([InlineKeyboardButton("▶️ Start Agent", callback_data='start_agent')])
            else:
                keyboard.append([InlineKeyboardButton("⏹️ Stop Agent", callback_data='stop_agent')])
            
            # Gateway status button
            keyboard.append([InlineKeyboardButton("🔌 Gateway Status", callback_data='gateway_status')])
            
            # Monitoring buttons (second row)
            keyboard.append([
                InlineKeyboardButton("📊 Performance", callback_data='performance'),
                InlineKeyboardButton("🔔 Signals", callback_data='signals'),
            ])
            
            # Config/health buttons (third row)
            keyboard.append([
                InlineKeyboardButton("⚙️ Config", callback_data='config'),
                InlineKeyboardButton("💚 Health", callback_data='health'),
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling status command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting status*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if agent service is running: `/health`\n"
                f"• Verify state file exists\n"
                f"• Try `/restart_agent` if service is stuck"
            )
            await self._send_message_or_edit(update, context, error_msg)
    
    async def _handle_quick_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /quick_status command - ultra-compact status."""
        logger.info(f"Received /quick_status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        try:
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                await self._send_message_or_edit(
                    update, context,
                    "🔴 *Agent:* NOT RUNNING\n"
                    "💡 Run `/start_agent` to start"
                )
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            process_running = self._is_agent_process_running()
            running = process_running and state.get("running", False)
            status_emoji = "🟢" if running else "🔴"
            
            cycles = state.get('cycle_count', 0)
            signals = state.get('signal_count', 0)
            buffer = state.get('buffer_size', 0)
            
            message = f"{status_emoji} *Quick Status*\n\n"
            message += f"🔄 {cycles:,} cycles\n"
            message += f"🔔 {signals} signals\n"
            message += f"📊 {buffer} bars\n"
            
            # Add performance if available
            try:
                perf = self.performance_tracker.get_performance_metrics(days=7)
                exited = perf.get("exited_signals", 0)
                if exited > 0:
                    wins = perf.get("wins", 0)
                    losses = perf.get("losses", 0)
                    total_pnl = perf.get("total_pnl", 0.0)
                    message += f"\n📈 {wins}W/{losses}L • ${total_pnl:,.2f}"
            except Exception:
                pass
            
            await self._send_message_or_edit(update, context, message)
            
        except Exception as e:
            logger.error(f"Error handling quick_status command: {e}", exc_info=True)
            error_msg = f"❌ Error: {str(e)}"
            await self._send_message_or_edit(update, context, error_msg)
    
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
                await self._send_message_or_edit(update, context, "📭 No signals found")
                return
            
            # Get last 10
            recent_signals = signals[-10:]
            recent_signals.reverse()  # Show newest first
            
            message = f"🔔 *Recent Signals ({len(recent_signals)})*\n\n"
            
            keyboard = []
            for i, sig_data in enumerate(recent_signals, 1):
                signal = sig_data.get("signal", {})
                signal_type = signal.get("type", "unknown")
                direction = signal.get("direction", "long").upper()
                entry_price = signal.get("entry_price", 0)
                status = sig_data.get("status", "unknown")
                signal_id = sig_data.get("signal_id", "")
                
                status_emoji = {
                    "generated": "🆕",
                    "entered": "✅",
                    "exited": "🏁",
                    "expired": "⏰",
                }.get(status, "⚪")
                
                message += f"{i}. {status_emoji} {signal_type} {direction}\n"
                message += f"   Entry: ${entry_price:.2f} | Status: {status}\n\n"
                
                # Add chart button for each signal
                if signal_id:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"📊 Chart {i}",
                            callback_data=f"signal_chart_{signal_id[:16]}"
                        )
                    ])
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling signals command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting signals*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if signals file exists\n"
                f"• Verify agent is running: `/status`\n"
                f"• Wait for signals to be generated"
            )
            await self._send_message_or_edit(update, context, error_msg)
    
    async def _handle_last_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /last_signal command - show most recent signal with chart."""
        logger.info(f"Received /last_signal command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(update, context, "📭 No signals found")
                return
            
            # Read all signals and get the last one
            signals = []
            with open(signals_file) as f:
                for line in f:
                    try:
                        signal_data = json.loads(line.strip())
                        signals.append(signal_data)
                    except json.JSONDecodeError:
                        continue
            
            if not signals:
                await self._send_message_or_edit(update, context, "📭 No signals found")
                return
            
            # Get last signal
            last_signal_data = signals[-1]
            signal = last_signal_data.get("signal", {})
            signal_id = last_signal_data.get("signal_id", "")
            status = last_signal_data.get("status", "unknown")
            
            signal_type = signal.get("type", "unknown")
            direction = signal.get("direction", "long").upper()
            entry_price = signal.get("entry_price", 0)
            stop_loss = signal.get("stop_loss", 0)
            take_profit = signal.get("take_profit", 0)
            
            status_emoji = {
                "generated": "🆕",
                "entered": "✅",
                "exited": "🏁",
                "expired": "⏰",
            }.get(status, "⚪")
            
            message = f"{status_emoji} *Last Signal*\n\n"
            message += f"*Type:* {signal_type} {direction}\n"
            message += f"*Entry:* ${entry_price:.2f}\n"
            if stop_loss:
                message += f"*Stop:* ${stop_loss:.2f}\n"
            if take_profit:
                message += f"*TP:* ${take_profit:.2f}\n"
            message += f"*Status:* {status}\n"
            message += f"*ID:* {signal_id[:16]}...\n"
            
            # Add chart button
            keyboard = []
            if signal_id and self.chart_generator:
                keyboard.append([
                    InlineKeyboardButton("📊 View Chart", callback_data=f"signal_chart_{signal_id[:16]}")
                ])
            keyboard.append([
                InlineKeyboardButton("🔔 All Signals", callback_data='signals')
            ])
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling last_signal command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting last signal*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 Try `/signals` to see all signals"
            )
            await self._send_message_or_edit(update, context, error_msg)
    
    async def _handle_active_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /active_trades command - show currently open positions."""
        logger.info(f"Received /active_trades command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(update, context, "📭 No signals found")
                return
            
            # Read all signals and filter for entered but not exited
            active_trades = []
            with open(signals_file) as f:
                for line in f:
                    try:
                        signal_data = json.loads(line.strip())
                        status = signal_data.get("status", "unknown")
                        if status == "entered":
                            active_trades.append(signal_data)
                    except json.JSONDecodeError:
                        continue
            
            if not active_trades:
                message = "📭 *No Active Trades*\n\n"
                message += "No positions are currently open."
                await self._send_message_or_edit(update, context, message)
                return
            
            message = f"📊 *Active Trades ({len(active_trades)})*\n\n"
            
            for i, trade_data in enumerate(active_trades, 1):
                signal = trade_data.get("signal", {})
                signal_type = signal.get("type", "unknown")
                direction = signal.get("direction", "long").upper()
                entry_price = signal.get("entry_price", 0)
                stop_loss = signal.get("stop_loss", 0)
                take_profit = signal.get("take_profit", 0)
                signal_id = trade_data.get("signal_id", "")
                
                message += f"{i}. {signal_type} {direction}\n"
                message += f"   Entry: ${entry_price:.2f}\n"
                if stop_loss:
                    message += f"   Stop: ${stop_loss:.2f}\n"
                if take_profit:
                    message += f"   TP: ${take_profit:.2f}\n"
                message += f"   ID: {signal_id[:16]}...\n\n"
            
            await self._send_message_or_edit(update, context, message)
            
        except Exception as e:
            logger.error(f"Error handling active_trades command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting active trades*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 Try `/signals` to see all signals"
            )
            await self._send_message_or_edit(update, context, error_msg)
    
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
            
            await self._send_message_or_edit(update, context, message)
            
        except Exception as e:
            logger.error(f"Error handling performance command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting performance*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if performance tracker is working\n"
                f"• Verify signals have been exited\n"
                f"• Try `/status` to check agent state"
            )
            await self._send_message_or_edit(update, context, error_msg)

    async def _handle_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /config command (read-only view of key config)."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        from pathlib import Path
        import yaml

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            project_root = Path(__file__).parent.parent.parent.parent
            config_path = project_root / "config" / "config.yaml"
            if not config_path.exists():
                await update.message.reply_text(
                    "⚙️ *Config:* `config/config.yaml` not found.",
                    parse_mode="Markdown",
                )
                return

            data = yaml.safe_load(config_path.read_text()) or {}
            symbol = data.get("symbol", "MNQ")
            timeframe = data.get("timeframe", "1m")
            scan_interval = data.get("scan_interval", 30)
            risk = data.get("risk", {})

            max_risk_per_trade = risk.get("max_risk_per_trade", 0.01)
            max_drawdown = risk.get("max_drawdown", 0.10)
            min_pos = risk.get("min_position_size", 5)
            max_pos = risk.get("max_position_size", 15)

            message = "⚙️ *Agent Configuration (read-only)*\n\n"
            message += f"*Symbol:* {symbol}\n"
            message += f"*Timeframe:* {timeframe}\n"
            message += f"*Scan Interval:* {scan_interval}s\n\n"
            message += "*Risk (prop firm style):*\n"
            message += f"- Max risk/trade: {max_risk_per_trade:.2%}\n"
            message += f"- Max drawdown: {max_drawdown:.2%}\n"
            message += f"- Position size: {min_pos}-{max_pos} MNQ\n"

            await self._send_message_or_edit(update, context, message)
        except Exception as e:
            logger.error(f"Error handling config command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting config*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if config file exists: `config/config.yaml`\n"
                f"• Verify file permissions\n"
                f"• Ensure YAML format is valid"
            )
            await self._send_message_or_edit(update, context, error_msg)

    async def _handle_health(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /health command (lightweight health summary)."""
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            # Service process + state freshness
            project_root = Path(__file__).parent.parent.parent.parent
            state_file = get_state_file(self.state_dir)

            process_running = self._is_agent_process_running()
            state_exists = state_file.exists()

            last_updated = "unknown"
            if state_exists:
                mtime = state_file.stat().st_mtime
                dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
                last_updated = dt.isoformat(timespec="seconds")

            health_emoji = "🟢" if process_running and state_exists else "🟡" if state_exists else "🔴"
            message = f"{health_emoji} *Agent Health*\n\n"
            message += f"- Service process: {'RUNNING' if process_running else 'NOT RUNNING'}\n"
            message += f"- State file: {'present' if state_exists else 'missing'}\n"
            message += f"- State last updated (UTC): {last_updated}\n"

            await self._send_message_or_edit(update, context, message)
        except Exception as e:
            logger.error(f"Error handling health command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error checking health*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check system permissions\n"
                f"• Verify process detection is working\n"
                f"• Try `/status` for basic status"
            )
            await self._send_message_or_edit(update, context, error_msg)
    
    async def _handle_start_gateway(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_gateway command."""
        logger.info(f"Received /start_gateway command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await update.message.reply_text("🔄 Starting IBKR Gateway... This may take up to 60 seconds.")

        result = await self.service_controller.start_gateway()

        message = f"{result['message']}\n"
        if result.get("details"):
            message += f"\n{result['details']}"

        await update.message.reply_text(message, parse_mode="Markdown")

    async def _handle_stop_gateway(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_gateway command."""
        logger.info(f"Received /stop_gateway command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await update.message.reply_text("🔄 Stopping IBKR Gateway...")

        result = await self.service_controller.stop_gateway()

        message = f"{result['message']}\n"
        if result.get("details"):
            message += f"\n{result['details']}"

        await update.message.reply_text(message, parse_mode="Markdown")

    async def _handle_gateway_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gateway_status command."""
        logger.info(f"Received /gateway_status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        status = self.service_controller.get_gateway_status()

        message = "🔌 *IBKR Gateway Status*\n\n"
        message += f"*Process:* {'🟢 RUNNING' if status['process_running'] else '🔴 STOPPED'}\n"
        message += f"*API Port:* {'🟢 LISTENING' if status['port_listening'] else '🔴 NOT LISTENING'}\n"
        message += f"\n*Status:* {status['message']}"

        await update.message.reply_text(message, parse_mode="Markdown")

    async def _handle_start_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_agent command."""
        logger.info(f"Received /start_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await update.message.reply_text("🔄 Starting NQ Agent Service...")

        result = await self.service_controller.start_agent(background=True)

        message = f"{result['message']}\n"
        if result.get("details"):
            message += f"\n{result['details']}"

        # Add gateway status warning if needed
        gateway_status = self.service_controller.get_gateway_status()
        if not gateway_status["process_running"]:
            message += "\n\n⚠️ *Warning:* IBKR Gateway is not running. Agent may not receive data."

        await update.message.reply_text(message, parse_mode="Markdown")

    async def _handle_stop_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_agent command."""
        logger.info(f"Received /stop_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await update.message.reply_text("🔄 Stopping NQ Agent Service...")

        result = await self.service_controller.stop_agent()

        message = f"{result['message']}\n"
        if result.get("details"):
            message += f"\n{result['details']}"

        await update.message.reply_text(message, parse_mode="Markdown")

    async def _handle_restart_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /restart_agent command."""
        logger.info(f"Received /restart_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await update.message.reply_text("🔄 Restarting NQ Agent Service...")

        # Stop first
        stop_result = await self.service_controller.stop_agent()
        if not stop_result["success"] and "not running" not in stop_result["message"].lower():
            await update.message.reply_text(
                f"⚠️ Stop failed: {stop_result['message']}\nAborting restart.",
                parse_mode="Markdown",
            )
            return

        # Wait a moment
        await asyncio.sleep(2)

        # Start
        start_result = await self.service_controller.start_agent(background=True)

        message = "🔄 *Restart Complete*\n\n"
        message += f"*Stop:* {stop_result['message']}\n"
        message += f"*Start:* {start_result['message']}"

        if start_result.get("details"):
            message += f"\n\n{start_result['details']}"

        await update.message.reply_text(message, parse_mode="Markdown")

    async def _handle_signal_chart(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        signal_id_prefix: str,
    ):
        """Handle signal chart viewing."""
        if not await self._check_authorized(update):
            if update.callback_query:
                await update.callback_query.edit_message_text("❌ Unauthorized access")
            else:
                await update.message.reply_text("❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            if not self.chart_generator:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generation not available. matplotlib may not be installed."
                )
                return
            
            # Find signal by ID
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(update, context, "📭 Signal not found")
                return
            
            signal_data = None
            with open(signals_file) as f:
                for line in f:
                    try:
                        sig_data = json.loads(line.strip())
                        sig_id = sig_data.get("signal_id", "")
                        if sig_id.startswith(signal_id_prefix):
                            signal_data = sig_data
                            break
                    except json.JSONDecodeError:
                        continue
            
            if not signal_data:
                await self._send_message_or_edit(update, context, "📭 Signal not found")
                return
            
            signal = signal_data.get("signal", {})
            
            # Try to get buffer data from state
            # Note: This is a simplified approach - in production, you might want to
            # store buffer data or fetch it from the service
            buffer_data = None
            state_file = get_state_file(self.state_dir)
            if state_file.exists():
                try:
                    with open(state_file) as f:
                        state = json.load(f)
                        # Check if buffer data is stored in state (it might not be)
                        # For now, we'll generate chart without buffer data if not available
                        # The chart generator will handle empty data gracefully
                except Exception:
                    pass
            
            # Generate chart (will work even without buffer data, just won't show price action)
            symbol = signal.get("symbol", "MNQ")
            chart_path = self.chart_generator.generate_entry_chart(
                signal, buffer_data if buffer_data is not None else pd.DataFrame(), symbol
            )
            
            if chart_path and chart_path.exists():
                try:
                    # Send chart
                    with open(chart_path, 'rb') as photo:
                        if update.callback_query:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=photo,
                                caption=f"📊 Chart for {signal.get('type', 'signal')} {signal.get('direction', '').upper()}"
                            )
                        else:
                            await update.message.reply_photo(
                                photo=photo,
                                caption=f"📊 Chart for {signal.get('type', 'signal')} {signal.get('direction', '').upper()}"
                            )
                    # Clean up
                    try:
                        chart_path.unlink()
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Error sending chart: {e}", exc_info=True)
                    await self._send_message_or_edit(
                        update, context,
                        f"❌ Error sending chart: {str(e)}"
                    )
            else:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Could not generate chart. Buffer data may not be available."
                )
                
        except Exception as e:
            logger.error(f"Error handling signal chart: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                f"❌ Error: {str(e)}"
            )
    
    async def _send_message_or_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "Markdown",
    ):
        """Helper to send message for commands or edit for callbacks."""
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                # If edit fails (e.g., message unchanged), send new message
                logger.debug(f"Could not edit message, sending new: {e}")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
        else:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks."""
        query = update.callback_query
        await query.answer()
        
        if not await self._check_authorized(update):
            await query.edit_message_text("❌ Unauthorized access")
            return
        
        callback_data = query.data
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        if callback_data == 'status':
            await self._handle_status(update, context)
        elif callback_data == 'performance':
            await self._handle_performance(update, context)
        elif callback_data == 'signals':
            await self._handle_signals(update, context)
        elif callback_data == 'config':
            await self._handle_config(update, context)
        elif callback_data == 'health':
            await self._handle_health(update, context)
        elif callback_data == 'start_agent':
            await self._handle_start_agent(update, context)
        elif callback_data == 'stop_agent':
            await self._handle_stop_agent(update, context)
        elif callback_data == 'gateway_status':
            await self._handle_gateway_status(update, context)
        elif callback_data.startswith('signal_chart_'):
            # Handle signal chart viewing
            signal_id_prefix = callback_data.replace('signal_chart_', '')
            await self._handle_signal_chart(update, context, signal_id_prefix)
        elif callback_data in ('pause', 'resume'):
            await query.edit_message_text(
                f"⚠️ {callback_data.title()} requires service integration.\n"
                "Use /stop_agent and /start_agent for full control."
            )
        else:
            await query.edit_message_text(f"❌ Unknown action: {callback_data}")
    
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



