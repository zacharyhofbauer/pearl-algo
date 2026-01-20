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
import os
import shutil
import subprocess
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
    from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logger.warning("python-telegram-bot not installed, command handler disabled")


# ---------------------------------------------------------------------------
# Optional OpenAI client imports (used by /ai_patch)
# ---------------------------------------------------------------------------
try:
    from pearlalgo.utils.openai_client import (
        OPENAI_AVAILABLE,
        OpenAIAPIError,
        OpenAIAPIKeyMissingError,
        OpenAIClient,
        OpenAINotAvailableError,
    )
except Exception:  # pragma: no cover - defensive fallback for minimal environments
    OPENAI_AVAILABLE = False
    OpenAIClient = None  # type: ignore[assignment]
    OpenAIAPIError = OpenAIAPIKeyMissingError = OpenAINotAvailableError = Exception  # type: ignore[misc,assignment]


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
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))

    def _count_open_challenge_positions(self) -> int:
        """Count open challenge positions from signals.jsonl file."""
        try:
            signals_file = self.state_dir / "signals.jsonl"
            if not signals_file.exists():
                return 0

            open_count = 0
            with open(signals_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            signal_data = json.loads(line.strip())
                            # Count signals that have entry_time but no exit_time
                            if (signal_data.get("entry_time") and
                                not signal_data.get("exit_time") and
                                signal_data.get("status") == "entered"):
                                open_count += 1
                        except json.JSONDecodeError:
                            continue
            return open_count
        except Exception as e:
            logger.warning(f"Error counting open challenge positions: {e}")
            return 0

    def _get_main_menu_keyboard(self) -> list:
        """Get the main menu keyboard layout with dynamic status indicators."""
        # Show quick preview of positions if available
        state = self._read_state()
        has_active = False
        positions = 0
        active_trades = 0
        daily_pnl = 0.0
        
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            # Also count open challenge positions
            challenge_positions = self._count_open_challenge_positions()
            total_active = positions + active_trades + challenge_positions
            has_active = total_active > 0
            daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)

        # Build dynamic button labels
        # Signals button - show count if active
        signals_label = "📡 Signals & Trades"
        if has_active:
            signals_label = f"⚡ Signals • {total_active} Open"
        
        # Performance button - show daily P&L
        performance_label = "📈 Performance"
        if daily_pnl != 0:
            pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
            pnl_sign = "+" if daily_pnl >= 0 else ""
            if abs(daily_pnl) >= 1000:
                pnl_display = f"{pnl_sign}${abs(daily_pnl)/1000:.1f}k"
            else:
                pnl_display = f"{pnl_sign}${abs(daily_pnl):.0f}"
            performance_label = f"📈 Performance {pnl_emoji}{pnl_display}"
        
        # Status button - show contextual info
        status_label = "🛰️ Status"
        if has_active:
            # Show position count when active
            status_label = f"🛰️ Status • {total_active} Active"
        elif state:
            # Show connection status when no positions
            connection_status = state.get("connection_status", "unknown")
            if connection_status == "connected":
                status_label = "🛰️ Status • Connected"
            elif connection_status == "disconnected":
                status_label = "🛰️ Status • Offline"
        
        # Bots button - show running status
        # Use same source of truth as main status (state file) for consistency
        bots_label = "👾 Bots"
        try:
            # First check state file (same as main status display)
            if state:
                agent_running = state.get("running", False)
                if agent_running:
                    bots_label = "👾 Bots • Running"
                else:
                    bots_label = "👾 Bots • Stopped"
            else:
                # Fallback to process check if state file not available
                sc = getattr(self, "service_controller", None)
                if sc is not None:
                    agent_status = sc.get_agent_status() or {}
                    if agent_status.get("running"):
                        bots_label = "👾 Bots • Running"
                    else:
                        bots_label = "👾 Bots • Stopped"
        except Exception:
            pass
        
        return [
            # Row 1: Signals + Performance
            [
                InlineKeyboardButton(signals_label, callback_data="menu:signals"),
                InlineKeyboardButton(performance_label, callback_data="menu:performance"),
            ],
            # Row 2: Status + quick actions + System
            [
                InlineKeyboardButton(status_label, callback_data="menu:status"),
                InlineKeyboardButton("🔄", callback_data="action:refresh_dashboard"),
                InlineKeyboardButton("📊", callback_data="action:toggle_chart"),
                InlineKeyboardButton("🎛️ System", callback_data="menu:system"),
            ],
            # Row 3: Bots
            [
                InlineKeyboardButton(bots_label, callback_data="menu:bots"),
            ],
            # Row 4: Settings + Help
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
                InlineKeyboardButton("💡 Help", callback_data="menu:help"),
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
                text = "🎯 Pearl Algo Bot's\n\nSelect an option:"
        else:
            # No state available, show simple menu
            text = "🎯 Pearl Algo Bot's\n\n❌ No state data available.\n\nSelect an option:"
        await update.message.reply_text(text, reply_markup=reply_markup)

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle plain text messages for AI patch wizard."""
        if not update.message:
            return
        if not await self._check_authorized(update):
            return

        text = str(update.message.text or "").strip()
        if not text:
            return

        state = None
        try:
            state = getattr(self, "_patch_wizard_state", {}).get("state")
        except Exception:
            state = None

        ai_state = None
        try:
            ai_state = getattr(self, "_ai_ops_state", {}).get("state")
        except Exception:
            ai_state = None

        if ai_state == "awaiting_aiops_file_text":
            rel_path = text
            if self._is_path_blocked(rel_path):
                await update.message.reply_text("❌ Blocked path. Send a different file path.")
                return
            self._ai_ops_state["file"] = rel_path
            self._ai_ops_state["state"] = "awaiting_aiops_instruction"
            await update.message.reply_text(
                "Send the instruction text now.\n\nExample:\nreduce stop_loss_pct by 0.002"
            )
            return

        if ai_state == "awaiting_aiops_instruction":
            rel_path = None
            try:
                rel_path = getattr(self, "_ai_ops_state", {}).get("file")
            except Exception:
                rel_path = None
            if not rel_path:
                await update.message.reply_text("No file selected. Tap AI Ops again.")
                return
            instruction = text
            self._ai_ops_state["instruction"] = instruction
            self._ai_ops_state["state"] = "generating"
            await self._run_ai_ops_patch(update, context)
            return

        if state == "awaiting_file_text":
            rel_path = text
            if self._is_path_blocked(rel_path):
                await update.message.reply_text("❌ Blocked path. Send a different file path.")
                return
            self._patch_wizard_state["file"] = rel_path
            self._patch_wizard_state["state"] = "awaiting_instruction"
            await update.message.reply_text(
                "Send the instruction text now.\n\nExample:\nadd jitter to retry backoff"
            )
            return

        if state == "awaiting_instruction":
            rel_path = None
            try:
                rel_path = getattr(self, "_patch_wizard_state", {}).get("file")
            except Exception:
                rel_path = None
            if not rel_path:
                await update.message.reply_text("No file selected. Tap AI Patch Wizard again.")
                return
            instruction = text
            self._patch_wizard_state["state"] = None
            await self._run_ai_patch(update, context, rel_path=rel_path, task=instruction)

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

        lines = ["AI Bot Report", f"Generated: {datetime.now(timezone.utc).isoformat()}"]

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
            lines.append("Bot recommendation:")
            if top:
                lines.append(f"- Top: {top.get('key')} (score {top.get('score', 0.0):.2f})")
                lines.append(f"- Trades: {top.get('count', 0)} | WR {top.get('win_rate', 0.0):.1%}")
                lines.append(f"- Max DD: {top.get('max_drawdown', 0.0):.2f}")
            else:
                lines.append("- No ranked bot found in selection report.")
        else:
            lines.append("")
            lines.append("No bot selection report found. Run:")
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
            # Telegram backtesting / strategy review flows
            if callback_data == "strategy_review:backtest":
                await self._render_pearl_backtest_menu(update, context)
                return
            if callback_data == "strategy_review:reports":
                await self._handle_backtest_reports(update, context, page=0)
                return
            if callback_data.startswith("reports:page:"):
                try:
                    page = int(callback_data.split(":")[-1])
                except Exception:
                    page = 0
                await self._handle_backtest_reports(update, context, page=page)
                return
            if callback_data.startswith("report:"):
                try:
                    report_idx = int(callback_data.split(":")[-1])
                except Exception:
                    report_idx = 0
                await self._handle_report_detail_by_idx(update, context, report_idx)
                return
            if callback_data.startswith("artifact:"):
                # artifact:<report_idx>:<artifact_idx>
                parts = callback_data.split(":")
                if len(parts) >= 3:
                    try:
                        report_idx = int(parts[1])
                    except Exception:
                        report_idx = 0
                    try:
                        artifact_idx = int(parts[2])
                    except Exception:
                        artifact_idx = 0
                    await self._handle_report_artifact_by_idx(update, context, report_idx, artifact_idx)
                    return

            if callback_data.startswith("pb:"):
                await self._handle_pearl_backtest_callback(update, context, callback_data)
                return

            if callback_data.startswith("patch:"):
                await self._handle_patch_callback(query, callback_data)
                return

            if callback_data.startswith("aiops:"):
                await self._handle_ai_ops_callback(query, callback_data)
                return

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
        elif action == "pearl_bots":
            await self._show_pearl_bots_menu(query)
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
                text = "🎯 Pearl Algo Bot's\n\nSelect an option:"
                await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            text = "🎯 Pearl Algo Bot's\n\n❌ No state data available.\n\nSelect an option:"
            await query.edit_message_text(text, reply_markup=reply_markup)

    async def _show_main_menu_with_chart(self, query: CallbackQuery) -> None:
        """Show the main menu with chart displayed above the menu text."""
        keyboard = self._get_main_menu_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        state = self._read_state()
        if state:
            try:
                message_text = await self._build_status_dashboard_message(state)
                chart_path = await self._generate_or_get_chart(state)
                
                if chart_path and chart_path.exists():
                    try:
                        message = query.message
                        # Check if message already has a photo
                        if message and message.photo:
                            # Message has photo, edit it
                            from telegram import InputMediaPhoto
                            with open(chart_path, 'rb') as f:
                                await query.edit_message_media(
                                    media=InputMediaPhoto(
                                        media=f,
                                        caption=message_text,
                                        parse_mode="Markdown"
                                    ),
                                    reply_markup=reply_markup
                                )
                        else:
                            # Message doesn't have photo, delete and send new one with photo
                            try:
                                await query.message.delete()
                            except Exception:
                                pass
                            # Send new message with photo
                            with open(chart_path, 'rb') as f:
                                sent_message = await query.message.chat.send_photo(
                                    photo=f,
                                    caption=message_text,
                                    reply_markup=reply_markup,
                                    parse_mode="Markdown"
                                )
                            await query.answer()  # Acknowledge the callback
                    except Exception as e:
                        logger.error(f"Error showing chart: {e}", exc_info=True)
                        # Fallback to text only
                        message = query.message
                        if message and message.photo:
                            # If we have a photo message, delete it first
                            try:
                                await message.delete()
                            except Exception:
                                pass
                            await message.chat.send_message(
                                text=message_text,
                                reply_markup=reply_markup,
                                parse_mode="Markdown"
                            )
                            await query.answer()
                        else:
                            await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    # No chart available - just show text menu quickly
                    message = query.message
                    if message and message.photo:
                        # If we have a photo message, delete it first
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        await message.chat.send_message(
                            text=message_text,
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                        await query.answer()
                    else:
                        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Error showing main menu with chart: {e}", exc_info=True)
                await self._show_main_menu(query)
        else:
            text = "🎯 Pearl Algo Bot's\n\n❌ No state data available.\n\nSelect an option:"
            message = query.message
            if message and message.photo:
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.chat.send_message(text=text, reply_markup=reply_markup)
                await query.answer()
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup)

    async def _toggle_chart_display(self, query: CallbackQuery) -> None:
        """Toggle chart display on/off."""
        try:
            message = query.message
            # Check if message currently has a photo (chart is showing)
            if message and message.photo:
                # Chart is showing, hide it (show text only)
                # Need to delete photo message and send text message
                try:
                    await message.delete()
                except Exception:
                    pass
                # Send new text message
                keyboard = self._get_main_menu_keyboard()
                reply_markup = InlineKeyboardMarkup(keyboard)
                state = self._read_state()
                if state:
                    try:
                        message_text = await self._build_status_dashboard_message(state)
                        await message.chat.send_message(
                            text=message_text,
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Error sending text message: {e}", exc_info=True)
                        text = "🎯 Pearl Algo Bot's\n\nSelect an option:"
                        await message.chat.send_message(text=text, reply_markup=reply_markup)
                else:
                    text = "🎯 Pearl Algo Bot's\n\n❌ No state data available.\n\nSelect an option:"
                    await message.chat.send_message(text=text, reply_markup=reply_markup)
                await query.answer()
            else:
                # Chart is not showing, show it
                await self._show_main_menu_with_chart(query)
        except Exception as e:
            logger.error(f"Error toggling chart: {e}", exc_info=True)
            await self._show_main_menu(query)

    async def _generate_or_get_chart(self, state: dict) -> Optional[Path]:
        """Generate chart on-demand using IBKR data."""
        import asyncio
        try:
            # First check if there's a recent exported chart (faster)
            chart_path = self.exports_dir / "dashboard_latest.png"
            if chart_path.exists():
                import time
                age = time.time() - chart_path.stat().st_mtime
                if age < 300:  # Use cached chart if < 5 minutes old
                    return chart_path
            
            # Generate fresh chart
            from datetime import timedelta
            import pandas as pd
            from pearlalgo.nq_agent.chart_generator import ChartGenerator
            from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
            from pearlalgo.config.config_loader import load_service_config
            from pearlalgo.utils.volume_pressure import timeframe_to_minutes
            
            symbol = state.get("symbol") or "MNQ"
            
            # Read chart settings from config.yaml (same source as the service chart push)
            svc_cfg = load_service_config()
            service_cfg = (svc_cfg.get("service", {}) or {}) if isinstance(svc_cfg, dict) else {}
            min_lookback_hours = 6.0
            max_lookback_hours = 24.0
            lookback_hours = float(service_cfg.get("dashboard_chart_lookback_hours", 8) or 8)
            if lookback_hours < min_lookback_hours:
                lookback_hours = min_lookback_hours
            if lookback_hours > max_lookback_hours:
                lookback_hours = max_lookback_hours

            chart_tf_pref = str(service_cfg.get("dashboard_chart_timeframe", "auto") or "auto").strip().lower()
            max_bars = int(service_cfg.get("dashboard_chart_max_bars", 420) or 420)

            def _choose_timeframe(hours: float, max_bars_local: int) -> str:
                # Keep candle count under max_bars for readability (same candidates as service).
                candidates = ["5m", "15m", "30m", "1h"]
                if chart_tf_pref in candidates:
                    return chart_tf_pref
                for tf in candidates:
                    mins = timeframe_to_minutes(tf) or 0
                    if mins <= 0:
                        continue
                    bars = int((hours * 60.0) / float(mins))
                    if bars <= max_bars_local:
                        return tf
                return "1h"

            chosen_tf = _choose_timeframe(lookback_hours, max_bars)
            tf_mins = float(timeframe_to_minutes(chosen_tf) or 5)
            bars_target = int((lookback_hours * 60.0) / tf_mins)
            bars_target = max(20, min(max_bars, bars_target))  # keep sane bounds
            
            # Create provider (executor manages connection automatically)
            provider = IBKRProvider(client_id=99)  # Use different client ID
            try:
                # Validate connection (this ensures executor is connected)
                connected = await provider.validate_connection()
                if not connected:
                    logger.warning("Could not connect to IBKR for chart generation")
                    # Fallback to cached chart
                    if chart_path.exists():
                        return chart_path
                    return None
                
                end = datetime.now(timezone.utc)
                start = end - timedelta(hours=lookback_hours)
                
                # fetch_historical is synchronous but handles its own event loop
                # Run in thread to avoid blocking
                df = await asyncio.to_thread(
                    provider.fetch_historical,
                    symbol,
                    start,
                    end,
                    chosen_tf,
                )
                
                if df is None or df.empty or len(df) < 20:
                    logger.debug(f"Not enough data for chart: {len(df) if df is not None else 0} bars")
                    # Fallback to cached chart
                    if chart_path.exists():
                        return chart_path
                    return None
                
                # Generate chart
                chart_gen = ChartGenerator()
                try:
                    right_pad_bars = int(service_cfg.get("dashboard_chart_right_pad_bars", 40) or 40)
                except Exception:
                    right_pad_bars = 40
                chart_gen.config.right_pad_bars = max(0, right_pad_bars)
                
                # Get recent trades for markers
                trades = self._get_trades_for_chart(df, symbol)
                
                # Label range (best-effort, compact)
                try:
                    hrs = float(lookback_hours)
                    range_label = f"{int(round(hrs))}h" if hrs < 72 else f"{int(round(hrs / 24.0))}d"
                except Exception:
                    range_label = None

                chart_path = chart_gen.generate_dashboard_chart(
                    data=df,
                    symbol=symbol,
                    timeframe=chosen_tf,
                    lookback_bars=min(int(bars_target), len(df)),
                    range_label=range_label or "Dashboard",
                    figsize=(14, 6),
                    dpi=120,
                    show_sessions=True,  # Show Tokyo/London/NY session shading
                    show_key_levels=True,  # Show RTH/ETH PDH/PDL/Open levels
                    show_vwap=True,  # Show VWAP line + bands
                    show_ma=True,  # Show moving averages
                    ma_periods=[20, 50, 200],  # MA20, MA50, MA200
                    show_rsi=True,  # Show RSI panel
                    show_pressure=True,  # Always show buy/sell pressure in menu chart
                    trades=trades,  # Overlay trade markers
                )
                
                # Save to exports for caching
                if chart_path and chart_path.exists():
                    self.exports_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    export_path = self.exports_dir / "dashboard_latest.png"
                    shutil.copy2(chart_path, export_path)
                    return export_path
                
                return chart_path
            finally:
                try:
                    await provider.close()
                except Exception:
                    pass
                    
        except Exception as e:
            logger.error(f"Error generating chart: {e}", exc_info=True)
            # Fallback to cached chart if available
            chart_path = self.exports_dir / "dashboard_latest.png"
            if chart_path.exists():
                return chart_path
            return None

    async def _show_status_menu(self, query: CallbackQuery) -> None:
        """Show status submenu with inline indicators."""
        # Show quick status preview
        state = self._read_state()
        preview = ""
        positions_label = "🎯 Positions & Trades"
        gateway_label = "🔌 Gateway"
        connection_label = "📡 Connection"
        
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            latest_price = state.get("latest_price")
            connection_status = state.get("connection_status", "unknown")
            
            preview = "\n"
            if latest_price:
                preview += f"💰 Price: ${latest_price:,.2f}\n"
            preview += f"🎯 Positions: {positions} | Active: {active_trades}\n"
            
            # Add inline stats to buttons
            total_active = positions + active_trades
            if total_active > 0:
                positions_label = f"🎯 Positions • {total_active} Active"
            
            # Gateway/Connection status
            if connection_status == "connected":
                gateway_label = "🔌 Gateway • 🟢 Online"
                connection_label = "📡 Connection • 🟢 Online"
            elif connection_status == "disconnected":
                gateway_label = "🔌 Gateway • 🔴 Offline"
                connection_label = "📡 Connection • 🔴 Offline"
        
        keyboard = [
            [InlineKeyboardButton("📊 System Status", callback_data="action:system_status")],
            [
                InlineKeyboardButton(positions_label, callback_data="action:active_trades"),
                InlineKeyboardButton(gateway_label, callback_data="action:gateway_status"),
            ],
            [
                InlineKeyboardButton(connection_label, callback_data="action:connection_status"),
                InlineKeyboardButton("💾 Data Quality", callback_data="action:data_quality"),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"🛰️ Status & Monitoring{preview}\nSelect an option:", reply_markup=reply_markup)

    async def _show_signals_menu(self, query: CallbackQuery) -> None:
        """Show signals & trades submenu with rich context and smart suggestions."""
        try:
            # Get comprehensive state for context
            state = self._read_state()
            active_count = 0
            daily_signals = 0
            current_pnl = 0.0
            
            if state:
                positions = (state.get("execution", {}).get("positions", 0) or 0)
                active_trades = state.get("active_trades_count", 0) or 0
                active_count = positions + active_trades
                daily_signals = state.get("daily_signals", 0) or 0
                current_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
            
            # Read recent signals for analysis
            signals = self._read_recent_signals(limit=10)
            recent_count = len(signals) if signals else 0
            
            # Build rich context message
            lines = ["⚡ *Signals & Trades*", ""]
            
            # Session overview
            if state:
                lines.append("*Today's Activity:*")
                lines.append(f"• Signals Generated: {daily_signals}")
                lines.append(f"• Currently Open: {active_count}")
                if current_pnl != 0:
                    pnl_emoji = "🟢" if current_pnl >= 0 else "🔴"
                    pnl_sign = "+" if current_pnl >= 0 else ""
                    lines.append(f"• Today's P&L: {pnl_emoji} {pnl_sign}${abs(current_pnl):.2f}")
                lines.append("")
            
            # Smart suggestions based on state
            suggestions = []
            if active_count > 0:
                suggestions.append("💡 *Tip:* Check active trades to monitor positions")
            elif recent_count > 0 and active_count == 0:
                suggestions.append("💡 *Notice:* Recent signals available but no active trades")
            elif recent_count == 0:
                suggestions.append("💡 *Status:* Waiting for new signal opportunities")
            
            if suggestions:
                lines.extend(suggestions)
                lines.append("")
            
            lines.append("*Select an option:*")
            
            # Build button labels with counts
            active_label = f"📋 Active Trades • {active_count}" if active_count > 0 else "📋 Active Trades"
            recent_label = f"🎯 Recent Signals • {recent_count}" if recent_count > 0 else "🎯 Recent Signals"
            
            # Conditional buttons based on state
            keyboard = [
                # Row 1: Current Activity
                [
                    InlineKeyboardButton(recent_label, callback_data="action:recent_signals"),
                    InlineKeyboardButton(active_label, callback_data="action:active_trades"),
                ],
                # Row 2: Historical Data
                [
                    InlineKeyboardButton("📊 Signal History", callback_data="action:signal_history"),
                    InlineKeyboardButton("🔍 Signal Details", callback_data="action:signal_details"),
                ],
            ]
            
            # Row 3: Contextual Actions
            if active_count > 0:
                keyboard.append([
                    InlineKeyboardButton(f"🚫 Close All ({active_count})", callback_data="action:close_all_trades"),
                    InlineKeyboardButton("🔄 Refresh", callback_data="menu:signals"),
                ])
            else:
                keyboard.append([
                    InlineKeyboardButton("🔄 Refresh", callback_data="menu:signals"),
                ])
            
            # Row 4: Navigation
            keyboard.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in _show_signals_menu: {e}", exc_info=True)
            # Fallback to simple menu
            keyboard = [
                [
                    InlineKeyboardButton("🎯 Recent Signals", callback_data="action:recent_signals"),
                    InlineKeyboardButton("📋 Active Trades", callback_data="action:active_trades"),
                ],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await query.edit_message_text("⚡ Signals & Trades\n\nSelect an option:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_performance_menu(self, query: CallbackQuery) -> None:
        """Show performance submenu with trends, comparisons, and insights."""
        try:
            # Get comprehensive performance data
            state = self._read_state()
            metrics = self._read_latest_metrics()
            
            # Build rich performance overview
            lines = ["💎 *Performance Dashboard*", ""]
            
            # Today's Performance
            if state:
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                daily_trades = state.get("daily_trades", 0) or 0
                daily_wins = state.get("daily_wins", 0) or 0
                daily_losses = state.get("daily_losses", 0) or 0
                
                lines.append("*Today:*")
                if daily_pnl != 0:
                    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                    pnl_sign = "+" if daily_pnl >= 0 else ""
                    # Add trend indicator
                    trend = "↗️" if daily_pnl > 0 else "↘️" if daily_pnl < 0 else "→"
                    lines.append(f"{pnl_emoji} P&L: {trend} {pnl_sign}${abs(daily_pnl):.2f}")
                else:
                    lines.append("• P&L: $0.00")
                
                if daily_trades > 0:
                    win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
                    wr_emoji = "🟢" if win_rate >= 50 else "🟡" if win_rate >= 40 else "🔴"
                    lines.append(f"• Trades: {daily_trades} ({daily_wins}W/{daily_losses}L)")
                    lines.append(f"• Win Rate: {wr_emoji} {win_rate:.0f}%")
                lines.append("")
            
            # Overall Performance (if metrics available)
            if metrics:
                total_trades = metrics.get("exited_signals", 0)
                total_pnl = float(metrics.get("total_pnl", 0.0) or 0.0)
                win_rate = float(metrics.get("win_rate", 0.0) or 0.0) * 100
                
                lines.append("*Overall:*")
                lines.append(f"• Total Trades: {total_trades}")
                if total_pnl != 0:
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    pnl_sign = "+" if total_pnl >= 0 else ""
                    lines.append(f"• Total P&L: {pnl_emoji} {pnl_sign}${abs(total_pnl):.2f}")
                if total_trades > 0:
                    wr_emoji = "🟢" if win_rate >= 50 else "🟡" if win_rate >= 40 else "🔴"
                    lines.append(f"• Win Rate: {wr_emoji} {win_rate:.1f}%")
                lines.append("")
            
            # Smart insights
            insights = []
            if state:
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                if daily_pnl < 0 and abs(daily_pnl) > 100:
                    insights.append("⚠️ *Alert:* Significant daily loss - consider reviewing strategy")
                elif daily_pnl > 200:
                    insights.append("✨ *Great:* Strong daily performance!")
            
            if metrics:
                win_rate = float(metrics.get("win_rate", 0.0) or 0.0) * 100
                if win_rate < 40:
                    insights.append("💡 *Tip:* Win rate below 40% - review signal quality")
                elif win_rate > 60:
                    insights.append("🎯 *Excellent:* Win rate above 60%!")
            
            if insights:
                lines.extend(insights)
                lines.append("")
            
            lines.append("*Select a report:*")
            
            # Build dynamic button labels
            daily_pnl_label = "📊 Daily Summary"
            pnl_overview_label = "💰 P&L Overview"
            metrics_label = "📈 Performance Metrics"
            
            if state:
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                if daily_pnl != 0:
                    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                    pnl_sign = "+" if daily_pnl >= 0 else ""
                    daily_pnl_label = f"📊 Daily {pnl_emoji}{pnl_sign}${abs(daily_pnl):.0f}"
                    pnl_overview_label = f"💰 P&L {pnl_emoji}{pnl_sign}${abs(daily_pnl):.0f}"
            
            if metrics:
                total_trades = metrics.get("exited_signals", 0)
                metrics_label = f"📈 Metrics • {total_trades} Trades"
            
            keyboard = [
                # Row 1: Core Metrics
                [
                    InlineKeyboardButton(metrics_label, callback_data="action:performance_metrics"),
                    InlineKeyboardButton(pnl_overview_label, callback_data="action:pnl_overview"),
                ],
                # Row 2: Time-based Reports
                [
                    InlineKeyboardButton(daily_pnl_label, callback_data="action:daily_summary"),
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
            await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in _show_performance_menu: {e}", exc_info=True)
            # Fallback to simple menu
            keyboard = [
                [
                    InlineKeyboardButton("📈 Performance Metrics", callback_data="action:performance_metrics"),
                    InlineKeyboardButton("💰 P&L Overview", callback_data="action:pnl_overview"),
                ],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await query.edit_message_text("💎 Performance\n\nSelect an option:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_bots_menu(self, query: CallbackQuery) -> None:
        """Show Pearl Bot control menu with comprehensive status and diagnostics."""
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
        gateway_ready = bool(gateway_status.get("process_running")) and bool(gateway_status.get("port_listening"))
        
        # Get additional context
        state = self._read_state()
        uptime_info = ""
        connection_info = ""
        trading_info = ""
        
        if state:
            # Connection status
            connection_status = state.get("connection_status", "unknown")
            if connection_status == "connected":
                connection_info = "🟢 Connected to market data"
            else:
                connection_info = "🔴 Not connected to market"
            
            # Trading activity
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            daily_signals = state.get("daily_signals", 0) or 0
            
            if positions + active_trades > 0:
                trading_info = f"📊 {positions + active_trades} active position(s), {daily_signals} signals today"
            elif daily_signals > 0:
                trading_info = f"📊 {daily_signals} signal(s) generated today"
            else:
                trading_info = "📊 No signals today yet"
        
        # Build rich status display
        lines = ["👾 *Pearl Bots*", ""]
        
        # Service Status
        lines.append("*Service Status:*")
        agent_emoji = "🟢" if running else "🔴"
        agent_line = "RUNNING" if running else "STOPPED"
        lines.append(f"{agent_emoji} Agent: {agent_line}")
        
        gateway_emoji = "🟢" if gateway_ready else "🔴"
        gateway_line = "READY" if gateway_ready else "NOT READY"
        lines.append(f"{gateway_emoji} Gateway: {gateway_line}")
        lines.append("")
        
        # Diagnostics
        lines.append("*Diagnostics:*")
        if connection_info:
            lines.append(f"• {connection_info}")
        if trading_info:
            lines.append(f"• {trading_info}")
        lines.append("")
        
        # Health Check & Recommendations
        health_status = []
        recommendations = []
        
        if running and gateway_ready and state and state.get("connection_status") == "connected":
            health_status.append("✅ *System Health:* All systems operational")
        else:
            health_status.append("⚠️ *System Health:* Issues detected")
            
            if not running:
                recommendations.append("💡 Start the agent to begin trading")
            if not gateway_ready:
                recommendations.append("💡 Check gateway connection")
            if state and state.get("connection_status") != "connected":
                recommendations.append("💡 Verify market data connection")
        
        if health_status:
            lines.extend(health_status)
        
        if recommendations:
            lines.append("")
            lines.extend(recommendations)
        
        lines.append("")
        lines.append("*Control Options:*")

        # Dynamic button labels
        start_label = "🚀 Start Agent" if not running else "🚀 Start Agent (Already Running)"
        stop_label = "🛑 Stop Agent"
        restart_label = "🔄 Restart Agent"

        if running:
            stop_label = "🛑 Stop Agent"
            restart_label = "🔄 Restart Agent"

        keyboard = [
            [
                InlineKeyboardButton(start_label, callback_data="action:start_agent"),
                InlineKeyboardButton(stop_label, callback_data="action:stop_agent"),
            ],
            [
                InlineKeyboardButton(restart_label, callback_data="action:restart_agent"),
                InlineKeyboardButton("🤖 Pearl Bots", callback_data="menu:pearl_bots"),
            ],
            [
                InlineKeyboardButton("🧠 AI Ops", callback_data="action:ai_ops"),
            ],
            [
                InlineKeyboardButton("🧪 Backtest Bots", callback_data="strategy_review:backtest"),
                InlineKeyboardButton("📑 Backtest Reports", callback_data="strategy_review:reports"),
            ],
            [
                InlineKeyboardButton("🔄 Refresh Status", callback_data="menu:bots"),
                InlineKeyboardButton("🏠 Back to Menu", callback_data="back"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")

    async def _show_pearl_bots_menu(self, query: CallbackQuery) -> None:
        """Show Pearl automated trading bots submenu with status and controls."""
        try:
            # Import pearl bot manager
            from pearlalgo.strategies.pearl_bots_integration import get_pearl_bot_manager

            bot_manager = get_pearl_bot_manager()
            active_bots = bot_manager.get_active_bots()
            bot_performance = bot_manager.get_bot_performance()

            lines = ["🤖 *PEARL Automated Trading Bots*", ""]

            # Overall status
            total_bots = len(bot_performance) if isinstance(bot_performance, dict) else 0
            active_count = len(active_bots)

            lines.append(f"*System Status:* {active_count}/{total_bots} bots active")
            lines.append("")

            # Individual bot status
            if isinstance(bot_performance, dict) and bot_performance:
                lines.append("*Bot Performance:*")

                for bot_name, perf in bot_performance.items():
                    if isinstance(perf, dict):
                        # Extract key metrics
                        total_signals = perf.get('total_signals_history', 0)
                        win_rate = perf.get('performance', {}).get('win_rate', 0) * 100
                        total_pnl = perf.get('performance', {}).get('total_pnl', 0)
                        active_positions = perf.get('active_signals', 0)

                        # Status indicator
                        is_active = bot_name in active_bots
                        status_emoji = "🟢" if is_active else "🔴"
                        status_text = "Active" if is_active else "Inactive"

                        # Format bot info
                        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                        pnl_sign = "+" if total_pnl >= 0 else ""

                        lines.append(f"{status_emoji} *{bot_name}*")
                        lines.append(f"  └─ Status: {status_text}")
                        lines.append(f"  └─ Signals: {total_signals}, Win Rate: {win_rate:.1f}%")
                        lines.append(f"  └─ P&L: {pnl_emoji} {pnl_sign}${abs(total_pnl):.2f}")
                        lines.append(f"  └─ Active Positions: {active_positions}")
                        lines.append("")

            else:
                lines.append("❌ *No bots configured*")
                lines.append("Add pearl_bots configuration to your config.yaml")
                lines.append("")

            lines.append("*Bot Controls:*")

            # Control buttons
            keyboard = [
                [
                    InlineKeyboardButton("🚀 Start All Bots", callback_data="action:start_all_bots"),
                    InlineKeyboardButton("🛑 Stop All Bots", callback_data="action:stop_all_bots"),
                ],
                [
                    InlineKeyboardButton("📊 Bot Performance", callback_data="action:show_bot_performance"),
                    InlineKeyboardButton("🔄 Refresh Status", callback_data="menu:pearl_bots"),
                ],
                [InlineKeyboardButton("🏠 Back to Bots", callback_data="menu:bots")],
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error showing pearl bots menu: {e}", exc_info=True)
            error_msg = "❌ *Error loading Pearl Bots menu*"
            keyboard = [[InlineKeyboardButton("🏠 Back to Bots", callback_data="menu:bots")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(error_msg, reply_markup=reply_markup, parse_mode="Markdown")

    async def _show_system_menu(self, query: CallbackQuery) -> None:
        """Show system control submenu with comprehensive risk warnings and status."""
        # Get system state for context
        state = self._read_state()
        agent_running = False
        has_positions = False
        positions_count = 0
        daily_pnl = 0.0
        
        try:
            sc = getattr(self, "service_controller", None)
            if sc is not None:
                agent_status = sc.get_agent_status() or {}
                agent_running = bool(agent_status.get("running"))
        except Exception:
            pass
        
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            positions_count = positions + active_trades
            has_positions = positions_count > 0
            daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
        
        # Build comprehensive context
        lines = ["🎛️ *System Control Panel*", ""]
        
        # Current Status
        lines.append("*System Status:*")
        agent_emoji = "🟢" if agent_running else "🔴"
        lines.append(f"{agent_emoji} Agent: {'Running' if agent_running else 'Stopped'}")
        if has_positions:
            lines.append(f"⚠️ Active Positions: {positions_count}")
            if daily_pnl != 0:
                pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                pnl_sign = "+" if daily_pnl >= 0 else ""
                lines.append(f"{pnl_emoji} Today's P&L: {pnl_sign}${abs(daily_pnl):.2f}")
        lines.append("")
        
        # Risk Warnings
        warnings = []
        if has_positions and positions_count > 0:
            warnings.append("⚠️ *WARNING:* Stopping agent with open positions is risky")
            warnings.append("💡 *Tip:* Close positions first or use Emergency Stop")
        
        if daily_pnl < -100:
            warnings.append(f"⚠️ *ALERT:* Daily loss exceeds $100 (${daily_pnl:.2f})")
        
        if warnings:
            lines.extend(warnings)
            lines.append("")
        
        # Time-based suggestions
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        hour = now.hour
        
        # Market hours context (futures trade nearly 24/7, but peak hours are important)
        if 13 <= hour < 21:  # US market hours (UTC)
            lines.append("🕐 *Market:* US hours - High activity period")
        elif 0 <= hour < 8:  # Asian session
            lines.append("🕐 *Market:* Asian session - Lower volatility")
        else:
            lines.append("🕐 *Market:* Off-peak hours")
        
        lines.append("")
        lines.append("⚠️ *CAUTION:* These actions affect live trading")
        lines.append("*Select an action:*")
        
        # Build dynamic buttons based on state
        start_label = "🚀 Start Agent"
        stop_label = "🛑 Stop Agent"
        emergency_label = "🚨 Emergency Stop"
        
        if not agent_running:
            start_label = "🚀 Start Agent"
        else:
            stop_label = f"🛑 Stop Agent" if not has_positions else f"🛑 Stop ({positions_count} open)"
        
        if has_positions:
            emergency_label = f"🚨 Emergency Stop ({positions_count})"
        
        keyboard = [
            # Row 1: Trading Agent Control
            [
                InlineKeyboardButton(start_label, callback_data="action:start_agent"),
                InlineKeyboardButton(stop_label, callback_data="action:stop_agent"),
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
        ]
        
        # Row 5: Emergency (only show if positions exist OR agent is running)
        if has_positions or agent_running:
            keyboard.append([
                InlineKeyboardButton(emergency_label, callback_data="action:emergency_stop"),
            ])
        
        # Row 6: Navigation
        keyboard.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")


    async def _show_settings_menu(self, query: CallbackQuery) -> None:
        """Show settings submenu with detailed descriptions and recommendations."""
        prefs = TelegramPrefs(state_dir=self.state_dir)
        auto_chart = bool(prefs.get("auto_chart_on_signal", False))
        interval_notifications = bool(prefs.get("interval_notifications", True))
        dashboard_buttons = bool(prefs.get("dashboard_buttons", False))
        signal_detail_expanded = bool(prefs.get("signal_detail_expanded", False))

        def _onoff(v: bool) -> str:
            return "🟢 ON" if v else "🔴 OFF"

        lines = ["⚙️ *Telegram Settings*", ""]
        
        # Current Configuration
        lines.append("*Current Settings:*")
        lines.append(f"📈 Auto-Chart: {_onoff(auto_chart)}")
        lines.append(f"🕐 Interval Notifications: {_onoff(interval_notifications)}")
        lines.append(f"🔘 Dashboard Buttons: {_onoff(dashboard_buttons)}")
        lines.append(f"🔍 Signal Details: {_onoff(signal_detail_expanded)}")
        lines.append("")
        
        # Helpful explanations
        lines.append("*What These Do:*")
        lines.append("📈 *Auto-Chart:* Send chart image with each signal")
        lines.append("🕐 *Interval:* Regular status updates every 30min")
        lines.append("🔘 *Buttons:* Show action buttons in notifications")
        lines.append("🔍 *Details:* Show full technical details in signals")
        lines.append("")
        
        # Smart recommendations
        recommendations = []
        if not auto_chart:
            recommendations.append("💡 *Tip:* Enable Auto-Chart for visual signal confirmation")
        if not interval_notifications:
            recommendations.append("💡 *Notice:* Interval notifications are off - you'll only get signal alerts")
        if auto_chart and interval_notifications:
            recommendations.append("✅ *Optimal:* Recommended settings enabled")
        
        if recommendations:
            lines.extend(recommendations)
            lines.append("")
        
        lines.append("*Tap to toggle:*")

        keyboard = [
            [
                InlineKeyboardButton(
                    f"📈 Chart: {_onoff(auto_chart)}",
                    callback_data="action:toggle_pref:auto_chart_on_signal",
                ),
                InlineKeyboardButton(
                    f"🕐 Updates: {_onoff(interval_notifications)}",
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
            [
                InlineKeyboardButton("🧩 AI Patch Wizard", callback_data="action:ai_patch_wizard"),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _ensure_openai_ready(self, target: Any) -> bool:
        """Ensure OpenAI dependency and API key are set."""
        if not OPENAI_AVAILABLE:
            msg = "❌ OpenAI Not Available (dependency not installed).\n\nInstall with: pip install -e '.[llm]'"
        elif not os.environ.get("OPENAI_API_KEY"):
            msg = "❌ OPENAI_API_KEY is not set."
        else:
            return True

        if hasattr(target, "edit_message_text"):
            await target.edit_message_text(msg)
        elif hasattr(target, "message") and getattr(target, "message", None):
            await target.message.reply_text(msg)
        elif hasattr(target, "reply_text"):
            await target.reply_text(msg)
        return False

    async def _show_ai_patch_wizard(self, query: CallbackQuery) -> None:
        """Show AI patch wizard with file selection buttons."""
        if not await self._ensure_openai_ready(query):
            return
        try:
            # Best-effort: store wizard state on instance-scoped dict
            if not hasattr(self, "_patch_wizard_state"):
                self._patch_wizard_state = {}
            self._patch_wizard_state["state"] = "awaiting_file"
            self._patch_wizard_state.pop("file", None)
        except Exception:
            pass

        lines = ["🧩 *AI Patch Wizard*", "", "Select a file:"]
        keyboard = [
            [InlineKeyboardButton("src/pearlalgo/utils/retry.py", callback_data="patch:file:src/pearlalgo/utils/retry.py")],
            [InlineKeyboardButton("src/pearlalgo/nq_agent/telegram_command_handler.py", callback_data="patch:file:src/pearlalgo/nq_agent/telegram_command_handler.py")],
            [InlineKeyboardButton("src/pearlalgo/nq_agent/service.py", callback_data="patch:file:src/pearlalgo/nq_agent/service.py")],
            [InlineKeyboardButton("config/config.yaml", callback_data="patch:file:config/config.yaml")],
            [InlineKeyboardButton("docs/AI_PATCH_GUIDE.md", callback_data="patch:file:docs/AI_PATCH_GUIDE.md")],
            [InlineKeyboardButton("Other file (type path)", callback_data="patch:other")],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _handle_patch_callback(self, query: CallbackQuery, callback_data: str) -> None:
        """Handle AI patch wizard callbacks."""
        if not hasattr(self, "_patch_wizard_state"):
            self._patch_wizard_state = {}

        if callback_data.startswith("patch:file:"):
            rel_path = callback_data[len("patch:file:") :]
            if self._is_path_blocked(rel_path):
                await query.edit_message_text("❌ Blocked path. Pick a different file.")
                return
            self._patch_wizard_state["file"] = rel_path
            self._patch_wizard_state["state"] = "awaiting_instruction"
            await query.edit_message_text(
                "Send the instruction text now.\n\nExample:\nadd jitter to retry backoff"
            )
            return

    async def _show_ai_ops_menu(self, query: CallbackQuery) -> None:
        """Show AI ops menu for bot selection."""
        if not await self._ensure_openai_ready(query):
            return
        try:
            from pearlalgo.strategies.pearl_bots_integration import get_pearl_bot_manager
            bot_manager = get_pearl_bot_manager()
            bot_names = list(bot_manager.bot_configs.keys())
        except Exception:
            bot_names = []

        lines = ["🧠 *AI Ops*", "", "Select a bot:"]
        keyboard = []
        for name in bot_names[:8]:
            keyboard.append([InlineKeyboardButton(name, callback_data=f"aiops:bot:{name}")])
        keyboard.append([InlineKeyboardButton("NQ Agent", callback_data="aiops:bot:nq_agent")])
        keyboard.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])

        if not hasattr(self, "_ai_ops_state"):
            self._ai_ops_state = {}
        self._ai_ops_state.clear()
        self._ai_ops_state["state"] = "awaiting_bot"

        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _handle_ai_ops_callback(self, query: CallbackQuery, callback_data: str) -> None:
        """Handle AI ops wizard callbacks."""
        if not hasattr(self, "_ai_ops_state"):
            self._ai_ops_state = {}

        if callback_data.startswith("aiops:bot:"):
            bot = callback_data[len("aiops:bot:") :]
            self._ai_ops_state["bot"] = bot
            self._ai_ops_state["state"] = "awaiting_scope"
            keyboard = [
                [InlineKeyboardButton("Config change", callback_data="aiops:scope:config")],
                [InlineKeyboardButton("Code change", callback_data="aiops:scope:code")],
                [InlineKeyboardButton("Both (config+code)", callback_data="aiops:scope:both")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await query.edit_message_text(
                f"Bot: `{bot}`\n\nSelect change scope:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        if callback_data.startswith("aiops:scope:"):
            scope = callback_data[len("aiops:scope:") :]
            self._ai_ops_state["scope"] = scope
            if scope == "config":
                self._ai_ops_state["file"] = "config/config.yaml"
                self._ai_ops_state["state"] = "awaiting_aiops_instruction"
                await query.edit_message_text(
                    "Send the instruction text now.\n\nExample:\nreduce stop_loss_pct by 0.002"
                )
                return

            lines = ["Select a file:"]
            keyboard = [
                [InlineKeyboardButton("src/pearlalgo/strategies/pearl_bots/bot_template.py", callback_data="aiops:file:src/pearlalgo/strategies/pearl_bots/bot_template.py")],
                [InlineKeyboardButton("src/pearlalgo/strategies/pearl_bots_integration.py", callback_data="aiops:file:src/pearlalgo/strategies/pearl_bots_integration.py")],
                [InlineKeyboardButton("src/pearlalgo/strategies/pearl_bots/market_regime_detector.py", callback_data="aiops:file:src/pearlalgo/strategies/pearl_bots/market_regime_detector.py")],
                [InlineKeyboardButton("config/config.yaml", callback_data="aiops:file:config/config.yaml")],
                [InlineKeyboardButton("Other file (type path)", callback_data="aiops:other")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            self._ai_ops_state["state"] = "awaiting_aiops_file"
            await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        if callback_data.startswith("aiops:file:"):
            rel_path = callback_data[len("aiops:file:") :]
            if self._is_path_blocked(rel_path):
                await query.edit_message_text("❌ Blocked path. Pick a different file.")
                return
            self._ai_ops_state["file"] = rel_path
            self._ai_ops_state["state"] = "awaiting_aiops_instruction"
            await query.edit_message_text(
                "Send the instruction text now.\n\nExample:\nreduce stop_loss_pct by 0.002"
            )
            return

        if callback_data == "aiops:other":
            self._ai_ops_state["state"] = "awaiting_aiops_file_text"
            self._ai_ops_state.pop("file", None)
            await query.edit_message_text(
                "Send the file path now.\n\nExample:\nsrc/pearlalgo/strategies/pearl_bots/bot_template.py"
            )
            return

        if callback_data == "aiops:accept":
            await self._apply_ai_ops_patch(query)
            return

        if callback_data == "aiops:decline":
            self._ai_ops_state.clear()
            await query.edit_message_text("Declined. No changes applied.")
            return

        if callback_data.startswith("aiops:restart:"):
            action = callback_data.split(":")[-1]
            await self._handle_ai_ops_restart(query, action)
            return

    def _load_ai_ops_memory(self) -> dict:
        path = self.state_dir / "ai_ops_memory.json"
        if not path.exists():
            return {"entries": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"entries": []}

    def _save_ai_ops_memory(self, memory: dict) -> None:
        path = self.state_dir / "ai_ops_memory.json"
        try:
            path.write_text(json.dumps(memory, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def _run_ai_ops_patch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Generate AI ops patch and present accept/decline."""
        if not await self._ensure_openai_ready(update):
            return
        state = getattr(self, "_ai_ops_state", {})
        bot = state.get("bot")
        rel_path = state.get("file")
        instruction = state.get("instruction")
        if not bot or not rel_path or not instruction:
            await update.message.reply_text("AI Ops state missing. Restart AI Ops.")
            return

        if self._is_path_blocked(rel_path):
            await update.message.reply_text("❌ Blocked path. Select a different file.")
            return

        memory = self._load_ai_ops_memory()
        memory_entries = memory.get("entries", [])[-5:]
        memory_summary = "\n".join(
            f"- {m.get('timestamp')} {m.get('bot')}: {m.get('summary')}" for m in memory_entries
        )

        perf_summary = {}
        bot_config = {}
        if bot != "nq_agent":
            try:
                from pearlalgo.strategies.pearl_bots_integration import get_pearl_bot_manager
                bot_manager = get_pearl_bot_manager()
                bot_config = bot_manager.bot_configs.get(bot, {})
                perf_summary = bot_manager.get_bot_performance(bot).get("performance", {}) if hasattr(bot_manager, "get_bot_performance") else {}
            except Exception:
                perf_summary = {}
        else:
            try:
                perf_summary = self._read_latest_metrics() or {}
            except Exception:
                perf_summary = {}

        try:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            target = (project_root / rel_path).resolve()
            if project_root not in target.parents and target != project_root:
                await update.message.reply_text("❌ Blocked path.")
                return
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            await update.message.reply_text(f"❌ Could not read file: {e}")
            return

        additional_context = (
            f"BOT: {bot}\n"
            f"BOT_CONFIG: {json.dumps(bot_config, indent=2)}\n"
            f"PERFORMANCE: {json.dumps(perf_summary, indent=2)}\n"
            f"MEMORY:\n{memory_summary or '- none'}"
        )

        try:
            client = OpenAIClient()
            diff = client.generate_patch(files={rel_path: content}, task=instruction, additional_context=additional_context)
        except OpenAIAPIKeyMissingError as e:
            await update.message.reply_text(f"❌ API Key missing: {e}")
            return
        except OpenAINotAvailableError as e:
            await update.message.reply_text(f"❌ Not Available: {e}\n\nInstall with: pip install -e '.[llm]'")
            return
        except OpenAIAPIError as e:
            await update.message.reply_text(f"❌ API Error: {e}")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

        exports_dir = self.state_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        diff_path = exports_dir / f"ai_ops_patch_{ts}.diff"
        try:
            diff_path.write_text(diff or "", encoding="utf-8")
        except Exception:
            pass

        self._ai_ops_state["diff"] = diff
        self._ai_ops_state["diff_path"] = str(diff_path)

        preview = diff or "(No diff returned)"
        if len(preview) > 3500:
            preview = preview[:3500] + "\n... (truncated)"

        text = (
            f"🧠 AI Ops Proposal\n"
            f"Bot: `{bot}`\n"
            f"File: `{rel_path}`\n\n"
            f"{preview}"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept", callback_data="aiops:accept"),
                InlineKeyboardButton("❌ Decline", callback_data="aiops:decline"),
            ],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _apply_ai_ops_patch(self, query: CallbackQuery) -> None:
        state = getattr(self, "_ai_ops_state", {})
        diff_path = state.get("diff_path")
        if not diff_path or not Path(diff_path).exists():
            await query.edit_message_text("❌ Patch not found. Re-run AI Ops.")
            return

        success, details = self._apply_patch_diff(Path(diff_path))
        if not success:
            await query.edit_message_text(f"❌ Patch apply failed:\n{details}")
            return

        memory = self._load_ai_ops_memory()
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bot": state.get("bot"),
            "summary": state.get("instruction"),
            "file": state.get("file"),
        }
        memory["entries"] = (memory.get("entries", []) + [entry])[-20:]
        self._save_ai_ops_memory(memory)

        keyboard = [
            [InlineKeyboardButton("Restart Agent", callback_data="aiops:restart:agent")],
            [InlineKeyboardButton("Restart Telegram", callback_data="aiops:restart:telegram")],
            [InlineKeyboardButton("Restart Gateway", callback_data="aiops:restart:gateway")],
            [InlineKeyboardButton("Restart All", callback_data="aiops:restart:all")],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await query.edit_message_text(
            "✅ Patch applied. Select a restart option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    def _apply_patch_diff(self, diff_path: Path) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", str(diff_path)],
                cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return True, result.stdout.strip() or "applied"
            return False, result.stderr.strip() or result.stdout.strip()
        except Exception as e:
            return False, str(e)

    async def _handle_ai_ops_restart(self, query: CallbackQuery, action: str) -> None:
        sc = getattr(self, "service_controller", None)
        if sc is None:
            await query.edit_message_text("❌ Service controller not available.")
            return

        if action == "agent":
            result = await sc.restart_agent(background=True)
        elif action == "telegram":
            result = await sc.restart_command_handler()
        elif action == "gateway":
            result = await sc.restart_gateway()
        elif action == "all":
            res_agent = await sc.restart_agent(background=True)
            res_tel = await sc.restart_command_handler()
            res_gw = await sc.restart_gateway()
            result = {
                "message": "Restarted agent, telegram, gateway",
                "details": f"Agent: {res_agent.get('message')}\nTelegram: {res_tel.get('message')}\nGateway: {res_gw.get('message')}",
            }
        else:
            await query.edit_message_text("Unknown restart option.")
            return

        msg = result.get("message", "Restart executed.")
        details = result.get("details")
        if details:
            msg = f"{msg}\n\n{details}"
        await query.edit_message_text(msg)

        if callback_data == "patch:other":
            self._patch_wizard_state["state"] = "awaiting_file_text"
            self._patch_wizard_state.pop("file", None)
            await query.edit_message_text(
                "Send the file path now.\n\nExample:\nsrc/pearlalgo/utils/retry.py"
            )
            return


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
            "⚡ Signals & Trades - View and manage trading activity\n"
            "💎 Performance - Performance metrics and reports\n"
            "🛰️ Status - System health and connection status\n"
            "🎛️ System Control - Start/stop services and emergency controls\n"
            "⚙️ Settings - Charts + notification preferences\n"
            "👾 Bots - Start/stop the Pearl Bot service\n\n"
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
            elif action_type == "ai_patch_wizard":
                await self._show_ai_patch_wizard(query)
            elif action_type == "ai_ops":
                await self._show_ai_ops_menu(query)
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
                    [InlineKeyboardButton("👾 Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "start_all_bots":
                try:
                    from pearlalgo.strategies.pearl_bots_integration import get_pearl_bot_manager
                    bot_manager = get_pearl_bot_manager()
                    active_bots = bot_manager.get_active_bots()

                    # Enable all configured bots
                    for bot_name in bot_manager.bot_configs.keys():
                        bot_manager.enable_bot(bot_name)

                    text = f"✅ Started all PEARL bots\n\nActive bots: {len(bot_manager.get_active_bots())}"
                except Exception as e:
                    logger.error(f"Error starting pearl bots: {e}")
                    text = "❌ Error starting PEARL bots"

                keyboard = [[InlineKeyboardButton("🤖 Pearl Bots", callback_data="menu:pearl_bots")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "stop_all_bots":
                try:
                    from pearlalgo.strategies.pearl_bots_integration import get_pearl_bot_manager
                    bot_manager = get_pearl_bot_manager()

                    # Disable all bots
                    for bot_name in bot_manager.bots.keys():
                        bot_manager.disable_bot(bot_name)

                    text = "🛑 Stopped all PEARL bots"
                except Exception as e:
                    logger.error(f"Error stopping pearl bots: {e}")
                    text = "❌ Error stopping PEARL bots"

                keyboard = [[InlineKeyboardButton("🤖 Pearl Bots", callback_data="menu:pearl_bots")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "show_bot_performance":
                try:
                    from pearlalgo.strategies.pearl_bots_integration import get_pearl_bot_manager
                    bot_manager = get_pearl_bot_manager()
                    performance = bot_manager.get_bot_performance()

                    lines = ["📊 *PEARL Bot Performance*", ""]

                    if isinstance(performance, dict) and performance:
                        for bot_name, perf in performance.items():
                            if isinstance(perf, dict):
                                total_signals = perf.get('total_signals_history', 0)
                                win_rate = perf.get('performance', {}).get('win_rate', 0) * 100
                                total_pnl = perf.get('performance', {}).get('total_pnl', 0)

                                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                                pnl_sign = "+" if total_pnl >= 0 else ""

                                lines.append(f"🤖 *{bot_name}*")
                                lines.append(f"  • Signals: {total_signals}")
                                lines.append(f"  • Win Rate: {win_rate:.1f}%")
                                lines.append(f"  • P&L: {pnl_emoji} {pnl_sign}${abs(total_pnl):.2f}")
                                lines.append("")
                    else:
                        lines.append("No performance data available")

                    text = "\n".join(lines)
                except Exception as e:
                    logger.error(f"Error showing bot performance: {e}")
                    text = "❌ Error loading bot performance"

                keyboard = [[InlineKeyboardButton("🤖 Pearl Bots", callback_data="menu:pearl_bots")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
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
            elif action_type == "emergency_stop":
                # Get detailed impact preview
                state = self._read_state()
                positions = 0
                daily_pnl = 0.0
                impact_lines = []
                
                if state:
                    positions = state.get("execution", {}).get("positions", 0) or 0
                    positions += state.get("active_trades_count", 0) or 0
                    daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                    
                    if positions > 0:
                        impact_lines.append(f"📊 *Impact Preview:*")
                        impact_lines.append(f"• Will close {positions} open position(s)")
                        if daily_pnl != 0:
                            pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                            pnl_sign = "+" if daily_pnl >= 0 else ""
                            impact_lines.append(f"• Current P&L: {pnl_emoji} {pnl_sign}${abs(daily_pnl):.2f}")
                        impact_lines.append("")
                
                lines = [
                    "🚨 *EMERGENCY STOP*",
                    "",
                ]
                
                if impact_lines:
                    lines.extend(impact_lines)
                
                lines.extend([
                    "⚠️ *This will:*",
                    "• Close ALL open positions immediately at market",
                    "• Stop the trading agent",
                    "• Cancel all pending orders",
                    "",
                    "🔴 *WARNING:* This action cannot be undone",
                    "💡 *Alternative:* Use 'Close All Trades' to keep agent running",
                    "",
                    "*Are you absolutely sure?*",
                ])
                
                keyboard = [
                    [InlineKeyboardButton("🚨 YES - EMERGENCY STOP", callback_data="confirm:emergency_stop")],
                    [InlineKeyboardButton("❌ No - Cancel", callback_data="back")],
                ]
                await query.edit_message_text(
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            elif action_type == "close_all_trades":
                # Get detailed position info
                state = self._read_state()
                positions = 0
                daily_pnl = 0.0
                daily_trades = 0
                
                if state:
                    positions = state.get("execution", {}).get("positions", 0) or 0
                    positions += state.get("active_trades_count", 0) or 0
                    daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                    daily_trades = state.get("daily_trades", 0) or 0
                
                lines = ["🚫 *Close All Trades*", ""]
                
                if positions == 0:
                    lines.extend([
                        "✅ *No open positions*",
                        "",
                        "There are currently no trades to close.",
                    ])
                    keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                else:
                    lines.extend([
                        "📊 *Position Summary:*",
                        f"• Open Positions: {positions}",
                        f"• Trades Today: {daily_trades}",
                    ])
                    
                    if daily_pnl != 0:
                        pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                        pnl_sign = "+" if daily_pnl >= 0 else ""
                        lines.append(f"• Current P&L: {pnl_emoji} {pnl_sign}${abs(daily_pnl):.2f}")
                    
                    lines.extend([
                        "",
                        "⚠️ *This will:*",
                        f"• Close all {positions} position(s) at market price",
                        "• Agent will continue running",
                        "• Can still generate new signals",
                        "",
                    ])
                    
                    # Smart warnings based on P&L
                    if daily_pnl > 0:
                        lines.append("💡 *Note:* Closing while in profit - consider trailing stop")
                    elif daily_pnl < -50:
                        lines.append("⚠️ *Notice:* Closing with daily loss - review strategy")
                    
                    lines.extend(["", "*Confirm to close all positions:*"])
                    
                    keyboard = [
                        [InlineKeyboardButton(f"✅ Yes - Close All ({positions})", callback_data="confirm:close_all_trades")],
                        [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                    ]
                
                await query.edit_message_text(
                    "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            elif action_type == "clear_cache":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Clear", callback_data="confirm:clear_cache")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text(
                    "🧹 Clear Cache\n\n"
                    "This will clear:\n"
                    "• Temporary data files\n"
                    "• Cached market data\n"
                    "• Session state (not trade history)\n\n"
                    "The agent will reload fresh data on next start.\n\n"
                    "Are you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif action_type == "reset_performance":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Reset", callback_data="confirm:reset_performance")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text(
                    "🔄 Reset Performance Stats\n\n"
                    "⚠️ This will reset:\n"
                    "• Daily P&L counters\n"
                    "• Win/loss statistics\n"
                    "• Performance metrics\n\n"
                    "Trade history will be preserved.\n\n"
                    "Are you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif action_type == "export_performance":
                await self._handle_export_performance(query)
            elif action_type == "refresh_dashboard":
                # Refresh the main dashboard
                # Check if chart is currently showing (message has photo)
                try:
                    message = query.message
                    if message and message.photo:
                        # Chart is showing, refresh it too
                        await self._show_main_menu_with_chart(query)
                    else:
                        await self._show_main_menu(query)
                except Exception:
                    await self._show_main_menu(query)
            elif action_type == "toggle_chart":
                # Toggle chart display
                await self._toggle_chart_display(query)
            else:
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text(f"Action not yet implemented: {action_type}", reply_markup=InlineKeyboardMarkup(keyboard))
        elif action == "activity":
            # Handle activity callback - show signals menu or activity info
            await self._show_signals_menu(query)
        elif action == "status":
            # Handle status callback - show status menu
            await self._show_status_menu(query)
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
                    [InlineKeyboardButton("👾 Bots", callback_data="menu:bots")],
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
                    [InlineKeyboardButton("👾 Bots", callback_data="menu:bots")],
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
            elif confirm_action == "emergency_stop":
                # Emergency stop: close all positions and stop agent
                try:
                    sc = getattr(self, "service_controller", None)
                    messages = ["🚨 *EMERGENCY STOP EXECUTED*\n"]
                    
                    # First, try to close all positions via state file signal
                    state_file = get_state_file(self.state_dir)
                    if state_file.exists():
                        try:
                            state = json.loads(state_file.read_text(encoding="utf-8"))
                            state["emergency_stop"] = True
                            state["emergency_stop_time"] = datetime.now(timezone.utc).isoformat()
                            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                            messages.append("✅ Emergency stop signal written to state")
                        except Exception as e:
                            messages.append(f"⚠️ Could not write emergency state: {e}")
                    
                    # Stop the agent
                    if sc is not None:
                        result = await sc.stop_agent()
                        messages.append(f"✅ Agent stopped: {result.get('message', 'OK')}")
                    else:
                        messages.append("⚠️ Service controller not available")
                    
                    keyboard = [
                        [InlineKeyboardButton("🤖 Check Bots", callback_data="menu:bots")],
                        [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                    ]
                    await query.edit_message_text(
                        "\n".join(messages),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                    logger.warning("EMERGENCY STOP executed via Telegram")
                except Exception as e:
                    logger.error(f"Emergency stop error: {e}", exc_info=True)
                    await query.edit_message_text(
                        f"❌ Emergency stop error: {e}",
                        reply_markup=reply_markup
                    )
            elif confirm_action == "close_all_trades":
                try:
                    # Signal to close all trades via state file
                    state_file = get_state_file(self.state_dir)
                    if state_file.exists():
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                        state["close_all_requested"] = True
                        state["close_all_requested_time"] = datetime.now(timezone.utc).isoformat()
                        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                        
                        keyboard = [
                            [InlineKeyboardButton("📡 Check Status", callback_data="menu:status")],
                            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                        ]
                        await query.edit_message_text(
                            "✅ Close All Trades Request Sent\n\n"
                            "The agent will close all positions at next opportunity.\n"
                            "Check status to confirm positions are closed.",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info("Close all trades requested via Telegram")
                    else:
                        await query.edit_message_text(
                            "❌ State file not found.\n\nIs the agent running?",
                            reply_markup=reply_markup
                        )
                except Exception as e:
                    logger.error(f"Close all trades error: {e}", exc_info=True)
                    await query.edit_message_text(f"❌ Error: {e}", reply_markup=reply_markup)
            elif confirm_action == "clear_cache":
                try:
                    cleared = []
                    # Clear common cache locations
                    cache_paths = [
                        self.state_dir / "cache",
                        self.state_dir / "temp",
                        self.state_dir / ".cache",
                    ]
                    for cache_path in cache_paths:
                        if cache_path.exists() and cache_path.is_dir():
                            shutil.rmtree(cache_path)
                            cache_path.mkdir(exist_ok=True)
                            cleared.append(str(cache_path.name))
                    
                    if cleared:
                        text = f"✅ Cache Cleared\n\nCleared: {', '.join(cleared)}"
                    else:
                        text = "✅ Cache Clear Complete\n\nNo cache directories found."
                    
                    keyboard = [
                        [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                    ]
                    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
                    logger.info(f"Cache cleared via Telegram: {cleared}")
                except Exception as e:
                    logger.error(f"Clear cache error: {e}", exc_info=True)
                    await query.edit_message_text(f"❌ Error clearing cache: {e}", reply_markup=reply_markup)
            elif confirm_action == "reset_performance":
                try:
                    # Reset performance counters in state
                    state_file = get_state_file(self.state_dir)
                    if state_file.exists():
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                        # Reset performance-related fields
                        state["daily_pnl"] = 0.0
                        state["daily_trades"] = 0
                        state["daily_wins"] = 0
                        state["daily_losses"] = 0
                        state["performance_reset_time"] = datetime.now(timezone.utc).isoformat()
                        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                        
                        keyboard = [
                            [InlineKeyboardButton("💎 Performance", callback_data="menu:performance")],
                            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                        ]
                        await query.edit_message_text(
                            "✅ Performance Stats Reset\n\n"
                            "Daily counters have been reset.\n"
                            "Trade history is preserved.",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info("Performance stats reset via Telegram")
                    else:
                        await query.edit_message_text(
                            "❌ State file not found.",
                            reply_markup=reply_markup
                        )
                except Exception as e:
                    logger.error(f"Reset performance error: {e}", exc_info=True)
                    await query.edit_message_text(f"❌ Error: {e}", reply_markup=reply_markup)
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
                f"{status_emoji} *Bot {action.title()}*\n\n"
                f"Bot: `{strategy_name}`\n\n"
                f"⚠️ *Restart the agent* for changes to take effect.\n\n"
                f"Use System menu → Restart Agent"
            )
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            logger.info(f"Strategy {strategy_name} {action} via Telegram")
            
        except Exception as e:
            logger.error(f"Error toggling strategy: {e}", exc_info=True)
            keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
            await query.edit_message_text(
                f"❌ Error updating bot: {e}\n\nPlease check config file manually.",
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
            
            # Service status - use live process check, not stale state file
            agent_running = bool(self._is_agent_process_running())
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
            execution_positions = int(execution.get("positions", 0) or 0)
            open_positions_count = max(execution_positions, int(active_trades_count or 0))
            
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
            challenge_per_strategy: dict = {}
            challenge_tracker_instance = None
            
            try:
                from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker
                
                # Always load/create challenge tracker (will create if doesn't exist)
                challenge_state_file = self.state_dir / "challenge_state.json"
                try:
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()  # Reload from file
                    challenge_status = challenge_tracker_instance.get_status_summary(bot_label="Pearl Bot")
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
                open_positions_count=open_positions_count,
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
                    challenge_status = challenge_tracker_instance.get_status_summary(bot_label="Pearl Bot")
                except Exception as e:
                    logger.error(f"Could not reload challenge status: {e}", exc_info=True)
            
            # If still no challenge_status, try to create/load one more time
            if not challenge_status:
                try:
                    from pearlalgo.nq_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()
                    challenge_status = challenge_tracker_instance.get_status_summary(bot_label="Pearl Bot")
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
                        # attempt_id intentionally not shown in UI (we label by bot instead)
                        dd_risk = attempt_perf.get("drawdown_risk_pct", 0.0)
                        bar_filled = min(10, int(dd_risk / 10))
                        bar = "▓" * bar_filled + "░" * (10 - bar_filled)
                        
                        challenge_status = (
                            "🏆 *50k Challenge* (Pearl Bot)\n"
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
                        
                        # attempt_id intentionally not shown in UI (we label by bot instead)
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
                            "🏆 *50k Challenge* (Pearl Bot)\n"
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
            
            # 30d by Bot (compact): keep only Total + Pearl Bot
            try:
                from pearlalgo.learning.trade_database import TradeDatabase

                db_path = self.state_dir / "trades.db"
                if db_path.exists():
                    trade_db = TradeDatabase(db_path)
                    strategy_perf = trade_db.get_performance_by_signal_type(days=30)
                    if strategy_perf:
                        message += "\n\n*30d by Bot:*"

                        total_pnl_all = sum(perf.get("total_pnl", 0.0) for perf in strategy_perf.values())
                        total_wins = sum(perf.get("wins", 0) for perf in strategy_perf.values())
                        total_losses = sum(perf.get("losses", 0) for perf in strategy_perf.values())
                        total_trades = total_wins + total_losses
                        total_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
                        total_emoji = "🟢" if total_pnl_all >= 0 else "🔴"

                        message += (
                            f"\n{total_emoji} *Total All Bots:* ${total_pnl_all:,.2f} "
                            f"({total_wins}W/{total_losses}L • {total_wr:.0f}% WR)"
                        )

                        # "Pearl Bot" is the bot running all signal types.
                        # So its 30d totals should reflect the full 30d trade set.
                        message += (
                            f"\n{total_emoji} *Pearl Bot:* ${total_pnl_all:,.2f} "
                            f"({total_wins}W/{total_losses}L • {total_wr:.0f}% WR)"
                        )
            except Exception as e:
                logger.debug(f"Could not load 30d by strategy (compact): {e}")

            # Challenge by Bot (current challenge run)
            if challenge_tracker_instance:
                try:
                    attempt_perf = challenge_tracker_instance.get_attempt_performance() or {}
                    pnl = float(attempt_perf.get("total_pnl", 0.0) or 0.0)
                    balance = float(
                        attempt_perf.get(
                            "current_balance",
                            attempt_perf.get("starting_balance", 50_000.0),
                        )
                        or 50_000.0
                    )
                    wins = int(attempt_perf.get("wins", 0) or 0)
                    losses = int(attempt_perf.get("losses", 0) or 0)
                    wr = float(attempt_perf.get("win_rate", 0.0) or 0.0) * 100
                    pnl_emoji = "🟢" if pnl >= 0 else "🔴"

                    message += "\n\n*Challenge by Bot:*"
                    message += (
                        f"\n{pnl_emoji} *Pearl Bot:* ${balance:,.2f} | ${pnl:+,.2f} "
                        f"({wins}W/{losses}L • {wr:.0f}% WR)"
                    )
                except Exception as e:
                    logger.debug(f"Could not load challenge by bot: {e}")

            # Recent exits (from state or fallback to signals.jsonl)
            recent_exits = state.get("recent_exits", [])
            if not isinstance(recent_exits, list) or not recent_exits:
                recent_signals = self._read_recent_signals(limit=50)
                recent_exits = []
                for rec in reversed(recent_signals):  # Most recent first
                    if rec.get("status") == "exited":
                        pnl = rec.get("pnl")
                        if pnl is not None:
                            # Fields may be at record-level OR nested in rec["signal"]
                            sig = rec.get("signal", {}) or {}
                            recent_exits.append(
                                {
                                    "signal_id": str(rec.get("signal_id") or ""),
                                    "type": str(rec.get("signal_type") or sig.get("type") or "unknown"),
                                    "direction": str(rec.get("direction") or sig.get("direction") or "long"),
                                    "pnl": pnl,
                                    "exit_reason": str(rec.get("exit_reason") or ""),
                                    "exit_time": rec.get("exit_time") or rec.get("timestamp"),
                                }
                            )
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

                    timestamp = t.get("exit_time") or t.get("exit_timestamp") or t.get("timestamp")
                    if timestamp:
                        try:
                            exit_time = parse_utc_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
                            if exit_time:
                                if hasattr(exit_time, "tzinfo") and exit_time.tzinfo is None:
                                    exit_time = exit_time.replace(tzinfo=timezone.utc)
                                try:
                                    et_exit = exit_time.astimezone(et_tz)
                                    time_label = et_exit.strftime("%I:%M %p").lstrip("0")
                                    message += f" • {time_label}"
                                except Exception:
                                    pass
                        except Exception:
                            pass
            
            # Add current position/signal if active
            if active_trades_count > 0:
                # Try to find active signal from recent signals
                recent_signals = self._read_recent_signals(limit=20)
                active_rec = next((s for s in recent_signals if s.get("status") == "entered"), None)
                
                if active_rec:
                    # Fields may be at record-level OR nested in rec["signal"]
                    sig = active_rec.get("signal", {}) or {}
                    message += "\n\n*Current Position:*"
                    direction = str(active_rec.get("direction") or sig.get("direction") or "long").upper()
                    signal_type = str(active_rec.get("signal_type") or sig.get("type") or "unknown")
                    entry_price = active_rec.get("entry_price") or sig.get("entry_price")
                    stop_loss = active_rec.get("stop_loss") or sig.get("stop_loss")
                    take_profit = active_rec.get("take_profit") or sig.get("take_profit")
                    confidence = active_rec.get("confidence") or sig.get("confidence")
                    
                    # Convert to float safely
                    try:
                        entry_price = float(entry_price) if entry_price else None
                    except Exception:
                        entry_price = None
                    try:
                        stop_loss = float(stop_loss) if stop_loss else None
                    except Exception:
                        stop_loss = None
                    try:
                        take_profit = float(take_profit) if take_profit else None
                    except Exception:
                        take_profit = None
                    try:
                        confidence = float(confidence) if confidence else None
                    except Exception:
                        confidence = None
                    
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
                    if stop_loss and entry_price:
                        stop_pts = abs(entry_price - stop_loss)
                        message += f"Stop: ${stop_loss:,.2f} ({stop_pts:.1f} pts)\n"
                    if take_profit and entry_price:
                        tp_pts = abs(take_profit - entry_price)
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
            age_minutes = None
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
            
            # Diagnostic info for stale data
            if age_minutes is not None and age_minutes > data_stale_threshold_minutes and agent_running and not paused:
                data_fetch_errors = state.get("data_fetch_errors", 0)
                connection_status = state.get("connection_status", "unknown")
                connection_failures = state.get("connection_failures", 0)
                
                text += "\n🔍 *Diagnostics:*\n"
                text += f"• Connection: {connection_status}\n"
                if data_fetch_errors > 0:
                    text += f"• Data fetch errors: {data_fetch_errors}\n"
                if connection_failures > 0:
                    text += f"• Connection failures: {connection_failures}\n"
        else:
            text += "❌ No data available\n"
            text += "\n*Possible reasons:*\n"
            text += "• Agent not running\n"
            text += "• Data fetcher not initialized\n"
            text += "• No market data received yet\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_export_performance(self, query: CallbackQuery) -> None:
        """Export performance report."""
        try:
            metrics = self._read_latest_metrics()
            state = self._read_state()
            
            if not metrics and not state:
                keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                await query.edit_message_text(
                    "❌ No performance data available to export.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # Build a text summary report
            lines = [
                "📋 *Performance Report*",
                f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                "",
            ]
            
            if metrics:
                lines.extend([
                    "*Trading Metrics:*",
                    f"• Total Trades: {metrics.get('exited_signals', 0)}",
                    f"• Win Rate: {metrics.get('win_rate', 0.0):.1%}",
                    f"• Total P&L: ${metrics.get('total_pnl', 0.0):,.2f}",
                    f"• Average P&L: ${metrics.get('avg_pnl', 0.0):,.2f}",
                    f"• Max Drawdown: ${metrics.get('max_drawdown', 0.0):,.2f}",
                    "",
                ])
            
            if state:
                lines.extend([
                    "*Current Session:*",
                    f"• Daily P&L: ${state.get('daily_pnl', 0.0):,.2f}",
                    f"• Daily Trades: {state.get('daily_trades', 0)}",
                    f"• Open Positions: {state.get('execution', {}).get('positions', 0)}",
                    "",
                ])
            
            keyboard = [
                [InlineKeyboardButton("💎 Performance", callback_data="menu:performance")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Export performance error: {e}", exc_info=True)
            keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
            await query.edit_message_text(
                f"❌ Error exporting performance: {e}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

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
            await self._send_message_or_edit(update, context, "⚡ Signals\n\nNo signals file found.")
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
            await self._send_message_or_edit(update, context, "⚡ Signals\n\nNo signals yet.")
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

        lines = ["💎 Performance"]
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

        # Prefer StateManager (testable + consistent), fallback to direct file read.
        recent: list[dict] = []
        try:
            if getattr(self, "state_manager", None) is not None and hasattr(self.state_manager, "get_recent_signals"):
                recent = self.state_manager.get_recent_signals(limit=100)  # type: ignore[assignment]
            else:
                recent = self._read_recent_signals(limit=100)
        except Exception:
            recent = self._read_recent_signals(limit=100)

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

            # Get entry time - check multiple fields
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

            # Get entry price, stop loss, take profit
            entry_price = item.get("entry_price") or sig.get("entry_price")
            stop_loss = item.get("stop_loss") or sig.get("stop_loss")
            take_profit = item.get("take_profit") or sig.get("take_profit")
            status = item.get("status") or sig.get("status", "unknown")
            
            # Only include trades that have been entered
            if status not in ["entered", "exited", "stopped", "target"]:
                continue

            trades.append(
                {
                    "signal_id": item.get("signal_id") or sig.get("signal_id") or "",
                    "direction": sig.get("direction") or item.get("direction") or "",
                    "entry_time": dt.isoformat(),
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "status": status,
                }
            )

        return trades

    def _get_back_to_menu_button(self):
        """Return a minimal 'Back to Menu' InlineKeyboardMarkup."""
        try:
            return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]])
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
        await self._run_ai_patch(update, context, rel_path=rel_path, task=task)

    async def _run_ai_patch(self, update: Any, context: Any, *, rel_path: str, task: str) -> None:
        """Shared AI patch runner for command and wizard flows."""
        if not await self._ensure_openai_ready(update):
            return
        if self._is_path_blocked(rel_path):
            await self._send_message_or_edit(update, context, f"❌ Blocked path: {rel_path}")
            return

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

        try:
            client = OpenAIClient()
            diff = client.generate_patch(files={rel_path: content}, task=task)
            msg = diff if diff else "(No diff returned)"
            if len(msg) > 4096:
                msg = msg[:4093] + "..."
            await self._send_message_or_edit(update, context, msg)
        except OpenAIAPIKeyMissingError as e:
            await self._send_message_or_edit(update, context, f"❌ API Key missing: {e}")
        except OpenAINotAvailableError as e:
            await self._send_message_or_edit(update, context, f"❌ Not Available: {e}\n\nInstall with: pip install -e '.[llm]'")
        except OpenAIAPIError as e:
            await self._send_message_or_edit(update, context, f"❌ API Error: {e}")
        except Exception as e:
            await self._send_message_or_edit(update, context, f"❌ Error: {e}")

    # ---------------------------------------------------------------------
    # Telegram-first PEARL bot backtesting
    # ---------------------------------------------------------------------

    async def _render_pearl_backtest_menu(self, update: Any, context: Any) -> None:
        """Render the PEARL bot backtest menu (Telegram-first; no CLI)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        lines = [
            "🧪 *PEARL Bot Backtesting*",
            "",
            "Choose a bot to backtest, then pick a historical period.",
            "",
            "Data source: `data/historical/MNQ_1m_*.parquet` (resampled to 5m).",
        ]

        keyboard = [
            [
                InlineKeyboardButton("📈 Trend Follower", callback_data="pb:bot:trend"),
                InlineKeyboardButton("⚡ Breakout", callback_data="pb:bot:break"),
            ],
            [
                InlineKeyboardButton("📉 Mean Reversion", callback_data="pb:bot:mean"),
                InlineKeyboardButton("🏆 Compare All", callback_data="pb:bot:all"),
            ],
            [
                InlineKeyboardButton("📑 Reports", callback_data="strategy_review:reports"),
                InlineKeyboardButton("🏠 Back to Menu", callback_data="back"),
            ],
        ]

        await self._send_message_or_edit(
            update,
            context,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _render_pearl_backtest_period_menu(self, update: Any, context: Any, bot_key: str) -> None:
        """Render the period picker for a given bot."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        bot_label = {
            "trend": "Trend Follower",
            "break": "Breakout",
            "mean": "Mean Reversion",
            "all": "Compare All",
        }.get(bot_key, bot_key)

        lines = [
            "🧪 *Backtest Period*",
            "",
            f"Bot: *{bot_label}*",
            "",
            "Pick a historical window:",
        ]

        keyboard = [
            [
                InlineKeyboardButton("1w", callback_data=f"pb:run:{bot_key}:1w"),
                InlineKeyboardButton("2w", callback_data=f"pb:run:{bot_key}:2w"),
            ],
            [
                InlineKeyboardButton("4w", callback_data=f"pb:run:{bot_key}:4w"),
                InlineKeyboardButton("6w", callback_data=f"pb:run:{bot_key}:6w"),
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="pb:menu"),
                InlineKeyboardButton("🏠 Back to Menu", callback_data="back"),
            ],
        ]

        await self._send_message_or_edit(
            update,
            context,
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _handle_pearl_backtest_callback(self, update: Any, context: Any, data: str) -> None:
        """Route pb:* callback_data for PEARL bot backtesting."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        if data == "pb:menu":
            await self._render_pearl_backtest_menu(update, context)
            return

        if data.startswith("pb:bot:"):
            bot_key = data.split(":")[-1]
            await self._render_pearl_backtest_period_menu(update, context, bot_key)
            return

        if data.startswith("pb:run:"):
            parts = data.split(":")
            bot_key = parts[2] if len(parts) > 2 else "trend"
            period_key = parts[3] if len(parts) > 3 else "2w"
            if bot_key == "all":
                await self._run_pearl_bots_comparison(update, context, period_key)
            else:
                await self._run_pearl_bot_backtest(update, context, bot_key, period_key)
            return

        await self._send_message_or_edit(update, context, f"❌ Unknown backtest action: {data}")

    def _get_repo_root(self) -> Path:
        """Get repository root from this file location."""
        return Path(__file__).resolve().parent.parent.parent.parent

    def _get_reports_dir(self) -> Path:
        """Directory where Telegram backtest reports are stored (shared with report viewer)."""
        try:
            state_dir = Path(getattr(self, "state_dir", "data/nq_agent_state"))
        except Exception:
            state_dir = Path("data/nq_agent_state")
        return state_dir.parent / "reports"

    def _load_historical_ohlcv(self, period_key: str) -> "pd.DataFrame":
        """Load OHLCV parquet for a given period key (1w/2w/4w/6w)."""
        import pandas as pd  # local import (Telegram handler should stay lightweight)

        period = (period_key or "").strip().lower()
        if period not in {"1w", "2w", "4w", "6w"}:
            raise ValueError(f"Unknown period: {period_key}")

        root = self._get_repo_root()
        path = root / "data" / "historical" / f"MNQ_1m_{period}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Historical data not found: {path}")

        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            for col in ("timestamp", "time", "datetime", "date"):
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                    df = df.dropna(subset=[col]).set_index(col)
                    break

        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("Historical data must have a DateTimeIndex or a timestamp column")

        df = df.sort_index()
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Historical data missing required columns: {missing}")

        return df

    def _create_pearl_bot_for_backtest(self, bot_key: str):
        """Create a PEARL bot instance with safe backtest defaults."""
        from pearlalgo.strategies.pearl_bots import BotConfig, create_bot

        bot_map = {
            "trend": ("TrendFollowerBot", {"min_trend_strength": 25.0, "max_pullback_pct": 0.02, "momentum_threshold": 0.005}),
            "break": ("BreakoutBot", {"min_pattern_strength": 0.6, "require_volume_confirmation": True, "min_momentum_acceleration": 0.001}),
            "mean": ("MeanReversionBot", {"min_mr_strength": 0.7, "require_divergence": False, "max_hold_bars": 10}),
        }
        if bot_key not in bot_map:
            raise ValueError(f"Unknown bot: {bot_key}")

        bot_class_name, params = bot_map[bot_key]
        cfg = BotConfig(
            name=bot_key,
            description=f"Telegram backtest config for {bot_class_name}",
            symbol="MNQ",
            timeframe="5m",
            max_positions=1,
            risk_per_trade=0.01,
            stop_loss_pct=0.005,
            take_profit_pct=0.01,
            min_confidence=0.6,
            parameters=params,
            enable_alerts=False,  # Never alert during backtests
            webhook_url=None,
        )
        return create_bot(bot_class_name, cfg)

    async def _run_pearl_bot_backtest(self, update: Any, context: Any, bot_key: str, period_key: str) -> None:
        """Run a single PEARL bot backtest and write a report under data/reports/."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        bot_label = {"trend": "Trend Follower", "break": "Breakout", "mean": "Mean Reversion"}.get(bot_key, bot_key)
        await self._send_message_or_edit(update, context, f"⏳ Running backtest…\n\nBot: {bot_label}\nPeriod: {period_key}")

        try:
            import pandas as pd  # noqa: F401
            from datetime import datetime, timezone

            from pearlalgo.strategies.pearl_bots.backtest_adapter import PearlBotBacktestAdapter

            df_1m = self._load_historical_ohlcv(period_key)
            bot = self._create_pearl_bot_for_backtest(bot_key)

            adapter = PearlBotBacktestAdapter(
                bot=bot,
                tick_value=2.0,  # MNQ
                slippage_ticks=0.5,
                max_concurrent_trades=1,
            )
            result = adapter.run_backtest(df_1m, timeframe="5m", return_signals=True, return_trades=True)

            reports_dir = self._get_reports_dir()
            reports_dir.mkdir(parents=True, exist_ok=True)

            run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            start = df_1m.index[0].strftime("%Y%m%d")
            end = df_1m.index[-1].strftime("%Y%m%d")
            report_name = f"pearlbot_{bot_key}_{period_key}_{start}_{end}_{run_ts}"
            report_dir = reports_dir / report_name
            report_dir.mkdir(parents=True, exist_ok=True)

            # Write artifacts
            (report_dir / "summary.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
            if result.signals:
                pd.DataFrame(result.signals).to_csv(report_dir / "signals.csv", index=False)
            if result.trades:
                pd.DataFrame(result.trades).to_csv(report_dir / "trades.csv", index=False)
            if result.skipped_signals:
                pd.DataFrame(result.skipped_signals).to_csv(report_dir / "skipped_signals.csv", index=False)

            # Show summary
            lines = [
                "✅ *Backtest Complete*",
                "",
                f"*Bot:* {bot_label}",
                f"*Period:* {period_key} (1m data → 5m backtest)",
                "",
                f"Trades: *{result.total_trades}* | Signals: *{result.total_signals}*",
                f"Win rate: *{(result.win_rate or 0.0) * 100:.1f}%* | PF: *{result.profit_factor:.2f}*",
                f"Total P&L: *${result.total_pnl:,.2f}*",
                f"Max DD: *${result.max_drawdown:,.2f}* | Sharpe: *{result.sharpe_ratio:.2f}*",
                "",
                f"Saved report: `{report_name}`",
            ]

            keyboard = [
                [InlineKeyboardButton("📑 Backtest Reports", callback_data="strategy_review:reports")],
                [InlineKeyboardButton("🧪 Backtest Another", callback_data="pb:menu")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]

            await self._send_message_or_edit(
                update,
                context,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Backtest error: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("🧪 Backtest Menu", callback_data="pb:menu")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await self._send_message_or_edit(
                update,
                context,
                f"❌ Backtest failed: {e}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    async def _run_pearl_bots_comparison(self, update: Any, context: Any, period_key: str) -> None:
        """Run the same backtest period for all PEARL bots and show a comparison."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        await self._send_message_or_edit(update, context, f"⏳ Running comparison backtest…\n\nBots: Trend/Breakout/MeanRev\nPeriod: {period_key}")

        try:
            import pandas as pd  # noqa: F401
            from datetime import datetime, timezone

            from pearlalgo.strategies.pearl_bots.backtest_adapter import PearlBotBacktestAdapter

            df_1m = self._load_historical_ohlcv(period_key)
            bots = [("trend", "Trend"), ("break", "Breakout"), ("mean", "MeanRev")]

            results = []
            for key, label in bots:
                bot = self._create_pearl_bot_for_backtest(key)
                adapter = PearlBotBacktestAdapter(
                    bot=bot,
                    tick_value=2.0,
                    slippage_ticks=0.5,
                    max_concurrent_trades=1,
                )
                r = adapter.run_backtest(df_1m, timeframe="5m", return_signals=False, return_trades=False)
                results.append((label, r))

            # Rank by total P&L
            ranked = sorted(results, key=lambda x: float(getattr(x[1], "total_pnl", 0.0) or 0.0), reverse=True)
            best_label, best = ranked[0]

            reports_dir = self._get_reports_dir()
            reports_dir.mkdir(parents=True, exist_ok=True)
            run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            start = df_1m.index[0].strftime("%Y%m%d")
            end = df_1m.index[-1].strftime("%Y%m%d")
            report_name = f"pearlbots_compare_{period_key}_{start}_{end}_{run_ts}"
            report_dir = reports_dir / report_name
            report_dir.mkdir(parents=True, exist_ok=True)

            summary = {
                "period": period_key,
                "results": [{"bot": lbl, **r.to_dict()} for (lbl, r) in results],
                "best": best_label,
            }
            (report_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            pd.DataFrame([{"bot": lbl, **r.to_dict()} for (lbl, r) in results]).to_csv(report_dir / "comparison.csv", index=False)

            lines = [
                "✅ *Comparison Backtest Complete*",
                "",
                f"*Period:* {period_key} (1m data → 5m backtest)",
                "",
                "*Results:*",
            ]
            for lbl, r in ranked:
                lines.append(
                    f"- *{lbl}*: P&L ${r.total_pnl:,.0f} | WR {(r.win_rate or 0.0) * 100:.0f}% | PF {r.profit_factor:.2f} | DD ${r.max_drawdown:,.0f}"
                )
            lines.extend(["", f"🏆 *Best:* {best_label}", "", f"Saved report: `{report_name}`"])

            keyboard = [
                [InlineKeyboardButton("📑 Backtest Reports", callback_data="strategy_review:reports")],
                [InlineKeyboardButton("🧪 Backtest Menu", callback_data="pb:menu")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await self._send_message_or_edit(
                update,
                context,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Comparison backtest error: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("🧪 Backtest Menu", callback_data="pb:menu")],
                [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
            ]
            await self._send_message_or_edit(
                update,
                context,
                f"❌ Comparison backtest failed: {e}",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    async def _handle_report_detail_by_idx(self, update: Any, context: Any, report_idx: int) -> None:
        """Show report artifacts using report index (short callback_data IDs)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        reports_dir = self._get_reports_dir()
        if not reports_dir.exists():
            await self._send_message_or_edit(update, context, "📑 Reports\n\nNo reports found.")
            return

        report_names = sorted([p.name for p in reports_dir.iterdir() if p.is_dir()])
        if report_idx < 0 or report_idx >= len(report_names):
            await self._send_message_or_edit(update, context, "❌ Report not found")
            return

        report_name = report_names[report_idx]
        report_dir = reports_dir / report_name
        artifacts = sorted([p.name for p in report_dir.iterdir() if p.is_file()])

        rows = []
        for i, name in enumerate(artifacts[:12]):
            rows.append([InlineKeyboardButton(name[:28], callback_data=f"artifact:{report_idx}:{i}")])
        rows.append([InlineKeyboardButton("⬅️ Reports", callback_data="strategy_review:reports")])
        rows.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])

        await self._send_message_or_edit(update, context, f"Report: {report_name}", reply_markup=InlineKeyboardMarkup(rows))

    async def _handle_report_artifact_by_idx(self, update: Any, context: Any, report_idx: int, artifact_idx: int) -> None:
        """Send a report artifact file to Telegram."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        reports_dir = self._get_reports_dir()
        report_names = sorted([p.name for p in reports_dir.iterdir() if p.is_dir()]) if reports_dir.exists() else []
        if report_idx < 0 or report_idx >= len(report_names):
            await self._send_message_or_edit(update, context, "❌ Report not found")
            return

        report_name = report_names[report_idx]
        report_dir = reports_dir / report_name
        artifacts = sorted([p for p in report_dir.iterdir() if p.is_file()])
        if artifact_idx < 0 or artifact_idx >= len(artifacts):
            await self._send_message_or_edit(update, context, "❌ File not found")
            return

        file_path = artifacts[artifact_idx]
        try:
            bot = getattr(context, "bot", None)
            chat_id = getattr(getattr(update, "effective_chat", None), "id", None) or getattr(self, "chat_id", None)
            if bot is None or chat_id is None:
                raise RuntimeError("Telegram bot/chat not available")
            # Send as document (works for CSV/JSON/PNG/HTML)
            with open(file_path, "rb") as f:
                await bot.send_document(chat_id=chat_id, document=f, filename=file_path.name)
        except Exception as e:
            logger.error(f"Failed to send artifact {file_path}: {e}", exc_info=True)
            await self._send_message_or_edit(update, context, f"❌ Could not send file: {e}")
            return

        # Keep navigation handy
        keyboard = [
            [InlineKeyboardButton("⬅️ Report", callback_data=f"report:{report_idx}")],
            [InlineKeyboardButton("📑 Reports", callback_data="strategy_review:reports")],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        await self._send_message_or_edit(
            update,
            context,
            f"📎 Sent: `{file_path.name}`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

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
        await self._send_message_or_edit(update, context, "Bot Review • More", reply_markup=rm)

    async def _render_strategy_review_cached(self, update: Any, context: Any) -> None:
        """Placeholder cached Strategy Review render (tests patch this)."""
        await self._send_message_or_edit(update, context, "Bot Review")

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
