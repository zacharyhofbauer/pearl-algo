"""
Telegram Command Handler for NQ Agent

Handles incoming Telegram commands and provides interactive bot functionality.
This can run as a separate service or be integrated into the main service.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Callable, Awaitable

import pandas as pd
import numpy as np

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
        
        # Data provider for fetching historical data (lazy initialization)
        self._data_provider = None
        self._historical_cache_dir = Path(self.state_dir.parent / "historical")
        self._historical_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Build application
        self.application = Application.builder().token(bot_token).build()
        
        # Register handlers
        self._register_handlers()
        
    def _register_handlers(self):
        """Register command and callback handlers."""
        from telegram.ext import MessageHandler, filters
        
        # Add a message handler to log all incoming messages for debugging (low priority)
        async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.message and update.message.text:
                logger.info(f"📨 Incoming message from chat {update.effective_chat.id}: {update.message.text}")
            elif update.callback_query:
                logger.info(f"🔘 Incoming callback from chat {update.effective_chat.id}: {update.callback_query.data}")
        
        # Add logging handler with low priority (so commands are processed first)
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_all_updates), group=99)
        
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
        self.application.add_handler(CommandHandler("backtest", self._handle_backtest))
        self.application.add_handler(CommandHandler("test_signal", self._handle_test_signal))
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
            logger.warning("Update has no effective_chat")
            return False
        chat_id = update.effective_chat.id
        authorized = str(chat_id) == str(self.chat_id)
        if not authorized:
            logger.warning(
                f"Unauthorized Telegram access attempt from chat_id={chat_id} (expected {self.chat_id})",
                extra={"chat_id": chat_id, "username": getattr(update.effective_user, 'username', None)},
            )
        else:
            logger.debug(f"Authorized access from chat_id={chat_id}")
        return authorized
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        logger.info(f"Received /start command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Check if agent is running
        agent_running = self._is_agent_process_running()
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        
        message = (
            "🤖 *NQ Agent Bot*\n\n"
            "Welcome! This is the *main menu* for controlling your NQ trading agent.\n\n"
            "💡 *Important:*\n"
            "• `/start` shows this menu (does NOT start the agent)\n"
            "• Use '▶️ Start Agent' button below to start the agent\n"
            "• Or use `/start_agent` command\n\n"
            "📋 *Quick Start:*\n"
            "1. Check Gateway Status first\n"
            "2. Start Agent when ready\n"
            "3. Monitor via Status & Signals\n\n"
            f"*Current State:*\n"
            f"{'🟢' if agent_running else '🔴'} Agent: {'RUNNING' if agent_running else 'STOPPED'}\n"
            f"{'🟢' if gateway_running else '🔴'} Gateway: {'RUNNING' if gateway_running else 'STOPPED'}"
        )
        
        reply_markup = self._get_main_menu_buttons(agent_running=agent_running, gateway_running=gateway_running)
        logger.info(f"Sending /start menu with {len(reply_markup.inline_keyboard)} button rows to chat {update.effective_chat.id}")
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        message = (
            "📚 *NQ Agent Bot Help*\n\n"
            "*Navigation:*\n"
            "Use the buttons below each message to navigate. No need to type commands!\n\n"
            "*Available Actions:*\n"
            "• Service Control: Start/Stop Agent & Gateway\n"
            "• Monitoring: Status, Signals, Performance\n"
            "• Configuration: View settings and health\n\n"
            "*Tip:* All actions are available via buttons for easy UI navigation."
        )
        
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
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
            
            # Get gateway status for button display
            gateway_status = self.service_controller.get_gateway_status()
            gateway_running = gateway_status.get("process_running", False)
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling status command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting status*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 *Suggestions:*\n"
                f"• Check if agent service is running\n"
                f"• Verify state file exists\n"
                f"• Try restarting the agent"
            )
            gateway_status = self.service_controller.get_gateway_status()
            gateway_running = gateway_status.get("process_running", False)
            reply_markup = self._get_main_menu_buttons(
                agent_running=self._is_agent_process_running(),
                gateway_running=gateway_running
            )
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    async def _handle_quick_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /quick_status command - ultra-compact status."""
        logger.info(f"Received /quick_status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        try:
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                reply_markup = self._get_main_menu_buttons(agent_running=False)
                await self._send_message_or_edit(
                    update, context,
                    "🔴 *Agent:* NOT RUNNING\n\n"
                    "💡 Tap 'Start Agent' below to begin",
                    reply_markup=reply_markup
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
            
            reply_markup = self._get_main_menu_buttons(agent_running=running)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling quick_status command: {e}", exc_info=True)
            error_msg = f"❌ Error: {str(e)}"
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    async def _handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pause command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Note: This requires integration with the running service
        # For now, just acknowledge the command
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running
        )
        await self._send_message_or_edit(
            update, context,
            "⏸️ *Pause command received*\n\n"
            "Note: Direct pause/resume requires service integration.\n"
            "Use Stop Agent and Start Agent buttons for full control.",
            reply_markup=reply_markup
        )
    
    async def _handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /resume command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running
        )
        await self._send_message_or_edit(
            update, context,
            "▶️ *Resume command received*\n\n"
            "Note: Direct pause/resume requires service integration.\n"
            "Use Stop Agent and Start Agent buttons for full control.",
            reply_markup=reply_markup
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
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "The signals file doesn't exist yet.\n"
                    "Signals will appear here once the agent generates trading opportunities.",
                    reply_markup=reply_markup
                )
                return
            
            # Check file size
            file_size = signals_file.stat().st_size
            if file_size == 0:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "The signals file exists but is empty.\n"
                    "This could mean:\n"
                    "• Signals haven't been generated yet\n"
                    "• Signals were generated but not saved (check logs)\n"
                    "• The file was cleared\n\n"
                    f"💡 Check: `ls -lh {signals_file}`",
                    reply_markup=reply_markup
                )
                return
            
            # Read all signals (handle both old and new formats)
            signals = []
            line_num = 0
            with open(signals_file) as f:
                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal_data = json.loads(line)
                        
                        # Handle both formats:
                        # New format: {"signal_id": "...", "timestamp": "...", "status": "...", "signal": {...}}
                        # Old format: {"signal_id": "...", "type": "...", "direction": "...", ...} (signal dict directly)
                        if "signal" in signal_data:
                            # New format - use as is
                            signals.append(signal_data)
                        elif "signal_id" in signal_data or "type" in signal_data:
                            # Old format - wrap it
                            signals.append({
                                "signal_id": signal_data.get("signal_id", f"unknown_{line_num}"),
                                "timestamp": signal_data.get("timestamp", ""),
                                "status": signal_data.get("status", "generated"),
                                "signal": signal_data,  # The whole thing is the signal
                            })
                        else:
                            logger.warning(f"Unknown signal format at line {line_num}: {signal_data.keys()}")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON at line {line_num} in signals file: {e}")
                        continue
            
            if not signals:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    f"📭 *No valid signals found*\n\n"
                    f"File exists ({file_size} bytes) but contains no valid signal records.\n"
                    f"Check logs for parsing errors.",
                    reply_markup=reply_markup
                )
                return
            
            # Get last 10
            recent_signals = signals[-10:]
            recent_signals.reverse()  # Show newest first
            
            total_count = len(signals)
            message = f"🔔 *Signals*\n\n"
            message += f"*Total:* {total_count} signal(s) stored\n"
            message += f"*Showing:* Last {len(recent_signals)} signal(s)\n\n"
            
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
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
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
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "Signals will appear here when the agent generates trading opportunities.",
                    reply_markup=reply_markup
                )
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
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "Signals will appear here when the agent generates trading opportunities.\n\n"
                    "💡 *Tip:* Make sure the agent is running and the market is open.",
                    reply_markup=reply_markup
                )
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
                InlineKeyboardButton("🔔 All Signals", callback_data='signals'),
                InlineKeyboardButton("📈 Performance", callback_data='performance'),
            ])
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data='start')])
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling last_signal command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting last signal*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 Try `/signals` to see all signals"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
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
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "No positions are currently open.",
                    reply_markup=reply_markup
                )
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
                reply_markup = self._get_back_to_menu_button()
                message = "📭 *No Active Trades*\n\n"
                message += "No positions are currently open."
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
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
            
            reply_markup = self._get_back_to_menu_button(include_refresh=True)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling active_trades command: {e}", exc_info=True)
            error_msg = (
                f"❌ *Error getting active trades*\n\n"
                f"`{str(e)}`\n\n"
                f"💡 Try `/signals` to see all signals"
            )
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    def _get_data_provider(self):
        """Get or create data provider for fetching historical data."""
        if self._data_provider is None:
            try:
                from pearlalgo.data_providers.factory import create_data_provider
                from pearlalgo.config.settings import get_settings
                
                settings = get_settings()
                # Try to get provider from config, default to 'ibkr'
                provider_name = getattr(settings, 'data_provider', 'ibkr') if hasattr(settings, 'data_provider') else 'ibkr'
                self._data_provider = create_data_provider(provider_name, settings=settings)
                logger.info(f"Initialized data provider: {provider_name}")
            except Exception as e:
                logger.warning(f"Could not initialize data provider: {e}")
                return None
        return self._data_provider
    
    async def _fetch_historical_data_for_backtest(
        self, 
        symbol: str = "MNQ", 
        months: int = 6,
        timeframe: str = "1m",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch and cache historical data for backtesting.
        
        Args:
            symbol: Symbol to fetch (default: MNQ)
            months: Number of months to fetch (default: 6)
            timeframe: Data timeframe (default: 1m)
            
        Returns:
            DataFrame with historical OHLCV data, or None if fetch failed
        """
        cache_file = self._historical_cache_dir / f"{symbol}_{timeframe}_{months}m.parquet"
        # Backtests should use *completed* historical data only.
        # If today is Monday, "yesterday" is Sunday (no session) which can cause HMDS weirdness/timeouts.
        # Clamp to the most recent weekday (Mon-Fri) at 23:59 UTC.
        end = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
            hour=23, minute=59, second=0, microsecond=0
        )
        while end.weekday() >= 5:  # Sat/Sun
            end = end - timedelta(days=1)
        start = end - timedelta(days=months * 30)
        
        logger.info(f"Fetching {months} months of historical data for {symbol}...")
        
        # Check for cached data first
        if cache_file.exists():
            try:
                cached_data = pd.read_parquet(cache_file)
                if not cached_data.empty:
                    # We REQUIRE a timestamp for backtests. Older caches were saved without it (lost index).
                    if 'timestamp' in cached_data.columns:
                        cached_data['timestamp'] = pd.to_datetime(cached_data['timestamp'])
                        cached_data = cached_data.dropna(subset=["timestamp"])
                        # Normalize return shape: keep timestamp column, but ensure DatetimeIndex for resampling.
                        cached_data = cached_data.sort_values('timestamp')
                        cached_data = cached_data.drop_duplicates(subset=['timestamp'], keep='first')
                        cached_data = cached_data.set_index('timestamp', drop=False)
                        logger.info(f"✅ Using cached data: {len(cached_data):,} bars")
                        return cached_data

                    if isinstance(cached_data.index, pd.DatetimeIndex):
                        cached_data = cached_data.reset_index()
                        # The reset index column name can vary; normalize it to 'timestamp'.
                        if 'timestamp' not in cached_data.columns and len(cached_data.columns) > 0:
                            first_col = cached_data.columns[0]
                            cached_data = cached_data.rename(columns={first_col: 'timestamp'})
                        if 'timestamp' in cached_data.columns:
                            cached_data['timestamp'] = pd.to_datetime(cached_data['timestamp'])
                            cached_data = cached_data.dropna(subset=["timestamp"])
                            cached_data = cached_data.sort_values('timestamp')
                            cached_data = cached_data.drop_duplicates(subset=['timestamp'], keep='first')
                            cached_data = cached_data.set_index('timestamp', drop=False)
                            logger.info(f"✅ Using cached data: {len(cached_data):,} bars")
                            return cached_data

                    logger.warning("Cached data missing timestamp; deleting invalid cache and re-fetching")
                    try:
                        cache_file.unlink()
                    except Exception as delete_error:
                        logger.warning(f"Could not delete invalid cache file: {delete_error}")
            except Exception as e:
                logger.warning(f"Error reading cache: {e}")

        # If an exact cache file doesn't exist (or was invalid), try deriving it from a *larger* cached file.
        # Example: if MNQ_1m_6m.parquet exists, we can slice it to create MNQ_1m_2m.parquet instantly.
        try:
            superset_files = list(self._historical_cache_dir.glob(f"{symbol}_{timeframe}_*m.parquet"))
            candidates = []
            for f in superset_files:
                if f == cache_file:
                    continue
                tail = f.name.split("_")[-1]  # e.g. "6m.parquet"
                if not tail.endswith("m.parquet"):
                    continue
                try:
                    k = int(tail[:-9])  # strip "m.parquet"
                except ValueError:
                    continue
                if k >= months:
                    candidates.append((k, f))

            if candidates:
                # Prefer the smallest superset (closest to requested months)
                candidates.sort(key=lambda x: x[0])
                _, superset_file = candidates[0]
                superset_df = pd.read_parquet(superset_file)
                if not superset_df.empty:
                    if "timestamp" not in superset_df.columns and isinstance(superset_df.index, pd.DatetimeIndex):
                        superset_df = superset_df.reset_index()
                        if "timestamp" not in superset_df.columns and len(superset_df.columns) > 0:
                            first_col = superset_df.columns[0]
                            superset_df = superset_df.rename(columns={first_col: "timestamp"})
                    if "timestamp" in superset_df.columns:
                        superset_df["timestamp"] = pd.to_datetime(superset_df["timestamp"])
                        superset_df = superset_df.dropna(subset=["timestamp"])
                        derived = superset_df[
                            (superset_df["timestamp"] >= start) & (superset_df["timestamp"] <= end)
                        ].copy()
                        if not derived.empty:
                            derived = derived.sort_values("timestamp")
                            derived = derived.drop_duplicates(subset=["timestamp"], keep="first")
                            derived = derived.set_index("timestamp", drop=False)
                            try:
                                derived.to_parquet(cache_file, index=False)
                                logger.info(
                                    f"💾 Derived cache {cache_file.name} from {superset_file.name} "
                                    f"({len(derived):,} bars)"
                                )
                            except Exception as e:
                                logger.warning(f"Could not write derived cache: {e}")
                            return derived
        except Exception as e:
            logger.debug(f"Could not derive cache from superset: {e}")
        
        # Fetch data
        data_provider = self._get_data_provider()
        if data_provider is None:
            logger.error("Data provider not available")
            return None
        
        try:
            # If the most recent window fails (often due to expiry/roll), automatically shift further back in time.
            # This matches your request: "pick past months if that's the only thing that works".
            max_window_shifts = 3
            all_chunks = []
            window_end = end
            window_start = start

            # Smaller chunks are far more reliable with IBKR HMDS for 1m bars.
            # We'll use weekly chunks and, if needed, fall back to daily chunks.
            base_chunk_days = 7

            for shift_idx in range(max_window_shifts + 1):
                if shift_idx > 0:
                    window_end = end - timedelta(days=shift_idx * 30)
                    window_end = window_end.replace(hour=23, minute=59, second=0, microsecond=0)
                    while window_end.weekday() >= 5:  # Sat/Sun
                        window_end = window_end - timedelta(days=1)
                    window_start = window_end - timedelta(days=months * 30)
                    logger.warning(
                        f"No data fetched for requested window; trying earlier window: "
                        f"{window_start.date()} to {window_end.date()}"
                    )

                all_chunks = []
                # Build weekly chunk ranges
                chunk_ranges = []
                cur = window_start
                while cur < window_end:
                    nxt = min(cur + timedelta(days=base_chunk_days), window_end)
                    chunk_ranges.append((cur, nxt))
                    cur = nxt

                total_chunks = max(1, len(chunk_ranges))
                for chunk_i, (chunk_start, chunk_end) in enumerate(chunk_ranges, start=1):
                    logger.info(
                        f"Fetching chunk {chunk_i}/{total_chunks}: {chunk_start.date()} to {chunk_end.date()}"
                    )

                    loop = asyncio.get_event_loop()

                    async def _fetch_range(cs, ce, timeout_s: float):
                        return await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda s=cs, e=ce: data_provider.fetch_historical(
                                    symbol=symbol,
                                    start=s,
                                    end=e,
                                    timeframe=timeframe,
                                )
                            ),
                            timeout=timeout_s,
                        )

                    try:
                        chunk_df = await _fetch_range(chunk_start, chunk_end, timeout_s=120.0)
                    except asyncio.TimeoutError:
                        chunk_df = None
                        logger.warning(
                            f"Chunk {chunk_i}/{total_chunks} timed out (weekly). Falling back to daily slices..."
                        )
                    except Exception as e:
                        chunk_df = None
                        logger.warning(
                            f"Chunk {chunk_i}/{total_chunks} failed (weekly): {e}. Falling back to daily slices..."
                        )

                    if chunk_df is not None and not chunk_df.empty:
                        all_chunks.append(chunk_df)
                        logger.info(f"Successfully fetched chunk: {len(chunk_df)} bars")
                        continue

                    # Daily fallback for this chunk (more requests, but much more reliable)
                    daily_cur = chunk_start
                    daily_chunks = []
                    while daily_cur < chunk_end:
                        daily_nxt = min(daily_cur + timedelta(days=1), chunk_end)
                        try:
                            day_df = await _fetch_range(daily_cur, daily_nxt, timeout_s=45.0)
                        except Exception:
                            day_df = None

                        if day_df is not None and not day_df.empty:
                            daily_chunks.append(day_df)
                        daily_cur = daily_nxt

                    if daily_chunks:
                        day_df_all = pd.concat(daily_chunks)
                        all_chunks.append(day_df_all)
                        logger.info(
                            f"Recovered chunk via daily slices: {len(day_df_all)} bars"
                        )
                        continue

                    # If we can't fetch anything for the earliest part of this window, shift earlier.
                    if not all_chunks:
                        logger.error(
                            f"⚠️ No data fetched for first chunk of window ({chunk_start.date()} to {chunk_end.date()}); "
                            f"trying earlier months..."
                        )
                        break

                    # Otherwise, we already have some data; stop here and use partial dataset.
                    logger.warning(
                        f"Stopping early due to repeated chunk failures; using partial data "
                        f"({len(all_chunks)} chunks fetched so far)."
                    )
                    break

                if all_chunks:
                    # Lock in the window that produced data
                    end = window_end
                    start = window_start
                    break

            if not all_chunks:
                logger.error("❌ No data fetched after trying multiple past windows")
                return None
            
            # Combine chunks
            # IBKRProvider returns a DatetimeIndex; do NOT drop it (older code used ignore_index=True and lost timestamps).
            df = pd.concat(all_chunks)
            if isinstance(df.index, pd.DatetimeIndex):
                df = df[~df.index.duplicated(keep='first')].sort_index()
                # Persist timestamp as a column for caching + downstream usage.
                df = df.reset_index()
                # Normalize index column name to 'timestamp' (index name can be lost during concat/reset).
                if 'timestamp' not in df.columns and len(df.columns) > 0:
                    first_col = df.columns[0]
                    df = df.rename(columns={first_col: 'timestamp'})
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.dropna(subset=["timestamp"])
            
            # Column mapping
            if 'timestamp' not in df.columns and df.index.name == 'timestamp':
                df = df.reset_index()
            
            column_mapping = {
                'Open': 'open', 'High': 'high', 'Low': 'low', 
                'Close': 'close', 'Volume': 'volume'
            }
            for old, new in column_mapping.items():
                if old in df.columns:
                    df = df.rename(columns={old: new})
            
            if 'timestamp' not in df.columns:
                if df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
                    df = df.reset_index()
                    if 'index' in df.columns:
                        df = df.rename(columns={'index': 'timestamp'})
            
            # Normalize return shape: keep timestamp column, but ensure DatetimeIndex for resampling/backtests.
            if 'timestamp' in df.columns:
                df = df.sort_values('timestamp')
                df = df.drop_duplicates(subset=['timestamp'], keep='first')
                df = df.set_index('timestamp', drop=False)

            # Cache
            try:
                df.to_parquet(cache_file, index=False)
                logger.info(f"💾 Cached {len(df):,} bars")
            except Exception as e:
                logger.warning(f"Could not cache: {e}")
            
            logger.info(f"✅ Complete: {len(df):,} bars")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching data: {e}", exc_info=True)
            return None
    
    async def _handle_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE, months: Optional[int] = None):
        """Handle /backtest command - run backtest and show results with chart."""
        logger.info(f"Received /backtest command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # If no months specified, show duration selection menu
        if months is None:
            mode = (context.user_data.get("backtest_mode") or "5m") if hasattr(context, "user_data") else "5m"
            if mode not in ("5m", "1m"):
                mode = "5m"
            mode_label = "5m decision (recommended)" if mode == "5m" else "1m (legacy)"

            message = (
                "📊 *Backtest Strategy*\n\n"
                f"*Mode:* {mode_label}\n\n"
                "Select backtest duration:\n\n"
                "Tip: 2 months is a great default. 6 months is for deeper checks."
            )
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("1 Month", callback_data='backtest_1m'),
                    InlineKeyboardButton("2 Months", callback_data='backtest_2m'),
                ],
                [
                    InlineKeyboardButton("3 Months", callback_data='backtest_3m'),
                    InlineKeyboardButton("4 Months", callback_data='backtest_4m'),
                ],
                [
                    InlineKeyboardButton("5 Months", callback_data='backtest_5m'),
                    InlineKeyboardButton("6 Months", callback_data='backtest_6m'),
                ],
                [
                    InlineKeyboardButton(
                        "✅ 5m mode" if mode == "5m" else "5m mode",
                        callback_data="backtest_setmode_5m",
                    ),
                    InlineKeyboardButton(
                        "✅ 1m legacy" if mode == "1m" else "1m legacy",
                        callback_data="backtest_setmode_1m",
                    ),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            from pearlalgo.strategies.nq_intraday.backtest_adapter import (
                run_signal_backtest,
                run_signal_backtest_5m_decision,
            )
            from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
            
            mode = (context.user_data.get("backtest_mode") or "5m") if hasattr(context, "user_data") else "5m"
            if mode not in ("5m", "1m"):
                mode = "5m"

            # Simple message like the original that worked (NO PROGRESS BAR)
            await self._send_message_or_edit(
                update, context,
                f"📊 *Fetching Historical Data*\n\n"
                f"Mode: {'5m decision' if mode == '5m' else '1m legacy'}\n"
                f"Fetching {months} month{'s' if months > 1 else ''} of historical data for backtest...\n"
                f"This may take a minute...",
                reply_markup=None
            )
            
            # Fetch data (no progress callbacks - they interfere)
            historical_data = await self._fetch_historical_data_for_backtest(
                symbol="MNQ",
                months=months,
                timeframe="1m",
            )
            
            signals_from_backtest = []
            
            if historical_data is not None and not historical_data.empty:
                # Prepare data for backtest
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
                
                # Ensure data is in correct format for backtest
                backtest_data = historical_data.copy()
                
                # CRITICAL: Ensure timestamp is properly set as DatetimeIndex
                if 'timestamp' in backtest_data.columns:
                    # Convert timestamp to datetime if it's not already
                    backtest_data['timestamp'] = pd.to_datetime(backtest_data['timestamp'])
                    backtest_data = backtest_data.set_index('timestamp')
                elif not isinstance(backtest_data.index, pd.DatetimeIndex):
                    # If index is not DatetimeIndex, try to convert it
                    logger.warning("Historical data index is not DatetimeIndex, attempting to convert")
                    if backtest_data.index.name == 'timestamp' or 'timestamp' in backtest_data.columns:
                        if 'timestamp' in backtest_data.columns:
                            backtest_data['timestamp'] = pd.to_datetime(backtest_data['timestamp'])
                            backtest_data = backtest_data.set_index('timestamp')
                        else:
                            # Try to convert the index itself
                            backtest_data.index = pd.to_datetime(backtest_data.index)
                    else:
                        # Last resort: reset index and use first datetime-like column
                        backtest_data = backtest_data.reset_index()
                        for col in backtest_data.columns:
                            if 'time' in col.lower() or 'date' in col.lower():
                                backtest_data[col] = pd.to_datetime(backtest_data[col])
                                backtest_data = backtest_data.set_index(col)
                                break
                
                # Ensure we have a DatetimeIndex
                if not isinstance(backtest_data.index, pd.DatetimeIndex):
                    raise ValueError(f"Could not convert data index to DatetimeIndex. Index type: {type(backtest_data.index)}")
                
                # Ensure required columns exist (uppercase for backtest)
                column_mapping = {
                    'open': 'Open', 'high': 'High', 'low': 'Low',
                    'close': 'Close', 'volume': 'Volume'
                }
                for lower, upper in column_mapping.items():
                    if lower in backtest_data.columns and upper not in backtest_data.columns:
                        backtest_data[upper] = backtest_data[lower]
                
                # Running backtest (no progress updates - they interfere)
                
                config = NQIntradayConfig()
                if mode == "5m":
                    result = run_signal_backtest_5m_decision(
                        backtest_data,
                        config=config,
                        return_signals=True,
                        decision_rule="5min",
                        context_rule_1="1h",
                        context_rule_2="4h",
                    )
                else:
                    result = run_signal_backtest(backtest_data, config=config, return_signals=True)
                        
                # Use actual signals from backtest if available
                if result.signals and len(result.signals) > 0:
                    # Use real signals from backtest
                    for signal in result.signals:
                        # Ensure timestamp is set
                        if 'timestamp' not in signal or not signal.get('timestamp'):
                            # Find closest timestamp in data
                            entry_price = signal.get('entry_price', 0)
                            if entry_price > 0:
                                close_col = 'Close' if 'Close' in backtest_data.columns else 'close'
                                closest_idx = (backtest_data[close_col] - entry_price).abs().idxmin()
                                signal['timestamp'] = closest_idx.isoformat() if hasattr(closest_idx, 'isoformat') else str(closest_idx)
                        signals_from_backtest.append(signal)
                
                # Generate backtest chart
                if self.chart_generator and not backtest_data.empty:
                    signals_shown = len(signals_from_backtest)
                    
                    # Create clearer title
                    data_start = backtest_data.index[0].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    data_end = backtest_data.index[-1].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    chart_title = (
                        f"Backtest Results ({data_start} to {data_end}) - "
                        f"{result.total_signals} Signals - "
                        f"{'5m decision' if mode == '5m' else '1m legacy'}"
                    )
                    
                    # Prepare performance data
                    performance_data = {
                        "total_signals": result.total_signals,
                        "avg_confidence": result.avg_confidence,
                        "avg_risk_reward": result.avg_risk_reward,
                        "win_rate": result.win_rate if result.win_rate is not None else 0.0,
                        "total_pnl": result.total_pnl if result.total_pnl is not None else 0.0,
                    }
                    
                    # Convert back to format expected by chart generator (reset index to get timestamp column)
                    if mode == "5m":
                        # Show the chart on 5-minute candles (matches trading workflow)
                        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
                        if "volume" in backtest_data.columns:
                            agg["volume"] = "sum"
                        df_5m = backtest_data.resample("5min").agg(agg).dropna()
                        chart_data = df_5m.reset_index()
                    else:
                        chart_data = backtest_data.reset_index()
                    if 'timestamp' not in chart_data.columns and chart_data.index.name == 'timestamp':
                        chart_data = chart_data.reset_index()
                    
                    chart_path = self.chart_generator.generate_backtest_chart(
                        chart_data,
                        signals_from_backtest,
                        'MNQ',
                        chart_title,
                        performance_data=performance_data,
                        timeframe=("5m" if mode == "5m" else "1m"),
                    )
                            
                    # Format results message
                    data_start = backtest_data.index[0].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    data_end = backtest_data.index[-1].strftime('%Y-%m-%d') if len(backtest_data) > 0 else 'N/A'
                    
                    win_rate_display = f"{result.win_rate:.1%}" if result.win_rate is not None else "N/A"
                    total_pnl_display = f"${result.total_pnl:.2f}" if result.total_pnl is not None else "N/A"

                    message = (
                        f"📊 *Backtest Results ({months} Month{'s' if months > 1 else ''})*\n\n"
                        f"*Period:* {data_start} to {data_end}\n"
                        f"*Bars Analyzed:* {result.total_bars:,}\n"
                        f"*Signals Generated:* {result.total_signals}\n"
                        f"*Signals on Chart:* {signals_shown}\n"
                        f"*Avg Confidence:* {result.avg_confidence:.2f}\n"
                        f"*Avg R:R:* {result.avg_risk_reward:.2f}:1\n"
                        f"*Win Rate:* {win_rate_display}\n"
                        f"*Total P&L:* {total_pnl_display}\n\n"
                        "📈 *Chart Components:*\n"
                        "• Green/Red candlesticks = Price action\n"
                        "• 🔼 Green triangles = Long entry signals\n"
                        "• 🔽 Orange triangles = Short entry signals\n"
                        "• Volume bars (bottom panel)\n"
                        "• VWAP line (orange)\n"
                        "• Moving averages (blue/purple)"
                    )
                            
                    reply_markup = InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Run Again", callback_data='backtest'),
                        InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                    ]])
                    
                    await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                    
                    # Send chart
                    if chart_path and chart_path.exists():
                        try:
                            with open(chart_path, 'rb') as photo:
                                if update.callback_query:
                                    await context.bot.send_photo(
                                        chat_id=update.effective_chat.id,
                                        photo=photo,
                                        caption="📊 Backtest Chart (6 Months Historical Data)"
                                    )
                                else:
                                    await update.message.reply_photo(
                                        photo=photo,
                                        caption="📊 Backtest Chart (6 Months Historical Data)"
                                    )
                            chart_path.unlink()
                        except Exception as e:
                            logger.error(f"Error sending backtest chart: {e}")
                else:
                    message = (
                        "📊 *Backtest Results*\n\n"
                        f"*Bars Analyzed:* {result.total_bars:,}\n"
                        f"*Signals Generated:* {result.total_signals}\n"
                        f"*Avg Confidence:* {result.avg_confidence:.2f}\n"
                        f"*Avg R:R:* {result.avg_risk_reward:.2f}:1\n\n"
                        "⚠️ Chart generation not available"
                    )
                    reply_markup = self._get_back_to_menu_button()
                    await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            else:
                # Failed to fetch historical data - check for any cached data
                cache_files = list(self._historical_cache_dir.glob("MNQ_1m_*.parquet"))
                cache_info = ""
                if cache_files:
                    # Find the most recent cache
                    most_recent = max(cache_files, key=lambda f: f.stat().st_mtime)
                    cache_age = datetime.now(timezone.utc) - datetime.fromtimestamp(
                        most_recent.stat().st_mtime, tz=timezone.utc
                    )
                    cache_info = (
                        f"\n💡 *Found cached data:* {most_recent.name} ({cache_age.days} days old)\n"
                        f"   Try using cached data (recommended) or retry fetching."
                    )
                else:
                    cache_info = (
                        "\n⚠️ *No cached data found.*\n"
                        "   IBKR HMDS may be timing out or rate-limiting requests.\n"
                        "   Try again in a few minutes or choose a shorter backtest window."
                    )
                
                message = (
                    "📊 *Backtest Strategy*\n\n"
                    "❌ Could not fetch historical data for backtest.\n\n"
                    "*Likely causes:*\n"
                    "• IBKR HMDS timeout / temporary outage\n"
                    "• Pacing / rate limiting on historical requests\n"
                    "• Contract rollover edge-case\n\n"
                    f"{cache_info}\n\n"
                    "*Solutions:*\n"
                    "1. Try again (sometimes HMDS recovers within minutes)\n"
                    "2. Choose a shorter backtest window (1–2 months)\n"
                    "3. Use command line with an existing data file:\n"
                    "```bash\n"
                    "python3 scripts/testing/backtest_nq_strategy.py data.parquet\n"
                    "```\n"
                    "4. If it still fails, retry later (IBKR side)"
                )
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Try Again", callback_data='backtest'),
                    InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                ]])
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                
        except Exception as e:
            logger.error(f"Error handling backtest command: {e}", exc_info=True)
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(
                update, context,
                f"❌ *Error:* {str(e)}",
                reply_markup=reply_markup
            )
    
    async def _handle_test_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /test_signal command - generate a test signal with chart for testing."""
        logger.info(f"Received /test_signal command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            if not self.chart_generator:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generation not available.\n\n"
                    "Install matplotlib: `pip install matplotlib`",
                    reply_markup=reply_markup
                )
                return
            
            # Generate test data using same method as test_mplfinance_chart.py
            def create_sample_data(num_bars=100):
                """Create sample OHLCV data for testing (same as test_mplfinance_chart.py)."""
                base_price = 25000.0
                dates = pd.date_range(
                    end=datetime.now(timezone.utc),
                    periods=num_bars,
                    freq='1min'
                )
                
                # Generate realistic price data
                np.random.seed(42)
                price_changes = np.random.randn(num_bars) * 5
                prices = base_price + np.cumsum(price_changes)
                
                data = []
                for i, (date, price) in enumerate(zip(dates, prices)):
                    volatility = abs(np.random.randn() * 2)
                    high = price + volatility
                    low = price - volatility
                    open_price = prices[i-1] if i > 0 else price
                    close_price = price
                    
                    data.append({
                        'timestamp': date,
                        'open': open_price,
                        'high': high,
                        'low': low,
                        'close': close_price,
                        'volume': int(np.random.uniform(1000, 5000))
                    })
                
                return pd.DataFrame(data)
            
            # Create sample data (same as test_mplfinance_chart.py)
            test_data = create_sample_data(100)
            
            # Calculate signal prices based on actual data range (so they're visible on chart)
            data_high = test_data['high'].max()
            data_low = test_data['low'].min()
            data_close = test_data['close'].iloc[-1]  # Use last close as reference
            
            # Entry price: slightly above current price (for long signal)
            entry_price = data_close + (data_high - data_low) * 0.1  # 10% of range above
            
            # Stop loss: below entry (risk of ~$50)
            stop_loss = entry_price - 50.0
            
            # Take profit: above entry (reward of ~$75, R:R = 1.5:1)
            take_profit = entry_price + 75.0
            
            # Ensure prices are within reasonable range of data
            if stop_loss < data_low:
                stop_loss = data_low - 10.0  # Slightly below data range
            if entry_price > data_high:
                entry_price = data_high + 10.0  # Slightly above data range
            if take_profit > data_high + 50:
                take_profit = data_high + 50.0  # Keep TP visible
            
            # Create test signal with prices based on actual data
            test_signal = {
                'entry_price': round(entry_price, 2),
                'stop_loss': round(stop_loss, 2),
                'take_profit': round(take_profit, 2),
                'direction': 'long',
                'type': 'momentum_breakout',
                'symbol': 'MNQ',
                'confidence': 0.75,
                'reason': 'Test signal for chart visualization',
            }
            
            # Generate chart
            chart_path = self.chart_generator.generate_entry_chart(
                test_signal, test_data, 'MNQ'
            )
            
            if chart_path and chart_path.exists():
                # Calculate R:R ratio
                risk = abs(entry_price - stop_loss)
                reward = abs(take_profit - entry_price)
                rr_ratio = reward / risk if risk > 0 else 0
                
                # Send test signal message
                message = (
                    "🧪 *Test Signal Generated*\n\n"
                    f"*Type:* Momentum Breakout (LONG)\n"
                    f"*Entry:* ${entry_price:,.2f}\n"
                    f"*Stop:* ${stop_loss:,.2f}\n"
                    f"*TP:* ${take_profit:,.2f}\n"
                    f"*R:R:* {rr_ratio:.2f}:1\n\n"
                    "📊 Chart generated below!"
                )
                
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Generate Another", callback_data='test_signal'),
                    InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                ]])
                
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                
                # Send chart
                try:
                    with open(chart_path, 'rb') as photo:
                        if update.callback_query:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=photo,
                                caption="📊 Test Signal Chart"
                            )
                        else:
                            await update.message.reply_photo(
                                photo=photo,
                                caption="📊 Test Signal Chart"
                            )
                    
                    # Clean up
                    chart_path.unlink()
                    logger.info("Test signal chart sent successfully")
                    
                except Exception as e:
                    logger.error(f"Error sending test chart: {e}", exc_info=True)
                    await self._send_message_or_edit(
                        update, context,
                        f"⚠️ Chart generated but failed to send: {str(e)}"
                    )
            else:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "❌ Failed to generate test chart",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error handling test_signal command: {e}", exc_info=True)
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(
                update, context,
                f"❌ *Error:* {str(e)}",
                reply_markup=reply_markup
            )
    
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
            
            reply_markup = self._get_back_to_menu_button(include_refresh=True)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
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
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

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

            reply_markup = self._get_back_to_menu_button(include_refresh=True)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
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
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

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

            reply_markup = self._get_back_to_menu_button(include_refresh=True)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
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
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
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
        
        # Get updated gateway status
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)

        reply_markup = self._get_gateway_buttons(gateway_running=gateway_running)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

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
        
        if not status['process_running']:
            message += "\n\n💡 *Tip:* Start Gateway before starting the Agent."

        reply_markup = self._get_gateway_buttons(gateway_running=status['process_running'])
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

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

        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        reply_markup = self._get_main_menu_buttons(agent_running=False, gateway_running=gateway_running)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

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
            reply_markup = self._get_main_menu_buttons(agent_running=True)
            await self._send_message_or_edit(
                update, context,
                f"⚠️ Stop failed: {stop_result['message']}\nAborting restart.",
                reply_markup=reply_markup
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

        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        reply_markup = self._get_main_menu_buttons(agent_running=True, gateway_running=gateway_running)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

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
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generation not available. matplotlib may not be installed.",
                    reply_markup=reply_markup
                )
                return
            
            # Find signal by ID
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *Signal not found*\n\n"
                    "The signals file doesn't exist.",
                    reply_markup=reply_markup
                )
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
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *Signal not found*\n\n"
                    "The requested signal could not be found in the signals file.",
                    reply_markup=reply_markup
                )
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
    
    def _get_main_menu_buttons(self, agent_running: bool = False, gateway_running: bool = False) -> InlineKeyboardMarkup:
        """Generate main menu inline keyboard buttons with improved UX."""
        keyboard = []
        
        # Primary actions row (most important)
        if agent_running:
            keyboard.append([
                InlineKeyboardButton("⏹️ Stop Agent", callback_data='stop_agent'),
                InlineKeyboardButton("🔄 Restart", callback_data='restart_agent'),
            ])
        else:
            keyboard.append([InlineKeyboardButton("▶️ Start Agent", callback_data='start_agent')])
        
        # Gateway control row
        gateway_status_text = "🔌 Gateway" + (" ✅" if gateway_running else " ❌")
        keyboard.append([
            InlineKeyboardButton(gateway_status_text, callback_data='gateway_status'),
            InlineKeyboardButton("🔄 Refresh", callback_data='status'),
        ])
        
        # Quick monitoring row
        keyboard.append([
            InlineKeyboardButton("📊 Status", callback_data='status'),
            InlineKeyboardButton("🔔 Signals", callback_data='signals'),
        ])
        
        # Analysis row
        keyboard.append([
            InlineKeyboardButton("📈 Performance", callback_data='performance'),
            InlineKeyboardButton("📉 Backtest", callback_data='backtest'),
        ])
        
        # Secondary actions row
        keyboard.append([
            InlineKeyboardButton("⚙️ Config", callback_data='config'),
            InlineKeyboardButton("💚 Health", callback_data='health'),
        ])
        
        # Testing row
        keyboard.append([
            InlineKeyboardButton("🧪 Test Signal", callback_data='test_signal'),
        ])
        
        # Help row
        keyboard.append([InlineKeyboardButton("❓ Help", callback_data='help')])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _get_gateway_buttons(self, gateway_running: bool = False) -> InlineKeyboardMarkup:
        """Generate gateway control buttons."""
        keyboard = []
        
        # Primary gateway actions
        if gateway_running:
            keyboard.append([
                InlineKeyboardButton("⏹️ Stop Gateway", callback_data='stop_gateway'),
                InlineKeyboardButton("🔄 Refresh", callback_data='gateway_status'),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("▶️ Start Gateway", callback_data='start_gateway'),
                InlineKeyboardButton("🔄 Refresh", callback_data='gateway_status'),
            ])
        
        # Navigation
        keyboard.append([
            InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
            InlineKeyboardButton("📊 Agent Status", callback_data='status'),
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    def _get_back_to_menu_button(self, include_refresh: bool = False) -> InlineKeyboardMarkup:
        """Generate navigation buttons - always returns to main menu (/start)."""
        keyboard = []
        if include_refresh:
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data='status'),
                InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
            ])
        else:
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data='start')])
        return InlineKeyboardMarkup(keyboard)
    
    def _get_signals_buttons(self, has_signals: bool = True) -> InlineKeyboardMarkup:
        """Generate buttons for signals view."""
        keyboard = []
        if has_signals:
            keyboard.append([
                InlineKeyboardButton("🔄 Refresh", callback_data='signals'),
                InlineKeyboardButton("📊 Last Signal", callback_data='last_signal'),
            ])
        # Always include main menu button
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data='start')])
        keyboard.append([
            InlineKeyboardButton("📈 Performance", callback_data='performance'),
            InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
        ])
        return InlineKeyboardMarkup(keyboard)
    
    async def _send_message_or_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "Markdown",
    ):
        """Helper to send message for commands or edit for callbacks."""
        try:
            if update.callback_query:
                try:
                    await update.callback_query.edit_message_text(
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    logger.debug(f"Edited message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                except Exception as e:
                    # If edit fails (e.g., message unchanged), send new message
                    logger.debug(f"Could not edit message, sending new: {e}")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    logger.debug(f"Sent new message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
            else:
                if update.message:
                    await update.message.reply_text(
                        message,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    logger.info(f"Sent message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows to chat {update.effective_chat.id}")
                else:
                    # Fallback: send directly via bot
                    logger.warning("No update.message, sending directly via bot")
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    logger.info(f"Sent message directly with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            # Try to send error message without markup
            try:
                error_msg = f"❌ Error sending message: {str(e)[:100]}"
                if update.message:
                    await update.message.reply_text(error_msg)
                else:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=error_msg)
            except Exception as e2:
                logger.error(f"Could not send error message: {e2}")
    
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
        elif callback_data == 'start_gateway':
            await self._handle_start_gateway(update, context)
        elif callback_data == 'stop_gateway':
            await self._handle_stop_gateway(update, context)
        elif callback_data == 'start' or callback_data == 'main_menu':
            # Main menu - always return to start
            await self._handle_start(update, context)
        elif callback_data == 'help':
            await self._handle_help(update, context)
        elif callback_data == 'test_signal':
            await self._handle_test_signal(update, context)
        elif callback_data == 'backtest':
            await self._handle_backtest(update, context)
        elif callback_data.startswith('backtest_setmode_'):
            # Toggle backtest mode (5m recommended vs 1m legacy)
            mode = callback_data.replace('backtest_setmode_', '')
            if mode not in ("5m", "1m"):
                mode = "5m"
            if hasattr(context, "user_data"):
                context.user_data["backtest_mode"] = mode
            await self._handle_backtest(update, context, months=None)
        elif callback_data.startswith('backtest_'):
            # Handle backtest duration selection (backtest_1m, backtest_2m, etc.)
            try:
                months_str = callback_data.replace('backtest_', '').replace('m', '')
                months = int(months_str)
                if 1 <= months <= 6:
                    await self._handle_backtest(update, context, months=months)
                else:
                    await self._send_message_or_edit(
                        update, context,
                        f"❌ Invalid duration: {months} months. Please select 1-6 months.",
                        reply_markup=self._get_back_to_menu_button()
                    )
            except ValueError:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Invalid backtest duration format.",
                    reply_markup=self._get_back_to_menu_button()
                )
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



