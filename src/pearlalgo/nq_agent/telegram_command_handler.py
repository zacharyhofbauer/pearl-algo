"""
Telegram Command Handler for NQ Agent

Handles incoming Telegram commands and provides interactive bot functionality.
This can run as a separate service or be integrated into the main service.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Callable, Awaitable, List

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
from pearlalgo.utils.telegram_alerts import (
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    format_time_ago,
    format_home_card,
    format_gate_status,
    format_service_status,
    safe_label,
    escape_subprocess_output,
    _format_currency,
    # Standardized terminology constants
    LABEL_AGENT,
    LABEL_GATEWAY,
    LABEL_ACTIVE_TRADES,
    LABEL_SCANS,
    LABEL_BUFFER,
    STATE_RUNNING,
    STATE_STOPPED,
    STATE_PAUSED,
    GATE_OPEN,
    GATE_CLOSED,
)

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
        self.application.add_handler(CommandHandler("data_quality", self._handle_data_quality))
        self.application.add_handler(CommandHandler("activity", self._handle_activity))
        self.application.add_handler(CommandHandler("glossary", self._handle_glossary))
        self.application.add_handler(CommandHandler("explain", self._handle_glossary))  # Alias
        self.application.add_handler(CommandHandler("chart", self._handle_chart))
        
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

    def _get_signals_file_stats(self, signals_file: Path) -> Dict:
        """
        Get quick diagnostics for signals.jsonl.

        Returns counts of total non-empty lines, valid JSON records, and parse errors.
        """
        stats: Dict = {
            "exists": False,
            "size_bytes": 0,
            "lines": 0,
            "valid": 0,
            "invalid": 0,
        }

        try:
            if not signals_file.exists():
                return stats

            stats["exists"] = True
            stats["size_bytes"] = int(signals_file.stat().st_size)
            if stats["size_bytes"] == 0:
                return stats

            with open(signals_file, "r") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    stats["lines"] += 1
                    try:
                        json.loads(line)
                        stats["valid"] += 1
                    except json.JSONDecodeError:
                        stats["invalid"] += 1

            return stats
        except Exception as e:
            logger.debug(f"Could not compute signals file stats: {e}")
            return stats

    # -------------------------------------------------------------------------
    # State parsing helpers (robust fallback chain for data age / price)
    # -------------------------------------------------------------------------

    def _extract_data_age_minutes(self, state: Dict) -> Optional[float]:
        """
        Extract data age in minutes from state with robust fallback chain.

        Priority:
          1. state["latest_bar_age_minutes"] (pre-computed by service)
          2. Parse state["latest_bar_timestamp"] (ISO string)
          3. Parse state["latest_bar"]["timestamp"] (nested dict)

        Returns None if unavailable.
        """
        # 1. Pre-computed age (most reliable when present)
        try:
            age = state.get("latest_bar_age_minutes")
            if age is not None:
                return float(age)
        except Exception:
            pass

        # 2. Parse top-level latest_bar_timestamp
        ts_str = state.get("latest_bar_timestamp")
        if ts_str:
            age = self._timestamp_to_age_minutes(ts_str)
            if age is not None:
                return age

        # 3. Parse nested latest_bar.timestamp
        latest_bar = state.get("latest_bar")
        if isinstance(latest_bar, dict):
            ts_str = latest_bar.get("timestamp")
            if ts_str:
                age = self._timestamp_to_age_minutes(ts_str)
                if age is not None:
                    return age

        return None

    def _timestamp_to_age_minutes(self, ts_str: str) -> Optional[float]:
        """Convert ISO timestamp string to age in minutes (now - ts)."""
        try:
            from pearlalgo.utils.paths import parse_utc_timestamp

            ts = parse_utc_timestamp(str(ts_str))
            if ts is None:
                return None
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_delta = datetime.now(timezone.utc) - ts
            return age_delta.total_seconds() / 60.0
        except Exception:
            return None

    def _extract_latest_price(self, state: Dict) -> Optional[float]:
        """
        Extract latest price from state with fallback chain.

        Priority:
          1. state["latest_bar"]["close"]
          2. state["latest_price"] (legacy / push dashboard field)
        """
        # 1. Nested latest_bar.close
        latest_bar = state.get("latest_bar")
        if isinstance(latest_bar, dict):
            close = latest_bar.get("close")
            if close is not None:
                try:
                    return float(close)
                except Exception:
                    pass

        # 2. Top-level latest_price (fallback)
        lp = state.get("latest_price")
        if lp is not None:
            try:
                return float(lp)
            except Exception:
                pass

        return None

    def _compute_state_stale_threshold(self, state: Dict) -> float:
        """
        Compute a sensible state staleness threshold based on configured cadence.

        Default: 2 * state_save_interval * scan_interval (in seconds).
        Floor: 120s to avoid over-sensitive warnings.

        The service saves state every state_save_interval cycles, and each cycle
        takes scan_interval seconds. Allow 2x headroom before flagging.
        """
        try:
            from pearlalgo.config.config_loader import load_service_config

            cfg = load_service_config()
            service_cfg = cfg.get("service", {})
            state_save_interval = int(service_cfg.get("state_save_interval", 10))
        except Exception:
            state_save_interval = 10

        # Scan interval from state (persisted by service)
        scan_interval = 60  # default
        try:
            config_block = state.get("config", {})
            if isinstance(config_block, dict):
                scan_interval = int(config_block.get("scan_interval", 60))
        except Exception:
            pass

        threshold = float(2 * state_save_interval * scan_interval)
        # Floor at 120s to avoid false warnings during normal operation
        return max(threshold, 120.0)

    # Control panel persistence removed (per user request to simplify)
    
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
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        
        message = (
            "🤖 *NQ Agent Bot*\n\n"
            "Welcome! This is the *main menu* for controlling your NQ trading agent.\n\n"
            "💡 *Important:*\n"
            "• `/start` shows this menu (does NOT start the agent)\n"
            "• Use '▶️ Start Agent' button below to start the agent\n"
            "• Or use `/start_agent` command\n\n"
            "📋 *Quick Start:*\n"
            f"1. Check {LABEL_GATEWAY} status first\n"
            f"2. Start {LABEL_AGENT} when ready\n"
            "3. Monitor via Status & Signals\n\n"
            f"*Current State:*\n"
            f"{'🟢' if agent_running else '🔴'} {LABEL_AGENT}: {STATE_RUNNING if agent_running else STATE_STOPPED}\n"
            f"{'🟢' if gateway_running else '🔴'} {LABEL_GATEWAY}: {STATE_RUNNING if gateway_running else STATE_STOPPED}"
        )
        
        reply_markup = self._get_main_menu_buttons(
            agent_running=agent_running,
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
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
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_glossary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /glossary or /explain command - show definitions for key terms.
        
        Provides concise explanations for:
        - Scans vs Signals
        - Pressure (buy/sell)
        - MTF (multi-timeframe)
        - Gates (Futures/Session)
        - Active Trades
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Check if a specific term was requested
        args = context.args if context.args else []
        
        # Define glossary entries
        glossary = {
            "scans": (
                "🔄 *Scans*\n"
                "Each scan is one iteration of the strategy loop. "
                "The agent scans market data at regular intervals "
                "(e.g., every 60s) looking for trading setups. "
                "High scan count = agent is actively working."
            ),
            "signals": (
                "🔔 *Signals*\n"
                "A signal is a trading opportunity detected by the strategy. "
                "Signals go through stages: generated → sent → entered → exited. "
                "'Generated' means a pattern matched; 'Sent' means it was delivered to Telegram."
            ),
            "pressure": (
                "📊 *Buy/Sell Pressure*\n"
                "Shows order flow imbalance from Level 2 data. "
                "Positive = more buy pressure; Negative = more sell pressure. "
                "Helps gauge short-term market sentiment. "
                "Only available with Level 2 market data subscription."
            ),
            "mtf": (
                "📈 *MTF (Multi-Timeframe)*\n"
                "Shows trend direction across multiple timeframes (5m, 15m, 1h, 4h, 1D). "
                "⬆️ = bullish, ⬇️ = bearish, ➡️ = neutral. "
                "Helps assess if trends align across timeframes for higher-probability trades."
            ),
            "gates": (
                "🚦 *Gates (Futures/Session)*\n"
                f"• *{LABEL_FUTURES}:* CME futures market hours (includes ETH). "
                "When closed, no live data flows.\n"
                f"• *{LABEL_SESSION}:* Strategy's trading window (9:30 AM - 4:00 PM ET). "
                "Signals are suppressed outside this window."
            ),
            "active_trades": (
                f"🎯 *{LABEL_ACTIVE_TRADES}*\n"
                "Currently open positions (signals with status='entered'). "
                "These are being monitored for stop-loss and take-profit levels. "
                "Use /active_trades to see details and unrealized P&L."
            ),
            "buffer": (
                f"📊 *Buffer ({LABEL_BUFFER})*\n"
                "Rolling window of recent price bars held in memory. "
                "Required for technical analysis calculations. "
                "Low buffer count means insufficient data for reliable signals."
            ),
        }
        
        if args:
            term = args[0].lower()
            if term in glossary:
                message = glossary[term]
            else:
                message = (
                    f"❓ Unknown term: `{term}`\n\n"
                    "Available terms: " + ", ".join(f"`{k}`" for k in glossary.keys())
                )
        else:
            # Show all terms in compact format
            message = "📚 *Glossary*\n\n"
            message += "Tap a button below for detailed explanation, or use `/glossary <term>`.\n\n"
            message += "*Quick Reference:*\n"
            message += f"• *Scans* – Strategy loop iterations\n"
            message += f"• *Signals* – Detected trading opportunities\n"
            message += f"• *Pressure* – Order flow imbalance\n"
            message += f"• *MTF* – Multi-timeframe trend alignment\n"
            message += f"• *Gates* – Market hours & session windows\n"
            message += f"• *{LABEL_ACTIVE_TRADES}* – Open positions\n"
            message += f"• *Buffer* – Rolling price data\n"
        
        # Build drill-down buttons
        keyboard = [
            [
                InlineKeyboardButton("🔄 Scans", callback_data="glossary_scans"),
                InlineKeyboardButton("🔔 Signals", callback_data="glossary_signals"),
            ],
            [
                InlineKeyboardButton("📊 Pressure", callback_data="glossary_pressure"),
                InlineKeyboardButton("📈 MTF", callback_data="glossary_mtf"),
            ],
            [
                InlineKeyboardButton("🚦 Gates", callback_data="glossary_gates"),
                InlineKeyboardButton("🎯 Trades", callback_data="glossary_active_trades"),
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /chart command - generate and send on-demand dashboard chart.
        
        Usage: /chart [hours]
        - hours: lookback window (default: 6, max: 24)
        """
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
        
        try:
            if not self.chart_generator:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Chart generator not available.\n\n"
                    "💡 Ensure matplotlib and mplfinance are installed.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Parse optional hours argument
            args = context.args if context.args else []
            lookback_hours = 12.0  # default (matches dashboard chart default)
            if args:
                try:
                    lookback_hours = float(args[0])
                    lookback_hours = max(1.0, min(24.0, lookback_hours))  # clamp 1-24h
                except ValueError:
                    pass
            
            # Get data provider
            data_provider = self._get_data_provider()
            if data_provider is None:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Data provider not available.\n\n"
                    "💡 Check Gateway status and try again.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Fetch historical data
            import asyncio
            from datetime import datetime, timezone
            import pandas as pd
            
            symbol = "MNQ"
            timeframe = "5m"
            end_time = datetime.now(timezone.utc)
            
            loop = asyncio.get_running_loop()
            bars = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    data_provider.get_historical_bars,
                    symbol,
                    timeframe,
                    lookback_hours,
                ),
                timeout=30.0,
            )
            
            if bars is None or (isinstance(bars, pd.DataFrame) and bars.empty) or (isinstance(bars, list) and len(bars) == 0):
                await self._send_message_or_edit(
                    update, context,
                    "❌ No data available for chart.\n\n"
                    "💡 Check Gateway connection or try again later.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Convert to DataFrame if needed
            if isinstance(bars, list):
                df = pd.DataFrame(bars)
            else:
                df = bars
            
            if df.empty:
                await self._send_message_or_edit(
                    update, context,
                    "❌ Insufficient data for chart.",
                    reply_markup=self._get_back_to_menu_button()
                )
                return
            
            # Generate chart
            chart_path = self.chart_generator.generate_dashboard_chart(
                df,
                symbol=symbol,
                timeframe=timeframe,
                lookback_hours=lookback_hours,
                show_pressure=True,
            )
            
            if chart_path and chart_path.exists():
                from pathlib import Path
                caption = f"📊 *{symbol}* {timeframe} Chart ({lookback_hours:.0f}h)\n"
                caption += f"🕐 Generated: {end_time.strftime('%H:%M UTC')}"
                
                # Build toggle buttons with active indicator
                def btn_label(hours: int) -> str:
                    if abs(lookback_hours - hours) < 1:
                        return f"✓ {hours}h"
                    return f"{hours}h"
                
                keyboard = [
                    [
                        InlineKeyboardButton(btn_label(12), callback_data="chart_12h"),
                        InlineKeyboardButton(btn_label(16), callback_data="chart_16h"),
                        InlineKeyboardButton(btn_label(24), callback_data="chart_24h"),
                    ],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=open(chart_path, "rb"),
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=reply_markup,
                )
                
                # Clean up temp file
                try:
                    chart_path.unlink()
                except Exception:
                    pass
            else:
                await self._send_message_or_edit(
                    update, context,
                    "📊 *Chart Unavailable*\n\n"
                    "Chart generation did not produce an image.\n\n"
                    "*What to try:*\n"
                    "• Wait a few minutes for data to accumulate\n"
                    "• Check /data_quality for data issues\n"
                    "• Try a shorter timeframe (12h)",
                    reply_markup=self._get_back_to_menu_button()
                )
                
        except asyncio.TimeoutError:
            await self._send_message_or_edit(
                update, context,
                "⏱️ *Chart Timed Out*\n\n"
                "Chart generation took too long.\n\n"
                "*What to try:*\n"
                "• Try again in a moment\n"
                "• Check /data_quality for connection issues\n"
                "• Use a shorter timeframe",
                reply_markup=self._get_back_to_menu_button()
            )
        except Exception as e:
            logger.error(f"Error handling chart command: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                "📊 *Chart Unavailable*\n\n"
                "Something went wrong generating the chart.\n\n"
                "*What to try:*\n"
                "• Try again in a moment\n"
                "• Check /data_quality for data issues\n"
                "• If problem persists, check logs",
                reply_markup=self._get_back_to_menu_button()
            )
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - unified Home Card view."""
        logger.info(f"Received /status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # Send typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            # Get gateway status first (needed for both message and buttons)
            gateway_status = self.service_controller.get_gateway_status()
            gateway_running = gateway_status.get("process_running", False)
            gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
            
            # Load state
            state_file = get_state_file(self.state_dir)
            if not state_file.exists():
                # No state file - show minimal Home Card with start prompt
                process_running = self._is_agent_process_running()
                message = format_home_card(
                    symbol="MNQ",
                    time_str=self._get_current_time_str(),
                    agent_running=process_running,
                    gateway_running=gateway_running,
                    futures_market_open=None,
                    strategy_session_open=None,
                )
                message += "\n\n⚠️ *No state file found*\n"
                message += "Agent may not have run yet. Start agent to begin."
                
                reply_markup = self._get_main_menu_buttons(
                    agent_running=process_running,
                    gateway_running=gateway_running,
                    gateway_api_ready=gateway_api_ready,
                )
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Determine if the actual service process is running
            process_running = self._is_agent_process_running()
            
            # Build status from state
            state_running = state.get("running", False)
            running = process_running and state_running
            paused = state.get("paused", False)
            pause_reason = state.get("pause_reason") or None
            
            # Extract metrics from state
            cycles_total = int(state.get("cycle_count", 0) or 0)
            cycles_session = state.get("cycle_count_session")
            try:
                cycles_session = int(cycles_session) if cycles_session is not None else None
            except Exception:
                cycles_session = None
            
            signals_generated = int(state.get("signal_count", 0) or 0)
            try:
                signals_sent = int(state.get("signals_sent", 0) or 0)
            except Exception:
                signals_sent = 0
            
            errors = int(state.get("error_count", 0) or 0)
            buffer_size = int(state.get("buffer_size", 0) or 0)
            buffer_target = state.get("buffer_size_target")
            try:
                buffer_target = int(buffer_target) if buffer_target is not None else None
            except Exception:
                buffer_target = None
            
            # Signal send failures (for error cue in Home Card)
            signal_send_failures = 0
            try:
                signal_send_failures = int(state.get("signals_send_failures", 0) or 0)
            except Exception:
                signal_send_failures = 0
            
            # Compute state file freshness (for liveness cue)
            state_age_seconds = None
            try:
                mtime = state_file.stat().st_mtime
                state_age_seconds = (datetime.now(timezone.utc).timestamp() - mtime)
            except Exception:
                state_age_seconds = None
            
            # Compute activity pulse from last_successful_cycle (more accurate than state file mtime)
            last_cycle_seconds = None
            try:
                last_cycle_ts = state.get("last_successful_cycle")
                if last_cycle_ts:
                    from pearlalgo.utils.paths import parse_utc_timestamp
                    last_cycle_dt = parse_utc_timestamp(str(last_cycle_ts))
                    if last_cycle_dt:
                        if last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
            except Exception:
                last_cycle_seconds = None
            
            # Count active trades (signals with status="entered")
            active_trades_count = 0
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    with open(signals_file) as f:
                        for line in f:
                            try:
                                sig = json.loads(line.strip())
                                if sig.get("status") == "entered":
                                    active_trades_count += 1
                            except Exception:
                                continue
            except Exception:
                active_trades_count = 0
            
            # Gate status
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")
            
            # Get latest price and data age using robust fallback helpers
            latest_price = self._extract_latest_price(state)
            data_age_minutes = self._extract_data_age_minutes(state)
            
            # Get stale threshold from state or use default
            data_stale_threshold_minutes = float(state.get("data_stale_threshold_minutes", 10.0))
            
            # Compute adaptive state staleness threshold based on configured save cadence
            state_stale_threshold = self._compute_state_stale_threshold(state)
            
            # Get 7-day performance
            perf = None
            try:
                perf = self.performance_tracker.get_performance_metrics(days=7)
            except Exception as e:
                logger.debug(f"Could not get performance for /status: {e}")
            
            # Get last signal age
            last_signal_age = None
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    # Read last line efficiently
                    with open(signals_file, 'rb') as f:
                        f.seek(0, 2)  # End of file
                        size = f.tell()
                        if size > 0:
                            # Read last 2KB
                            f.seek(max(0, size - 2048))
                            lines = f.read().decode('utf-8', errors='ignore').strip().split('\n')
                            if lines:
                                last_line = lines[-1]
                                try:
                                    last_sig = json.loads(last_line)
                                    sig_ts = last_sig.get("timestamp") or last_sig.get("signal", {}).get("timestamp")
                                    if sig_ts:
                                        last_signal_age = format_time_ago(str(sig_ts))
                                except Exception:
                                    pass
            except Exception as e:
                logger.debug(f"Could not get last signal age: {e}")
            
            # Build Home Card message with enhanced confidence/clarity cues (calm-minimal)
            message = format_home_card(
                symbol=state.get("symbol", "MNQ"),
                time_str=self._get_current_time_str(),
                agent_running=running,
                gateway_running=gateway_running,
                futures_market_open=futures_market_open,
                strategy_session_open=strategy_session_open,
                paused=paused,
                pause_reason=pause_reason,
                cycles_session=cycles_session,
                cycles_total=cycles_total,
                signals_generated=signals_generated,
                signals_sent=signals_sent,
                errors=errors,
                buffer_size=buffer_size,
                buffer_target=buffer_target,
                latest_price=latest_price,
                performance=perf,
                last_signal_age=last_signal_age,
                # Confidence/clarity cues (adaptive threshold based on save cadence)
                state_age_seconds=state_age_seconds,
                state_stale_threshold=state_stale_threshold,
                signal_send_failures=signal_send_failures,
                buy_sell_pressure=state.get("buy_sell_pressure"),
                # Calm-minimal: activity pulse + active trades
                last_cycle_seconds=last_cycle_seconds,
                active_trades_count=active_trades_count,
                # v6 fields for data staleness
                data_age_minutes=data_age_minutes,
                data_stale_threshold_minutes=data_stale_threshold_minutes,
            )
            
            # Use consistent main menu buttons
            reply_markup = self._get_main_menu_buttons(
                agent_running=running,
                gateway_running=gateway_running,
                gateway_api_ready=gateway_api_ready,
            )
            
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
            gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
            reply_markup = self._get_main_menu_buttons(
                agent_running=self._is_agent_process_running(),
                gateway_running=gateway_running,
                gateway_api_ready=gateway_api_ready,
            )
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)
    
    def _get_current_time_str(self) -> str:
        """Get current time formatted for display (ET timezone)."""
        try:
            import pytz
            now = datetime.now(timezone.utc)
            et_tz = pytz.timezone('US/Eastern')
            et_time = now.astimezone(et_tz)
            return et_time.strftime("%I:%M %p ET")
        except Exception:
            return datetime.now(timezone.utc).strftime("%H:%M UTC")
    
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
                    f"🔴 *{LABEL_AGENT}:* {STATE_STOPPED}\n\n"
                    f"💡 Tap 'Start {LABEL_AGENT}' below to begin",
                    reply_markup=reply_markup
                )
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            process_running = self._is_agent_process_running()
            running = process_running and state.get("running", False)
            status_emoji = "🟢" if running else "🔴"
            
            scans = state.get('cycle_count', 0)
            signals = state.get('signal_count', 0)
            buffer = state.get('buffer_size', 0)
            
            message = f"{status_emoji} *Quick Status*\n\n"
            message += f"🔄 {scans:,} scans\n"
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
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
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
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
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

        # For explicit /signals commands (not button callbacks), default to newest page.
        if not update.callback_query and hasattr(context, "user_data"):
            context.user_data["signals_page"] = 0
        
        try:
            signals_file = get_signals_file(self.state_dir)
            # Pull state signal_count for mismatch diagnostics (state can show signals even if file is empty)
            state_signal_count = 0
            try:
                state_file = get_state_file(self.state_dir)
                if state_file.exists():
                    with open(state_file, "r") as sf:
                        st = json.load(sf)
                    state_signal_count = int(st.get("signal_count", 0) or 0)
            except Exception:
                state_signal_count = 0

            if not signals_file.exists():
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📭 *No signals found*\n\n"
                    "The signals file doesn't exist yet.\n"
                    f"*State reports:* {state_signal_count} signal(s)\n\n"
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
                    f"*State reports:* {state_signal_count} signal(s)\n\n"
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
                sig_stats = self._get_signals_file_stats(signals_file)
                lines = int(sig_stats.get("lines", 0) or 0)
                invalid = int(sig_stats.get("invalid", 0) or 0)
                await self._send_message_or_edit(
                    update, context,
                    f"📭 *No valid signals found*\n\n"
                    f"File exists ({file_size} bytes) but has 0 valid signal records.\n"
                    f"*State reports:* {state_signal_count} signal(s)\n"
                    f"*Lines parsed:* {lines} • *Invalid JSON lines:* {invalid}\n\n"
                    f"💡 Try: `python3 scripts/testing/check_signals.py`",
                    reply_markup=reply_markup
                )
                return
            
            # Filters (persist per-chat; single-admin setup makes this straightforward)
            user_data = context.user_data if hasattr(context, "user_data") else {}
            dir_filter = (user_data.get("signals_dir") or "all").lower()
            type_filter = (user_data.get("signals_type") or "all").lower()
            try:
                min_conf = float(user_data.get("signals_min_conf", 0.0) or 0.0)
            except Exception:
                min_conf = 0.0

            if dir_filter not in ("all", "long", "short"):
                dir_filter = "all"
            if type_filter not in ("all", "momentum", "mean_reversion", "breakout", "other"):
                type_filter = "all"
            if min_conf not in (0.0, 0.5, 0.6, 0.7):
                # Keep it predictable (button presets)
                min_conf = 0.0

            def _bucket_type(t: str) -> str:
                t = (t or "").lower()
                if "momentum" in t:
                    return "momentum"
                if "breakout" in t:
                    return "breakout"
                if "mean_reversion" in t or "vwap_reversion" in t or "sr_bounce" in t or "engulfing" in t:
                    return "mean_reversion"
                return "other"

            filtered: List[Dict] = []
            for sig_data in signals:
                signal = sig_data.get("signal", {}) or {}
                sig_dir = (signal.get("direction", "long") or "long").lower()
                sig_type = signal.get("type", "unknown")
                try:
                    conf_val = float(signal.get("confidence", 0.0) or 0.0)
                except Exception:
                    conf_val = 0.0

                if dir_filter != "all" and sig_dir != dir_filter:
                    continue
                if conf_val < min_conf:
                    continue
                if type_filter != "all" and _bucket_type(sig_type) != type_filter:
                    continue
                filtered.append(sig_data)

            total_count = len(signals)
            filtered_count = len(filtered)

            # Paging (newest-first)
            page_size = 10
            try:
                page = int(user_data.get("signals_page", 0) or 0)
            except Exception:
                page = 0
            if page < 0:
                page = 0

            total_pages = max(1, (filtered_count + page_size - 1) // page_size) if filtered_count > 0 else 1
            if page > total_pages - 1:
                page = total_pages - 1

            # Persist clamped page
            if hasattr(context, "user_data"):
                context.user_data["signals_page"] = page

            end = filtered_count - (page * page_size)
            start = max(0, end - page_size)
            page_signals = filtered[start:end]
            page_signals.reverse()

            message = "🔔 *Signals*\n\n"
            message += f"*Stored:* {total_count}  |  *Matching filters:* {filtered_count}\n"
            message += f"*Page:* {page + 1}/{total_pages}  |  *Showing:* {len(page_signals)}\n\n"
            message += f"*Filters:* dir={dir_filter}, type={type_filter}, conf≥{int(min_conf*100)}%\n\n"

            keyboard: List[List[InlineKeyboardButton]] = []

            # Compact filter controls (reduced from 4 rows to 2)
            # Row 1: Direction + Confidence
            keyboard.append([
                InlineKeyboardButton("✓All" if dir_filter == "all" else "All", callback_data="signals:setdir:all"),
                InlineKeyboardButton("✓L" if dir_filter == "long" else "L", callback_data="signals:setdir:long"),
                InlineKeyboardButton("✓S" if dir_filter == "short" else "S", callback_data="signals:setdir:short"),
                InlineKeyboardButton("│", callback_data="signals:noop"),
                InlineKeyboardButton("✓0%" if min_conf == 0.0 else "0%", callback_data="signals:setconf:0.0"),
                InlineKeyboardButton("✓50" if min_conf == 0.5 else "50", callback_data="signals:setconf:0.5"),
                InlineKeyboardButton("✓70" if min_conf == 0.7 else "70", callback_data="signals:setconf:0.7"),
            ])
            # Row 2: Signal type filters
            keyboard.append([
                InlineKeyboardButton("✓All" if type_filter == "all" else "All", callback_data="signals:settype:all"),
                InlineKeyboardButton("✓Mom" if type_filter == "momentum" else "Mom", callback_data="signals:settype:momentum"),
                InlineKeyboardButton("✓MR" if type_filter == "mean_reversion" else "MR", callback_data="signals:settype:mean_reversion"),
                InlineKeyboardButton("✓BO" if type_filter == "breakout" else "BO", callback_data="signals:settype:breakout"),
                InlineKeyboardButton("✓Oth" if type_filter == "other" else "Oth", callback_data="signals:settype:other"),
            ])

            # Paging row (compact)
            if filtered_count > 0 and total_pages > 1:
                pager_row: List[InlineKeyboardButton] = []
                if page < total_pages - 1:
                    pager_row.append(InlineKeyboardButton("◀ Older", callback_data="signals:page:older"))
                if page > 0:
                    pager_row.append(InlineKeyboardButton("Newer ▶", callback_data="signals:page:newer"))
                pager_row.append(InlineKeyboardButton("🔝", callback_data="signals:page:newest"))
                keyboard.append(pager_row)

            # Quick actions
            keyboard.append([
                InlineKeyboardButton("🆕 Last", callback_data="last_signal"),
                InlineKeyboardButton("📊 Active", callback_data="active_trades"),
                InlineKeyboardButton("🔄", callback_data="signals"),
            ])

            if not page_signals:
                message += "📭 No signals match these filters.\n"
            else:
                # Build compact signal list with freshness indicators
                for i, sig_data in enumerate(page_signals, 1):
                    signal = sig_data.get("signal", {}) or {}
                    signal_type = signal.get("type", "unknown")
                    status = sig_data.get("status", "unknown")
                    signal_id = sig_data.get("signal_id", "")
                    entry_price = float(signal.get("entry_price", 0.0) or 0.0)
                    try:
                        conf_val = float(signal.get("confidence", 0.0) or 0.0)
                    except Exception:
                        conf_val = 0.0

                    # Use shared helpers for consistent formatting
                    is_win = sig_data.get("is_win") if status == "exited" else None
                    status_emoji, _ = format_signal_status(status, is_win)
                    _, dir_label = format_signal_direction(signal.get("direction", "long"))
                    
                    # Freshness: time since signal was generated
                    sig_ts = sig_data.get("timestamp") or signal.get("timestamp")
                    age_str = format_time_ago(sig_ts)
                    age_part = f" • {age_str}" if age_str else ""

                    # Compact one-liner: status, type, direction, confidence, age
                    message += f"{i}. {status_emoji} {signal_type} {dir_label} • {conf_val:.0%}{age_part}\n"
                    
                    # Second line: entry price + PnL for exited, or short status for others
                    if status == "exited":
                        pnl = float(sig_data.get("pnl", 0.0) or 0.0)
                        pnl_emoji, pnl_str = format_pnl(pnl)
                        exit_reason = str(sig_data.get("exit_reason", "") or "")[:8]
                        message += f"   {pnl_emoji} {pnl_str} ({exit_reason}) @ ${entry_price:.2f}\n\n"
                    else:
                        message += f"   Entry: ${entry_price:.2f} | `{signal_id[:8]}…`\n\n"

                # Compact numeric grid for actions (batch multiple signals per row)
                action_buttons: List[InlineKeyboardButton] = []
                for i, sig_data in enumerate(page_signals, 1):
                    signal_id = sig_data.get("signal_id", "")
                    if signal_id:
                        action_buttons.append(
                            InlineKeyboardButton(f"ℹ️{i}", callback_data=f"signal_detail_{signal_id[:16]}")
                        )
                # Group action buttons in rows of 5
                for j in range(0, len(action_buttons), 5):
                    keyboard.append(action_buttons[j : j + 5])

            # Navigation
            keyboard.append([
                InlineKeyboardButton("🛡 Data Quality", callback_data="data_quality"),
                InlineKeyboardButton("📈 Performance", callback_data="performance"),
            ])
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])

            reply_markup = InlineKeyboardMarkup(keyboard)
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
            entry_price = float(signal.get("entry_price", 0) or 0)
            stop_loss = float(signal.get("stop_loss", 0) or 0)
            take_profit = float(signal.get("take_profit", 0) or 0)
            try:
                conf_val = float(signal.get("confidence", 0.0) or 0.0)
            except Exception:
                conf_val = 0.0
            
            # Use shared helpers for consistent formatting
            is_win = last_signal_data.get("is_win") if status == "exited" else None
            status_emoji, status_label = format_signal_status(status, is_win)
            dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
            conf_emoji, conf_tier = format_signal_confidence_tier(conf_val)
            
            # Freshness indicator
            sig_ts = last_signal_data.get("timestamp") or signal.get("timestamp")
            age_str = format_time_ago(sig_ts)
            
            message = f"{status_emoji} *Last Signal*\n\n"
            message += f"*Type:* {signal_type} {dir_emoji} {dir_label}\n"
            message += f"*Entry:* ${entry_price:.2f}\n"
            if stop_loss:
                message += f"*Stop:* ${stop_loss:.2f}\n"
            if take_profit:
                message += f"*TP:* ${take_profit:.2f}\n"
            message += f"*Confidence:* {conf_emoji} {conf_val:.0%} ({conf_tier})\n"
            message += f"*Status:* {status_label}\n"
            if age_str:
                message += f"*Age:* {age_str}\n"
            message += f"*ID:* `{signal_id[:16]}…`\n"
            
            # Show PnL for exited signals
            if status == "exited":
                pnl = float(last_signal_data.get("pnl", 0.0) or 0.0)
                pnl_emoji, pnl_str = format_pnl(pnl)
                exit_reason = str(last_signal_data.get("exit_reason", "") or "")
                message += f"\n{pnl_emoji} *P&L:* {pnl_str}"
                if exit_reason:
                    message += f" ({exit_reason})"
                message += "\n"
            
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
            
            # Try to get current price for unrealized PnL
            current_price = None
            try:
                data_provider = self._get_data_provider()
                if data_provider is not None:
                    loop = asyncio.get_running_loop()
                    latest = await asyncio.wait_for(
                        loop.run_in_executor(None, data_provider.get_latest_bar, "MNQ"),
                        timeout=5.0,
                    )
                    if isinstance(latest, dict) and "close" in latest:
                        current_price = float(latest["close"])
                        message += f"*Current Price:* ${current_price:.2f}\n\n"
            except Exception as e:
                logger.debug(f"Could not fetch current price for active trades: {e}")
            
            for i, trade_data in enumerate(active_trades, 1):
                signal = trade_data.get("signal", {})
                signal_type = signal.get("type", "unknown")
                direction = (signal.get("direction", "long") or "long").upper()
                entry_price = float(signal.get("entry_price", 0) or 0)
                stop_loss = float(signal.get("stop_loss", 0) or 0)
                take_profit = float(signal.get("take_profit", 0) or 0)
                signal_id = trade_data.get("signal_id", "")
                tick_value = float(signal.get("tick_value", 2.0) or 2.0)
                position_size = float(signal.get("position_size", 1.0) or 1.0)
                
                message += f"{i}. 🎯 {signal_type} {direction}\n"
                message += f"   Entry: ${entry_price:.2f}"
                
                # Show unrealized PnL if we have current price
                if current_price is not None and entry_price > 0:
                    if direction == "LONG":
                        pnl_pts = current_price - entry_price
                    else:
                        pnl_pts = entry_price - current_price
                    unrealized_pnl = pnl_pts * tick_value * position_size
                    pnl_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                    pnl_str = f"+${unrealized_pnl:.2f}" if unrealized_pnl >= 0 else f"-${abs(unrealized_pnl):.2f}"
                    message += f" | {pnl_emoji} {pnl_str}"
                message += "\n"
                
                if stop_loss:
                    message += f"   Stop: ${stop_loss:.2f}"
                    if current_price is not None:
                        dist_to_stop = abs(current_price - stop_loss)
                        message += f" ({dist_to_stop:.2f} pts away)"
                    message += "\n"
                if take_profit:
                    message += f"   TP: ${take_profit:.2f}"
                    if current_price is not None:
                        dist_to_tp = abs(take_profit - current_price)
                        message += f" ({dist_to_tp:.2f} pts away)"
                    message += "\n"
                message += f"   ID: {signal_id[:16]}...\n\n"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="active_trades")],
                [InlineKeyboardButton("🔔 All Signals", callback_data="signals")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
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
                # Use a dedicated client_id for the command handler to avoid colliding with the main service.
                # Prefer IBKR_DATA_CLIENT_ID if set; otherwise offset the default client id by +1.
                client_id = None
                try:
                    base = getattr(settings, "ib_client_id", 1)
                    data_cid = getattr(settings, "ib_data_client_id", None)
                    if data_cid is not None:
                        client_id = int(data_cid)
                    else:
                        client_id = min(100, max(0, int(base) + 1))
                except Exception:
                    client_id = None

                self._data_provider = create_data_provider(provider_name, settings=settings, client_id=client_id)
                logger.info(f"Initialized data provider: {provider_name} (client_id={client_id})")
            except Exception as e:
                logger.warning(f"Could not initialize data provider: {e}")
                return None
        return self._data_provider
    
    async def _fetch_historical_data_for_backtest(
        self, 
        symbol: str = "MNQ", 
        weeks: int = 2,
        timeframe: str = "1m",
    ) -> Optional[pd.DataFrame]:
        """
        Fetch and cache historical data for backtesting.
        
        Args:
            symbol: Symbol to fetch (default: MNQ)
            weeks: Number of weeks to fetch (default: 2)
            timeframe: Data timeframe (default: 1m)
            
        Returns:
            DataFrame with historical OHLCV data, or None if fetch failed
        """
        cache_file = self._historical_cache_dir / f"{symbol}_{timeframe}_{weeks}w.parquet"
        # Backtests should use *completed* historical data only.
        # If today is Monday, "yesterday" is Sunday (no session) which can cause HMDS weirdness/timeouts.
        # Clamp to the most recent weekday (Mon-Fri) at 23:59 UTC.
        end = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
            hour=23, minute=59, second=0, microsecond=0
        )
        while end.weekday() >= 5:  # Sat/Sun
            end = end - timedelta(days=1)
        start = end - timedelta(days=weeks * 7)
        
        logger.info(f"Fetching {weeks} weeks of historical data for {symbol}...")
        
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
        # This supports both new week caches (e.g. *_6w.parquet) and legacy month caches (e.g. *_2m.parquet).
        try:
            superset_files: List[Path] = []
            superset_files.extend(self._historical_cache_dir.glob(f"{symbol}_{timeframe}_*w.parquet"))
            superset_files.extend(self._historical_cache_dir.glob(f"{symbol}_{timeframe}_*m.parquet"))

            candidates: List[tuple[float, Path]] = []
            for f in superset_files:
                if f == cache_file:
                    continue
                tail = f.name.split("_")[-1]  # e.g. "6w.parquet" or "2m.parquet"
                dur_weeks = None
                if tail.endswith("w.parquet"):
                    try:
                        dur_weeks = float(int(tail[:-9]))
                    except Exception:
                        dur_weeks = None
                elif tail.endswith("m.parquet"):
                    try:
                        m = int(tail[:-9])
                        dur_weeks = float(m * 30) / 7.0
                    except Exception:
                        dur_weeks = None
                if dur_weeks is None:
                    dur_weeks = 1e9
                if dur_weeks >= float(weeks):
                    candidates.append((dur_weeks, f))

            if not candidates:
                # If we can't parse durations, try any existing cache file as a last resort.
                candidates = [(1e9, f) for f in superset_files if f != cache_file]

            if candidates:
                # Prefer the smallest superset (closest to requested duration)
                candidates.sort(key=lambda x: x[0])
                for _, superset_file in candidates:
                    superset_df = pd.read_parquet(superset_file)
                    if superset_df is None or superset_df.empty:
                        continue

                    if "timestamp" not in superset_df.columns and isinstance(superset_df.index, pd.DatetimeIndex):
                        superset_df = superset_df.reset_index()
                        if "timestamp" not in superset_df.columns and len(superset_df.columns) > 0:
                            first_col = superset_df.columns[0]
                            superset_df = superset_df.rename(columns={first_col: "timestamp"})

                    if "timestamp" not in superset_df.columns:
                        continue

                    superset_df["timestamp"] = pd.to_datetime(superset_df["timestamp"], errors="coerce", utc=True)
                    superset_df = superset_df.dropna(subset=["timestamp"])

                    derived = superset_df[
                        (superset_df["timestamp"] >= start) & (superset_df["timestamp"] <= end)
                    ].copy()
                    if derived.empty:
                        continue

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
            # This matches your request: "pick past weeks if that's the only thing that works".
            max_window_shifts = 3
            all_chunks = []
            window_end = end
            window_start = start

            # Smaller chunks are far more reliable with IBKR HMDS for 1m bars.
            # We'll use weekly chunks and, if needed, fall back to daily chunks.
            base_chunk_days = 7

            for shift_idx in range(max_window_shifts + 1):
                if shift_idx > 0:
                    window_end = end - timedelta(days=shift_idx * 7)
                    window_end = window_end.replace(hour=23, minute=59, second=0, microsecond=0)
                    while window_end.weekday() >= 5:  # Sat/Sun
                        window_end = window_end - timedelta(days=1)
                    window_start = window_end - timedelta(days=weeks * 7)
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
                            f"trying earlier weeks..."
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
    
    async def _handle_backtest(self, update: Update, context: ContextTypes.DEFAULT_TYPE, weeks: Optional[int] = None):
        """Handle /backtest command - run backtest and show results with chart."""
        logger.info(f"Received /backtest command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return
        
        # If no weeks specified, show duration selection menu
        if weeks is None:
            mode = (context.user_data.get("backtest_mode") or "5m") if hasattr(context, "user_data") else "5m"
            if mode not in ("5m", "1m"):
                mode = "5m"
            mode_label = "5m decision (recommended)" if mode == "5m" else "1m (legacy)"

            # Preset parameters (persist per-chat)
            user_data = context.user_data if hasattr(context, "user_data") else {}
            try:
                pos_size = int(user_data.get("backtest_contracts", 5) or 5)
            except Exception:
                pos_size = 5
            try:
                slippage_ticks = float(user_data.get("backtest_slippage_ticks", 0.5) or 0.5)
            except Exception:
                slippage_ticks = 0.5

            message = (
                "📊 *Backtest Strategy*\n\n"
                f"*Mode:* {mode_label}\n\n"
                f"*Contracts:* {pos_size} MNQ  |  *Slippage:* {slippage_ticks} ticks\n\n"
                "Select backtest duration:\n\n"
                "Tip: 2 weeks is a good starting point. 4-6 weeks for deeper validation."
            )
            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("1 Week", callback_data='backtest_1w'),
                    InlineKeyboardButton("2 Weeks", callback_data='backtest_2w'),
                ],
                [
                    InlineKeyboardButton("3 Weeks", callback_data='backtest_3w'),
                    InlineKeyboardButton("4 Weeks", callback_data='backtest_4w'),
                ],
                [
                    InlineKeyboardButton("5 Weeks", callback_data='backtest_5w'),
                    InlineKeyboardButton("6 Weeks", callback_data='backtest_6w'),
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
                [
                    InlineKeyboardButton(
                        "✅ 1x" if pos_size == 1 else "1x",
                        callback_data="backtest_setpos_1",
                    ),
                    InlineKeyboardButton(
                        "✅ 5x" if pos_size == 5 else "5x",
                        callback_data="backtest_setpos_5",
                    ),
                    InlineKeyboardButton(
                        "✅ 10x" if pos_size == 10 else "10x",
                        callback_data="backtest_setpos_10",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "✅ slip 0.5" if slippage_ticks == 0.5 else "slip 0.5",
                        callback_data="backtest_setslip_0.5",
                    ),
                    InlineKeyboardButton(
                        "✅ slip 1.0" if slippage_ticks == 1.0 else "slip 1.0",
                        callback_data="backtest_setslip_1.0",
                    ),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data='start')],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return
        
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        try:
            from pearlalgo.strategies.nq_intraday.backtest_adapter import (
                export_trade_journal,
                run_full_backtest,
                run_full_backtest_5m_decision,
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
                f"Fetching {weeks} week{'s' if weeks > 1 else ''} of historical data for backtest...\n"
                f"This may take a moment...",
                reply_markup=None
            )
            
            # Fetch data (no progress callbacks - they interfere)
            historical_data = await self._fetch_historical_data_for_backtest(
                symbol="MNQ",
                weeks=weeks,
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
                
                # Ensure required OHLCV columns exist (prefer lowercase for strategy/backtest stack)
                column_mapping = {
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                }
                for lower, upper in column_mapping.items():
                    # If provider returned uppercase, mirror to lowercase
                    if upper in backtest_data.columns and lower not in backtest_data.columns:
                        backtest_data[lower] = backtest_data[upper]
                    # If lowercase exists, optionally mirror to uppercase for any charting helpers
                    if lower in backtest_data.columns and upper not in backtest_data.columns:
                        backtest_data[upper] = backtest_data[lower]
                
                # Run backtest (default: full trade simulation)
                user_data = context.user_data if hasattr(context, "user_data") else {}
                try:
                    pos_size = int(user_data.get("backtest_contracts", 5) or 5)
                except Exception:
                    pos_size = 5
                if pos_size not in (1, 5, 10):
                    pos_size = 5
                try:
                    slippage_ticks = float(user_data.get("backtest_slippage_ticks", 0.5) or 0.5)
                except Exception:
                    slippage_ticks = 0.5
                if slippage_ticks not in (0.5, 1.0):
                    slippage_ticks = 0.5

                config = NQIntradayConfig()
                tick_value = float(getattr(config, "tick_value", 2.0) or 2.0)

                if mode == "5m":
                    result = run_full_backtest_5m_decision(
                        backtest_data,
                        config=config,
                        position_size=pos_size,
                        tick_value=tick_value,
                        slippage_ticks=slippage_ticks,
                        return_trades=True,
                        decision_rule="5min",
                        context_rule_1="1h",
                        context_rule_2="4h",
                    )
                else:
                    result = run_full_backtest(
                        backtest_data,
                        config=config,
                        position_size=pos_size,
                        tick_value=tick_value,
                        slippage_ticks=slippage_ticks,
                        return_trades=True,
                    )
                        
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
                        "total_trades": result.total_trades if result.total_trades is not None else 0,
                        "profit_factor": result.profit_factor if result.profit_factor is not None else 0.0,
                        "max_drawdown": result.max_drawdown if result.max_drawdown is not None else 0.0,
                        "sharpe_ratio": result.sharpe_ratio if result.sharpe_ratio is not None else 0.0,
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
                    profit_factor_display = f"{result.profit_factor:.2f}" if result.profit_factor is not None else "N/A"
                    max_dd_display = f"${result.max_drawdown:.2f}" if result.max_drawdown is not None else "N/A"
                    sharpe_display = f"{result.sharpe_ratio:.2f}" if result.sharpe_ratio is not None else "N/A"
                    trades_display = f"{result.total_trades}" if result.total_trades is not None else "0"

                    message = (
                        f"📊 *Backtest Results ({weeks} Week{'s' if weeks > 1 else ''})*\n\n"
                        f"*Period:* {data_start} to {data_end}\n"
                        f"*Bars Analyzed:* {result.total_bars:,}\n"
                        f"*Signals Generated:* {result.total_signals}\n"
                        f"*Signals on Chart:* {signals_shown}\n\n"
                        f"*Contracts:* {pos_size} MNQ  |  *Slippage:* {slippage_ticks} ticks\n"
                        f"*Trades:* {trades_display}  |  *Win Rate:* {win_rate_display}  |  *PF:* {profit_factor_display}\n"
                        f"*Avg Confidence:* {result.avg_confidence:.2f}\n"
                        f"*Avg R:R:* {result.avg_risk_reward:.2f}:1\n"
                        f"*Total P&L:* {total_pnl_display}  |  *Max DD:* {max_dd_display}  |  *Sharpe:* {sharpe_display}\n\n"
                        "📈 *Chart Components:*\n"
                        "• Green/Red candlesticks = Price action\n"
                        "• 🔼 Green triangles = Long entry signals\n"
                        "• 🔽 Orange triangles = Short entry signals\n"
                        "• Volume bars (bottom panel)\n"
                        "• VWAP line (orange)\n"
                        "• Moving averages (blue/purple)"
                    )
                            
                    # Export artifacts (trade journal + metrics)
                    export_paths: Dict[str, str] = {}
                    try:
                        exports_dir = self.state_dir / "exports"
                        exports_dir.mkdir(parents=True, exist_ok=True)
                        ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                        base_name = f"backtest_{mode}_{weeks}w_{ts_tag}"

                        # Metrics JSON (always)
                        metrics_path = exports_dir / f"{base_name}_metrics.json"
                        metrics_obj = {
                            "mode": mode,
                            "weeks": weeks,
                            "contracts": pos_size,
                            "slippage_ticks": slippage_ticks,
                            "total_bars": result.total_bars,
                            "total_signals": result.total_signals,
                            "avg_confidence": result.avg_confidence,
                            "avg_risk_reward": result.avg_risk_reward,
                            "total_trades": result.total_trades,
                            "win_rate": result.win_rate,
                            "total_pnl": result.total_pnl,
                            "profit_factor": result.profit_factor,
                            "max_drawdown": result.max_drawdown,
                            "max_drawdown_pct": result.max_drawdown_pct,
                            "sharpe_ratio": result.sharpe_ratio,
                            "avg_win": result.avg_win,
                            "avg_loss": result.avg_loss,
                            "avg_hold_time_minutes": result.avg_hold_time_minutes,
                        }
                        with open(metrics_path, "w") as f:
                            json.dump(metrics_obj, f, indent=2)
                        export_paths["metrics"] = str(metrics_path)

                        # Trades (if available)
                        if getattr(result, "trades", None):
                            trades_csv = exports_dir / f"{base_name}_trades.csv"
                            trades_json = exports_dir / f"{base_name}_trades.json"
                            export_trade_journal(result.trades, str(trades_csv), format="csv")
                            export_trade_journal(result.trades, str(trades_json), format="json")
                            export_paths["csv"] = str(trades_csv)
                            export_paths["json"] = str(trades_json)

                        if hasattr(context, "user_data"):
                            context.user_data["backtest_export_paths"] = export_paths
                    except Exception as e:
                        logger.warning(f"Could not create export artifacts: {e}")

                    # Buttons
                    keyboard = []
                    export_row = []
                    if export_paths.get("csv"):
                        export_row.append(InlineKeyboardButton("📄 Trades CSV", callback_data="backtest_export:csv"))
                    if export_paths.get("json"):
                        export_row.append(InlineKeyboardButton("🧾 Trades JSON", callback_data="backtest_export:json"))
                    if export_row:
                        keyboard.append(export_row)
                    keyboard.append([
                        InlineKeyboardButton("📊 Metrics JSON", callback_data="backtest_export:metrics"),
                        InlineKeyboardButton("🔄 Run Again", callback_data="backtest"),
                    ])
                    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                    
                    # Send chart
                    if chart_path and chart_path.exists():
                        try:
                            with open(chart_path, 'rb') as photo:
                                if update.callback_query:
                                    await context.bot.send_photo(
                                        chat_id=update.effective_chat.id,
                                        photo=photo,
                                        caption=f"📊 Backtest Chart ({weeks} Week{'s' if weeks > 1 else ''}, {mode} mode)"
                                    )
                                else:
                                    await update.message.reply_photo(
                                        photo=photo,
                                        caption=f"📊 Backtest Chart ({weeks} Week{'s' if weeks > 1 else ''}, {mode} mode)"
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
                    "2. Choose a shorter backtest window (1–2 weeks)\n"
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

    async def _handle_backtest_export(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        kind: str,
    ) -> None:
        """Send the most recent backtest export artifact (CSV/JSON)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        paths = {}
        if hasattr(context, "user_data"):
            paths = context.user_data.get("backtest_export_paths", {}) or {}

        key = kind.lower().strip()
        if key not in ("csv", "json", "metrics"):
            key = "metrics"

        target = paths.get(key)
        if not target:
            await self._send_message_or_edit(
                update,
                context,
                "❌ *No export available*\n\nRun a backtest first, then try export again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📉 Backtest", callback_data="backtest")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]),
            )
            return

        try:
            p = Path(target)
            if not p.exists() or not p.is_file():
                raise FileNotFoundError(str(p))

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
            with open(p, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=p.name,
                )

            await self._send_message_or_edit(
                update,
                context,
                f"✅ Sent `{p.name}`",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("📉 Backtest", callback_data="backtest"),
                        InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
                    ]
                ]),
            )
        except Exception as e:
            logger.error(f"Error exporting backtest artifact: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"❌ *Export failed*\n\n`{str(e)}`",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_performance_export(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        kind: str,
    ) -> None:
        """Send the most recent performance export artifact."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        paths = {}
        if hasattr(context, "user_data"):
            paths = context.user_data.get("performance_export_paths", {}) or {}

        key = kind.lower().strip()
        if key == "signals":
            target = paths.get("signals_jsonl")
        elif key == "exited":
            target = paths.get("exited_csv")
        else:
            target = paths.get("metrics")

        if not target:
            await self._send_message_or_edit(
                update,
                context,
                "❌ *No export available*\n\nOpen `/performance` first to generate export files.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📈 Performance", callback_data="performance")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
                ]),
            )
            return

        try:
            p = Path(target)
            if not p.exists() or not p.is_file():
                raise FileNotFoundError(str(p))

            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_document")
            with open(p, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=p.name,
                )

            await self._send_message_or_edit(
                update,
                context,
                f"✅ Sent `{p.name}`",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("📈 Performance", callback_data="performance"),
                        InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
                    ]
                ]),
            )
        except Exception as e:
            logger.error(f"Error exporting performance artifact: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"❌ *Export failed*\n\n`{str(e)}`",
                reply_markup=self._get_back_to_menu_button(),
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

            symbol = "MNQ"

            # Prefer a real historical slice (cached) so the chart looks identical to production.
            # This avoids synthetic candle edge cases and avoids hammering IBKR.
            def _load_cached_history() -> tuple[Optional[pd.DataFrame], Optional[str], Optional[str]]:
                """Return (df, source_name, inferred_tf) where df has a DateTimeIndex + lowercase OHLCV."""
                try:
                    candidates = []
                    candidates.extend(self._historical_cache_dir.glob(f"{symbol}_1m_*.parquet"))
                    candidates.extend(self._historical_cache_dir.glob(f"{symbol}_5m_*.parquet"))
                    files = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
                except Exception:
                    files = []

                for f in files:
                    try:
                        tmp = pd.read_parquet(f)
                        if tmp is None or tmp.empty:
                            continue

                        inferred_tf = "1m" if "_1m_" in f.name else "5m" if "_5m_" in f.name else None

                        # Normalize timestamp/index
                        if "timestamp" in tmp.columns:
                            tmp["timestamp"] = pd.to_datetime(tmp["timestamp"], errors="coerce", utc=True)
                            tmp = tmp.dropna(subset=["timestamp"])
                            tmp = tmp.sort_values("timestamp")
                            tmp = tmp.drop_duplicates(subset=["timestamp"], keep="first")
                            tmp = tmp.set_index("timestamp")
                        elif isinstance(tmp.index, pd.DatetimeIndex):
                            if tmp.index.tz is None:
                                tmp.index = tmp.index.tz_localize(timezone.utc)
                            tmp = tmp.sort_index()
                        else:
                            continue

                        # Normalize column names to lowercase
                        col_map = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
                        for old, new in col_map.items():
                            if old in tmp.columns and new not in tmp.columns:
                                tmp = tmp.rename(columns={old: new})

                        if not all(c in tmp.columns for c in ("open", "high", "low", "close")):
                            continue

                        return tmp, f.name, inferred_tf
                    except Exception:
                        continue

                return None, None, None

            hist_df, hist_src, hist_tf = _load_cached_history()

            # Fallback: synthetic data (should be rare)
            def _create_synthetic_5m(num_bars: int = 160) -> pd.DataFrame:
                np.random.seed(42)
                base_price = 25000.0
                dates = pd.date_range(end=datetime.now(timezone.utc), periods=num_bars, freq="5min")
                price_changes = np.random.randn(num_bars) * 8
                prices = base_price + np.cumsum(price_changes)
                rows = []
                for date, price in zip(dates, prices):
                    candle_range = abs(np.random.randn() * 8) + 5
                    if np.random.random() > 0.5:
                        open_price = price - candle_range * 0.3
                        close_price = price + candle_range * 0.3
                    else:
                        open_price = price + candle_range * 0.3
                        close_price = price - candle_range * 0.3
                    high = max(open_price, close_price) + abs(np.random.randn() * 3) + 2
                    low = min(open_price, close_price) - abs(np.random.randn() * 3) - 2
                    rows.append(
                        {
                            "timestamp": date,
                            "open": open_price,
                            "high": high,
                            "low": low,
                            "close": close_price,
                            "volume": int(np.random.uniform(1000, 5000)),
                        }
                    )
                df = pd.DataFrame(rows)
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                return df.set_index("timestamp")

            # Convert to 5m bars for charting
            df_5m: pd.DataFrame
            src_label = hist_src or "synthetic"
            if hist_df is None or hist_df.empty:
                df_5m = _create_synthetic_5m(220)
                src_label = "synthetic"
            else:
                if hist_tf == "5m":
                    df_5m = hist_df.copy()
                else:
                    # Resample 1m → 5m
                    df_5m = (
                        hist_df.resample("5min")
                        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                        .dropna()
                    )

            # Choose a recent random window so it feels like a real trade snapshot
            window_bars = 160
            if len(df_5m) < window_bars + 10:
                df_5m = df_5m.tail(window_bars + 10)

            max_end = len(df_5m) - 1
            min_end = max(window_bars, max_end - 3000)  # ~last 10 days of 5m bars
            end_i = random.randint(min_end, max_end) if max_end > min_end else max_end
            window = df_5m.iloc[end_i - window_bars : end_i + 1].copy()

            # Simple ATR-based risk sizing for realistic SL/TP distances
            def _atr(d: pd.DataFrame, period: int = 14) -> float:
                try:
                    h = d["high"].astype(float)
                    l = d["low"].astype(float)
                    c = d["close"].astype(float)
                    pc = c.shift(1)
                    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
                    v = tr.rolling(period).mean().iloc[-1]
                    return float(v) if v is not None and np.isfinite(v) else 0.0
                except Exception:
                    return 0.0

            entry_price = float(window["close"].iloc[-1])
            atr_val = _atr(window)
            stop_dist = max(10.0, atr_val * 1.5 if atr_val > 0 else 15.0)
            direction = random.choice(["long", "short"])

            if direction == "long":
                stop_loss = entry_price - stop_dist
                take_profit = entry_price + (stop_dist * 1.5)
            else:
                stop_loss = entry_price + stop_dist
                take_profit = entry_price - (stop_dist * 1.5)

            sig_type = random.choice(["momentum_breakout", "trend_continuation", "mean_reversion"])
            confidence = float(round(random.uniform(0.58, 0.86), 2))

            test_signal: Dict[str, Any] = {
                "entry_price": round(entry_price, 2),
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "direction": direction,
                "type": sig_type,
                "symbol": symbol,
                "confidence": confidence,
                "reason": f"Test signal (replica) from {src_label}",
                # Used by chart HUD RR box
                "tick_value": 2.0,  # MNQ ~$2/point
                "position_size": 1,
            }

            # Optional: enrich with HUD context (sessions/key levels/etc.)
            try:
                from pearlalgo.strategies.nq_intraday.hud_context import build_hud_context

                test_signal["hud_context"] = build_hud_context(window, symbol=symbol, tick_size=0.25)
            except Exception:
                pass

            # Generate entry chart (production generator)
            chart_path = self.chart_generator.generate_entry_chart(test_signal, window, symbol)
            
            if chart_path and chart_path.exists():
                # Calculate R:R ratio
                risk = abs(entry_price - stop_loss)
                reward = abs(take_profit - entry_price)
                rr_ratio = reward / risk if risk > 0 else 0
                
                # Send test signal message
                side = "LONG" if direction == "long" else "SHORT"
                type_label = sig_type.replace("_", " ").title()
                message = (
                    "🧪 *Test Signal Generated*\n\n"
                    f"*Type:* {type_label} ({side})\n"
                    f"*Entry:* ${entry_price:,.2f}\n"
                    f"*Stop:* ${stop_loss:,.2f}\n"
                    f"*TP:* ${take_profit:,.2f}\n"
                    f"*R:R:* {rr_ratio:.2f}:1\n\n"
                    "📊 Entry chart generated below!"
                )
                
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Generate Another", callback_data='test_signal'),
                    InlineKeyboardButton("🏠 Main Menu", callback_data='start'),
                ]])
                
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                
                # Send chart
                try:
                    with open(chart_path, 'rb') as photo:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption="📊 Test Signal Entry Chart",
                        )
                    
                    # Clean up
                    chart_path.unlink()
                    logger.info("Test signal chart sent successfully")

                    # Auto-send a simulated exit after 10 seconds (replica lifecycle)
                    chat_id = update.effective_chat.id
                    bot = context.bot

                    exit_win = random.random() < 0.55
                    exit_reason = "take_profit" if exit_win else "stop_loss"
                    exit_price = float(take_profit if exit_win else stop_loss)

                    # PnL in USD (approx, MNQ: $2/point)
                    pnl_points = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
                    pnl_usd = float(pnl_points) * float(test_signal.get("tick_value") or 2.0) * float(test_signal.get("position_size") or 1.0)

                    async def _send_test_exit():
                        await asyncio.sleep(10)
                        try:
                            result = "WIN" if exit_reason == "take_profit" else "LOSS"
                            msg = (
                                f"🧪 *Test Exit ({result})*\n\n"
                                f"*Exit:* ${exit_price:,.2f} ({exit_reason.replace('_', ' ').title()})\n"
                                f"*P&L:* ${pnl_usd:,.2f}\n\n"
                                "📉 Exit chart below!"
                            )
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

                            exit_chart = self.chart_generator.generate_exit_chart(
                                test_signal,
                                exit_price=exit_price,
                                exit_reason=exit_reason,
                                pnl=pnl_usd,
                                buffer_data=window,
                                symbol=symbol,
                                timeframe="5m",
                            )
                            if exit_chart and exit_chart.exists():
                                with open(exit_chart, "rb") as photo2:
                                    await bot.send_photo(
                                        chat_id=chat_id,
                                        photo=photo2,
                                        caption="📉 Test Signal Exit Chart",
                                    )
                                try:
                                    exit_chart.unlink()
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"Error sending test exit: {e}", exc_info=True)

                    asyncio.create_task(_send_test_exit())
                    
                except Exception as e:
                    logger.error(f"Error sending test chart: {e}", exc_info=True)
                    await self._send_message_or_edit(
                        update, context,
                        "📊 *Test Chart Delivery Failed*\n\n"
                        "Chart was generated but couldn't be sent.\n\n"
                        "💡 Try again"
                    )
            else:
                reply_markup = self._get_back_to_menu_button()
                await self._send_message_or_edit(
                    update, context,
                    "📊 *Test Chart Unavailable*\n\n"
                    "Could not generate test chart.\n\n"
                    "💡 Check /data_quality for data issues",
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error handling test_signal command: {e}", exc_info=True)
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(
                update, context,
                "📊 *Test Signal Failed*\n\n"
                "Something went wrong generating the test signal.\n\n"
                "💡 Try again or check /data_quality",
                reply_markup=reply_markup
            )
    
    async def _handle_performance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /performance command."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
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
                message += f"⏱️ Avg Hold: {performance.get('avg_hold_minutes', 0.0):.1f} min\n"
            else:
                message += "⏳ No completed trades yet\n"

            # Breakdown by signal type (top 6 by count)
            by_type = performance.get("by_signal_type", {}) or {}
            if by_type:
                message += "\n🧾 *By Signal Type*\n"
                items = []
                for sig_type, m in by_type.items():
                    items.append(
                        (
                            int(m.get("count", 0) or 0),
                            str(sig_type),
                            float(m.get("win_rate", 0.0) or 0.0),
                            float(m.get("total_pnl", 0.0) or 0.0),
                        )
                    )
                items.sort(key=lambda x: x[0], reverse=True)
                for count, sig_type, wr, pnl in items[:6]:
                    message += f"- `{sig_type}`: {count} • {wr*100:.0f}% • ${pnl:,.2f}\n"

            # Prepare export artifacts (signals + metrics)
            export_paths: Dict[str, str] = {}
            try:
                exports_dir = self.state_dir / "exports"
                exports_dir.mkdir(parents=True, exist_ok=True)
                ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                base_name = f"performance_7d_{ts_tag}"

                # Metrics JSON
                metrics_path = exports_dir / f"{base_name}_metrics.json"
                with open(metrics_path, "w") as f:
                    json.dump(performance, f, indent=2)
                export_paths["metrics"] = str(metrics_path)

                # Export last 7d signals (JSONL) + exited signals CSV
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    cutoff = datetime.now(timezone.utc).timestamp() - (7 * 24 * 60 * 60)
                    kept = []
                    with open(signals_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            ts_str = rec.get("timestamp") or rec.get("signal", {}).get("timestamp") or ""
                            try:
                                ts = pd.to_datetime(ts_str).timestamp() if ts_str else None
                            except Exception:
                                ts = None
                            if ts is None or ts < cutoff:
                                continue
                            kept.append(rec)

                    if kept:
                        signals_jsonl = exports_dir / f"{base_name}_signals.jsonl"
                        with open(signals_jsonl, "w") as f:
                            for rec in kept:
                                f.write(json.dumps(rec) + "\n")
                        export_paths["signals_jsonl"] = str(signals_jsonl)

                        # Exited-only CSV (best-effort)
                        exited = [r for r in kept if r.get("status") == "exited"]
                        if exited:
                            rows = []
                            for r in exited:
                                s = r.get("signal", {}) or {}
                                rows.append(
                                    {
                                        "timestamp": r.get("timestamp"),
                                        "signal_id": r.get("signal_id"),
                                        "type": s.get("type"),
                                        "direction": s.get("direction"),
                                        "confidence": s.get("confidence"),
                                        "entry_price": s.get("entry_price"),
                                        "stop_loss": s.get("stop_loss"),
                                        "take_profit": s.get("take_profit"),
                                        "exit_price": r.get("exit_price"),
                                        "exit_reason": r.get("exit_reason"),
                                        "pnl": r.get("pnl"),
                                        "is_win": r.get("is_win"),
                                        "hold_minutes": r.get("hold_duration_minutes"),
                                    }
                                )
                            df_out = pd.DataFrame(rows)
                            csv_path = exports_dir / f"{base_name}_exited.csv"
                            df_out.to_csv(csv_path, index=False)
                            export_paths["exited_csv"] = str(csv_path)

                if hasattr(context, "user_data"):
                    context.user_data["performance_export_paths"] = export_paths
            except Exception as e:
                logger.warning(f"Could not create performance export artifacts: {e}")

            # Buttons (exports)
            keyboard = []
            export_row = []
            if export_paths.get("signals_jsonl"):
                export_row.append(
                    InlineKeyboardButton(
                        "📄 Signals JSONL",
                        callback_data="performance_export:signals",
                    )
                )
            if export_paths.get("exited_csv"):
                export_row.append(
                    InlineKeyboardButton(
                        "📄 Exited CSV",
                        callback_data="performance_export:exited",
                    )
                )
            if export_row:
                keyboard.append(export_row)

            keyboard.append(
                [
                    InlineKeyboardButton(
                        "📊 Metrics JSON",
                        callback_data="performance_export:metrics",
                    ),
                    InlineKeyboardButton("🔄 Refresh", callback_data="performance"),
                ]
            )
            keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="start")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
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
            message = f"{health_emoji} *{LABEL_AGENT} Health*\n\n"
            message += f"- {LABEL_AGENT}: {STATE_RUNNING if process_running else STATE_STOPPED}\n"
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

    async def _handle_activity(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /activity command - answers "is the bot doing anything?"
        
        Shows:
        - Last cycle time and status
        - Current buffer status
        - Active positions (if any)
        - Next expected action
        """
        logger.info(f"Received /activity command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            state_file = get_state_file(self.state_dir)
            process_running = self._is_agent_process_running()
            
            if not state_file.exists():
                message = "📈 *Activity Status*\n\n"
                message += f"🔴 *{LABEL_AGENT}:* {STATE_STOPPED}\n\n"
                message += "ℹ️ No activity data available.\n"
                message += f"💡 Start the {LABEL_AGENT.lower()} to begin monitoring.\n"
                reply_markup = self._get_main_menu_buttons(agent_running=False)
                await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
                return
            
            with open(state_file) as f:
                state = json.load(f)
            
            # Get activity pulse from last_successful_cycle (more accurate than state file mtime)
            from pearlalgo.utils.telegram_alerts import format_activity_pulse, format_next_session_time
            from pearlalgo.utils.paths import parse_utc_timestamp
            
            last_cycle_seconds = None
            try:
                last_cycle_ts = state.get("last_successful_cycle")
                if last_cycle_ts:
                    last_cycle_dt = parse_utc_timestamp(str(last_cycle_ts))
                    if last_cycle_dt:
                        if last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
            except Exception:
                last_cycle_seconds = None
            
            # Fallback: if no last_successful_cycle, use nq_agent.log mtime as liveness proxy
            if last_cycle_seconds is None and process_running:
                try:
                    project_root = Path(__file__).parent.parent.parent.parent
                    log_file = project_root / "logs" / "nq_agent.log"
                    if log_file.exists():
                        log_mtime = log_file.stat().st_mtime
                        last_cycle_seconds = datetime.now(timezone.utc).timestamp() - log_mtime
                except Exception:
                    pass
            
            running = process_running and state.get("running", False)
            paused = state.get("paused", False)
            
            # Compute data freshness using robust helper
            data_age_minutes = self._extract_data_age_minutes(state)
            data_stale_threshold = float(state.get("data_stale_threshold_minutes", 10.0))
            is_data_stale = data_age_minutes is not None and data_age_minutes > data_stale_threshold
            
            # Build activity message
            message = "📈 *Activity Status*\n\n"
            
            # Service status (using standardized terminology)
            if not running:
                message += f"🔴 *{LABEL_AGENT}:* {STATE_STOPPED}\n"
            elif paused:
                message += f"⏸️ *{LABEL_AGENT}:* {STATE_PAUSED}\n"
                pause_reason = state.get("pause_reason")
                if pause_reason:
                    message += f"   Reason: {pause_reason}\n"
            else:
                message += f"🟢 *{LABEL_AGENT}:* {STATE_RUNNING}\n"
            
            # Activity pulse (using last_successful_cycle for accuracy)
            if last_cycle_seconds is not None:
                pulse_emoji, pulse_text = format_activity_pulse(last_cycle_seconds, is_paused=paused)
                message += f"\n{pulse_emoji} *Last Scan:* {pulse_text}\n"
            
            # Scan information (standardized: "scans" not "cycles")
            scans_total = int(state.get("cycle_count", 0) or 0)
            scans_session = state.get("cycle_count_session")
            if scans_session is not None:
                message += f"🔄 *Scans:* {scans_session:,} (session) / {scans_total:,} (total)\n"
            else:
                message += f"🔄 *Scans:* {scans_total:,}\n"
            
            # Buffer status
            buffer_size = int(state.get("buffer_size", 0) or 0)
            buffer_target = state.get("buffer_size_target")
            if buffer_target:
                buffer_pct = (buffer_size / int(buffer_target)) * 100 if int(buffer_target) > 0 else 0
                message += f"📊 *Buffer:* {buffer_size}/{buffer_target} {LABEL_BUFFER} ({buffer_pct:.0f}%)\n"
            else:
                message += f"📊 *Buffer:* {buffer_size} {LABEL_BUFFER}\n"
            
            # Latest bar info + data freshness
            latest_price = self._extract_latest_price(state)
            if latest_price is not None:
                message += f"💰 *Latest Price:* ${latest_price:,.2f}\n"
            
            # Data freshness cue (concise + actionable when stale)
            if data_age_minutes is not None:
                if is_data_stale:
                    age_str = f"{data_age_minutes:.0f}m" if data_age_minutes < 60 else f"{data_age_minutes / 60:.1f}h"
                    message += f"⏰ *Data:* stale ({age_str}) • /data_quality\n"
                else:
                    message += f"🟢 *Data:* fresh ({data_age_minutes:.0f}m old)\n"
            
            # Active trades count (standardized terminology)
            try:
                signals_file = get_signals_file(self.state_dir)
                if signals_file.exists():
                    active_count = 0
                    with open(signals_file) as f:
                        for line in f:
                            try:
                                sig = json.loads(line.strip())
                                if sig.get("status") == "entered":
                                    active_count += 1
                            except Exception:
                                continue
                    if active_count > 0:
                        message += f"\n🎯 *{LABEL_ACTIVE_TRADES}:* {active_count}\n"
            except Exception:
                pass
            
            # Next expected action (consistent with pulse status)
            message += "\n*What's Next:*\n"
            futures_open = state.get("futures_market_open")
            session_open = state.get("strategy_session_open")
            
            if not running:
                message += f"💡 Start {LABEL_AGENT.lower()} to begin monitoring\n"
            elif paused:
                message += f"💡 Resume {LABEL_AGENT.lower()} or address pause reason\n"
            elif is_data_stale:
                # Data stale - prioritize this issue
                message += "⏰ Data stale—signals paused • /data_quality\n"
            elif last_cycle_seconds is not None and last_cycle_seconds > 300:
                # Stale pulse - highlight potential issue
                message += "⚠️ Scans appear stalled—check /health or logs\n"
            elif session_open is False:
                next_session = format_next_session_time()
                message += f"⏳ Waiting for session • {next_session}\n"
            elif futures_open is False:
                message += "⏳ Waiting for market to open\n"
            else:
                # Get scan_interval from nested config block
                config_block = state.get("config", {})
                scan_interval = config_block.get("scan_interval", 60) if isinstance(config_block, dict) else 60
                message += f"🔄 Next scan in ~{scan_interval}s\n"
            
            # Buttons
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="activity"),
                    InlineKeyboardButton("📊 Active Trades", callback_data="active_trades"),
                ],
                [
                    InlineKeyboardButton("🔔 Signals", callback_data="signals"),
                    InlineKeyboardButton("📈 Performance", callback_data="performance"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error handling activity command: {e}", exc_info=True)
            error_msg = f"❌ *Error:* {str(e)}"
            reply_markup = self._get_back_to_menu_button()
            await self._send_message_or_edit(update, context, error_msg, reply_markup=reply_markup)

    async def _handle_data_quality(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        diagnose: bool = False,
    ):
        """Handle /data_quality command (data freshness + buffer + gateway triage)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Load state file (written by agent service)
        state_file = get_state_file(self.state_dir)
        state: Dict = {}
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
            except Exception:
                state = {}

        agent_running = self._is_agent_process_running()
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False)

        # Compute state file freshness (operator signal)
        state_last_updated_utc = None
        state_age_seconds = None
        if state_file.exists():
            try:
                mtime = state_file.stat().st_mtime
                state_last_updated_utc = datetime.fromtimestamp(mtime, tz=timezone.utc)
                state_age_seconds = (datetime.now(timezone.utc) - state_last_updated_utc).total_seconds()
            except Exception:
                state_last_updated_utc = None
                state_age_seconds = None

        # Market/session status is relevant for stale-data interpretation and signal expectations.
        # Prefer persisted state values when available (so the UI reflects what the agent believed),
        # but fall back to live evaluation if missing.
        futures_market_open = state.get("futures_market_open")
        strategy_session_open = state.get("strategy_session_open")
        if futures_market_open is None:
            try:
                from pearlalgo.utils.market_hours import get_market_hours

                futures_market_open = bool(get_market_hours().is_market_open())
            except Exception:
                futures_market_open = None

        # Data freshness metadata (populated by service._save_state)
        data_fresh = state.get("data_fresh")
        latest_bar_timestamp = state.get("latest_bar_timestamp")
        latest_bar_age_minutes = state.get("latest_bar_age_minutes")

        # Backward-compatible: if age isn't persisted but timestamp is, compute age.
        if latest_bar_age_minutes is None and latest_bar_timestamp:
            try:
                ts = datetime.fromisoformat(str(latest_bar_timestamp).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                latest_bar_age_minutes = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
            except Exception:
                latest_bar_age_minutes = None

        buffer_size = int(state.get("buffer_size", 0) or 0)
        buffer_target = state.get("buffer_size_target")
        try:
            buffer_target = int(buffer_target) if buffer_target is not None else None
        except Exception:
            buffer_target = None

        # Identify issues (keep short; top 3 shown)
        issues: list[str] = []
        if not agent_running:
            issues.append(f"{LABEL_AGENT} process not running")
        if not gateway_running:
            issues.append(f"IBKR {LABEL_GATEWAY} not running")
        elif not gateway_api_ready:
            issues.append(f"{LABEL_GATEWAY} running but API not ready (port 4002 not listening)")

        # State file should update frequently when agent is healthy
        if state_age_seconds is not None and state_age_seconds > 60:
            issues.append(f"State file update lag ({int(state_age_seconds)}s)")

        if data_fresh is False:
            issues.append("Market data appears stale while market is open")
        if buffer_size < 10:
            issues.append(f"Buffer low ({buffer_size} bars; min 10)")

        # Heuristics: likely causes (prioritized)
        likely_causes: list[str] = []
        if not agent_running:
            likely_causes.append("Agent stopped/crashed (restart agent)")
        if not gateway_running:
            likely_causes.append("Gateway down (start/restart gateway)")
        if gateway_running and not gateway_api_ready:
            likely_causes.append("Gateway still authenticating / 2FA / API not ready")
        if data_fresh is False and (futures_market_open is True or futures_market_open is None):
            likely_causes.append("IBKR market data entitlement / delayed feed / connectivity issue")
        if buffer_size < 10:
            likely_causes.append("Historical fetch failing (HMDS pacing/outage) or connection issue")

        # Render message using standardized terminology
        title = "🛡 *Data Quality*" + (" (diagnose)" if diagnose else "")
        message = f"{title}\n\n"

        message += f"🤖 *{LABEL_AGENT}:* {'🟢 ' + STATE_RUNNING if agent_running else '🔴 ' + STATE_STOPPED}\n"
        message += (
            f"🔌 *{LABEL_GATEWAY}:* {'🟢 ' + STATE_RUNNING if gateway_running else '🔴 ' + STATE_STOPPED}"
            + (f" • API {'🟢 READY' if gateway_api_ready else '🔴 NOT READY'}" if gateway_running else "")
            + "\n"
        )
        
        # Buffer with target/percent
        if buffer_target is not None and buffer_target > 0:
            buffer_pct = (buffer_size / buffer_target) * 100
            message += f"📊 *Buffer:* {buffer_size}/{buffer_target} {LABEL_BUFFER} ({buffer_pct:.0f}%)\n"
        else:
            message += f"📊 *Buffer:* {buffer_size} {LABEL_BUFFER}\n"

        if latest_bar_age_minutes is not None:
            freshness_emoji = "🟢" if data_fresh is True else "🔴" if data_fresh is False else "⚪"
            message += f"{freshness_emoji} *Latest Bar Age:* {float(latest_bar_age_minutes):.1f} min\n"
        else:
            message += "⚪ *Latest Bar Age:* unknown\n"

        # Use standardized gate terminology
        message += format_gate_status(futures_market_open, strategy_session_open) + "\n"

        if state_last_updated_utc:
            message += f"\n🗂️ *State Updated:* {state_last_updated_utc.isoformat(timespec='seconds')}\n"

        # Impact section: explain what issues mean for trading
        if issues:
            message += "\n⚠️ *Issues:*\n"
            for i, issue in enumerate(issues[:3], start=1):
                message += f"{i}. {issue}\n"
            
            # Add short impact summary
            message += "\n📉 *Impact:*\n"
            if not agent_running or not gateway_running:
                message += "• Signal generation halted\n"
            elif data_fresh is False:
                message += "• Signals paused until data refreshes\n"
            elif buffer_size < 10:
                message += "• Insufficient data for reliable signals\n"
            else:
                message += "• May affect signal accuracy\n"

        if likely_causes:
            message += "\n💡 *Likely causes:*\n"
            for i, cause in enumerate(likely_causes[:2], start=1):
                message += f"• {cause}\n"

        if diagnose:
            try:
                from pearlalgo.config.config_loader import load_service_config

                cfg = load_service_config()
                data_cfg = cfg.get("data", {})
                svc_cfg = cfg.get("service", {})
                stale_thr = data_cfg.get("stale_data_threshold_minutes", 10)
                alert_int = svc_cfg.get("data_quality_alert_interval", 300)
                buf_target = data_cfg.get("buffer_size", 100)
                message += "\n🔎 *Diagnostics:*\n"
                message += f"- stale_threshold_minutes: {stale_thr}\n"
                message += f"- data_quality_alert_interval_sec: {alert_int}\n"
                message += f"- configured_buffer_size: {buf_target}\n"
            except Exception:
                pass

        # Buttons
        keyboard = [
            [
                InlineKeyboardButton("🔎 Diagnose", callback_data="data_quality:diagnose"),
                InlineKeyboardButton("🔄 Refresh", callback_data="data_quality"),
            ],
            [
                InlineKeyboardButton("🔁 Restart Agent", callback_data="confirm:restart_agent"),
                InlineKeyboardButton("🔁 Restart Gateway", callback_data="confirm:restart_gateway"),
            ],
            [
                InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
    
    async def _handle_start_gateway(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start_gateway command."""
        logger.info(f"Received /start_gateway command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(
            update,
            context,
            "🔄 Starting *IBKR Gateway*...\n\nThis may take up to 60–120 seconds.",
            reply_markup=None,
        )

        result = await self.service_controller.start_gateway()

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"

        gateway_status = self.service_controller.get_gateway_status()
        reply_markup = self._get_gateway_buttons(gateway_running=gateway_status.get("process_running", False))
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_stop_gateway(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_gateway command."""
        logger.info(f"Received /stop_gateway command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Stopping *IBKR Gateway*...", reply_markup=None)

        result = await self.service_controller.stop_gateway()

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"
        
        # Get updated gateway status
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)

        reply_markup = self._get_gateway_buttons(gateway_running=gateway_running)
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_gateway_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gateway_status command."""
        logger.info(f"Received /gateway_status command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
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
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Starting *NQ Agent Service*...", reply_markup=None)

        result = await self.service_controller.start_agent(background=True)

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"

        # Add gateway status warning if needed
        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        if not gateway_running:
            message += "\n\n⚠️ *Warning:* IBKR Gateway is not running. Agent may not receive data."

        reply_markup = self._get_main_menu_buttons(
            agent_running=self._is_agent_process_running(),
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_stop_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop_agent command."""
        logger.info(f"Received /stop_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Stopping *NQ Agent Service*...", reply_markup=None)

        result = await self.service_controller.stop_agent()

        message = f"{result['message']}\n"
        if result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(result['details'])
            message += f"\n{escaped_details}"

        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=False,
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_restart_agent(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /restart_agent command."""
        logger.info(f"Received /restart_agent command from chat {update.effective_chat.id}")
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        await self._send_message_or_edit(update, context, "🔄 Restarting *NQ Agent Service*...", reply_markup=None)

        # Stop first
        stop_result = await self.service_controller.stop_agent()
        if not stop_result["success"] and "not running" not in stop_result["message"].lower():
            reply_markup = self._get_main_menu_buttons(agent_running=True)
            await self._send_message_or_edit(
                update, context,
                f"⚠️ Stop failed: {escape_subprocess_output(stop_result['message'])}\nAborting restart.",
                reply_markup=reply_markup
            )
            return

        # Wait a moment
        await asyncio.sleep(2)

        # Start
        start_result = await self.service_controller.start_agent(background=True)

        message = "🔄 *Restart Complete*\n\n"
        message += f"*Stop:* {escape_subprocess_output(stop_result['message'])}\n"
        message += f"*Start:* {escape_subprocess_output(start_result['message'])}"

        if start_result.get("details"):
            # Escape subprocess output to prevent Markdown parse errors
            escaped_details = escape_subprocess_output(start_result['details'])
            message += f"\n\n{escaped_details}"

        gateway_status = self.service_controller.get_gateway_status()
        gateway_running = gateway_status.get("process_running", False)
        gateway_api_ready = gateway_status.get("port_listening", False) if gateway_running else False
        reply_markup = self._get_main_menu_buttons(
            agent_running=True,
            gateway_running=gateway_running,
            gateway_api_ready=gateway_api_ready,
        )
        await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)

    async def _handle_signal_detail(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        signal_id_prefix: str,
    ) -> None:
        """Show a rich, text-only signal detail view (fast; chart optional)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                await self._send_message_or_edit(
                    update,
                    context,
                    "📭 *No signals found*\n\nSignals will appear here once the agent generates opportunities.",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return

            # Search recent signals (tail) for matching prefix
            found: Optional[Dict] = None
            with open(signals_file, "r") as f:
                lines = f.readlines()[-500:]
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "signal" in raw:
                    record = raw
                else:
                    record = {
                        "signal_id": raw.get("signal_id", ""),
                        "timestamp": raw.get("timestamp", ""),
                        "status": raw.get("status", "generated"),
                        "signal": raw,
                    }

                sig_id = record.get("signal_id", "") or ""
                if sig_id.startswith(signal_id_prefix):
                    found = record
                    break

            if not found:
                await self._send_message_or_edit(
                    update,
                    context,
                    f"❌ *Signal not found*\n\nNo signal matching `{signal_id_prefix}` in recent history.",
                    reply_markup=self._get_back_to_menu_button(),
                )
                return

            signal = found.get("signal", {}) or {}
            sig_type = str(signal.get("type", "unknown"))
            status = str(found.get("status", "unknown"))
            sig_id = str(found.get("signal_id", "")) or ""

            entry = float(signal.get("entry_price", 0.0) or 0.0)
            stop = float(signal.get("stop_loss", 0.0) or 0.0)
            tp = float(signal.get("take_profit", 0.0) or 0.0)
            conf = float(signal.get("confidence", 0.0) or 0.0)

            # Use shared helpers for consistent formatting
            is_win = found.get("is_win") if status == "exited" else None
            status_emoji, status_label = format_signal_status(status, is_win)
            dir_emoji, dir_label = format_signal_direction(signal.get("direction", "long"))
            conf_emoji, conf_tier = format_signal_confidence_tier(conf)

            # Calculate R:R
            rr = None
            if entry > 0 and stop > 0 and tp > 0:
                if dir_label == "LONG":
                    risk = entry - stop
                    reward = tp - entry
                else:
                    risk = stop - entry
                    reward = entry - tp
                if risk > 0:
                    rr = reward / risk

            # Freshness indicator
            sig_ts = found.get("timestamp") or signal.get("timestamp")
            age_str = format_time_ago(sig_ts)

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # DECISION-FIRST LAYOUT: Trade plan at the top for fast action
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            message = f"{status_emoji} *Signal Detail*\n"
            message += f"{dir_emoji} *{sig_type.replace('_', ' ').title()}* {dir_label}\n"
            message += "━━━━━━━━━━━━━━━━━━━━━\n\n"

            # Trade Plan (always visible first)
            message += "📋 *Trade Plan*\n"
            if entry:
                message += f"   Entry: ${entry:.2f}\n"
            if stop:
                stop_dist = abs(entry - stop) if entry else 0
                message += f"   Stop:  ${stop:.2f} ({stop_dist:.2f} pts)\n"
            if tp:
                tp_dist = abs(tp - entry) if entry else 0
                message += f"   TP:    ${tp:.2f} ({tp_dist:.2f} pts)\n"
            if rr is not None:
                message += f"   R:R:   {rr:.2f}:1\n"
            message += "\n"

            # Confidence + Status
            message += f"{conf_emoji} *Confidence:* {conf:.0%} ({conf_tier})\n"
            message += f"📌 *Status:* {status_label}"
            if age_str:
                message += f" • {age_str}"
            message += "\n"

            # P&L for exited signals
            if status == "exited":
                pnl = float(found.get("pnl", 0.0) or 0.0)
                pnl_emoji, pnl_str = format_pnl(pnl)
                exit_reason = str(found.get("exit_reason", "") or "")
                message += f"{pnl_emoji} *P&L:* {pnl_str}"
                if exit_reason:
                    message += f" ({exit_reason})"
                message += "\n"

            message += f"🆔 `{sig_id[:16]}…`\n"

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # CONTEXT BLOCKS: Trader-facing labels, collapsible conceptually
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # Optional enhanced context
            regime = signal.get("regime", {}) or {}
            mtf = signal.get("mtf_analysis", {}) or {}
            vwap = signal.get("vwap_data", {}) or {}
            flow = signal.get("order_flow", {}) or {}
            quality = signal.get("quality_score", {}) or {}
            sr_levels = signal.get("sr_levels", {}) or {}

            context_lines = []

            # Quality metrics (trader-facing labels)
            if quality:
                q_parts = []
                if "quality_score" in quality:
                    q_parts.append(f"Score: {float(quality.get('quality_score', 0.0)):.2f}")
                if "confluence_score" in quality:
                    q_parts.append(f"Confluence: {float(quality.get('confluence_score', 0.0)):.2f}")
                if "historical_wr" in quality:
                    q_parts.append(f"Historical WR: {float(quality.get('historical_wr', 0.0)):.0%}")
                if q_parts:
                    context_lines.append("🧠 *Quality:* " + " • ".join(q_parts))

            # Regime context
            if regime and regime.get("regime"):
                r_regime = str(regime.get("regime", "")).replace("_", " ").title()
                r_vol = str(regime.get("volatility", "")).title()
                r_session = str(regime.get("session", "")).replace("_", " ").title()
                context_lines.append(f"🧭 *Regime:* {r_regime} | {r_vol} Vol | {r_session}")

            # MTF alignment
            alignment = mtf.get("alignment")
            if alignment:
                mtf_score = mtf.get("alignment_score")
                mtf_str = f"🧩 *MTF:* {alignment.title()}"
                if mtf_score is not None:
                    mtf_str += f" ({float(mtf_score):.2f})"
                context_lines.append(mtf_str)

            # VWAP position
            if vwap and vwap.get("vwap"):
                vwap_val = float(vwap.get("vwap", 0.0))
                dist_pct = vwap.get("distance_pct")
                vwap_str = f"📍 *VWAP:* ${vwap_val:.2f}"
                if dist_pct is not None:
                    vwap_str += f" ({float(dist_pct):+.2f}%)"
                context_lines.append(vwap_str)

            # Order flow
            if flow and flow.get("recent_trend"):
                flow_trend = str(flow.get("recent_trend", "")).title()
                net = flow.get("net_pressure")
                flow_str = f"🌊 *Flow:* {flow_trend}"
                if net is not None:
                    flow_str += f" ({float(net):+.2f})"
                context_lines.append(flow_str)

            # S/R levels
            if sr_levels:
                sup = sr_levels.get("strongest_support")
                res = sr_levels.get("strongest_resistance")
                if sup or res:
                    lvl_parts = []
                    if sup:
                        lvl_parts.append(f"Sup: ${float(sup):.2f}")
                    if res:
                        lvl_parts.append(f"Res: ${float(res):.2f}")
                    context_lines.append("🧱 *Levels:* " + " | ".join(lvl_parts))

            if context_lines:
                message += "\n" + "\n".join(context_lines) + "\n"

            # Keyboard with chart and navigation
            keyboard = []
            if sig_id and self.chart_generator:
                keyboard.append([
                    InlineKeyboardButton("📊 View Chart", callback_data=f"signal_chart_{sig_id[:16]}"),
                    InlineKeyboardButton("🔔 Signals", callback_data="signals"),
                ])
            else:
                keyboard.append([InlineKeyboardButton("🔔 Signals", callback_data="signals")])
            keyboard.append([
                InlineKeyboardButton("📊 Active Trades", callback_data="active_trades"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=InlineKeyboardMarkup(keyboard))

        except Exception as e:
            logger.error(f"Error handling signal detail: {e}", exc_info=True)
            await self._send_message_or_edit(
                update,
                context,
                f"❌ *Error*\n\n`{str(e)}`",
                reply_markup=self._get_back_to_menu_button(),
            )

    async def _handle_signal_chart(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        signal_id_prefix: str,
    ):
        """Handle signal chart viewing with historical data fetch and exit chart support."""
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
            status = signal_data.get("status", "generated")
            symbol = signal.get("symbol", "MNQ")
            
            # Fetch historical data around signal time for chart rendering
            buffer_data = pd.DataFrame()
            try:
                signal_ts = signal_data.get("timestamp") or signal.get("timestamp")
                if signal_ts:
                    from pearlalgo.utils.paths import parse_utc_timestamp
                    signal_time = parse_utc_timestamp(str(signal_ts))
                    
                    # Fetch enough history for meaningful context (>= 6h requested).
                    # We include a small forward window so the chart also shows immediate post-signal behavior.
                    start_time = signal_time - timedelta(hours=6)
                    end_time = min(signal_time + timedelta(hours=1), datetime.now(timezone.utc))
                    
                    data_provider = self._get_data_provider()
                    if data_provider is not None:
                        try:
                            loop = asyncio.get_running_loop()
                            buffer_data = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None,
                                    lambda: data_provider.fetch_historical(
                                        symbol=symbol,
                                        start=start_time,
                                        end=end_time,
                                        bar_size="1 min",
                                    ),
                                ),
                                timeout=30.0,
                            )
                            if buffer_data is not None and not buffer_data.empty:
                                logger.info(f"Fetched {len(buffer_data)} bars for signal chart")
                        except asyncio.TimeoutError:
                            logger.warning("Timeout fetching historical data for signal chart")
                        except Exception as e:
                            logger.warning(f"Could not fetch historical data for signal chart: {e}")
            except Exception as e:
                logger.warning(f"Error preparing historical fetch for signal chart: {e}")
            
            # Generate chart based on signal status
            chart_path = None
            caption = ""
            
            if status == "exited":
                # Exited signal: show exit chart with PnL
                exit_price = float(signal_data.get("exit_price", 0.0) or 0.0)
                exit_reason = str(signal_data.get("exit_reason", "unknown") or "unknown")
                pnl = float(signal_data.get("pnl", 0.0) or 0.0)
                is_win = signal_data.get("is_win", pnl > 0)
                
                if exit_price > 0:
                    chart_path = self.chart_generator.generate_exit_chart(
                        signal=signal,
                        exit_price=exit_price,
                        exit_reason=exit_reason,
                        pnl=pnl,
                        buffer_data=buffer_data if buffer_data is not None else pd.DataFrame(),
                        symbol=symbol,
                    )
                    result_emoji = "✅" if is_win else "❌"
                    caption = (
                        f"{result_emoji} {signal.get('type', 'signal')} {signal.get('direction', '').upper()} | "
                        f"Exit: {exit_reason} | PnL: ${pnl:+.2f}"
                    )
                else:
                    # Fallback to entry chart if exit_price missing
                    chart_path = self.chart_generator.generate_entry_chart(
                        signal, buffer_data if buffer_data is not None else pd.DataFrame(), symbol
                    )
                    caption = f"📊 {signal.get('type', 'signal')} {signal.get('direction', '').upper()} (exited)"
            else:
                # Entry or active signal: show entry chart
                chart_path = self.chart_generator.generate_entry_chart(
                    signal, buffer_data if buffer_data is not None else pd.DataFrame(), symbol
                )
                status_emoji = "🎯" if status == "entered" else "📊"
                caption = f"{status_emoji} {signal.get('type', 'signal')} {signal.get('direction', '').upper()}"
            
            if chart_path and chart_path.exists():
                try:
                    # Send chart
                    with open(chart_path, 'rb') as photo:
                        if update.callback_query:
                            await context.bot.send_photo(
                                chat_id=update.effective_chat.id,
                                photo=photo,
                                caption=caption
                            )
                        else:
                            await update.message.reply_photo(
                                photo=photo,
                                caption=caption
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
                        "📊 *Chart Delivery Failed*\n\n"
                        "Chart was generated but couldn't be sent.\n\n"
                        "💡 Try again or check /data_quality"
                    )
            else:
                await self._send_message_or_edit(
                    update, context,
                    "📊 *Chart Unavailable*\n\n"
                    "Could not generate chart for this signal.\n\n"
                    "*Possible reasons:*\n"
                    "• Historical data not available\n"
                    "• Data still loading\n\n"
                    "💡 Try /data_quality to check data status"
                )
                
        except Exception as e:
            logger.error(f"Error handling signal chart: {e}", exc_info=True)
            await self._send_message_or_edit(
                update, context,
                "📊 *Chart Unavailable*\n\n"
                "Something went wrong loading the chart.\n\n"
                "💡 Try again or check /data_quality"
            )
    
    def _get_main_menu_buttons(
        self,
        agent_running: bool = False,
        gateway_running: bool = False,
        gateway_api_ready: Optional[bool] = None,
    ) -> InlineKeyboardMarkup:
        """
        Generate main menu inline keyboard buttons (unified Home Card layout).
        
        Layout optimized for quick access and discoverability:
        - Row 1: Agent control (Start/Stop/Restart) + Gateway status
        - Row 2: Quick Actions (Last Signal, Active Trades, Activity)
        - Row 3: Signals + Performance (most-used monitoring)
        - Row 4: Data Quality + Health (system status)
        - Row 5: Config + Backtest + Help
        
        Gateway indicator tri-state:
        - ✅ when running and API ready
        - 🟡 when running but API not ready (authenticating/2FA)
        - ❌ when stopped
        """
        keyboard = []
        
        # Row 1: Agent control + Gateway (service management with tri-state indicator)
        if gateway_running:
            if gateway_api_ready is True:
                gateway_status_text = "🔌 ✅"  # Running + API ready
            elif gateway_api_ready is False:
                gateway_status_text = "🔌 🟡"  # Running but API not ready
            else:
                gateway_status_text = "🔌 ✅"  # Assume ready if not specified (backward compat)
        else:
            gateway_status_text = "🔌 ❌"  # Stopped
        if agent_running:
            keyboard.append([
                InlineKeyboardButton("⏹️ Stop", callback_data='stop_agent'),
                InlineKeyboardButton("🔄 Restart", callback_data='restart_agent'),
                InlineKeyboardButton(gateway_status_text, callback_data='gateway_status'),
                InlineKeyboardButton("🔄", callback_data='status'),
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("▶️ Start Agent", callback_data='start_agent'),
                InlineKeyboardButton(gateway_status_text, callback_data='gateway_status'),
                InlineKeyboardButton("🔄", callback_data='status'),
            ])
        
        # Row 2: Quick Actions (most common monitoring needs)
        keyboard.append([
            InlineKeyboardButton("🆕 Last Signal", callback_data='last_signal'),
            InlineKeyboardButton("📊 Active", callback_data='active_trades'),
            InlineKeyboardButton("📈 Activity", callback_data='activity'),
        ])
        
        # Row 3: Signals + Performance (primary monitoring)
        keyboard.append([
            InlineKeyboardButton("🔔 Signals", callback_data='signals'),
            InlineKeyboardButton("📈 Performance", callback_data='performance'),
        ])
        
        # Row 4: System status
        keyboard.append([
            InlineKeyboardButton("🛡 Data Quality", callback_data='data_quality'),
            InlineKeyboardButton("💚 Health", callback_data='health'),
        ])
        
        # Row 5: Secondary (config, backtest, help)
        keyboard.append([
            InlineKeyboardButton("⚙️ Config", callback_data='config'),
            InlineKeyboardButton("📉 Backtest", callback_data='backtest'),
            InlineKeyboardButton("❓ Help", callback_data='help'),
        ])
        
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

    def _get_confirm_buttons(
        self,
        action: str,
        cancel_callback: str = "data_quality",
    ) -> InlineKeyboardMarkup:
        """Generic confirm buttons for dangerous operations."""
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=f"do:{action}"),
                InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _format_confirm_message(self, action: str) -> str:
        """Format confirm message for a dangerous operation."""
        if action == "restart_agent":
            return (
                "⚠️ *Confirm: Restart Agent*\n\n"
                "This will *stop* and then *start* the NQ Agent service.\n"
                "You may miss signals during the restart.\n\n"
                "Proceed?"
            )
        if action == "restart_gateway":
            return (
                "⚠️ *Confirm: Restart Gateway*\n\n"
                "This will *stop* and then *start* the IBKR Gateway.\n"
                "The gateway may take 60–120s to become API-ready.\n\n"
                "Proceed?"
            )
        return (
            "⚠️ *Confirm Action*\n\n"
            f"Proceed with: `{action}`?"
        )

    async def _run_confirmed_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
    ) -> None:
        """Execute a confirmed operation and report results."""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        if action == "restart_agent":
            await self._send_message_or_edit(
                update,
                context,
                "🔄 Restarting *Agent*...\n\n"
                "Stopping service, then starting again. This should take ~10–20s.",
                reply_markup=None,
            )
            stop_result = await self.service_controller.stop_agent()
            await asyncio.sleep(2)
            start_result = await self.service_controller.start_agent(background=True)

            message = "🔄 *Restart Agent Complete*\n\n"
            message += f"*Stop:* {stop_result.get('message', 'N/A')}\n"
            message += f"*Start:* {start_result.get('message', 'N/A')}\n"
            if start_result.get("details"):
                message += f"\n{start_result['details']}"

            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🛡 Data Quality", callback_data="data_quality"),
                    InlineKeyboardButton("🏠 Main Menu", callback_data="start"),
                ],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return

        if action == "restart_gateway":
            await self._send_message_or_edit(
                update,
                context,
                "🔄 Restarting *Gateway*...\n\n"
                "Stopping gateway, then starting again. This can take up to ~2 minutes.",
                reply_markup=None,
            )
            stop_result = await self.service_controller.stop_gateway()
            await asyncio.sleep(2)
            start_result = await self.service_controller.start_gateway()

            message = "🔄 *Restart Gateway Complete*\n\n"
            message += f"*Stop:* {stop_result.get('message', 'N/A')}\n"
            message += f"*Start:* {start_result.get('message', 'N/A')}\n"
            if start_result.get("details"):
                message += f"\n{start_result['details']}"

            reply_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🛡 Data Quality", callback_data="data_quality"),
                    InlineKeyboardButton("🔌 Gateway Status", callback_data="gateway_status"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")],
            ])
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
            return

        await self._send_message_or_edit(
            update,
            context,
            f"❌ Unknown confirmed action: `{action}`",
            reply_markup=self._get_back_to_menu_button(),
        )
    
    async def _send_message_or_edit(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "Markdown",
    ):
        """
        Helper to send message for commands or edit for callbacks.
        
        Includes Markdown parse fallback: if Markdown parsing fails, retries
        as plain text to ensure the UI never fails silently due to formatting.
        """
        async def _try_send(text: str, mode: str | None) -> bool:
            """Try to send/edit with given parse mode. Returns True on success."""
            try:
                if update.callback_query:
                    try:
                        await update.callback_query.edit_message_text(
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.debug(f"Edited message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                        return True
                    except Exception as e:
                        error_str = str(e).lower()
                        # Check for Markdown parsing errors
                        if "parse entities" in error_str or "can't parse" in error_str:
                            raise  # Propagate to trigger fallback
                        # If edit fails for other reasons (e.g., message unchanged), send new message
                        logger.debug(f"Could not edit message, sending new: {e}")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.debug(f"Sent new message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                        return True
                else:
                    if update.message:
                        await update.message.reply_text(
                            text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.info(f"Sent message with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows to chat {update.effective_chat.id}")
                        return True
                    else:
                        # Fallback: send directly via bot
                        logger.warning("No update.message, sending directly via bot")
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=mode,
                        )
                        logger.info(f"Sent message directly with {len(reply_markup.inline_keyboard) if reply_markup else 0} button rows")
                        return True
            except Exception as e:
                error_str = str(e).lower()
                if "parse entities" in error_str or "can't parse" in error_str:
                    raise  # Propagate Markdown errors for fallback handling
                logger.error(f"Error sending message: {e}", exc_info=True)
                return False
            return False

        try:
            # First attempt with requested parse mode
            if await _try_send(message, parse_mode):
                return
        except Exception as e:
            error_str = str(e).lower()
            if "parse entities" in error_str or "can't parse" in error_str:
                # Markdown parsing error - fallback to plain text
                logger.warning(f"Markdown parsing error, retrying as plain text: {e}")
                try:
                    # Strip Markdown formatting and retry
                    plain_message = message.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
                    if await _try_send(plain_message, None):
                        return
                except Exception as e2:
                    logger.error(f"Plain text fallback also failed: {e2}")
        
        # Final fallback: try to send error message without markup
        try:
            error_msg = f"❌ Error sending message (see logs for details)"
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
        elif callback_data.startswith("performance_export:"):
            kind = callback_data.split("performance_export:", 1)[1].strip()
            await self._handle_performance_export(update, context, kind)
        elif callback_data == 'signals':
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:page:"):
            action = callback_data.split("signals:page:", 1)[1].strip()
            if hasattr(context, "user_data"):
                try:
                    cur = int(context.user_data.get("signals_page", 0) or 0)
                except Exception:
                    cur = 0
                if action == "older":
                    cur += 1
                elif action == "newer":
                    cur = max(0, cur - 1)
                elif action == "newest":
                    cur = 0
                context.user_data["signals_page"] = cur
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:setdir:"):
            if hasattr(context, "user_data"):
                context.user_data["signals_dir"] = callback_data.split("signals:setdir:", 1)[1]
                context.user_data["signals_page"] = 0
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:setconf:"):
            if hasattr(context, "user_data"):
                raw = callback_data.split("signals:setconf:", 1)[1]
                try:
                    context.user_data["signals_min_conf"] = float(raw)
                except Exception:
                    context.user_data["signals_min_conf"] = 0.0
                context.user_data["signals_page"] = 0
            await self._handle_signals(update, context)
        elif callback_data.startswith("signals:settype:"):
            if hasattr(context, "user_data"):
                context.user_data["signals_type"] = callback_data.split("signals:settype:", 1)[1]
                context.user_data["signals_page"] = 0
            await self._handle_signals(update, context)
        elif callback_data == "signals:noop":
            # Noop callback for UI separator buttons - just acknowledge
            pass
        elif callback_data == 'config':
            await self._handle_config(update, context)
        elif callback_data == 'health':
            await self._handle_health(update, context)
        elif callback_data == 'activity':
            await self._handle_activity(update, context)
        elif callback_data == 'data_quality':
            await self._handle_data_quality(update, context)
        elif callback_data == 'data_quality:diagnose':
            await self._handle_data_quality(update, context, diagnose=True)
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
        elif callback_data == 'restart_agent':
            # Route menu restart button through confirm flow
            message = self._format_confirm_message("restart_agent")
            reply_markup = self._get_confirm_buttons("restart_agent", cancel_callback="data_quality")
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
        elif callback_data == 'start' or callback_data == 'main_menu':
            # Main menu - always return to start
            await self._handle_start(update, context)
        elif callback_data == 'help':
            await self._handle_help(update, context)
        elif callback_data == 'glossary':
            await self._handle_glossary(update, context)
        elif callback_data.startswith('glossary_'):
            # Handle glossary drill-down buttons
            term = callback_data.replace('glossary_', '')
            # Simulate args for the glossary handler
            context.args = [term]
            await self._handle_glossary(update, context)
            context.args = []  # Reset
        elif callback_data == 'chart':
            await self._handle_chart(update, context)
        elif callback_data == 'chart_12h':
            context.args = ['12']
            await self._handle_chart(update, context)
            context.args = []
        elif callback_data == 'chart_16h':
            context.args = ['16']
            await self._handle_chart(update, context)
            context.args = []
        elif callback_data == 'chart_24h':
            context.args = ['24']
            await self._handle_chart(update, context)
            context.args = []
        elif callback_data == 'last_signal':
            await self._handle_last_signal(update, context)
        elif callback_data == 'active_trades':
            await self._handle_active_trades(update, context)
        elif callback_data == 'test_signal':
            await self._handle_test_signal(update, context)
        elif callback_data == 'backtest':
            await self._handle_backtest(update, context)
        elif callback_data.startswith("backtest_export:"):
            kind = callback_data.split("backtest_export:", 1)[1].strip()
            await self._handle_backtest_export(update, context, kind)
        elif callback_data.startswith('backtest_setmode_'):
            # Toggle backtest mode (5m recommended vs 1m legacy)
            mode = callback_data.replace('backtest_setmode_', '')
            if mode not in ("5m", "1m"):
                mode = "5m"
            if hasattr(context, "user_data"):
                context.user_data["backtest_mode"] = mode
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith("backtest_setpos_"):
            # Set position size (contracts) for backtest simulation
            try:
                pos = int(callback_data.replace("backtest_setpos_", ""))
            except Exception:
                pos = 5
            if pos not in (1, 5, 10):
                pos = 5
            if hasattr(context, "user_data"):
                context.user_data["backtest_contracts"] = pos
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith("backtest_setslip_"):
            # Set slippage ticks for backtest simulation
            raw = callback_data.replace("backtest_setslip_", "")
            try:
                slip = float(raw)
            except Exception:
                slip = 0.5
            if slip not in (0.5, 1.0):
                slip = 0.5
            if hasattr(context, "user_data"):
                context.user_data["backtest_slippage_ticks"] = slip
            await self._handle_backtest(update, context, weeks=None)
        elif callback_data.startswith('backtest_'):
            # Handle backtest duration selection (backtest_1w, backtest_2w, etc.)
            try:
                weeks_str = callback_data.replace('backtest_', '').replace('w', '')
                weeks = int(weeks_str)
                if 1 <= weeks <= 6:
                    await self._handle_backtest(update, context, weeks=weeks)
                else:
                    await self._send_message_or_edit(
                        update, context,
                        f"❌ Invalid duration: {weeks} weeks. Please select 1-6 weeks.",
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
        elif callback_data.startswith('signal_detail_'):
            signal_id_prefix = callback_data.replace('signal_detail_', '')
            await self._handle_signal_detail(update, context, signal_id_prefix)
        elif callback_data.startswith('confirm:'):
            action = callback_data.replace('confirm:', '', 1).strip()
            message = self._format_confirm_message(action)
            reply_markup = self._get_confirm_buttons(action, cancel_callback="data_quality")
            await self._send_message_or_edit(update, context, message, reply_markup=reply_markup)
        elif callback_data.startswith('do:'):
            action = callback_data.replace('do:', '', 1).strip()
            await self._run_confirmed_action(update, context, action)
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

    # Optional: configure market-hours overrides from config/config.yaml (disabled by default).
    # This preserves the module boundary: utils never imports config.
    try:
        from pearlalgo.config.config_loader import load_market_hours_overrides
        from pearlalgo.utils.market_hours import configure_market_hours

        holidays, early_closes = load_market_hours_overrides(validate=False)
        configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
    except Exception as e:
        logger.warning(f"Could not configure market hours overrides: {e}")
    
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



