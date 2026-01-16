"""
Telegram Command Handler for NQ Agent.

Provides simple button-based remote control interface for the trading system.

Commands:
  /start - Show main menu
  /menu - Same as /start
  /help - Show help information

Simple and intuitive nested button menu system.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_state_file, get_signals_file, parse_utc_timestamp
from pearlalgo.utils.service_controller import ServiceController
from pearlalgo.utils.telegram_alerts import (
    TelegramPrefs,
    format_home_card,
    format_pnl,
    format_signal_direction,
    safe_label,
)

try:
    from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
    from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, command handler disabled")


# ---------------------------------------------------------------------------
# Optional AI client imports (used by /ai_patch and chat mode)
# ---------------------------------------------------------------------------
try:
    from pearlalgo.utils.claude_client import (
        ANTHROPIC_AVAILABLE,
        ClaudeAPIError,
        ClaudeAPIKeyMissingError,
        ClaudeClient,
        ClaudeNotAvailableError,
    )
except Exception:  # pragma: no cover - defensive fallback for minimal environments
    ANTHROPIC_AVAILABLE = False
    ClaudeClient = None  # type: ignore[assignment]
    ClaudeAPIError = ClaudeAPIKeyMissingError = ClaudeNotAvailableError = Exception  # type: ignore[misc,assignment]


class TelegramCommandHandler:
    """Full-featured command handler for PEARLalgo trading system."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        state_dir: Optional[Path] = None,
        startup_ping: bool = True,
    ):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot required for command handler")
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.state_dir = ensure_state_dir(state_dir)
        self.exports_dir = self.state_dir / "exports"
        self._startup_ping = bool(startup_ping)
        self.application = (
            Application.builder()
            .token(bot_token)
            .post_init(self._post_init)
            .build()
        )
        self.service_controller = ServiceController()
        self._register_handlers()

    async def _post_init(self, application: Application) -> None:
        """Runs once after the Telegram application initializes."""
        # Set simple command menu
        try:
            await application.bot.set_my_commands([
                BotCommand('start', 'Show main menu'),
                BotCommand('menu', 'Show main menu'),
                BotCommand('help', 'Show help information'),
                BotCommand('settings', 'Alert preferences (charts, notifications)'),
            ])
        except Exception as e:
            logger.debug(f"Could not set bot commands: {e}")

        # Send a startup ping so users can confirm connectivity immediately.
        if self._startup_ping:
            try:
                logger.info(f"Sending startup ping to chat_id={self.chat_id}")
                keyboard = self._get_main_menu_keyboard()
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Try to send comprehensive status, fallback to simple message
                state = self._read_state()
                if state:
                    try:
                        message = await self._build_status_dashboard_message(state)
                        await application.bot.send_message(
                            chat_id=self.chat_id,
                            text=message,
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.warning(f"Could not send status dashboard in startup: {e}")
                        await application.bot.send_message(
                            chat_id=self.chat_id,
                            text="✅ PEARLalgo command handler is online!\n\nTap the buttons below to control the system:",
                            reply_markup=reply_markup
                        )
                else:
                    await application.bot.send_message(
                        chat_id=self.chat_id,
                        text="✅ PEARLalgo command handler is online!\n\nTap the buttons below to control the system:",
                        reply_markup=reply_markup
                    )
                logger.info("Startup ping sent")
            except Exception as e:
                # Do not crash the handler; reply_text() still works in any chat that sends commands.
                logger.warning(f"Could not send startup ping to chat_id={self.chat_id}: {e}")

    def _register_handlers(self) -> None:
        # Main menu commands
        self.application.add_handler(CommandHandler("start", self.handle_start))
        self.application.add_handler(CommandHandler("menu", self.handle_start))
        self.application.add_handler(CommandHandler("help", self.handle_help))
        self.application.add_handler(CommandHandler("settings", self.handle_settings))

        # Callback query handler for button presses
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    def _get_main_menu_keyboard(self) -> list:
        """Get the main menu keyboard layout."""
        # Show quick preview of positions if available
        state = self._read_state()
        has_active = False
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            has_active = positions > 0 or active_trades > 0

        return [
            # Row 1: Core Trading Functions
            [
                InlineKeyboardButton("🎯 Signals & Trades", callback_data="menu:signals"),
                InlineKeyboardButton("📊 Performance", callback_data="menu:performance"),
            ],
            # Row 2: System Management
            [
                InlineKeyboardButton("📡 Status" + (" 🎯" if has_active else ""), callback_data="menu:status"),
                InlineKeyboardButton("⚙️ System Control", callback_data="menu:system"),
            ],
            # Row 3: Advanced Features
            [
                InlineKeyboardButton("🤖 AI & Analysis", callback_data="menu:analysis"),
                InlineKeyboardButton("🤖 Bots", callback_data="menu:bots"),
            ],
            # Row 4: Settings + Help
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
                InlineKeyboardButton("❓ Help", callback_data="menu:help"),
            ],
        ]

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send the comprehensive status dashboard with menu buttons."""
        if not update.message:
            return
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        logger.info("Received /start or /menu command - showing status dashboard")
        
        # Get comprehensive status
        state = self._read_state()
        keyboard = self._get_main_menu_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)

        if state:
            # Show comprehensive status dashboard
            try:
                await self._send_status_dashboard(update.message, reply_markup)
                return
            except Exception as e:
                logger.error(f"Error sending status dashboard: {e}", exc_info=True)
                # Fallback to simple menu
                text = "🎯 PEARLalgo Trading System\n\nSelect an option:"
        else:
            # No state available, show simple menu
            text = "🎯 PEARLalgo Trading System\n\n❌ No state data available.\n\nSelect an option:"
        await update.message.reply_text(text, reply_markup=reply_markup)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show help information."""
        if not update.message:
            return
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        logger.info("Received /help command")

        text = (
            "🎯 PEARLalgo Command Handler\n\n"
            "Available commands:\n"
            "/start - Show main menu\n"
            "/menu - Show main menu\n"
            "/help - Show this help message\n"
            "/settings - Alert preferences (charts, notifications)\n\n"
            "Use the Bots menu to start/stop the Pearl Bot service."
        )
        await update.message.reply_text(text)

    async def handle_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show Telegram alert preferences (charts, notifications, UI)."""
        if not update.message:
            return
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        logger.info("Received /settings command")

        prefs = TelegramPrefs(state_dir=self.state_dir)
        auto_chart = bool(prefs.get("auto_chart_on_signal", False))
        interval_notifications = bool(prefs.get("interval_notifications", True))
        dashboard_buttons = bool(prefs.get("dashboard_buttons", False))
        signal_detail_expanded = bool(prefs.get("signal_detail_expanded", False))

        def _onoff(v: bool) -> str:
            return "ON" if v else "OFF"

        text = (
            "⚙️ Settings\n\n"
            f"📈 Auto-Chart on Signal: {_onoff(auto_chart)}\n"
            f"🕐 Interval Notifications: {_onoff(interval_notifications)}\n"
            f"🔘 Dashboard Buttons: {_onoff(dashboard_buttons)}\n"
            f"🔍 Expanded Signal Details: {_onoff(signal_detail_expanded)}\n\n"
            "Tap a button to toggle:"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    f"📈 Auto-Chart: {_onoff(auto_chart)}",
                    callback_data="action:toggle_pref:auto_chart_on_signal",
                ),
                InlineKeyboardButton(
                    f"🕐 Interval: {_onoff(interval_notifications)}",
                    callback_data="action:toggle_pref:interval_notifications",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🔘 Buttons: {_onoff(dashboard_buttons)}",
                    callback_data="action:toggle_pref:dashboard_buttons",
                ),
                InlineKeyboardButton(
                    f"🔍 Details: {_onoff(signal_detail_expanded)}",
                    callback_data="action:toggle_pref:signal_detail_expanded",
                ),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    def _read_state(self) -> Optional[dict]:
        """Read current state from state.json."""
        state_file = get_state_file(self.state_dir)
        if not state_file.exists():
            return None
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read state file: {e}")
            return None

    def _read_recent_signals(self, limit: int = 10) -> list:
        """Read recent signals from signals.jsonl."""
        signals_file = get_signals_file(self.state_dir)
        if not signals_file.exists():
            return []
        try:
            signals = []
            with open(signals_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            signal = json.loads(line)
                            signals.append(signal)
                        except json.JSONDecodeError:
                            continue
            # Return most recent signals first
            return signals[-limit:] if len(signals) > limit else signals
        except Exception as e:
            logger.warning(f"Failed to read signals file: {e}")
            return []

    def _read_latest_metrics(self) -> Optional[dict]:
        if not self.exports_dir.exists():
            return None
        metrics_files = sorted(
            self.exports_dir.glob("performance_*_metrics.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not metrics_files:
            return None
        try:
            return json.loads(metrics_files[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    def _read_strategy_selection(self) -> Optional[dict]:
        if not self.exports_dir.exists():
            return None
        candidates = list(self.exports_dir.glob("strategy_selection_*.json"))
        if not candidates:
            latest = self.exports_dir / "strategy_selection_latest.json"
            candidates = [latest] if latest.exists() else []
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        try:
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    async def handle_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        logger.info("Received /analyze command")
        metrics = self._read_latest_metrics()
        selection = self._read_strategy_selection()

        lines = ["AI Strategy Report", f"Generated: {datetime.now(timezone.utc).isoformat()}"]

        if metrics:
            lines.extend(
                [
                    "",
                    "Performance (latest export):",
                    f"- Trades: {metrics.get('exited_signals', 0)}",
                    f"- Win rate: {metrics.get('win_rate', 0.0):.1%}",
                    f"- Total PnL: {metrics.get('total_pnl', 0.0):.2f}",
                    f"- Avg PnL: {metrics.get('avg_pnl', 0.0):.2f}",
                ]
            )
        else:
            lines.append("")
            lines.append("No performance metrics export found.")

        if selection:
            top = None
            ranked = selection.get("ranked_by_type_direction", [])
            if ranked:
                top = ranked[0]
            lines.append("")
            lines.append("Strategy recommendation:")
            if top:
                lines.append(f"- Top: {top.get('key')} (score {top.get('score', 0.0):.2f})")
                lines.append(f"- Trades: {top.get('count', 0)} | WR {top.get('win_rate', 0.0):.1%}")
                lines.append(f"- Max DD: {top.get('max_drawdown', 0.0):.2f}")
            else:
                lines.append("- No ranked strategy found in selection report.")
        else:
            lines.append("")
            lines.append("No strategy selection report found. Run:")
            lines.append("  python3 scripts/backtesting/strategy_selection.py")

        await update.message.reply_text("\n".join(lines))

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button callback queries."""
        query = update.callback_query
        if not query:
            return

        await query.answer()  # Acknowledge the callback
        if not await self._check_authorized(update):
            try:
                await query.edit_message_text("❌ Unauthorized access")
            except Exception:
                pass
            return
        callback_data = query.data
        logger.info(f"Received callback: {callback_data}")

        # Parse callback data (format: "menu:action" or "action")
        if callback_data.startswith("menu:"):
            action = callback_data[5:]  # Remove "menu:" prefix
            await self._handle_menu_action(query, action)
        elif callback_data == "back":
            # Return to main menu
            await self._show_main_menu(query)
        else:
            # Handle other actions (from notifier, etc.)
            await self._handle_action(query, callback_data)

    async def _handle_menu_action(self, query: CallbackQuery, action: str) -> None:
        """Handle menu button actions."""
        if action == "status":
            await self._show_status_menu(query)
        elif action == "signals":
            await self._show_signals_menu(query)
        elif action == "performance":
            await self._show_performance_menu(query)
        elif action == "bots":
            await self._show_bots_menu(query)
        elif action == "analysis":
            await self._show_analysis_menu(query)
        elif action == "system":
            await self._show_system_menu(query)
        elif action == "settings":
            await self._show_settings_menu(query)
        elif action == "help":
            await self._show_help(query)
        else:
            await query.edit_message_text(f"Unknown action: {action}")

    async def _show_main_menu(self, query: CallbackQuery) -> None:
        """Show the comprehensive status dashboard with menu buttons."""
        keyboard = self._get_main_menu_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        state = self._read_state()
        if state:
            try:
                message_text = await self._build_status_dashboard_message(state)
                await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Error showing main menu status: {e}", exc_info=True)
                text = "🎯 PEARLalgo Trading System\n\nSelect an option:"
                await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            text = "🎯 PEARLalgo Trading System\n\n❌ No state data available.\n\nSelect an option:"
            await query.edit_message_text(text, reply_markup=reply_markup)

    async def _show_status_menu(self, query: CallbackQuery) -> None:
        """Show status submenu."""
        # Show quick status preview
        state = self._read_state()
        preview = ""
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            latest_price = state.get("latest_price")
            
            preview = "\n"
            if latest_price:
                preview += f"💰 Price: ${latest_price:,.2f}\n"
            preview += f"🎯 Positions: {positions} | Active: {active_trades}\n"
        
            keyboard = [
            [InlineKeyboardButton("📊 System Status", callback_data="action:system_status")],
            [
                InlineKeyboardButton("🎯 Positions & Trades", callback_data="action:active_trades"),
                InlineKeyboardButton("🔌 Gateway", callback_data="action:gateway_status"),
            ],
            [
                InlineKeyboardButton("📡 Connection", callback_data="action:connection_status"),
                InlineKeyboardButton("💾 Data Quality", callback_data="action:data_quality"),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"📊 Status & Monitoring{preview}\nSelect an option:", reply_markup=reply_markup)

    async def _show_signals_menu(self, query: CallbackQuery) -> None:
        """Show signals & trades submenu."""
        keyboard = [
            # Row 1: Current Activity
            [
                InlineKeyboardButton("🎯 Recent Signals", callback_data="action:recent_signals"),
                InlineKeyboardButton("📋 Active Trades", callback_data="action:active_trades"),
            ],
            # Row 2: Historical Data
            [
                InlineKeyboardButton("📊 Signal History", callback_data="action:signal_history"),
                InlineKeyboardButton("🔍 Signal Details", callback_data="action:signal_details"),
            ],
            # Row 3: Quick Actions
            [
                InlineKeyboardButton("🚫 Close All Trades", callback_data="action:close_all_trades"),
                InlineKeyboardButton("🔄 Refresh", callback_data="menu:signals"),
            ],
            # Row 4: Navigation
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🎯 Signals & Trades\n\nSelect an option:", reply_markup=reply_markup)

    async def _show_performance_menu(self, query: CallbackQuery) -> None:
        """Show performance submenu."""
        keyboard = [
            # Row 1: Core Metrics
            [
                InlineKeyboardButton("📈 Performance Metrics", callback_data="action:performance_metrics"),
                InlineKeyboardButton("💰 P&L Overview", callback_data="action:pnl_overview"),
            ],
            # Row 2: Time-based Reports
            [
                InlineKeyboardButton("📊 Daily Summary", callback_data="action:daily_summary"),
                InlineKeyboardButton("📉 Weekly Summary", callback_data="action:weekly_summary"),
            ],
            # Row 3: Actions
            [
                InlineKeyboardButton("🔄 Reset Stats", callback_data="action:reset_performance"),
                InlineKeyboardButton("📋 Export Report", callback_data="action:export_performance"),
            ],
            # Row 4: Navigation
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📊 Performance\n\nSelect an option:", reply_markup=reply_markup)

    async def _show_bots_menu(self, query: CallbackQuery) -> None:
        """Show single Pearl Bot control menu."""
        agent_status = {"running": False, "message": "Unknown"}
        gateway_status = {"process_running": False, "port_listening": False}

        try:
            sc = getattr(self, "service_controller", None)
            if sc is not None:
                agent_status = sc.get_agent_status() or agent_status
                gateway_status = sc.get_gateway_status() or gateway_status
        except Exception as e:
            logger.warning(f"Could not load bot status: {e}")

        running = bool(agent_status.get("running"))
        agent_line = "🟢 RUNNING" if running else "🔴 STOPPED"
        gateway_ready = bool(gateway_status.get("process_running")) and bool(gateway_status.get("port_listening"))
        gateway_line = "🟢 READY" if gateway_ready else "🔴 NOT READY"

        text = (
            "🤖 *Pearl Bot*\n\n"
            f"Agent Service: {agent_line}\n"
            f"Gateway: {gateway_line}\n\n"
            "Control the live trading service with the buttons below."
        )

        keyboard = [
            [
                InlineKeyboardButton("🚀 Start Pearl Bot", callback_data="action:start_agent"),
                InlineKeyboardButton("🛑 Stop Pearl Bot", callback_data="action:stop_agent"),
            ],
            [
                InlineKeyboardButton("🔄 Restart Pearl Bot", callback_data="action:restart_agent"),
                InlineKeyboardButton("🔄 Refresh", callback_data="menu:bots"),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _show_analysis_menu(self, query: CallbackQuery) -> None:
        """Show AI & analysis submenu."""
        keyboard = [
            # Row 1: Strategy Analysis
            [
                InlineKeyboardButton("🔍 Strategy Analysis", callback_data="action:strategy_analysis"),
                InlineKeyboardButton("📊 Trade Analysis", callback_data="action:trade_analysis"),
            ],
            # Row 2: Signal Analysis
            [
                InlineKeyboardButton("📈 Signal Analysis", callback_data="action:signal_analysis"),
                InlineKeyboardButton("🎯 AI Analysis", callback_data="action:ai_analysis"),
            ],
            # Row 3: AI Features
            [
                InlineKeyboardButton("🤖 AI Strategy Review", callback_data="action:ai_strategy_review"),
                InlineKeyboardButton("💡 AI Config Tips", callback_data="action:ai_config_suggestions"),
            ],
            # Row 4: Navigation
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🤖 AI & Analysis\n\nSelect an option:", reply_markup=reply_markup)

    async def _show_system_menu(self, query: CallbackQuery) -> None:
        """Show system control submenu."""
        keyboard = [
            # Row 1: Trading Agent Control
            [
                InlineKeyboardButton("🚀 Start Agent", callback_data="action:start_agent"),
                InlineKeyboardButton("🛑 Stop Agent", callback_data="action:stop_agent"),
            ],
            # Row 2: Gateway Control
            [
                InlineKeyboardButton("🔌 Restart Gateway", callback_data="action:restart_gateway"),
                InlineKeyboardButton("🔍 Gateway Status", callback_data="action:gateway_status"),
            ],
            # Row 3: System Management
            [
                InlineKeyboardButton("🔄 Reset Challenge", callback_data="action:reset_challenge"),
                InlineKeyboardButton("🧹 Clear Cache", callback_data="action:clear_cache"),
            ],
            # Row 4: Configuration & Logs
            [
                InlineKeyboardButton("⚙️ Configuration", callback_data="action:config"),
                InlineKeyboardButton("📋 Logs", callback_data="action:logs"),
            ],
            # Row 5: Emergency
            [
                InlineKeyboardButton("🚨 Emergency Stop", callback_data="action:emergency_stop"),
            ],
            # Row 6: Navigation
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("⚙️ System Control\n\n⚠️ Use with caution - these actions affect live trading:", reply_markup=reply_markup)


    async def _show_settings_menu(self, query: CallbackQuery) -> None:
        """Show settings submenu (Telegram alert preferences)."""
        prefs = TelegramPrefs(state_dir=self.state_dir)
        auto_chart = bool(prefs.get("auto_chart_on_signal", False))
        interval_notifications = bool(prefs.get("interval_notifications", True))
        dashboard_buttons = bool(prefs.get("dashboard_buttons", False))
        signal_detail_expanded = bool(prefs.get("signal_detail_expanded", False))

        def _onoff(v: bool) -> str:
            return "ON" if v else "OFF"

        text = (
            "⚙️ Settings\n\n"
            f"📈 Auto-Chart on Signal: {_onoff(auto_chart)}\n"
            f"🕐 Interval Notifications: {_onoff(interval_notifications)}\n"
            f"🔘 Dashboard Buttons: {_onoff(dashboard_buttons)}\n"
            f"🔍 Expanded Signal Details: {_onoff(signal_detail_expanded)}\n\n"
            "Tap a button to toggle:"
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    f"📈 Auto-Chart: {_onoff(auto_chart)}",
                    callback_data="action:toggle_pref:auto_chart_on_signal",
                ),
                InlineKeyboardButton(
                    f"🕐 Interval: {_onoff(interval_notifications)}",
                    callback_data="action:toggle_pref:interval_notifications",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🔘 Buttons: {_onoff(dashboard_buttons)}",
                    callback_data="action:toggle_pref:dashboard_buttons",
                ),
                InlineKeyboardButton(
                    f"🔍 Details: {_onoff(signal_detail_expanded)}",
                    callback_data="action:toggle_pref:signal_detail_expanded",
                ),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


    async def _show_help(self, query: CallbackQuery) -> None:
        """Show help information."""
        help_text = (
            "🎯 PEARLalgo Command Handler\n\n"
            "*Quick Commands:*\n"
            "/start - Show main menu\n"
            "/menu - Show main menu\n"
            "/help - Show this help\n\n"
            "/settings - Alert preferences (charts, notifications)\n\n"
            "*Menu Structure:*\n"
            "🎯 Signals & Trades - View and manage trading activity\n"
            "📊 Performance - Performance metrics and reports\n"
            "📡 Status - System health and connection status\n"
            "⚙️ System Control - Start/stop services and emergency controls\n"
            "⚙️ Settings - Charts + notification preferences\n"
            "🤖 AI & Analysis - AI-powered insights and analysis\n"
            "🤖 Bots - Start/stop the Pearl Bot service\n\n"
            "*Quick Tips:*\n"
            "• Use 'Back to Menu' to return to main menu\n"
            "• Status indicators show active positions/trades\n"
            "• Emergency Stop closes all positions immediately\n"
            "• All actions are logged for audit trail"
        )
        keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_action(self, query: CallbackQuery, action: str) -> None:
        """Handle action button presses."""
        if action.startswith("action:"):
            action_type = action[7:]  # Remove "action:" prefix

            # Preferences toggles (settings menu)
            if action_type.startswith("toggle_pref:"):
                pref_key = action_type[len("toggle_pref:") :]
                prefs = TelegramPrefs(state_dir=self.state_dir)
                try:
                    current = prefs.get(pref_key)
                    if isinstance(current, bool):
                        prefs.set(pref_key, not current)
                except Exception:
                    pass
                await self._show_settings_menu(query)
                return
            
            keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if action_type == "system_status":
                await self._handle_system_status(query, reply_markup)
            elif action_type == "gateway_status":
                await self._handle_gateway_status(query, reply_markup)
            elif action_type == "connection_status":
                await self._handle_connection_status(query, reply_markup)
            elif action_type == "data_quality":
                await self._handle_data_quality(query, reply_markup)
            elif action_type == "recent_signals":
                await self._handle_recent_signals(query, reply_markup)
            elif action_type == "active_trades":
                await self._handle_active_trades(query, reply_markup)
            elif action_type == "signal_history":
                await self._handle_signal_history(query, reply_markup)
            elif action_type == "signal_details":
                await query.edit_message_text("🔍 Signal Details\n\nUse /signal <id> to view details", reply_markup=reply_markup)
            elif action_type == "performance_metrics":
                await query.edit_message_text("📈 Performance Metrics: Loading...\n\nFeature coming soon.", reply_markup=reply_markup)
                # TODO: Implement actual metrics retrieval
            elif action_type == "daily_summary":
                await query.edit_message_text("📊 Daily Summary: Loading...\n\nFeature coming soon.", reply_markup=reply_markup)
                # TODO: Implement actual daily summary
            elif action_type == "weekly_summary":
                await query.edit_message_text("📉 Weekly Summary: Loading...\n\nFeature coming soon.", reply_markup=reply_markup)
                # TODO: Implement actual weekly summary
            elif action_type == "pnl_overview":
                await query.edit_message_text("💰 P&L Overview: Loading...\n\nFeature coming soon.", reply_markup=reply_markup)
                # TODO: Implement actual P&L overview
            elif action_type == "strategy_analysis":
                metrics = self._read_latest_metrics()
                text = "🔍 Strategy Analysis\n\n"
                if metrics:
                    text += f"Trades: {metrics.get('exited_signals', 0)}\n"
                    text += f"Win Rate: {metrics.get('win_rate', 0.0):.1%}\n"
                    text += f"Total P&L: {metrics.get('total_pnl', 0.0):.2f}\n"
                else:
                    text += "No metrics available."
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "trade_analysis":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("📊 Trade Analysis: Feature coming soon...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "signal_analysis":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("📈 Signal Analysis: Loading...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "ai_analysis":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("🎯 AI Analysis: Loading...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "ai_strategy_review":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("🤖 AI Strategy Review: Analyzing...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "ai_signal_analysis":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("📋 AI Signal Analysis: Analyzing...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "ai_system_analysis":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("🔧 AI System Analysis: Analyzing...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "ai_config_suggestions":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("💡 AI Config Suggestions: Generating...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "restart_agent":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Restart", callback_data="confirm:restart_agent")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text("🔄 Restart Agent\n\n⚠️ This will restart the NQ Agent service.\n\nAre you sure?", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "stop_agent":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Stop", callback_data="confirm:stop_agent")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text("🛑 Stop Agent\n\n⚠️ This will stop the NQ Agent service.\n\nAre you sure?", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "start_agent":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    result = await sc.start_agent(background=True)
                    text = result.get("message", "Started agent.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "restart_gateway":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Restart", callback_data="confirm:restart_gateway")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text("🔌 Restart Gateway\n\n⚠️ This will restart the IBKR Gateway.\n\nAre you sure?", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "config":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("⚙️ Configuration: Loading...\n\nFeature coming soon.", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "logs":
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text("📋 Logs: Feature coming soon...", reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "reset_challenge":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Reset", callback_data="confirm:reset_challenge")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text(
                    "🔄 Reset Challenge\n\n"
                    "⚠️ This will start a fresh 50k Challenge attempt.\n\n"
                    "Metrics:\n"
                    "• Starting Balance: $50,000\n"
                    "• Profit Target: +$3,000\n"
                    "• Max Drawdown: -$2,000\n\n"
                    "Current attempt will be saved to history.\n\n"
                    "Are you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text(f"Action not yet implemented: {action_type}", reply_markup=InlineKeyboardMarkup(keyboard))
        elif action.startswith("toggle_strategy:"):
            strategy_name = action[16:]  # Remove "toggle_strategy:" prefix
            await self._toggle_strategy(query, strategy_name)
        elif action.startswith("confirm:"):
            confirm_action = action[8:]  # Remove "confirm:" prefix
            keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if confirm_action == "restart_agent":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    result = await sc.restart_agent(background=True)
                    text = result.get("message", "Restarted agent.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif confirm_action == "stop_agent":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    result = await sc.stop_agent()
                    text = result.get("message", "Stopped agent.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif confirm_action == "restart_gateway":
                # TODO: Implement actual gateway restart
                await query.edit_message_text("🔌 Restarting IBKR Gateway...\n\nPlease check status.", reply_markup=reply_markup)
            elif confirm_action == "reset_challenge":
                try:
                    from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker = ChallengeTracker(state_dir=self.state_dir)
                    new_attempt = challenge_tracker.manual_reset(reason="telegram_reset")
                    
                    keyboard = [
                        [InlineKeyboardButton("🔄 Refresh Status", callback_data="menu:status")],
                        [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                    ]
                    await query.edit_message_text(
                        f"✅ Challenge Reset Complete\n\n"
                        f"New attempt started: #{new_attempt.attempt_id}\n\n"
                        f"Starting Balance: ${new_attempt.starting_balance:,.2f}\n"
                        f"Profit Target: +$3,000\n"
                        f"Max Drawdown: -$2,000\n\n"
                        f"Previous attempt saved to history.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    logger.info(f"Challenge reset via Telegram: new attempt #{new_attempt.attempt_id}")
                except Exception as e:
                    logger.error(f"Error resetting challenge: {e}", exc_info=True)
                    await query.edit_message_text(
                        f"❌ Error resetting challenge: {e}\n\nPlease check logs.",
                        reply_markup=reply_markup
                    )
            else:
                await query.edit_message_text(f"Unknown confirmation action: {confirm_action}", reply_markup=reply_markup)

    async def _toggle_strategy(self, query: CallbackQuery, strategy_name: str) -> None:
        """Toggle a strategy on/off by updating config.yaml."""
        config_path = Path("config/config.yaml")
        if not config_path.exists():
            keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
            await query.edit_message_text(
                f"❌ Config file not found: {config_path}\n\nCannot modify strategies.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        try:
            import yaml
            
            # Read current config
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            
            # Ensure strategy section exists
            if "strategy" not in config:
                config["strategy"] = {}
            
            strategy_config = config["strategy"]
            enabled_signals = list(strategy_config.get("enabled_signals", []))
            disabled_signals = list(strategy_config.get("disabled_signals", []))
            
            # Toggle the strategy
            if strategy_name in enabled_signals:
                # Disable it
                enabled_signals.remove(strategy_name)
                if strategy_name not in disabled_signals:
                    disabled_signals.append(strategy_name)
                action = "disabled"
            elif strategy_name in disabled_signals:
                # Enable it
                disabled_signals.remove(strategy_name)
                if strategy_name not in enabled_signals:
                    enabled_signals.append(strategy_name)
                action = "enabled"
            else:
                # Not in either list, enable it
                if strategy_name not in enabled_signals:
                    enabled_signals.append(strategy_name)
                action = "enabled"
            
            # Update config
            strategy_config["enabled_signals"] = enabled_signals
            strategy_config["disabled_signals"] = disabled_signals
            config["strategy"] = strategy_config
            
            # Backup original config
            backup_path = config_path.with_suffix('.yaml.backup')
            shutil.copy2(config_path, backup_path)
            
            # Write updated config
            with open(config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
            # Show success message
            status_emoji = "🟢" if action == "enabled" else "🔴"
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Bots", callback_data="menu:bots")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            message = (
                f"{status_emoji} *Strategy {action.title()}*\n\n"
                f"Strategy: `{strategy_name}`\n\n"
                f"⚠️ *Restart the agent* for changes to take effect.\n\n"
                f"Use System menu → Restart Agent"
            )
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            logger.info(f"Strategy {strategy_name} {action} via Telegram")
            
        except Exception as e:
            logger.error(f"Error toggling strategy: {e}", exc_info=True)
            keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
            await query.edit_message_text(
                f"❌ Error updating strategy: {e}\n\nPlease check config file manually.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def _send_status_dashboard(self, message_obj, reply_markup: InlineKeyboardMarkup) -> None:
        """Send comprehensive status dashboard to a message object (not callback query)."""
        state = self._read_state()
        if not state:
            await message_obj.reply_text("❌ Could not read system state.", reply_markup=reply_markup)
            return
        
        message_text = await self._build_status_dashboard_message(state)
        await message_obj.reply_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _build_status_dashboard_message(self, state: dict) -> str:
        """Build the comprehensive status dashboard message from state."""
        try:
            # Extract data for format_home_card
            symbol = state.get("symbol", "MNQ")
            
            # Format time
            from datetime import datetime, timezone
            import pytz
            current_time = state.get("current_time")
            if not current_time:
                current_time = datetime.now(timezone.utc)
            elif isinstance(current_time, str):
                current_time = parse_utc_timestamp(current_time)
            if hasattr(current_time, 'tzinfo') and current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
            
            try:
                et_tz = pytz.timezone('US/Eastern')
                et_time = current_time.astimezone(et_tz)
                time_str = et_time.strftime("%I:%M %p ET").lstrip('0')
            except Exception:
                time_str = current_time.strftime("%H:%M UTC") if hasattr(current_time, 'strftime') else ""
            
            # Service status
            agent_running = state.get("running", False)
            paused = state.get("paused", False)
            pause_reason = state.get("pause_reason")
            
            # Gateway status
            gateway_running = True  # Assume running if we have data
            gateway_unknown = False
            
            # Market gates
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")
            
            # Activity metrics
            cycles_session = state.get("cycle_count_session")
            cycles_total = state.get("cycle_count", 0) or 0
            signals_generated = state.get("signal_count", 0) or 0
            signals_sent = state.get("signals_sent", 0) or 0
            signal_send_failures = state.get("signals_send_failures", 0) or 0
            errors = state.get("error_count", 0) or 0
            
            # Buffer
            buffer_size = state.get("buffer_size", 0) or 0
            buffer_target = state.get("buffer_size_target")
            
            # Price
            latest_price = state.get("latest_price")
            
            # Performance
            performance = state.get("performance", {})
            
            # Active trades
            active_trades_count = state.get("active_trades_count", 0) or 0
            active_trades_unrealized_pnl = state.get("active_trades_unrealized_pnl")
            active_trades_price_source = state.get("latest_price_source")
            
            # Data quality
            latest_bar = state.get("latest_bar", {})
            data_level = latest_bar.get("_data_level") if isinstance(latest_bar, dict) else None
            
            # Data age (read threshold from config)
            data_stale_threshold_minutes = 10.0  # Default
            try:
                import yaml
                config_path = Path("config/config.yaml")
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f) or {}
                        data_config = config.get("data", {})
                        data_stale_threshold_minutes = float(data_config.get("stale_data_threshold_minutes", 10.0))
            except Exception:
                pass
            
            data_age_minutes = None
            if latest_bar and isinstance(latest_bar, dict):
                timestamp = latest_bar.get("timestamp")
                if timestamp:
                    try:
                        bar_time = parse_utc_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
                        if bar_time:
                            now = datetime.now(timezone.utc)
                            if hasattr(bar_time, 'tzinfo') and bar_time.tzinfo is None:
                                bar_time = bar_time.replace(tzinfo=timezone.utc)
                            age_seconds = (now - bar_time).total_seconds()
                            data_age_minutes = age_seconds / 60
                            
                            # Only show stale warning if:
                            # 1. Agent is running (not stopped)
                            # 2. Market is open (or session is open)
                            # 3. Data is actually stale
                            if not agent_running or paused:
                                # Agent not running, stale data is expected
                                data_age_minutes = None
                            elif futures_market_open is False and strategy_session_open is False:
                                # Both market and session closed, stale data is expected
                                data_age_minutes = None
                            elif data_age_minutes and data_age_minutes <= data_stale_threshold_minutes:
                                # Data is fresh, don't show as stale
                                data_age_minutes = None
                    except Exception as e:
                        logger.debug(f"Could not calculate data age: {e}")
                        pass
            
            # Buy/Sell pressure
            buy_sell_pressure = state.get("buy_sell_pressure")
            buy_sell_pressure_raw = state.get("buy_sell_pressure_raw")
            
            # Execution status
            execution = state.get("execution", {}) or {}
            execution_enabled = execution.get("enabled", False)
            execution_armed = execution.get("armed", False)
            execution_mode = execution.get("mode")
            
            # Quiet reason and diagnostics
            quiet_reason = state.get("quiet_reason")
            signal_diagnostics = state.get("signal_diagnostics")
            
            # Last cycle time
            last_cycle_seconds = None
            last_successful_cycle = state.get("last_successful_cycle")
            if last_successful_cycle:
                try:
                    last_cycle_dt = parse_utc_timestamp(str(last_successful_cycle))
                    if last_cycle_dt:
                        if hasattr(last_cycle_dt, 'tzinfo') and last_cycle_dt.tzinfo is None:
                            last_cycle_dt = last_cycle_dt.replace(tzinfo=timezone.utc)
                        last_cycle_seconds = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
                except Exception:
                    pass
            
            # Check for challenge mode and load challenge data if available
            challenge_status = None
            challenge_per_strategy = {}
            challenge_tracker_instance = None
            
            try:
                from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker
                from pearlalgo.learning.trade_database import TradeDatabase
                
                # Always load/create challenge tracker (will create if doesn't exist)
                challenge_state_file = self.state_dir / "challenge_state.json"
                try:
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()  # Reload from file
                    challenge_status = challenge_tracker_instance.get_status_summary()
                    if not challenge_status:
                        logger.warning("Challenge tracker returned empty status summary")
                    else:
                        logger.debug(f"Challenge status loaded: {challenge_status[:100]}")
                except Exception as e:
                    logger.error(f"Error loading challenge tracker: {e}", exc_info=True)
                    challenge_tracker_instance = None
                    challenge_status = None
                
                # Also check if performance should include attempt_id
                if challenge_status and not performance.get("attempt_id"):
                    attempt_perf = challenge_tracker_instance.get_attempt_performance()
                    if attempt_perf:
                        performance = dict(performance) if performance else {}
                        performance["attempt_id"] = attempt_perf.get("attempt_id")
                
                # Calculate per-strategy challenge metrics (for current attempt)
                try:
                    db_path = self.state_dir / "trades.db"
                    if db_path.exists():
                        trade_db = TradeDatabase(db_path)
                        attempt_perf = challenge_tracker_instance.get_attempt_performance()
                        attempt_start = attempt_perf.get("attempt_started_at") if attempt_perf else None
                        
                        if attempt_start:
                            # Get trades since attempt started, grouped by strategy
                            cutoff = parse_utc_timestamp(attempt_start) if isinstance(attempt_start, str) else attempt_start
                            if cutoff:
                                # Get all trades since attempt started
                                all_trades = trade_db.get_recent_trades_by_exit(limit=10000)
                                attempt_trades = []
                                for trade in all_trades:
                                    try:
                                        exit_time = trade.get("exit_time") or trade.get("timestamp")
                                        if exit_time:
                                            trade_time = parse_utc_timestamp(exit_time) if isinstance(exit_time, str) else exit_time
                                            if trade_time:
                                                if hasattr(trade_time, 'tzinfo') and trade_time.tzinfo is None:
                                                    trade_time = trade_time.replace(tzinfo=timezone.utc)
                                                if hasattr(cutoff, 'tzinfo') and cutoff.tzinfo is None:
                                                    cutoff = cutoff.replace(tzinfo=timezone.utc)
                                                if hasattr(trade_time, '__ge__') and trade_time >= cutoff:
                                                    attempt_trades.append(trade)
                                    except Exception:
                                        pass
                                
                                # Group by signal_type and calculate challenge metrics
                                strategy_challenge = {}
                                for trade in attempt_trades:
                                    signal_type = trade.get("signal_type") or "unknown"
                                    pnl = float(trade.get("pnl", 0.0))
                                    is_win = bool(trade.get("is_win", False))
                                    
                                    if signal_type not in strategy_challenge:
                                        strategy_challenge[signal_type] = {
                                            "pnl": 0.0,
                                            "trades": 0,
                                            "wins": 0,
                                            "losses": 0,
                                        }
                                    
                                    strategy_challenge[signal_type]["pnl"] += pnl
                                    strategy_challenge[signal_type]["trades"] += 1
                                    if is_win:
                                        strategy_challenge[signal_type]["wins"] += 1
                                    else:
                                        strategy_challenge[signal_type]["losses"] += 1
                                
                                challenge_per_strategy = strategy_challenge
                except Exception as e:
                    logger.debug(f"Could not calculate per-strategy challenge: {e}")
                        
            except Exception as e:
                logger.error(f"Could not load challenge data: {e}", exc_info=True)
                # Don't set challenge_status to None here - try to load it again below
                challenge_tracker_instance = None
            
            # Build the comprehensive dashboard message
            message = format_home_card(
                symbol=symbol,
                time_str=time_str,
                agent_running=agent_running,
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
                performance=performance,
                sparkline=None,
                price_change_str=None,
                signal_send_failures=signal_send_failures,
                gateway_unknown=gateway_unknown,
                quiet_reason=quiet_reason,
                signal_diagnostics=signal_diagnostics,
                buy_sell_pressure=buy_sell_pressure,
                buy_sell_pressure_raw=buy_sell_pressure_raw,
                active_trades_count=active_trades_count,
                active_trades_unrealized_pnl=active_trades_unrealized_pnl,
                active_trades_price_source=active_trades_price_source,
                data_age_minutes=data_age_minutes,
                data_stale_threshold_minutes=data_stale_threshold_minutes,
                last_cycle_seconds=last_cycle_seconds,
                session_start=None,
                session_end=None,
                data_level=data_level,
                execution_enabled=execution_enabled,
                execution_armed=execution_armed,
                execution_mode=execution_mode,
            )
            
            # Add challenge metrics if available (before recent exits)
            # Always show challenge - it should always exist (created automatically if missing)
            if not challenge_status and challenge_tracker_instance:
                try:
                    challenge_tracker_instance.refresh()
                    challenge_status = challenge_tracker_instance.get_status_summary()
                except Exception as e:
                    logger.error(f"Could not reload challenge status: {e}", exc_info=True)
            
            # If still no challenge_status, try to create/load one more time
            if not challenge_status:
                try:
                    from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()
                    challenge_status = challenge_tracker_instance.get_status_summary()
                    logger.info(f"Challenge status loaded: {challenge_status[:50] if challenge_status else 'None'}...")
                except Exception as e:
                    logger.error(f"Could not load challenge at all: {e}", exc_info=True)
            
            # Always show challenge if we have it - with multiple fallbacks
            challenge_displayed = False
            
            if challenge_status:
                message += "\n\n" + challenge_status
                challenge_displayed = True
            elif challenge_tracker_instance:
                # If we have tracker but no status, try to get it directly
                try:
                    attempt_perf = challenge_tracker_instance.get_attempt_performance()
                    if attempt_perf:
                        pnl = attempt_perf.get("total_pnl", 0.0)
                        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                        balance = attempt_perf.get("current_balance", 50000.0)
                        trades = attempt_perf.get("exited_signals", 0)
                        wr = attempt_perf.get("win_rate", 0.0) * 100
                        attempt_id = attempt_perf.get("attempt_id", 1)
                        dd_risk = attempt_perf.get("drawdown_risk_pct", 0.0)
                        bar_filled = min(10, int(dd_risk / 10))
                        bar = "▓" * bar_filled + "░" * (10 - bar_filled)
                        
                        challenge_status = (
                            f"🏆 *50k Challenge* (Attempt #{attempt_id})\n"
                            f"Balance: `${balance:,.2f}` | {pnl_emoji} {pnl_str}\n"
                            f"DD Risk: {bar} {dd_risk:.0f}%\n"
                            f"Trades: {trades} | WR: {wr:.0f}%"
                        )
                        message += "\n\n" + challenge_status
                        challenge_displayed = True
                except Exception as e:
                    logger.error(f"Error building challenge status manually: {e}", exc_info=True)
            
            # Final fallback: if challenge file exists, load it directly
            if not challenge_displayed:
                try:
                    challenge_state_file = self.state_dir / "challenge_state.json"
                    if challenge_state_file.exists():
                        import json
                        with open(challenge_state_file, 'r') as f:
                            challenge_data = json.load(f)
                        current_attempt = challenge_data.get("current_attempt", {})
                        config = challenge_data.get("config", {})
                        
                        attempt_id = current_attempt.get("attempt_id", 1)
                        pnl = current_attempt.get("pnl", 0.0)
                        balance = config.get("start_balance", 50000.0) + pnl
                        trades = current_attempt.get("trades", 0)
                        wins = current_attempt.get("wins", 0)
                        losses = current_attempt.get("losses", 0)
                        wr = (wins / trades * 100) if trades > 0 else 0.0
                        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                        max_dd = config.get("max_drawdown", 2000.0)
                        dd_risk = min(100.0, (abs(min(0.0, pnl)) / max_dd) * 100)
                        bar_filled = min(10, int(dd_risk / 10))
                        bar = "▓" * bar_filled + "░" * (10 - bar_filled)
                        
                        challenge_status = (
                            f"🏆 *50k Challenge* (Attempt #{attempt_id})\n"
                            f"Balance: `${balance:,.2f}` | {pnl_emoji} {pnl_str}\n"
                            f"DD Risk: {bar} {dd_risk:.0f}%\n"
                            f"Trades: {trades} | WR: {wr:.0f}%"
                        )
                        message += "\n\n" + challenge_status
                        challenge_displayed = True
                        logger.info("Challenge loaded directly from file as fallback")
                except Exception as e:
                    logger.error(f"Error loading challenge from file directly: {e}", exc_info=True)
            
            if not challenge_displayed:
                logger.warning("Challenge status could not be displayed despite file existing")
            
            # Always show 7d all-time performance if available (matches screenshot format)
            # Show it even if challenge_status exists, as it's separate historical data
            if performance:
                exited = performance.get("exited_signals", 0)
                wins = performance.get("wins", 0)
                losses = performance.get("losses", 0)
                total_pnl = performance.get("total_pnl", 0.0)
                
                # Show 7d All-Time if we have any trades or PnL data
                if exited > 0 or wins > 0 or losses > 0 or total_pnl != 0:
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    # Match screenshot format: "7d All-Time: 🔴 -$3,450.04 (41W/119L)"
                    pnl_sign = "-" if total_pnl < 0 else "+"
                    message += "\n\n*7d All-Time:*\n"
                    message += f"{pnl_emoji} {pnl_sign}${abs(total_pnl):,.2f} ({wins}W/{losses}L)"
                        
            # Add per-strategy breakdown (30 days performance by strategy) - always show if available
            try:
                from pearlalgo.learning.trade_database import TradeDatabase
                db_path = self.state_dir / "trades.db"
                if db_path.exists():
                    trade_db = TradeDatabase(db_path)
                    strategy_perf = trade_db.get_performance_by_signal_type(days=30)
                    if strategy_perf:
                        message += "\n\n*30d by Strategy:*"
                        # Sort by PnL descending
                        sorted_strategies = sorted(strategy_perf.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True)
                        
                        # Calculate total PNL across all strategies
                        total_pnl_all = sum(perf.get("total_pnl", 0.0) for perf in strategy_perf.values())
                        total_wins = sum(perf.get("wins", 0) for perf in strategy_perf.values())
                        total_losses = sum(perf.get("losses", 0) for perf in strategy_perf.values())
                        total_trades = total_wins + total_losses
                        total_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
                        total_emoji = "🟢" if total_pnl_all >= 0 else "🔴"
                        
                        # Show total PNL for all strategies
                        message += f"\n{total_emoji} *Total All Strategies:* ${total_pnl_all:,.2f} ({total_wins}W/{total_losses}L • {total_wr:.0f}% WR)"
                        
                        # Show individual strategies
                        for strategy_name, perf in sorted_strategies:
                            wins = perf.get("wins", 0)
                            losses = perf.get("losses", 0)
                            wr = perf.get("win_rate", 0.0) * 100
                            pnl = perf.get("total_pnl", 0.0)
                            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                            strategy_display = strategy_name.replace('_', ' ').title()
                            if strategy_name == "unified_strategy":
                                strategy_display = "Unified Strategy"
                            message += f"\n{pnl_emoji} *{strategy_display}:* ${pnl:,.2f} ({wins}W/{losses}L • {wr:.0f}% WR)"
            except Exception as e:
                logger.debug(f"Could not load per-strategy performance: {e}")
            
            # Add per-strategy challenge metrics (one challenge per strategy)
            # Load per-strategy challenges
            try:
                from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker
                from pearlalgo.learning.trade_database import TradeDatabase
                
                db_path = self.state_dir / "trades.db"
                if db_path.exists():
                    trade_db = TradeDatabase(db_path)
                    # Get all strategies
                    all_strategies = trade_db.get_performance_by_signal_type(days=365)
                    
                    per_strategy_challenges = {}
                    for strategy_name in all_strategies.keys():
                        # Each strategy has its own challenge state directory
                        strategy_state_dir = self.state_dir / f"challenge_{strategy_name}"
                        strategy_state_dir.mkdir(parents=True, exist_ok=True)
                        
                        strategy_challenge_file = strategy_state_dir / "challenge_state.json"
                        if strategy_challenge_file.exists():
                            strategy_tracker = ChallengeTracker(state_dir=strategy_state_dir)
                            strategy_tracker.refresh()
                            strategy_status = strategy_tracker.get_status_summary()
                            attempt_perf = strategy_tracker.get_attempt_performance()
                            
                            if strategy_status:
                                per_strategy_challenges[strategy_name] = {
                                    "status": strategy_status,
                                    "attempt_id": attempt_perf.get("attempt_id", 1),
                                    "balance": attempt_perf.get("current_balance", 50000.0),
                                    "pnl": attempt_perf.get("total_pnl", 0.0),
                                    "trades": attempt_perf.get("exited_signals", 0),
                                    "wr": attempt_perf.get("win_rate", 0.0) * 100,
                                }
                    
                    # Display per-strategy challenges
                    if per_strategy_challenges:
                        message += "\n\n*Challenge by Strategy (One per Strategy):*"
                        sorted_strategies = sorted(per_strategy_challenges.items(), key=lambda x: x[1].get("pnl", 0), reverse=True)
                        for strategy_name, challenge_data in sorted_strategies:
                            strategy_display = strategy_name.replace('_', ' ').title()
                            if strategy_name == "unified_strategy":
                                strategy_display = "Unified Strategy"
                            attempt_id = challenge_data.get("attempt_id", 1)
                            balance = challenge_data.get("balance", 50000.0)
                            pnl = challenge_data.get("pnl", 0.0)
                            trades = challenge_data.get("trades", 0)
                            wr = challenge_data.get("wr", 0.0)
                            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                            pnl_sign = "-" if pnl < 0 else "+"
                            message += f"\n\n🏆 *{strategy_display}* (Attempt #{attempt_id})"
                            message += f"\nBalance: ${balance:,.2f} | {pnl_emoji} {pnl_sign}${abs(pnl):,.2f}"
                            message += f"\nTrades: {trades} | WR: {wr:.0f}%"
            except Exception as e:
                logger.debug(f"Could not load per-strategy challenges: {e}")
            
            # Add per-strategy challenge metrics (current attempt only) - legacy overall challenge breakdown
            # Show this section if we have challenge data and per-strategy breakdown
            if challenge_status and challenge_tracker_instance:
                # Try to get per-strategy breakdown if we haven't already
                if not challenge_per_strategy:
                    try:
                        from pearlalgo.learning.trade_database import TradeDatabase
                        db_path = self.state_dir / "trades.db"
                        if db_path.exists():
                            trade_db = TradeDatabase(db_path)
                            attempt_perf = challenge_tracker_instance.get_attempt_performance()
                            attempt_start = attempt_perf.get("attempt_started_at") if attempt_perf else None
                            
                            if attempt_start:
                                cutoff = parse_utc_timestamp(attempt_start) if isinstance(attempt_start, str) else attempt_start
                                if cutoff:
                                    all_trades = trade_db.get_recent_trades_by_exit(limit=10000)
                                    attempt_trades = []
                                    for trade in all_trades:
                                        try:
                                            exit_time = trade.get("exit_time") or trade.get("timestamp")
                                            if exit_time:
                                                trade_time = parse_utc_timestamp(exit_time) if isinstance(exit_time, str) else exit_time
                                                if trade_time:
                                                    if hasattr(trade_time, 'tzinfo') and trade_time.tzinfo is None:
                                                        trade_time = trade_time.replace(tzinfo=timezone.utc)
                                                    if hasattr(cutoff, 'tzinfo') and cutoff.tzinfo is None:
                                                        cutoff = cutoff.replace(tzinfo=timezone.utc)
                                                    if hasattr(trade_time, '__ge__') and trade_time >= cutoff:
                                                        attempt_trades.append(trade)
                                        except Exception:
                                            pass
                                    
                                    strategy_challenge = {}
                                    for trade in attempt_trades:
                                        signal_type = trade.get("signal_type") or "unknown"
                                        pnl = float(trade.get("pnl", 0.0))
                                        is_win = bool(trade.get("is_win", False))
                                        
                                        if signal_type not in strategy_challenge:
                                            strategy_challenge[signal_type] = {
                                                "pnl": 0.0,
                                                "trades": 0,
                                                "wins": 0,
                                                "losses": 0,
                                            }
                                        
                                        strategy_challenge[signal_type]["pnl"] += pnl
                                        strategy_challenge[signal_type]["trades"] += 1
                                        if is_win:
                                            strategy_challenge[signal_type]["wins"] += 1
                                        else:
                                            strategy_challenge[signal_type]["losses"] += 1
                                    
                                    challenge_per_strategy = strategy_challenge
                    except Exception as e:
                        logger.debug(f"Could not calculate per-strategy challenge (retry): {e}")
                
                # Display per-strategy challenge breakdown if we have data
                if challenge_per_strategy:
                    message += "\n\n*Challenge by Strategy (Current Attempt):*"
                    # Get attempt starting balance
                    try:
                        attempt_perf = challenge_tracker_instance.get_attempt_performance()
                        start_balance = attempt_perf.get("starting_balance", 50000.0)
                    except Exception:
                        start_balance = 50000.0
                    
                    sorted_strategies = sorted(challenge_per_strategy.items(), key=lambda x: x[1].get("pnl", 0), reverse=True)
                    for strategy_name, metrics in sorted_strategies:
                        pnl = metrics.get("pnl", 0.0)
                        trades = metrics.get("trades", 0)
                        wins = metrics.get("wins", 0)
                        losses = metrics.get("losses", 0)
                        wr = (wins / trades * 100) if trades > 0 else 0
                        balance = start_balance + pnl
                        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                        strategy_display = strategy_name.replace('_', ' ').title()
                        if strategy_name == "unified_strategy":
                            strategy_display = "Unified Strategy"
                        message += f"\n{pnl_emoji} *{strategy_display}:* ${balance:,.2f} | ${pnl:+,.2f} ({wins}W/{losses}L • {wr:.0f}% WR)"
            
            # Add recent exits (from state or fallback to signals.jsonl)
            recent_exits = state.get("recent_exits", [])
            if not isinstance(recent_exits, list) or not recent_exits:
                # Fallback: read from signals.jsonl
                recent_signals = self._read_recent_signals(limit=50)
                recent_exits = []
                for signal in reversed(recent_signals):  # Most recent first
                    if signal.get("status") == "exited":
                        pnl = signal.get("pnl")
                        if pnl is not None:
                            recent_exits.append({
                                "signal_id": str(signal.get("signal_id") or ""),
                                "type": str(signal.get("type") or "unknown"),
                                "direction": str(signal.get("direction") or "long"),
                                "pnl": pnl,
                                "exit_reason": str(signal.get("exit_reason") or ""),
                                "exit_time": signal.get("exit_time") or signal.get("timestamp"),
                            })
                        if len(recent_exits) >= 3:
                            break
            
            if isinstance(recent_exits, list) and recent_exits:
                message += "\n\n*Recent exits:*"
                for t in recent_exits[:3]:
                    try:
                        pnl_val = float(t.get("pnl") or 0.0)
                    except Exception:
                        pnl_val = 0.0
                    pnl_emoji, pnl_str = format_pnl(pnl_val)
                    dir_emoji, dir_label = format_signal_direction(t.get("direction", "long"))
                    sig_type = safe_label(str(t.get("type") or "unknown"))
                    reason = safe_label(str(t.get("exit_reason") or "")).strip()
                    line = f"\n{pnl_emoji} *{pnl_str}* • {dir_emoji} {dir_label} • {sig_type}"
                    if reason:
                        line += f" • {reason}"
                    message += line
                    
                    # Add timestamp if available
                    timestamp = t.get("exit_time") or t.get("exit_timestamp") or t.get("timestamp")
                    if timestamp:
                        try:
                            exit_time = parse_utc_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
                            if exit_time:
                                if hasattr(exit_time, 'tzinfo') and exit_time.tzinfo is None:
                                    exit_time = exit_time.replace(tzinfo=timezone.utc)
                                try:
                                    et_exit = exit_time.astimezone(et_tz)
                                    time_label = et_exit.strftime("%I:%M %p").lstrip('0')
                                    message += f" • {time_label}"
                                except Exception:
                                    pass
                        except Exception:
                            pass
            
            # Add current position/signal if active
            if active_trades_count > 0:
                # Try to find active signal from recent signals
                recent_signals = self._read_recent_signals(limit=20)
                active_signal = next((s for s in recent_signals if s.get("status") == "entered"), None)
                
                if active_signal:
                    message += "\n\n*Current Position:*"
                    direction = active_signal.get("direction", "").upper()
                    signal_type = active_signal.get("type", "unknown")
                    entry_price = active_signal.get("entry_price")
                    stop_loss = active_signal.get("stop_loss")
                    take_profit = active_signal.get("take_profit")
                    confidence = active_signal.get("confidence")
                    
                    message += f"\n🎯 {symbol} {direction} | {signal_type}\n"
                    if entry_price:
                        message += f"Entry: ${entry_price:,.2f}\n"
                    if stop_loss and take_profit and entry_price:
                        if direction == "LONG":
                            risk = entry_price - stop_loss
                            reward = take_profit - entry_price
                        else:
                            risk = stop_loss - entry_price
                            reward = entry_price - take_profit
                        if risk > 0:
                            rr = reward / risk
                            message += f"R:R {rr:.1f}:1\n"
                    if stop_loss:
                        stop_pts = abs(entry_price - stop_loss) if entry_price else 0
                        message += f"Stop: ${stop_loss:,.2f} ({stop_pts:.1f} pts)\n"
                    if take_profit:
                        tp_pts = abs(take_profit - entry_price) if entry_price else 0
                        message += f"TP: ${take_profit:,.2f} ({tp_pts:.1f} pts)\n"
                    if confidence:
                        conf_pct = confidence * 100 if confidence <= 1 else confidence
                        conf_label = "High" if conf_pct >= 80 else "Medium" if conf_pct >= 50 else "Low"
                        message += f"Confidence: {conf_pct:.0f}% ({conf_label})"
            
            return message
            
        except Exception as e:
            logger.error(f"Error building status dashboard: {e}", exc_info=True)
            return f"❌ Error building status: {e}"

    async def _handle_system_status(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display comprehensive system status dashboard."""
        state = self._read_state()
        if not state:
            await query.edit_message_text("❌ Could not read system state.\n\nState file not found or invalid.", reply_markup=reply_markup)
            return
        
        try:
            message_text = await self._build_status_dashboard_message(state)
            await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")
            return
            
        except Exception as e:
            logger.error(f"Error formatting status: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Error displaying status: {e}", reply_markup=reply_markup)

    async def _handle_active_trades(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display active trades/positions."""
        state = self._read_state()
        if not state:
            await query.edit_message_text("❌ Could not read system state.", reply_markup=reply_markup)
            return
        
        # Get active trades from state
        active_trades_count = state.get("active_trades_count", 0) or 0
        execution = state.get("execution", {})
        positions = execution.get("positions", 0) or 0
        active_trades_unrealized_pnl = state.get("active_trades_unrealized_pnl")
        
        text = "📋 *Active Trades*\n\n"
        
        if active_trades_count == 0 and positions == 0:
            text += "No active trades or positions.\n"
        else:
            text += f"🎯 *Positions:* {positions}\n"
            text += f"📊 *Active Trades:* {active_trades_count}\n"
            
            if active_trades_unrealized_pnl is not None:
                pnl_emoji = "💰" if active_trades_unrealized_pnl >= 0 else "📉"
                text += f"\n{pnl_emoji} *Unrealized P&L:* ${active_trades_unrealized_pnl:,.2f}\n"
        
        # Try to get detailed trade info from signals
        recent_signals = self._read_recent_signals(limit=20)
        active_signals = [s for s in recent_signals if s.get("status") == "entered"]
        
        if active_signals:
            text += "\n*Recent Active Signals:*\n"
            for i, signal in enumerate(active_signals[-5:], 1):  # Show last 5
                signal_id = signal.get("signal_id", "unknown")[:8]
                direction = signal.get("direction", "").upper()
                entry_price = signal.get("entry_price", 0)
                signal_type = signal.get("type", "unknown")
                text += f"\n{i}. {direction} {signal_type}\n"
                text += f"   ID: {signal_id}\n"
                if entry_price:
                    text += f"   Entry: ${entry_price:,.2f}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_recent_signals(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display recent signals."""
        signals = self._read_recent_signals(limit=10)
        
        text = "🎯 *Recent Signals*\n\n"
        
        if not signals:
            text += "No signals found.\n"
        else:
            text += f"Showing last {len(signals)} signals:\n\n"
            for i, signal in enumerate(reversed(signals[-10:]), 1):  # Most recent first
                signal_id = signal.get("signal_id", "unknown")[:8]
                direction = signal.get("direction", "").upper()
                signal_type = signal.get("type", "unknown")
                status = signal.get("status", "unknown")
                entry_price = signal.get("entry_price")
                timestamp = signal.get("timestamp", "")
                
                # Format timestamp
                time_str = ""
                if timestamp:
                    try:
                        ts = parse_utc_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
                        time_str = ts.strftime("%H:%M") if hasattr(ts, 'strftime') else str(timestamp)[:5]
                    except Exception:
                        time_str = str(timestamp)[:5] if timestamp else ""
                
                text += f"{i}. {direction} {signal_type} - {status}\n"
                if entry_price:
                    text += f"   Entry: ${entry_price:,.2f}"
                if time_str:
                    text += f" @ {time_str}"
                text += f"\n   ID: {signal_id}\n\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_signal_history(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display signal history summary."""
        signals = self._read_recent_signals(limit=100)
        
        text = "📊 *Signal History*\n\n"
        
        if not signals:
            text += "No signals in history.\n"
        else:
            # Count by status
            status_counts = {}
            type_counts = {}
            direction_counts = {}
            
            for signal in signals:
                status = signal.get("status", "unknown")
                signal_type = signal.get("type", "unknown")
                direction = signal.get("direction", "unknown").upper()
                
                status_counts[status] = status_counts.get(status, 0) + 1
                type_counts[signal_type] = type_counts.get(signal_type, 0) + 1
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
            
            text += f"*Total Signals:* {len(signals)}\n\n"
            
            text += "*By Status:*\n"
            for status, count in sorted(status_counts.items()):
                text += f"  • {status}: {count}\n"
            
            text += "\n*By Direction:*\n"
            for direction, count in sorted(direction_counts.items()):
                text += f"  • {direction}: {count}\n"
            
            text += "\n*By Type:*\n"
            for sig_type, count in sorted(type_counts.items()):
                text += f"  • {sig_type}: {count}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_gateway_status(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display gateway status."""
        state = self._read_state()
        if not state:
            await query.edit_message_text("❌ Could not read system state.", reply_markup=reply_markup)
            return
        
        text = "🔌 *Gateway Status*\n\n"
        
        connection_status = state.get("connection_status", "unknown")
        connection_failures = state.get("connection_failures", 0)
        
        if connection_status == "connected":
            text += "🟢 *Status:* CONNECTED\n"
        elif connection_status == "disconnected":
            text += "🔴 *Status:* DISCONNECTED\n"
        else:
            text += f"⚪ *Status:* {connection_status.upper()}\n"
        
        if connection_failures > 0:
            text += f"⚠️ *Failures:* {connection_failures}\n"
        
        # Data source info
        latest_bar = state.get("latest_bar", {})
        if latest_bar:
            data_level = latest_bar.get("_data_level", "unknown")
            text += f"\n📊 *Data Level:* {data_level}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_connection_status(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display connection status."""
        await self._handle_gateway_status(query, reply_markup)  # Same as gateway status

    async def _handle_data_quality(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display data quality information."""
        state = self._read_state()
        if not state:
            await query.edit_message_text("❌ Could not read system state.", reply_markup=reply_markup)
            return
        
        text = "💾 *Data Quality*\n\n"
        
        # Get threshold from config
        data_stale_threshold_minutes = 10.0
        try:
            import yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
                    data_config = config.get("data", {})
                    data_stale_threshold_minutes = float(data_config.get("stale_data_threshold_minutes", 10.0))
        except Exception:
            pass
        
        latest_bar = state.get("latest_bar", {})
        agent_running = state.get("running", False)
        paused = state.get("paused", False)
        futures_market_open = state.get("futures_market_open")
        strategy_session_open = state.get("strategy_session_open")
        
        if latest_bar:
            data_level = latest_bar.get("_data_level", "unknown")
            text += f"📊 *Data Level:* {data_level}\n"
            
            # Check data age
            timestamp = latest_bar.get("timestamp")
            if timestamp:
                try:
                    from datetime import datetime, timezone
                    bar_time = parse_utc_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
                    if bar_time:
                        now = datetime.now(timezone.utc)
                        if isinstance(bar_time, str):
                            bar_time = parse_utc_timestamp(bar_time)
                        if hasattr(bar_time, 'tzinfo') and bar_time.tzinfo is None:
                            bar_time = bar_time.replace(tzinfo=timezone.utc)
                        age_seconds = (now - bar_time).total_seconds()
                        age_minutes = age_seconds / 60
                        
                        text += f"\n⏰ *Data Age:* {age_minutes:.1f} minutes\n"
                        text += f"📏 *Threshold:* {data_stale_threshold_minutes:.0f} minutes\n\n"
                        
                        # Explain why it might be stale
                        if age_minutes > data_stale_threshold_minutes:
                            text += "⚠️ *Data is stale*\n\n"
                            text += "*Possible reasons:*\n"
                            if not agent_running or paused:
                                text += "• Agent is not running\n"
                            if futures_market_open is False:
                                text += "• Futures market is closed\n"
                            if strategy_session_open is False:
                                text += "• Trading session is closed\n"
                            if agent_running and not paused and (futures_market_open is True or strategy_session_open is True):
                                text += "• Data fetcher may not be working\n"
                                text += "• Check gateway connection\n"
                                text += "• Check data provider status\n"
                        else:
                            text += "🟢 *Data is fresh*\n"
                except Exception as e:
                    text += f"\n⚠️ Could not calculate data age: {e}\n"
            
            # Buffer info
            buffer_size = state.get("buffer_size", 0)
            buffer_target = state.get("buffer_size_target")
            if buffer_size or buffer_target:
                text += f"\n📊 *Buffer:* {buffer_size}"
                if buffer_target:
                    text += f" / {buffer_target} (target)"
                text += "\n"
        else:
            text += "❌ No data available\n"
            text += "\n*Possible reasons:*\n"
            text += "• Agent not running\n"
            text += "• Data fetcher not initialized\n"
            text += "• No market data received yet\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    def run(self) -> None:
        logger.info("Starting PEARLalgo Telegram Command Handler")
        logger.info(f"Bot token: {'***' + self.bot_token[-4:] if len(self.bot_token) > 4 else '***'}")
        logger.info(f"Chat ID: {self.chat_id}")
        logger.info("Button-based interface: use /start or /menu to see the menu")
        logger.info("Press Ctrl+C to stop")
        logger.info("Connecting to Telegram...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)



    # ---------------------------------------------------------------------
    # Legacy/test compatibility helpers
    # ---------------------------------------------------------------------

    async def _send_message_or_edit(self, update: Any, context: Any, msg: str, **kwargs) -> None:
        """Send a message or edit an existing one (test-friendly helper)."""
        try:
            query = getattr(update, "callback_query", None)
            if query is not None and callable(getattr(query, "edit_message_text", None)):
                await query.edit_message_text(msg, **kwargs)
                return
        except Exception:
            pass

        try:
            message = getattr(update, "message", None)
            if message is not None and callable(getattr(message, "reply_text", None)):
                await message.reply_text(msg, **kwargs)
                return
        except Exception:
            pass

        # Fallback to bot.send_message
        try:
            bot = getattr(context, "bot", None)
            if bot is not None and callable(getattr(bot, "send_message", None)):
                chat_id = (
                    getattr(getattr(update, "effective_chat", None), "id", None)
                    or getattr(self, "chat_id", None)
                )
                await bot.send_message(chat_id=chat_id, text=msg, **kwargs)
        except Exception:
            pass

    async def _check_authorized(self, update: Any) -> bool:
        """Return True if update comes from the configured chat_id."""
        expected = str(getattr(self, "chat_id", "") or "")
        if not expected:
            return False
        got = getattr(getattr(update, "effective_chat", None), "id", None)
        return str(got) == expected

    async def _handle_callback(self, update: Any, context: Any) -> None:
        """Legacy callback handler expected by tests."""
        query = getattr(update, "callback_query", None)
        if query is None:
            return

        # Always acknowledge callbacks first
        try:
            if callable(getattr(query, "answer", None)):
                await query.answer()
        except Exception:
            pass

        if not await self._check_authorized(update):
            if callable(getattr(query, "edit_message_text", None)):
                await query.edit_message_text("❌ Unauthorized access")
            else:
                await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        data = str(getattr(query, "data", "") or "")

        # Strategy Review: variant week selector
        if data.startswith("strategy_review:variant_weeks:"):
            try:
                weeks = int(data.split(":")[-1])
            except Exception:
                weeks = 1

            user_data = getattr(context, "user_data", None)
            if isinstance(user_data, dict):
                user_data["strategy_review_variant_weeks"] = weeks
            else:
                try:
                    context.user_data = {"strategy_review_variant_weeks": weeks}
                except Exception:
                    pass

            render = getattr(self, "_render_strategy_review_cached", None)
            if callable(render):
                await render(update, context)
            return

        # Fallback to the current callback handler implementation
        handler = getattr(self, "handle_callback", None)
        if callable(handler):
            await handler(update, context)

    def _is_agent_process_running(self) -> bool:
        """Best-effort check if agent process is running (patched in tests)."""
        sc = getattr(self, "service_controller", None)
        try:
            fn = getattr(sc, "is_agent_process_running", None)
            if callable(fn):
                return bool(fn())
        except Exception:
            pass
        return False

    def _get_current_time_str(self) -> str:
        """Return a short time string for status output."""
        try:
            return datetime.now(timezone.utc).strftime("%H:%M UTC")
        except Exception:
            return ""

    def _compute_state_stale_threshold(self, _state: dict) -> float:
        """Return stale threshold (seconds) for Home Card freshness warning."""
        return 120.0

    def _extract_latest_price(self, state: dict) -> Optional[float]:
        """Extract a latest price from the state payload."""
        try:
            v = state.get("latest_price")
            if v is not None:
                return float(v)
        except Exception:
            pass
        try:
            bar = state.get("latest_bar") or {}
            v = bar.get("close")
            return float(v) if v is not None else None
        except Exception:
            return None

    def _extract_data_age_minutes(self, state: dict) -> Optional[float]:
        """Best-effort market-data age in minutes (derived from latest_bar timestamp)."""
        try:
            bar = state.get("latest_bar") or {}
            ts = bar.get("timestamp")
            if not ts:
                return None
            dt = parse_utc_timestamp(str(ts))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
        except Exception:
            return None

    async def _handle_status(self, update: Any, context: Any) -> None:
        """Legacy /status handler expected by tests."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        state = None
        try:
            state = self._read_state()
        except Exception:
            state = None

        symbol = "MNQ"
        if isinstance(state, dict):
            try:
                symbol = str(state.get("symbol") or symbol)
            except Exception:
                pass

        time_str = self._get_current_time_str()

        if not state:
            msg = f"📊 *{symbol}* • {time_str}\n\n❌ No state file found.\n\nStart the agent service to begin."
            if len(msg) > 4096:
                msg = msg[:4093] + "..."
            await self._send_message_or_edit(update, context, msg, parse_mode="Markdown")
            return

        # Gateway status (best-effort)
        gateway_running = True
        sc = getattr(self, "service_controller", None)
        try:
            fn = getattr(sc, "get_gateway_status", None)
            if callable(fn):
                gs = fn() or {}
                gateway_running = bool(gs.get("process_running", True)) and bool(gs.get("port_listening", True))
        except Exception:
            gateway_running = True

        agent_running = bool(self._is_agent_process_running())

        futures_market_open = state.get("futures_market_open")
        strategy_session_open = state.get("strategy_session_open")
        paused = bool(state.get("paused", False))
        pause_reason = state.get("pause_reason")

        cycles_total = int(state.get("cycle_count", 0) or 0)
        signals_generated = int(state.get("signal_count", 0) or 0)
        errors = int(state.get("error_count", 0) or 0)
        buffer_size = int(state.get("buffer_size", 0) or 0)

        latest_price = self._extract_latest_price(state)
        data_age_minutes = self._extract_data_age_minutes(state)

        # State age (seconds) from last_successful_cycle if present
        state_age_seconds = None
        try:
            ts = state.get("last_successful_cycle")
            if ts:
                dt = parse_utc_timestamp(str(ts))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                state_age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            state_age_seconds = None

        stale_threshold = float(self._compute_state_stale_threshold(state))

        msg = format_home_card(
            symbol=symbol,
            time_str=time_str,
            agent_running=agent_running,
            gateway_running=gateway_running,
            futures_market_open=futures_market_open,
            strategy_session_open=strategy_session_open,
            paused=paused,
            pause_reason=pause_reason,
            cycles_total=cycles_total,
            signals_generated=signals_generated,
            errors=errors,
            buffer_size=buffer_size,
            latest_price=latest_price,
            state_age_seconds=state_age_seconds,
            state_stale_threshold=stale_threshold,
            data_age_minutes=data_age_minutes,
        )

        if len(msg) > 4096:
            msg = msg[:4093] + "..."

        await self._send_message_or_edit(update, context, msg, parse_mode="Markdown")

    async def _handle_signals(self, update: Any, context: Any) -> None:
        """Legacy /signals handler expected by tests."""
        if not await self._check_authorized(update):
            # Tests expect reply_text called with EXACT args (no kwargs)
            message = getattr(update, "message", None)
            if message is not None and callable(getattr(message, "reply_text", None)):
                await message.reply_text("❌ Unauthorized access")
            else:
                await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        try:
            state_dir = getattr(self, "state_dir", None) or ensure_state_dir(None)
        except Exception:
            state_dir = Path("data/nq_agent_state")

        signals_file = get_signals_file(Path(state_dir))
        if not signals_file.exists():
            await self._send_message_or_edit(update, context, "🎯 Signals\n\nNo signals file found.")
            return

        raw_lines = []
        try:
            raw_lines = signals_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            raw_lines = []

        signals = []
        for line in raw_lines:
            line = (line or "").strip()
            if not line:
                continue
            try:
                signals.append(json.loads(line))
            except Exception:
                continue

        if not signals:
            await self._send_message_or_edit(update, context, "🎯 Signals\n\nNo signals yet.")
            return

        # Render a compact summary (keep under Telegram limit)
        shown = signals[-10:]
        lines = ["🎯 Recent Signals"]
        for s in shown:
            try:
                direction = format_signal_direction(str(s.get("direction") or s.get("signal", {}).get("direction") or ""))
            except Exception:
                direction = ""
            typ = str(s.get("type") or s.get("signal", {}).get("type") or s.get("signal_type") or "signal")
            price = s.get("entry_price") or s.get("signal", {}).get("entry_price")
            price_str = f" @ {price}" if price is not None else ""
            lines.append(f"- {direction} {safe_label(typ)}{price_str}")

        msg = "\n".join(lines)
        if len(msg) > 4096:
            msg = msg[:4093] + "..."
        await self._send_message_or_edit(update, context, msg)

    async def _handle_performance(self, update: Any, context: Any) -> None:
        """Legacy /performance handler expected by tests."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        tracker = getattr(self, "performance_tracker", None)
        metrics = {}
        try:
            fn = getattr(tracker, "get_performance_metrics", None)
            metrics = fn() if callable(fn) else {}
        except Exception:
            metrics = {}

        total_signals = int(metrics.get("total_signals", 0) or 0)
        exited = int(metrics.get("exited_signals", 0) or 0)
        wins = int(metrics.get("wins", 0) or 0)
        losses = int(metrics.get("losses", 0) or 0)
        win_rate = float(metrics.get("win_rate", 0.0) or 0.0)
        total_pnl = float(metrics.get("total_pnl", 0.0) or 0.0)
        avg_pnl = float(metrics.get("avg_pnl", 0.0) or 0.0)
        avg_hold = float(metrics.get("avg_hold_minutes", 0.0) or 0.0)

        lines = ["📈 Performance"]
        lines.append(f"• Signals: {total_signals} (completed {exited})")
        if exited <= 0:
            lines.append("• No completed trades yet")
        else:
            lines.append(f"• Win rate: {win_rate:.0%} ({wins}W/{losses}L)")
            lines.append(f"• Total PnL: {format_pnl(total_pnl)}")
            lines.append(f"• Avg PnL: {format_pnl(avg_pnl)}")
            lines.append(f"• Avg hold: {avg_hold:.0f}m")

        # Per-type summary (best-effort)
        by_type = metrics.get("by_signal_type") or {}
        if isinstance(by_type, dict) and by_type:
            lines.append("")
            lines.append("By type:")
            for k, v in list(by_type.items())[:8]:
                try:
                    c = int((v or {}).get("count", 0) or 0)
                    wr = float((v or {}).get("win_rate", 0.0) or 0.0)
                    pnl = float((v or {}).get("total_pnl", 0.0) or 0.0)
                    lines.append(f"• {safe_label(str(k))}: {c} • {wr:.0%} • {format_pnl(pnl)}")
                except Exception:
                    continue

        msg = "\n".join(lines)
        if len(msg) > 4096:
            msg = msg[:4093] + "..."
        await self._send_message_or_edit(update, context, msg)

    async def _handle_doctor(self, update: Any, context: Any) -> None:
        """Legacy /doctor rollup expected by tests (prefers SQLite TradeDatabase if present)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        db = getattr(self, "_trade_db", None)
        if db is not None:
            try:
                from datetime import timedelta

                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                counts = db.get_signal_event_counts(from_time=cutoff) or {}
                trades = int(db.get_trade_count() or 0)

                lines = ["🩺 Doctor (24h)", "", "Signals:"]
                if isinstance(counts, dict) and counts:
                    for k in sorted(counts.keys()):
                        lines.append(f"- {k}: {counts[k]}")
                else:
                    lines.append("- (no signal events)")

                lines.append("")
                lines.append(f"Trades: {trades}")

                msg = "\n".join(lines)
            except Exception as e:
                msg = f"🩺 Doctor\n\n❌ Error reading trade DB: {e}"
        else:
            msg = "🩺 Doctor\n\nNo trade database available."

        if len(msg) > 4096:
            msg = msg[:4093] + "..."

        await self._send_message_or_edit(update, context, msg, reply_markup=self._get_back_to_menu_button())

    def _get_trades_for_chart(self, chart_data: Any, symbol: str = "MNQ") -> list[dict]:
        """Convert recent entered signals to trade markers within chart time window."""
        if chart_data is None:
            return []

        # Pandas-friendly guards
        try:
            import pandas as pd  # type: ignore

            if isinstance(chart_data, pd.DataFrame) and chart_data.empty:
                return []
            if not isinstance(chart_data, pd.DataFrame):
                return []
            if "timestamp" not in chart_data.columns:
                return []
            ts = chart_data["timestamp"]
            if ts.empty:
                return []
            start = ts.min()
            end = ts.max()
        except Exception:
            return []

        sm = getattr(self, "state_manager", None)
        recent = []
        try:
            fn = getattr(sm, "get_recent_signals", None)
            recent = fn() if callable(fn) else []
        except Exception:
            recent = []

        trades: list[dict] = []
        sym = str(symbol or "").upper()

        for item in (recent or []):
            if not isinstance(item, dict):
                continue
            sig = item.get("signal") or {}
            if not isinstance(sig, dict):
                sig = {}
            if str(sig.get("symbol", "")).upper() != sym:
                continue

            entry_time = item.get("entry_time") or item.get("timestamp") or sig.get("timestamp")
            if not entry_time:
                continue

            try:
                dt = parse_utc_timestamp(str(entry_time))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            # Compare against pandas timestamps
            try:
                if dt < start.to_pydatetime() or dt > end.to_pydatetime():
                    continue
            except Exception:
                # If conversion fails, best-effort compare
                try:
                    if dt < start or dt > end:
                        continue
                except Exception:
                    pass

            trades.append(
                {
                    "signal_id": item.get("signal_id") or sig.get("signal_id") or "",
                    "direction": sig.get("direction") or item.get("direction") or "",
                    "entry_time": dt.isoformat(),
                    "entry_price": item.get("entry_price") or sig.get("entry_price"),
                    "status": item.get("status"),
                }
            )

        return trades

    def _get_back_to_menu_button(self):
        """Return a minimal 'Back to Menu' InlineKeyboardMarkup."""
        try:
            return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]])
        except Exception:
            return None

    def _get_claude_hub_buttons(self):
        """Buttons for Claude AI Hub (minimal)."""
        try:
            return InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🟢 AI On", callback_data="action:ai_on"), InlineKeyboardButton("🔴 AI Off", callback_data="action:ai_off")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
            )
        except Exception:
            return None

    def _is_path_blocked(self, rel_path: str) -> bool:
        """Block unsafe files for AI patching (case-insensitive)."""
        p = str(rel_path or "").strip().replace("\\", "/")
        if not p:
            return True
        low = p.lower()

        # Block obvious secret/runtime dirs
        if low.startswith("data/") or "/data/" in low:
            return True
        if low.startswith("logs/") or "/logs/" in low:
            return True
        if low.startswith("ibkr/") or "/ibkr/" in low:
            return True

        # Block sensitive directories
        if "/.venv/" in low or low.startswith(".venv/") or "/.venv" in low:
            return True
        if "/.git/" in low or low.startswith(".git/") or "/.git" in low:
            return True

        # Block env files
        if low.endswith("/.env") or low == ".env" or low.endswith(".env"):
            return True

        # Block compiled + binary-ish artifacts
        if low.endswith(".pyc") or "__pycache__" in low:
            return True

        # Block json by default (state/credentials often live here)
        if low.endswith(".json"):
            return True

        return False

    def _search_files(self, query: str, all_files: list[str], *, limit: int = 8) -> list[str]:
        """Simple ranked search used by patch wizard tests."""
        q = str(query or "")
        if not q:
            return list(all_files[: int(limit or 8)])

        ql = q.lower()

        candidates = [p for p in all_files if p and not self._is_path_blocked(p)]

        def score(p: str) -> tuple[int, int, int]:
            low = p.lower()
            name = low.split("/")[-1]
            s = 0
            if ql in name:
                s += 100
            if ql in low:
                s += 10
            # Prefer shorter paths when scores tie
            return (s, -len(name), -len(p))

        matches = [p for p in candidates if ql in p.lower()]
        matches.sort(key=score, reverse=True)
        return matches[: int(limit or 8)]

    def _get_prefs(self) -> Any:
        prefs = getattr(self, "prefs", None)
        if prefs is not None:
            return prefs
        try:
            prefs = TelegramPrefs(state_dir=getattr(self, "state_dir", None))
        except Exception:
            prefs = TelegramPrefs()
        self.prefs = prefs
        return prefs

    async def _handle_ai_hub(self, update: Any, context: Any) -> None:
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        prefs = self._get_prefs()
        chat_mode = False
        try:
            chat_mode = bool(prefs.get("ai_chat_mode", False))
        except Exception:
            pass

        status = "ON" if chat_mode else "OFF"
        msg = f"🤖 Claude AI Hub\n\nChat Mode: {status}\n\nUse /ai_on or /ai_off, or tap buttons below."
        await self._send_message_or_edit(update, context, msg, reply_markup=self._get_claude_hub_buttons())

    async def _handle_ai_on(self, update: Any, context: Any) -> None:
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        prefs = self._get_prefs()
        try:
            prefs.set("ai_chat_mode", True)
        except Exception:
            pass

        await self._send_message_or_edit(update, context, "✅ Chat Mode: ON", reply_markup=self._get_claude_hub_buttons())

    async def _handle_ai_off(self, update: Any, context: Any) -> None:
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        prefs = self._get_prefs()
        try:
            prefs.set("ai_chat_mode", False)
        except Exception:
            pass

        await self._send_message_or_edit(update, context, "✅ Chat Mode: OFF", reply_markup=self._get_claude_hub_buttons())

    async def _handle_claude_message(self, update: Any, context: Any) -> None:
        """Route plain messages to wizard or AI chat when enabled."""
        if not await self._check_authorized(update):
            return

        user_data = getattr(context, "user_data", None) or {}
        if isinstance(user_data, dict):
            state = user_data.get("claude_wizard_state")
        else:
            state = None

        text = str(getattr(getattr(update, "message", None), "text", "") or "")

        if state == "awaiting_task":
            await self._process_wizard_task(update, context, text)
            return
        if state == "refine_search":
            await self._process_wizard_search(update, context, text)
            return

        prefs = self._get_prefs()
        try:
            chat_mode = bool(prefs.get("ai_chat_mode", False))
        except Exception:
            chat_mode = False

        if not chat_mode:
            return

        await self._process_claude_chat(update, context, text)

    async def _process_claude_chat(self, update: Any, context: Any, text: str) -> None:
        """Minimal AI chat handler (tests patch this)."""
        await self._send_message_or_edit(update, context, "(AI chat not configured in this build)")

    async def _process_wizard_task(self, update: Any, context: Any, text: str) -> None:
        await self._send_message_or_edit(update, context, "(Wizard not configured in this build)")

    async def _process_wizard_search(self, update: Any, context: Any, text: str) -> None:
        await self._send_message_or_edit(update, context, "(Wizard not configured in this build)")

    async def _handle_ai_patch(self, update: Any, context: Any) -> None:
        """Generate a unified diff patch for a file via AI."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        args = list(getattr(context, "args", []) or [])
        if len(args) < 2:
            usage = (
                "Usage: /ai_patch <relative_path> <instruction>\n"
                "Example: /ai_patch src/pearlalgo/utils/retry.py add jitter\n"
            )
            await self._send_message_or_edit(update, context, usage)
            return

        rel_path = str(args[0])
        task = " ".join(str(a) for a in args[1:]).strip()

        if self._is_path_blocked(rel_path):
            await self._send_message_or_edit(update, context, f"❌ Blocked path: {rel_path}")
            return

        if not ANTHROPIC_AVAILABLE:
            await self._send_message_or_edit(
                update,
                context,
                "❌ Claude AI Not Available (dependency not installed).\n\nInstall with: pip install -e '.[llm]'",
            )
            return

        # Resolve file within repo
        try:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            target = (project_root / rel_path).resolve()
            if project_root not in target.parents and target != project_root:
                await self._send_message_or_edit(update, context, f"❌ Blocked path: {rel_path}")
                return
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            await self._send_message_or_edit(update, context, f"❌ Could not read file: {e}")
            return

        # Call AI client
        try:
            client = ClaudeClient()
            diff = client.generate_patch(files={rel_path: content}, task=task)
            msg = diff if diff else "(No diff returned)"
            if len(msg) > 4096:
                msg = msg[:4093] + "..."
            await self._send_message_or_edit(update, context, msg)
        except ClaudeAPIKeyMissingError as e:
            await self._send_message_or_edit(update, context, f"❌ API Key missing: {e}")
        except ClaudeNotAvailableError as e:
            await self._send_message_or_edit(update, context, f"❌ Not Available: {e}\n\nInstall with: pip install -e '.[llm]'")
        except ClaudeAPIError as e:
            await self._send_message_or_edit(update, context, f"❌ API Error: {e}")
        except Exception as e:
            await self._send_message_or_edit(update, context, f"❌ Error: {e}")

    async def _render_strategy_review_more_menu(self, update: Any, context: Any) -> None:
        """Render Strategy Review 'More' menu (test expects Backtest/Reports/Export buttons)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        rm = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🧪 Backtest", callback_data="strategy_review:backtest"),
                    InlineKeyboardButton("📑 Reports", callback_data="strategy_review:reports"),
                ],
                [InlineKeyboardButton("📤 Export", callback_data="strategy_review:export")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
        )
        await self._send_message_or_edit(update, context, "Strategy Review • More", reply_markup=rm)

    async def _render_strategy_review_cached(self, update: Any, context: Any) -> None:
        """Placeholder cached Strategy Review render (tests patch this)."""
        await self._send_message_or_edit(update, context, "Strategy Review")

    async def _handle_backtest_reports(self, update: Any, context: Any, *, page: int = 0) -> None:
        """List backtest reports with short callback_data IDs (<= 64 bytes)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        try:
            state_dir = Path(getattr(self, "state_dir", "data/nq_agent_state"))
        except Exception:
            state_dir = Path("data/nq_agent_state")

        reports_dir = state_dir.parent / "reports"
        if not reports_dir.exists():
            await self._send_message_or_edit(update, context, "📑 Reports\n\nNo reports found.")
            return

        report_names = sorted([p.name for p in reports_dir.iterdir() if p.is_dir()])
        page = max(0, int(page or 0))
        page_size = 6
        start = page * page_size
        chunk = report_names[start : start + page_size]

        rows = []
        for i, name in enumerate(chunk):
            idx = start + i
            rows.append([InlineKeyboardButton(name[:28], callback_data=f"report:{idx}")])

        # Navigation
        nav = []
        if start > 0:
            nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"reports:page:{page-1}"))
        if start + page_size < len(report_names):
            nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"reports:page:{page+1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])

        await self._send_message_or_edit(update, context, "📑 Backtest Reports", reply_markup=InlineKeyboardMarkup(rows))

    async def _handle_report_detail(self, update: Any, context: Any, report_name: str) -> None:
        """Show report artifacts with short callback_data IDs (<= 64 bytes)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        try:
            state_dir = Path(getattr(self, "state_dir", "data/nq_agent_state"))
        except Exception:
            state_dir = Path("data/nq_agent_state")

        report_dir = state_dir.parent / "reports" / str(report_name)
        if not report_dir.exists():
            await self._send_message_or_edit(update, context, "❌ Report not found")
            return

        artifacts = [p.name for p in report_dir.iterdir() if p.is_file()]
        rows = []
        for i, name in enumerate(sorted(artifacts)[:12]):
            rows.append([InlineKeyboardButton(name[:28], callback_data=f"artifact:{i}")])
        rows.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])

        await self._send_message_or_edit(update, context, f"Report: {report_name}", reply_markup=InlineKeyboardMarkup(rows))

def main() -> None:
    import os
    
    # Load .env file (same pattern as other modules)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        logger.warning("python-dotenv not installed, using system environment variables only")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in environment or .env file. "
            f"Current values: BOT_TOKEN={'***' if bot_token else 'NOT SET'}, CHAT_ID={'***' if chat_id else 'NOT SET'}"
        )
    handler = TelegramCommandHandler(bot_token=bot_token, chat_id=chat_id)
    handler.run()

if __name__ == "__main__":
    main()
