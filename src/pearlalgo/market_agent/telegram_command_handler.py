"""
Telegram Command Handler for Market Agent.

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
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_state_file, get_signals_file, parse_utc_timestamp
from pearlalgo.utils.service_controller import ServiceController
from pearlalgo.utils.telegram_alerts import (
    TelegramPrefs,
    format_home_card,
    format_glanceable_card,
    format_pnl,
    format_signal_direction,
    format_signal_status,
    format_signal_confidence_tier,
    format_time_ago,
    safe_label,
)
from pearlalgo.utils.telegram_ui_contract import (
    resolve_callback,
    parse_callback,
    PREFIX_MENU,
    PREFIX_ACTION,
    PREFIX_CONFIRM,
    PREFIX_SIGNAL_DETAIL,
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
        self._available_markets = ["NQ", "ES", "GC"]
        self.active_market = "NQ"
        self._repo_root = self._get_repo_root()

        # If a state_dir is explicitly provided, honor it (single-market/pinned use).
        # Otherwise, default to per-market state under <repo>/data/agent_state/<MARKET>.
        env_market = os.getenv("PEARLALGO_MARKET", "NQ")
        if state_dir is not None:
            self.active_market = str(env_market or "NQ").strip().upper()
            self.state_dir = ensure_state_dir(state_dir)
            self.exports_dir = self.state_dir / "exports"
        else:
            self._set_active_market(env_market)
        self._startup_ping = bool(startup_ping)
        self.application = (
            Application.builder()
            .token(bot_token)
            .post_init(self._post_init)
            .build()
        )
        self.service_controller = ServiceController()
        self._register_handlers()

    def _state_dir_path_for_market(self, market: str) -> Path:
        """Absolute state dir path for a given market (does not create it)."""
        market_upper = str(market or "NQ").strip().upper()
        return (Path(self._repo_root) / "data" / "agent_state" / market_upper).resolve()

    def _resolve_state_dir_for_market(self, market: str) -> Path:
        return ensure_state_dir(self._state_dir_path_for_market(market))

    def _set_active_market(self, market: str) -> None:
        market_upper = str(market or "NQ").strip().upper()
        if market_upper not in self._available_markets:
            market_upper = "NQ"
        self.active_market = market_upper
        self.state_dir = self._resolve_state_dir_for_market(market_upper)
        self.exports_dir = self.state_dir / "exports"

    async def _post_init(self, application: Application) -> None:
        """Runs once after the Telegram application initializes."""
        # Set simple command menu (menu is the primary entry point)
        try:
            await application.bot.set_my_commands([
                BotCommand('menu', 'Show main dashboard'),
                BotCommand('help', 'Show help information'),
                BotCommand('settings', 'Alert preferences'),
            ])
        except Exception as e:
            logger.debug(f"Could not set bot commands: {e}")

        # Send visual dashboard with 12h chart on startup
        if self._startup_ping:
            try:
                logger.info(f"Sending visual dashboard to chat_id={self.chat_id}")
                keyboard = self._get_main_menu_keyboard()
                reply_markup = InlineKeyboardMarkup(keyboard)

                state = self._read_state()
                if state:
                    try:
                        # Build full dashboard message
                        dashboard_text = await self._build_status_dashboard_message(state)
                        
                        # Generate 12h chart
                        chart_path = await self._generate_or_get_chart(state)
                        
                        if chart_path and chart_path.exists():
                            # Send visual dashboard with chart
                            with open(chart_path, 'rb') as f:
                                await application.bot.send_photo(
                                    chat_id=self.chat_id,
                                    photo=f,
                                    caption=dashboard_text,
                                    reply_markup=reply_markup,
                                    parse_mode="Markdown"
                                )
                            logger.info("Visual dashboard with chart sent")
                        else:
                            # Fallback to text-only dashboard
                            await application.bot.send_message(
                                chat_id=self.chat_id,
                                text=dashboard_text,
                                reply_markup=reply_markup,
                                parse_mode="Markdown"
                            )
                            logger.info("Text-only dashboard sent (no chart available)")
                    except Exception as e:
                        logger.warning(f"Could not send visual dashboard: {e}")
                        await application.bot.send_message(
                            chat_id=self.chat_id,
                            text="✅ PEARLalgo online\n\nTap 🔄 Refresh for visual dashboard:",
                            reply_markup=reply_markup
                        )
                else:
                    # No state yet - show system health overview
                    agent_running = bool(self._is_agent_process_running())
                    gateway_status = None
                    try:
                        sc = getattr(self, "service_controller", None)
                        if sc:
                            gateway_status = sc.get_gateway_status() or {}
                    except Exception:
                        gateway_status = {}
                    
                    gw_proc = bool(gateway_status.get("process_running", False)) if gateway_status else False
                    gw_port = bool(gateway_status.get("port_listening", False)) if gateway_status else False
                    gw_ok = gw_proc and gw_port
                    
                    # Build system health dashboard
                    lines = [
                        f"📊 *{self.active_market} Dashboard*",
                        "",
                        "━━━━━ *System Health* ━━━━━",
                        f"🤖 Agent: {'🟢 RUNNING' if agent_running else '🔴 STOPPED'}",
                        f"🔌 Gateway: {'🟢 ONLINE' if gw_ok else '🔴 OFFLINE'}",
                        f"📡 Handler: 🟢 ONLINE",
                        "",
                        "━━━━━ *Status* ━━━━━",
                        "⚠️ No trading data yet.",
                        "",
                        "_Start the agent to see live dashboard._",
                        "_Tap 🔄 Refresh after agent starts._",
                    ]
                    await application.bot.send_message(
                        chat_id=self.chat_id,
                        text="\n".join(lines),
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                logger.info("Startup complete")
            except Exception as e:
                logger.warning(f"Could not send startup dashboard to chat_id={self.chat_id}: {e}")

    def _register_handlers(self) -> None:
        # Main menu command (primary entry point)
        self.application.add_handler(CommandHandler("menu", self.handle_menu))
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
        """
        Main menu keyboard - 4 distinct sections, no overlap.
        
        ┌─────────────────────────────────────────────────────────┐
        │  MAIN MENU ARCHITECTURE (each button = unique domain)  │
        ├─────────────────────────────────────────────────────────┤
        │  📊 Activity  │  Trades, signals, P&L, history         │
        │  🎛️ System    │  Agent/Gateway start/stop, config      │
        │  🛡️ Health    │  Connection, data quality, diagnostics │
        │  ⚙️ Settings  │  Preferences, markets, AI tools        │
        └─────────────────────────────────────────────────────────┘
        """
        state = self._read_state()
        total_active = 0
        daily_pnl = 0.0
        agent_running = False
        gateway_running = False
        connection_ok = False
        
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            challenge_positions = self._count_open_challenge_positions()
            total_active = positions + active_trades + challenge_positions
            daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
            agent_running = bool(self._is_agent_process_running())
            connection_ok = state.get("connection_status") == "connected"
        
        # Check gateway status
        try:
            sc = getattr(self, "service_controller", None)
            if sc:
                gw_status = sc.get_gateway_status() or {}
                gateway_running = bool(gw_status.get("process_running")) and bool(gw_status.get("port_listening"))
        except Exception:
            pass

        # ─────────────────────────────────────────────────────────────────
        # Dynamic labels with live status indicators
        # ─────────────────────────────────────────────────────────────────
        
        # Activity: show P&L and active count
        if total_active > 0 and daily_pnl != 0:
            pnl_dot = "🟢" if daily_pnl >= 0 else "🔴"
            activity_label = f"📊 {total_active} | {pnl_dot}${abs(daily_pnl):.0f}"
        elif total_active > 0:
            activity_label = f"📊 Activity ({total_active})"
        elif daily_pnl != 0:
            pnl_dot = "🟢" if daily_pnl >= 0 else "🔴"
            activity_label = f"📊 {pnl_dot}${abs(daily_pnl):.0f}"
        else:
            activity_label = "📊 Activity"
        
        # System: agent + gateway status
        if agent_running and gateway_running:
            system_label = "🎛️ System 🟢"
        elif agent_running or gateway_running:
            system_label = "🎛️ System 🟡"
        else:
            system_label = "🎛️ System 🔴"
        
        # Health: connection status
        if connection_ok:
            health_label = "🛡️ Health 🟢"
        elif state:
            health_label = "🛡️ Health 🔴"
        else:
            health_label = "🛡️ Health ⚪"
        
        # Settings: static
        settings_label = "⚙️ Settings"

        # ─────────────────────────────────────────────────────────────────
        # Clean 4-button menu (2x2 grid) - each leads to unique submenu
        # ─────────────────────────────────────────────────────────────────
        return [
            [
                InlineKeyboardButton(activity_label, callback_data="menu:activity"),
                InlineKeyboardButton(system_label, callback_data="menu:system"),
            ],
            [
                InlineKeyboardButton(health_label, callback_data="menu:status"),
                InlineKeyboardButton(settings_label, callback_data="menu:settings"),
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="action:refresh_dashboard"),
            ],
        ]

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send visual dashboard with 12h chart and compact navigation menu."""
        if not update.message:
            return
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return
        logger.info("Received /start or /menu command - sending visual dashboard")
        
        # Always send visual dashboard with chart
        await self._send_visual_dashboard(update.message)

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
            "Use 🎛️ System to start/stop the agent.\n"
            "Use 🤖 Bots for trading bot controls, backtests, and reports."
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
        
        # Resolve legacy callbacks to canonical form (backward compatibility)
        raw_callback = query.data
        callback_data = resolve_callback(raw_callback)
        if callback_data != raw_callback:
            logger.debug(f"Resolved legacy callback: {raw_callback} -> {callback_data}")
        logger.info(f"Received callback: {callback_data}")

        # Parse and route callback using canonical format
        callback_type, action, param = parse_callback(callback_data)
        
        # IMPORTANT: If current message is a photo (chart dashboard), we need to
        # convert to text message before showing submenus. Delete photo and track
        # that we need to send a new message instead of editing.
        message = query.message
        is_photo_message = message and message.photo
        
        if is_photo_message and callback_type in ("menu", "action", "confirm") and action != "main":
            # Delete photo message so submenus can use text editing
            try:
                await message.delete()
            except Exception:
                pass
            # Create a fake query that will send new messages instead of editing
            query._from_photo = True  # Mark that we came from a photo
        
        try:
            if callback_type == "menu":
                # Handle "menu:main" as return to main menu
                if action == "main":
                    await self._show_main_menu(query)
                else:
                    await self._handle_menu_action(query, action)
            elif callback_type == "back":
                # Return to main menu
                await self._show_main_menu(query)
            elif callback_type == "signal_detail":
                # Signal detail drill-down (action = signal_id_prefix)
                await self._handle_signal_detail(query, action)
            elif callback_type == "patch":
                await self._handle_patch_callback(query, callback_data)
            elif callback_type == "aiops":
                await self._handle_ai_ops_callback(query, callback_data)
            elif callback_type == "confirm":
                # Confirmations are handled inside _handle_action
                await self._handle_action(query, callback_data)
            elif callback_type == "action":
                # Route to action handler with canonical format
                await self._handle_action(query, callback_data)
            else:
                # Unrecognized format - try legacy action handling
                await self._handle_action(query, callback_data)
        except Exception as e:
            # Handle "no text in message" error by sending new message
            err_str = str(e).lower()
            if "no text in the message" in err_str or "message to edit not found" in err_str:
                logger.warning(f"Edit failed (likely photo message), sending new message: {e}")
                try:
                    keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
                    await message.chat.send_message(
                        f"⚠️ Navigation error. Tap Back to return to menu.",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except Exception:
                    pass
            else:
                logger.error(f"Callback error: {e}", exc_info=True)
                raise

    async def _safe_edit_or_send(
        self,
        query: CallbackQuery,
        text: str,
        reply_markup: InlineKeyboardMarkup = None,
        parse_mode: str = "Markdown"
    ) -> None:
        """Safely edit message text or send new message if current is photo/deleted.
        
        This handles the case where the main menu shows a chart (photo message)
        and buttons need to navigate to text-only screens.
        """
        message = query.message
        
        # Check if message was already deleted (from photo handling in callback)
        from_photo = getattr(query, "_from_photo", False)
        
        if from_photo:
            # Message was deleted, send new
            try:
                await message.chat.send_message(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            except Exception as send_err:
                logger.error(f"Failed to send message after photo delete: {send_err}")
            return
        
        try:
            # Try to edit text first (works for text messages)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            err_str = str(e).lower()
            # If edit fails (e.g., photo message or deleted), send new
            if "no text in the message" in err_str or "message to edit not found" in err_str or "message is not modified" in err_str:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    await message.chat.send_message(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                except Exception as send_err:
                    logger.error(f"Failed to send replacement message: {send_err}")
            else:
                # Re-raise if it's a different error
                raise

    async def _handle_menu_action(self, query: CallbackQuery, action: str) -> None:
        """Handle menu button actions."""
        if action == "status":
            await self._show_status_menu(query)
        elif action == "signals":
            await self._show_activity_menu(query)  # Redirect to unified Activity
        elif action == "performance":
            await self._show_activity_menu(query)  # Redirect to unified Activity
        elif action == "activity":
            await self._show_activity_menu(query)
        elif action == "bots":
            await self._show_bots_menu(query)
        elif action == "markets":
            await self._show_markets_menu(query)
        elif action == "system":
            await self._show_system_menu(query)
        elif action == "settings":
            await self._show_settings_menu(query)
        elif action == "help":
            await self._show_help(query)
        else:
            await self._safe_edit_or_send(query, f"Unknown action: {action}")

    async def _show_main_menu(self, query: CallbackQuery) -> None:
        """Show visual dashboard with 12h chart - the primary menu view."""
        # Visual dashboard = chart + status text + compact nav (always)
        await self._show_main_menu_with_chart(query)

    async def _show_markets_menu(self, query: CallbackQuery) -> None:
        """Show market selector menu with per-market status overview."""
        # Small fallback mapping for display when a market has no state yet.
        default_symbols = {"NQ": "MNQ", "ES": "MES", "GC": "MGC"}

        active_symbol = default_symbols.get(self.active_market, self.active_market)
        try:
            active_state = self._read_state() or {}
            active_symbol = str(active_state.get("symbol") or active_symbol)
        except Exception:
            pass

        lines = [
            "🌐 *Markets*",
            "",
            f"Active market: *{self.active_market}* ({active_symbol})",
            "",
            "*Overview:*",
        ]

        # Build quick status lines from process check + state.json (if present).
        sc = getattr(self, "service_controller", None)
        for market in self._available_markets:
            running = False
            try:
                if sc is not None:
                    running = bool((sc.get_agent_status(market=market) or {}).get("running"))
            except Exception:
                running = False

            state = None
            try:
                state_file = self._state_dir_path_for_market(market) / "state.json"
                if state_file.exists():
                    state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                state = None

            symbol = default_symbols.get(market, market)
            bot_status = "unknown"
            if isinstance(state, dict) and state:
                symbol = str(state.get("symbol") or symbol)
                tb = state.get("trading_bot") or {}
                tb_enabled = bool(tb.get("enabled", False))
                tb_selected = tb.get("selected") or "pearl_bot_auto"
                bot_status = tb_selected if tb_enabled else "OFF (scanner)"
            else:
                bot_status = "no state"

            status_emoji = "🟢" if running else "🔴"
            lines.append(f"- *{market}* {status_emoji} | {symbol} | 🤖 {bot_status}")

        lines.extend(
            [
                "",
                "Select a market (this only switches the Telegram UI context):",
            ]
        )

        keyboard = []
        for market in self._available_markets:
            label = f"✅ {market}" if market == self.active_market else market
            keyboard.append([InlineKeyboardButton(label, callback_data=f"action:set_market:{market}")])
        keyboard.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="back")])
        await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
                                await query.message.chat.send_photo(
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

    async def _send_visual_dashboard(self, message_obj) -> None:
        """Send visual dashboard with 12h chart to a new message (for /menu command).
        
        This is the primary dashboard view - always includes chart when available.
        Used for initial messages (not callback edits).
        """
        keyboard = self._get_main_menu_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        state = self._read_state()
        if not state:
            await message_obj.reply_text(
                "🎯 Pearl Algo Bot's\n\n❌ No state data available.\n\nSelect an option:",
                reply_markup=reply_markup
            )
            return
        
        try:
            message_text = await self._build_status_dashboard_message(state)
            chart_path = await self._generate_or_get_chart(state)
            
            if chart_path and chart_path.exists():
                # Send photo with caption
                with open(chart_path, 'rb') as f:
                    await message_obj.reply_photo(
                        photo=f,
                        caption=message_text,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
            else:
                # Fallback to text-only if chart unavailable
                await message_obj.reply_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error sending visual dashboard: {e}", exc_info=True)
            # Fallback to simple menu
            await message_obj.reply_text(
                "🎯 Pearl Algo Bot's\n\nSelect an option:",
                reply_markup=reply_markup
            )

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
            from pearlalgo.market_agent.chart_generator import ChartGenerator
            from pearlalgo.data_providers.ibkr.ibkr_provider import IBKRProvider
            from pearlalgo.config.config_loader import load_service_config
            from pearlalgo.utils.volume_pressure import timeframe_to_minutes
            
            symbol = state.get("symbol") or "MNQ"
            
            # Read chart settings from config.yaml (same source as the service chart push)
            # Default: 12h lookback for comprehensive visual dashboard
            svc_cfg = load_service_config()
            service_cfg = (svc_cfg.get("service", {}) or {}) if isinstance(svc_cfg, dict) else {}
            min_lookback_hours = 6.0
            max_lookback_hours = 24.0
            lookback_hours = float(service_cfg.get("dashboard_chart_lookback_hours", 12) or 12)
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
        """Show health & diagnostics submenu."""
        state = self._read_state()
        
        # Determine status indicators
        gw_status = "🟢" 
        conn_status = "🟢"
        data_status = "🟢"
        
        if state:
            connection_status = state.get("connection_status", "unknown")
            if connection_status != "connected":
                gw_status = "🔴"
                conn_status = "🔴"
            
            # Check data freshness
            latest_bar = state.get("latest_bar", {})
            if not latest_bar:
                data_status = "🔴"
        else:
            gw_status = "⚪"
            conn_status = "⚪"
            data_status = "⚪"
        
        lines = [
            "🛡️ *Health*",
            "",
            f"Gateway: {gw_status} | Connection: {conn_status} | Data: {data_status}",
        ]
        
        keyboard = [
            [
                InlineKeyboardButton(f"🔌 Gateway {gw_status}", callback_data="action:gateway_status"),
                InlineKeyboardButton(f"📡 Connection {conn_status}", callback_data="action:connection_status"),
            ],
            [
                InlineKeyboardButton(f"📊 Data Quality {data_status}", callback_data="action:data_quality"),
                InlineKeyboardButton("📋 Full Status", callback_data="action:system_status"),
            ],
            [InlineKeyboardButton("🏠 Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")

    async def _show_ui_doctor(self, query: CallbackQuery) -> None:
        """Self-serve Telegram UI diagnostics and safe test sends."""
        from datetime import datetime, timezone

        prefs = TelegramPrefs(state_dir=self.state_dir)
        state = None
        try:
            state = self._read_state()
        except Exception:
            state = None
        if not isinstance(state, dict):
            state = {}

        # Prefs (operator-facing)
        auto_chart = bool(prefs.get("auto_chart_on_signal", False))
        interval_notifications = bool(prefs.get("interval_notifications", True))
        expanded_details = bool(prefs.get("signal_detail_expanded", False))
        pinned_dashboard = bool(prefs.get("dashboard_edit_in_place", False))
        snooze_on = bool(getattr(prefs, "snooze_noncritical_alerts", False))
        pinned_id = prefs.get("dashboard_message_id")

        # Last dashboard time (persisted by notifier)
        last_dash = prefs.get("last_dashboard_sent_at")
        last_dash_age = format_time_ago(str(last_dash)) if last_dash else ""

        # Data freshness (from latest_bar)
        latest_bar = state.get("latest_bar") if isinstance(state.get("latest_bar"), dict) else {}
        data_level = (latest_bar or {}).get("_data_level")
        data_age_min = None
        try:
            ts = (latest_bar or {}).get("timestamp")
            if ts:
                dt = parse_utc_timestamp(str(ts))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt:
                    data_age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
        except Exception:
            data_age_min = None

        # Service status (best-effort)
        agent_running = False
        try:
            agent_running = bool(self._is_agent_process_running())
        except Exception:
            agent_running = False

        gateway_status = None
        try:
            sc = getattr(self, "service_controller", None)
            fn = getattr(sc, "get_gateway_status", None)
            if callable(fn):
                gateway_status = fn() or {}
        except Exception:
            gateway_status = None

        symbol = str(state.get("symbol") or "MNQ")
        market = str(state.get("market") or self.active_market)

        lines: list[str] = []
        lines.append("🩺 *UI Doctor*")
        lines.append("")
        lines.append(f"🌐 Market: *{safe_label(market)}* | 📈 Symbol: *{safe_label(symbol)}*")
        lines.append(f"🤖 Agent: {'🟢 RUNNING' if agent_running else '🔴 STOPPED'}")
        if isinstance(gateway_status, dict) and gateway_status:
            proc = bool(gateway_status.get("process_running", False))
            port = bool(gateway_status.get("port_listening", False))
            gw_ok = proc and port
            lines.append(f"🔌 Gateway: {'🟢 Online' if gw_ok else '🔴 Offline'} (proc={proc}, port={port})")
        else:
            lines.append("🔌 Gateway: ⚪ Unknown")

        # Freshness line
        if data_age_min is None:
            lines.append("📡 Data: ⚪ Unknown")
        else:
            lvl = safe_label(str(data_level or "unknown"))
            lines.append(f"📡 Data: *{lvl}* • Age: *{data_age_min:.1f}m*")

        # Prefs summary
        def _onoff(v: bool) -> str:
            return "🟢 ON" if v else "🔴 OFF"

        lines.append("")
        lines.append("*Prefs:*")
        lines.append(f"- 🔘 Menu navigation: 🟢 ON (always)")
        lines.append(f"- 📌 Pinned dashboard: {_onoff(pinned_dashboard)}")
        lines.append(f"- 🕐 Interval dashboards: {_onoff(interval_notifications)}")
        lines.append(f"- 📈 Auto-chart on signal: {_onoff(auto_chart)}")
        lines.append(f"- 🔍 Expanded details: {_onoff(expanded_details)}")
        if snooze_on:
            until = prefs.get("snooze_until")
            until_age = format_time_ago(str(until)) if until else ""
            lines.append(f"- 🔕 Snooze (non-critical): 🟢 ON {('(' + until_age + ')') if until_age else ''}".rstrip())
        else:
            lines.append(f"- 🔕 Snooze (non-critical): {_onoff(False)}")

        if last_dash:
            lines.append(f"- 🧾 Last dashboard: {safe_label(str(last_dash_age or last_dash))}")
        else:
            lines.append("- 🧾 Last dashboard: N/A")
        if pinned_id:
            try:
                lines.append(f"- 🆔 Pinned msg id: `{int(pinned_id)}`")
            except Exception:
                lines.append("- 🆔 Pinned msg id: (invalid)")

        lines.append("")
        lines.append("*Safe tests (UI-only):*")

        keyboard = [
            [
                InlineKeyboardButton("🧪 Test Dashboard", callback_data="action:ui_doctor:test_dashboard"),
                InlineKeyboardButton("⚠️ Test Risk Alert", callback_data="action:ui_doctor:test_risk"),
            ],
            [
                InlineKeyboardButton("🧪 Test Signal", callback_data="action:ui_doctor:test_signal"),
                InlineKeyboardButton("🔕 Toggle Snooze", callback_data="action:ui_doctor:toggle_snooze"),
            ],
            [
                InlineKeyboardButton("📌 Toggle Pinned", callback_data="action:ui_doctor:toggle_pinned"),
                InlineKeyboardButton("🧹 Reset Pinned ID", callback_data="action:ui_doctor:reset_pinned"),
            ],
            [
                InlineKeyboardButton("🛡 Back to Health", callback_data="menu:status"),
                InlineKeyboardButton("🏠 Menu", callback_data="back"),
            ],
        ]
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _handle_ui_doctor_action(self, query: CallbackQuery, action: str) -> None:
        """Handle UI Doctor actions (test sends + preference toggles)."""
        from datetime import datetime, timezone
        from pathlib import Path

        prefs = TelegramPrefs(state_dir=self.state_dir)

        # Local helper to build a notifier instance (UI-only sends).
        def _build_notifier():
            try:
                from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
                return MarketAgentTelegramNotifier(
                    bot_token=self.bot_token,
                    chat_id=str(self.chat_id),
                    state_dir=Path(self.state_dir),
                    enabled=True,
                )
            except Exception:
                return None

        if action == "toggle_snooze":
            try:
                if bool(getattr(prefs, "snooze_noncritical_alerts", False)):
                    prefs.disable_snooze()
                else:
                    prefs.enable_snooze(hours=1.0)
            except Exception:
                pass
            await self._show_ui_doctor(query)
            return

        if action == "toggle_pinned":
            try:
                cur = bool(prefs.get("dashboard_edit_in_place", False))
                prefs.set("dashboard_edit_in_place", not cur)
                prefs.set("dashboard_message_id", None)
            except Exception:
                pass
            await self._show_ui_doctor(query)
            return

        if action == "reset_pinned":
            try:
                prefs.set("dashboard_message_id", None)
            except Exception:
                pass
            await self._show_ui_doctor(query)
            return

        notifier = _build_notifier()
        if notifier is None:
            await query.edit_message_text(
                "❌ UI Doctor could not initialize Telegram notifier.\n\nCheck TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛡 Back to Health", callback_data="menu:status")]]),
            )
            return

        # Real state (if available) for tests.
        try:
            state = self._read_state()
        except Exception:
            state = None
        if not isinstance(state, dict):
            state = {}

        now = datetime.now(timezone.utc)

        if action == "test_dashboard":
            # Build a safe, synthetic dashboard payload (no trading side effects).
            latest_bar = state.get("latest_bar") if isinstance(state.get("latest_bar"), dict) else {}
            latest_price = state.get("latest_price")
            if latest_price is None and isinstance(latest_bar, dict):
                latest_price = latest_bar.get("close")
            status = {
                "symbol": state.get("symbol", "MNQ"),
                "current_time": now,
                "latest_price": latest_price,
                "latest_bar": latest_bar or {"timestamp": now.isoformat(), "close": latest_price or 0.0, "_data_level": "unknown"},
                "cycle_count": int(state.get("cycle_count", 0) or 0),
                "cycle_count_session": state.get("cycle_count_session"),
                "signal_count": int(state.get("signal_count", 0) or 0),
                "signals_sent": int(state.get("signals_sent", 0) or 0),
                "signals_send_failures": int(state.get("signals_send_failures", 0) or 0),
                "error_count": int(state.get("error_count", 0) or 0),
                "buffer_size": int(state.get("buffer_size", 0) or 0),
                "buffer_size_target": state.get("buffer_size_target"),
                "paused": bool(state.get("paused", False)),
                "pause_reason": state.get("pause_reason"),
                "strategy_session_open": state.get("strategy_session_open"),
                "futures_market_open": state.get("futures_market_open"),
                "execution": state.get("execution") or {},
                "active_trades_count": int(state.get("active_trades_count", 0) or 0),
                "active_trades_unrealized_pnl": state.get("active_trades_unrealized_pnl"),
                "latest_price_source": state.get("latest_price_source"),
                "quiet_reason": state.get("quiet_reason") or "NoOpportunity",
                # Unique marker to avoid dedupe and make it obvious this is a test.
                "signal_diagnostics": f"UI Doctor test dashboard @ {now.strftime('%H:%M:%S')} UTC",
            }
            await notifier.send_dashboard(status)
            await self._show_ui_doctor(query)
            return

        if action == "test_risk":
            await notifier.send_data_quality_alert(
                alert_type="data_gap",
                message=f"🧪 UI Doctor test risk alert ({now.strftime('%H:%M:%S')} UTC)",
                details={"severity": "low", "suggestion": "Tap Snooze 1h to suppress non-critical alerts"},
            )
            await self._show_ui_doctor(query)
            return

        if action == "test_signal":
            test_signal = {
                "_is_test": True,
                "signal_id": f"ui_doctor_test_{int(now.timestamp())}",
                "symbol": state.get("symbol", "MNQ") or "MNQ",
                "type": "ui_doctor_test",
                "direction": "long",
                "status": "generated",
                "entry_price": float(state.get("latest_price") or 25000.0),
                "stop_loss": float(state.get("latest_price") or 25000.0) - 20.0,
                "take_profit": float(state.get("latest_price") or 25000.0) + 40.0,
                "confidence": 0.70,
                "timestamp": now.isoformat(),
                "reason": "test ui doctor",
            }
            await notifier.send_signal(test_signal, buffer_data=None)
            await self._show_ui_doctor(query)
            return

        # Unknown sub-action → just re-render.
        await self._show_ui_doctor(query)

    async def _show_activity_menu(self, query: CallbackQuery) -> None:
        """Show unified Activity menu (merged Trades + Performance)."""
        try:
            state = self._read_state()
            metrics = self._read_latest_metrics()
            
            # Gather data
            active_count = 0
            daily_signals = 0
            daily_pnl = 0.0
            daily_trades = 0
            daily_wins = 0
            daily_losses = 0
            
            if state:
                positions = (state.get("execution", {}).get("positions", 0) or 0)
                active_trades = state.get("active_trades_count", 0) or 0
                active_count = positions + active_trades
                daily_signals = state.get("daily_signals", 0) or 0
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                daily_trades = state.get("daily_trades", 0) or 0
                daily_wins = state.get("daily_wins", 0) or 0
                daily_losses = state.get("daily_losses", 0) or 0
            
            signals = self._read_recent_signals(limit=10)
            recent_count = len(signals) if signals else 0
            
            # Build compact activity summary
            lines = ["📊 *Activity*", ""]
            
            # Performance card (compact)
            pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
            pnl_sign = "+" if daily_pnl >= 0 else ""
            lines.append(f"*Today:* {pnl_emoji} {pnl_sign}${abs(daily_pnl):.2f}")
            
            if daily_trades > 0:
                wr = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
                lines.append(f"Trades: {daily_trades} ({daily_wins}W/{daily_losses}L) | {wr:.0f}% WR")
            
            lines.append(f"Signals: {daily_signals} | Open: {active_count}")
            lines.append("")
            
            # Build buttons
            active_label = f"📋 Active ({active_count})" if active_count > 0 else "📋 Active"
            recent_label = f"🎯 Signals ({recent_count})" if recent_count > 0 else "🎯 Signals"
            
            keyboard = [
                # Row 1: Current positions & signals
                [
                    InlineKeyboardButton(active_label, callback_data="action:active_trades"),
                    InlineKeyboardButton(recent_label, callback_data="action:recent_signals"),
                ],
                # Row 2: Reports
                [
                    InlineKeyboardButton("📈 Performance", callback_data="action:performance_metrics"),
                    InlineKeyboardButton("📊 History", callback_data="action:signal_history"),
                ],
                # Row 3: Actions
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="menu:activity"),
                    InlineKeyboardButton("🏠 Back", callback_data="back"),
                ],
            ]
            
            # Add Close All if positions exist
            if active_count > 0:
                keyboard.insert(2, [
                    InlineKeyboardButton(f"🚫 Close All ({active_count})", callback_data="action:close_all_trades"),
                    InlineKeyboardButton("💰 P&L Detail", callback_data="action:pnl_overview"),
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in _show_activity_menu: {e}", exc_info=True)
            keyboard = [
                [
                    InlineKeyboardButton("🎯 Signals", callback_data="action:recent_signals"),
                    InlineKeyboardButton("📋 Active", callback_data="action:active_trades"),
                ],
                [InlineKeyboardButton("🏠 Back", callback_data="back")],
            ]
            await self._safe_edit_or_send(query, "📊 Activity\n\nSelect an option:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_signals_menu(self, query: CallbackQuery) -> None:
        """Legacy signals menu - redirects to Activity menu."""
        await self._show_activity_menu(query)

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
            await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")
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
        """Show bot hub menu with trading mode picker and service status."""
        agent_status = {"running": False, "message": "Unknown"}
        gateway_status = {"process_running": False, "port_listening": False}

        try:
            sc = getattr(self, "service_controller", None)
            if sc is not None:
                agent_status = sc.get_agent_status(market=self.active_market) or agent_status
                gateway_status = sc.get_gateway_status() or gateway_status
        except Exception as e:
            logger.warning(f"Could not load bot status: {e}")

        running = bool(agent_status.get("running"))
        gateway_ready = bool(gateway_status.get("process_running")) and bool(gateway_status.get("port_listening"))
        
        # Get trading mode from state
        state = self._read_state()
        trading_bot_enabled = False
        trading_bot_selected = "pearl_bot_auto"
        
        if state:
            tb_state = state.get("trading_bot") or {}
            trading_bot_enabled = bool(tb_state.get("enabled", False))
            trading_bot_selected = tb_state.get("selected") or "pearl_bot_auto"
        
        # Determine current mode
        if trading_bot_enabled:
            mode_label = "🟢 Pearl Bot Auto"
            mode_desc = "Active trading enabled"
        else:
            mode_label = "🔴 Scanner Only"
            mode_desc = "Scan signals, no execution"
        
        # Build rich status display
        lines = ["🤖 *Trading Bots*", f"*Market:* {self.active_market}", ""]
        
        # Trading Mode Section
        lines.append("━━━━━ *Trading Mode* ━━━━━")
        lines.append(f"Current: *{mode_label}*")
        lines.append(f"_{mode_desc}_")
        lines.append("")
        
        # Service Status
        lines.append("━━━━━ *Services* ━━━━━")
        agent_emoji = "🟢" if running else "🔴"
        lines.append(f"🤖 Agent: {agent_emoji} {'RUNNING' if running else 'STOPPED'}")
        gateway_emoji = "🟢" if gateway_ready else "🔴"
        lines.append(f"🔌 Gateway: {gateway_emoji} {'ONLINE' if gateway_ready else 'OFFLINE'}")
        lines.append("")
        
        # Startup Sequence Guidance
        if not gateway_ready or not running:
            lines.append("━━━━━ *Quick Start* ━━━━━")
            if not gateway_ready:
                lines.append("1️⃣ Start Gateway first")
            if not running:
                step = "2️⃣" if not gateway_ready else "1️⃣"
                lines.append(f"{step} Then start Agent")
            lines.append("_Use 🎛️ System for controls_")
            lines.append("")
        
        # Mode buttons
        if trading_bot_enabled:
            mode_btn_label = "🔴 Switch to Scanner"
            mode_btn_callback = "action:set_trading_mode:scanner"
        else:
            mode_btn_label = "🟢 Enable Pearl Bot"
            mode_btn_callback = "action:set_trading_mode:pearl_bot_auto"

        keyboard = [
            # Row 1: Trading Mode & System
            [
                InlineKeyboardButton(mode_btn_label, callback_data=mode_btn_callback),
                InlineKeyboardButton("🎛️ System", callback_data="menu:system"),
            ],
            # Row 2: Tools
            [
                InlineKeyboardButton("🧪 Backtest", callback_data="strategy_review:backtest"),
                InlineKeyboardButton("📑 Reports", callback_data="strategy_review:reports"),
            ],
            # Row 3: Navigation
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="menu:bots"),
                InlineKeyboardButton("🏠 Back", callback_data="back"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")

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
                agent_status = sc.get_agent_status(market=self.active_market) or {}
                agent_running = bool(agent_status.get("running"))
        except Exception:
            pass
        
        if state:
            positions = (state.get("execution", {}).get("positions", 0) or 0)
            active_trades = state.get("active_trades_count", 0) or 0
            positions_count = positions + active_trades
            has_positions = positions_count > 0
            daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
        
        # Check gateway status
        gateway_running = False
        gateway_port = False
        try:
            sc = getattr(self, "service_controller", None)
            if sc:
                gw_status = sc.get_gateway_status() or {}
                gateway_running = bool(gw_status.get("process_running"))
                gateway_port = bool(gw_status.get("port_listening"))
        except Exception:
            pass
        
        # Clean, compact system status
        gw_status_txt = "🟢 ON" if (gateway_running and gateway_port) else "🔴 OFF"
        agent_status_txt = "🟢 ON" if agent_running else "🔴 OFF"
        
        lines = [
            "🎛️ *System*",
            "",
            f"Gateway: {gw_status_txt} | Agent: {agent_status_txt}",
        ]
        
        if has_positions:
            lines.append(f"⚠️ {positions_count} open position{'s' if positions_count != 1 else ''}")
        
        # Dynamic button labels
        agent_btn = "🛑 Stop Agent" if agent_running else "🚀 Start Agent"
        agent_action = "action:stop_agent" if agent_running else "action:start_agent"
        
        gw_btn = "🛑 Stop Gateway" if (gateway_running and gateway_port) else "🚀 Start Gateway"
        gw_action = "action:stop_gateway" if (gateway_running and gateway_port) else "action:start_gateway"
        
        keyboard = [
            # Row 1: Agent & Gateway controls
            [
                InlineKeyboardButton(agent_btn, callback_data=agent_action),
                InlineKeyboardButton(gw_btn, callback_data=gw_action),
            ],
            # Row 2: Restart & Status
            [
                InlineKeyboardButton("🔄 Restart All", callback_data="action:restart_gateway"),
                InlineKeyboardButton("📊 Status", callback_data="action:gateway_status"),
            ],
            # Row 3: Config & Logs
            [
                InlineKeyboardButton("⚙️ Config", callback_data="action:config"),
                InlineKeyboardButton("📋 Logs", callback_data="action:logs"),
            ],
            # Row 4: Advanced
            [
                InlineKeyboardButton("🔄 Reset Challenge", callback_data="action:reset_challenge"),
                InlineKeyboardButton("🧹 Clear Cache", callback_data="action:clear_cache"),
            ],
        ]
        
        # Emergency stop (only if positions exist)
        if has_positions:
            keyboard.append([
                InlineKeyboardButton(f"🚨 Emergency Close ({positions_count})", callback_data="action:emergency_stop"),
            ])
        
        # Back
        keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")


    async def _show_settings_menu(self, query: CallbackQuery) -> None:
        """Show settings submenu with detailed descriptions and recommendations."""
        prefs = TelegramPrefs(state_dir=self.state_dir)
        auto_chart = bool(prefs.get("auto_chart_on_signal", False))
        interval_notifications = bool(prefs.get("interval_notifications", True))
        signal_detail_expanded = bool(prefs.get("signal_detail_expanded", False))
        pinned_dashboard = bool(prefs.get("dashboard_edit_in_place", False))
        snooze_on = bool(getattr(prefs, "snooze_noncritical_alerts", False))
        snooze_until_str: str | None = None
        if snooze_on:
            try:
                import pytz
                from datetime import datetime, timezone

                snooze_until = prefs.get("snooze_until")
                if snooze_until:
                    expiry = datetime.fromisoformat(str(snooze_until).replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    et = expiry.astimezone(pytz.timezone("US/Eastern"))
                    snooze_until_str = et.strftime("%I:%M %p ET").lstrip("0")
            except Exception:
                snooze_until_str = None

        def _onoff(v: bool) -> str:
            return "🟢 ON" if v else "🔴 OFF"

        # Determine current alert mode
        if auto_chart and interval_notifications and signal_detail_expanded:
            current_mode = "verbose"
            mode_emoji = "🔊"
        elif auto_chart and interval_notifications:
            current_mode = "standard"
            mode_emoji = "📊"
        else:
            current_mode = "minimal"
            mode_emoji = "🔕"

        lines = [
            "⚙️ *Settings*",
            "",
            f"*Market:* {self.active_market}",
            f"*Alert Mode:* {mode_emoji} {current_mode.title()}",
            f"*Pinned:* {_onoff(pinned_dashboard)} | *Snooze:* {_onoff(snooze_on)}",
        ]

        keyboard = [
            # Row 1: Market Selection
            [
                InlineKeyboardButton(f"🌐 Market: {self.active_market}", callback_data="menu:markets"),
                InlineKeyboardButton("🤖 Trading Bot", callback_data="menu:bots"),
            ],
            # Row 2: Alert Mode Presets
            [
                InlineKeyboardButton(
                    f"{'✅' if current_mode == 'minimal' else '🔕'} Minimal",
                    callback_data="action:set_alert_mode:minimal",
                ),
                InlineKeyboardButton(
                    f"{'✅' if current_mode == 'standard' else '📊'} Standard",
                    callback_data="action:set_alert_mode:standard",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{'✅' if current_mode == 'verbose' else '🔊'} Verbose",
                    callback_data="action:set_alert_mode:verbose",
                ),
                InlineKeyboardButton("❓ Help", callback_data="menu:help"),
            ],
            # Row 4: Advanced toggles
            [
                InlineKeyboardButton(
                    f"📌 Pinned: {_onoff(pinned_dashboard)}",
                    callback_data="action:toggle_pref:dashboard_edit_in_place",
                ),
                InlineKeyboardButton(
                    f"🔕 Snooze: {_onoff(snooze_on)}",
                    callback_data="action:toggle_pref:snooze_noncritical_alerts",
                ),
            ],
            # Row 5: AI Tools
            [
                InlineKeyboardButton("🧩 AI Patch", callback_data="action:ai_patch_wizard"),
                InlineKeyboardButton("🧠 AI Ops", callback_data="action:ai_ops"),
            ],
            # Row 6: Back
            [InlineKeyboardButton("🏠 Menu", callback_data="back")],
        ]
        await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _ensure_openai_ready(self, target: Any, context: Any | None = None) -> bool:
        """Ensure OpenAI dependency and API key are set.

        For command flows (Update + Context), prefer `_send_message_or_edit` so the
        behavior is consistent (and unit-testable). For callback flows, fall back
        to editing the message directly.
        """
        msg: str | None = None
        if not OPENAI_AVAILABLE:
            msg = "❌ OpenAI Not Available (dependency not installed).\n\nInstall with: pip install -e '.[llm]'"
        else:
            # Validate that OpenAIClient can be constructed (covers missing API key).
            try:
                OpenAIClient()
                return True
            except OpenAIAPIKeyMissingError as e:
                msg = f"❌ API Key missing: {e}"
            except OpenAINotAvailableError as e:
                msg = f"❌ Not Available: {e}\n\nInstall with: pip install -e '.[llm]'"
            except Exception as e:
                msg = f"❌ Error: {e}"

        if context is not None:
            try:
                await self._send_message_or_edit(target, context, msg)
                return False
            except Exception:
                # Fall back to raw telegram methods below
                pass

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
            [InlineKeyboardButton("src/pearlalgo/market_agent/telegram_command_handler.py", callback_data="patch:file:src/pearlalgo/market_agent/telegram_command_handler.py")],
            [InlineKeyboardButton("src/pearlalgo/market_agent/service.py", callback_data="patch:file:src/pearlalgo/market_agent/service.py")],
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
        bot_names: list[str] = []

        lines = ["🧠 *AI Ops*", "", "Select a target:"]
        keyboard = []
        for name in bot_names[:8]:
            keyboard.append([InlineKeyboardButton(name, callback_data=f"aiops:bot:{name}")])
        keyboard.append([InlineKeyboardButton("Market Agent", callback_data="aiops:bot:market_agent")])
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
                [InlineKeyboardButton("src/pearlalgo/strategies/trading_bots/pearl_bot_auto.py", callback_data="aiops:file:src/pearlalgo/strategies/trading_bots/pearl_bot_auto.py")],
                # market_regime_detector.py removed
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
                "Send the file path now.\n\nExample:\nsrc/pearlalgo/strategies/trading_bots/pearl_bot_auto.py"
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
        if bot == "market_agent":
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
            result = await sc.restart_agent(background=True, market=self.active_market)
        elif action == "telegram":
            result = await sc.restart_command_handler()
        elif action == "gateway":
            result = await sc.restart_gateway()
        elif action == "all":
            res_agent = await sc.restart_agent(background=True, market=self.active_market)
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
            "🛡 Health - System health and connection status\n"
            "🎛️ System Control - Start/stop services and emergency controls\n"
            "⚙️ Settings - Charts + notification preferences\n"
            "🤖 Bots - trading bot controls, backtests, reports\n\n"
            "*Quick Tips:*\n"
            "• Use 'Back to Menu' to return to main menu\n"
            "• Status indicators show active positions/trades\n"
            "• Emergency Stop closes all positions immediately\n"
            "• All actions are logged for audit trail"
        )
        keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, help_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_action(self, query: CallbackQuery, action: str) -> None:
        """Handle action button presses."""
        if action.startswith("action:"):
            action_type = action[7:]  # Remove "action:" prefix

            if action_type.startswith("set_market:"):
                market = action_type.split(":", 1)[1]
                self._set_active_market(market)
                await self._show_markets_menu(query)
                return

            # Alert mode presets (settings menu)
            if action_type.startswith("set_alert_mode:"):
                mode = action_type.split(":", 1)[1]
                prefs = TelegramPrefs(state_dir=self.state_dir)
                try:
                    if mode == "minimal":
                        # Signals only, no charts, no interval updates
                        prefs.set("auto_chart_on_signal", False)
                        prefs.set("interval_notifications", False)
                        prefs.set("signal_detail_expanded", False)
                    elif mode == "standard":
                        # Signals + charts (recommended)
                        prefs.set("auto_chart_on_signal", True)
                        prefs.set("interval_notifications", True)
                        prefs.set("signal_detail_expanded", False)
                    elif mode == "verbose":
                        # Everything + detailed info
                        prefs.set("auto_chart_on_signal", True)
                        prefs.set("interval_notifications", True)
                        prefs.set("signal_detail_expanded", True)
                except Exception as e:
                    logger.error(f"Error setting alert mode: {e}")
                await self._show_settings_menu(query)
                return

            # Preferences toggles (settings menu)
            if action_type.startswith("toggle_pref:"):
                pref_key = action_type[len("toggle_pref:") :]
                prefs = TelegramPrefs(state_dir=self.state_dir)
                try:
                    # Snooze is not a simple boolean toggle: it requires an expiry.
                    if pref_key == "snooze_noncritical_alerts":
                        if bool(getattr(prefs, "snooze_noncritical_alerts", False)):
                            prefs.disable_snooze()
                        else:
                            prefs.enable_snooze(hours=1.0)
                        await self._show_settings_menu(query)
                        return

                    # Operator policy: navigation buttons are always on.
                    if pref_key == "dashboard_buttons":
                        prefs.set("dashboard_buttons", True)
                        await self._show_settings_menu(query)
                        return

                    # Pinned dashboards: when toggling, reset the stored message_id so the
                    # next dashboard creates (or stops using) a pinned message cleanly.
                    if pref_key == "dashboard_edit_in_place":
                        cur = bool(prefs.get(pref_key, False))
                        prefs.set(pref_key, not cur)
                        prefs.set("dashboard_message_id", None)
                        await self._show_settings_menu(query)
                        return

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
            elif action_type.startswith("ui_doctor"):
                # UI Doctor removed from menus; keep old buttons from breaking.
                await self._show_status_menu(query)
            elif action_type == "recent_signals":
                await self._handle_recent_signals(query, reply_markup)
            elif action_type == "active_trades":
                await self._handle_active_trades(query, reply_markup)
            elif action_type == "signal_history":
                await self._handle_signal_history(query, reply_markup)
            elif action_type == "signal_details":
                await query.edit_message_text(
                    "🔍 *Signal Details*\n\n"
                    "To view details for a specific signal:\n\n"
                    "1. Go to *Signals & Trades* → *Recent Signals*\n"
                    "2. Tap the *ℹ️ Details* button on entry/exit notifications\n\n"
                    "💡 Enable *Dashboard Buttons* in Settings to see Details buttons on trade alerts.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            elif action_type == "performance_metrics":
                await self._handle_performance_metrics(query, reply_markup)
            elif action_type == "daily_summary":
                await self._handle_daily_summary(query, reply_markup)
            elif action_type == "weekly_summary":
                await self._handle_weekly_summary(query, reply_markup)
            elif action_type == "pnl_overview":
                await self._handle_pnl_overview(query, reply_markup)
            elif action_type == "ai_patch_wizard":
                await self._show_ai_patch_wizard(query)
            elif action_type == "ai_ops":
                await self._show_ai_ops_menu(query)
            elif action_type == "restart_agent":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Restart", callback_data="confirm:restart_agent")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text(
                    f"🔄 Restart Agent ({self.active_market})\n\n⚠️ This will restart the agent service.\n\nAre you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            elif action_type == "stop_agent":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Stop", callback_data="confirm:stop_agent")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="back")],
                ]
                await query.edit_message_text(
                    f"🛑 Stop Agent ({self.active_market})\n\n⚠️ This will stop the agent service.\n\nAre you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            elif action_type == "start_agent":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    result = await sc.start_agent(background=True, market=self.active_market)
                    text = result.get("message", "Started agent.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif action_type == "start_gateway":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Start", callback_data="confirm:start_gateway")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="menu:system")],
                ]
                await query.edit_message_text(
                    "🟢 *Start IBKR Gateway*\n\n"
                    "This will start the IBKR Gateway service.\n\n"
                    "⏱️ Startup takes ~30-60 seconds.\n\n"
                    "Are you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            elif action_type == "stop_gateway":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Stop", callback_data="confirm:stop_gateway")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="menu:system")],
                ]
                await query.edit_message_text(
                    "🔴 *Stop IBKR Gateway*\n\n"
                    "⚠️ *WARNING:* This will disconnect from IBKR.\n"
                    "• Chart generation will fail\n"
                    "• Trading will be disabled\n\n"
                    "Are you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            elif action_type == "restart_gateway":
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm Restart", callback_data="confirm:restart_gateway")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="menu:system")],
                ]
                await query.edit_message_text(
                    "🔄 *Restart IBKR Gateway*\n\n"
                    "⚠️ This will restart the IBKR Gateway.\n"
                    "⏱️ Takes ~60 seconds.\n\n"
                    "Are you sure?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            elif action_type.startswith("set_trading_mode:"):
                mode = action_type.split(":", 1)[1]
                await self._handle_set_trading_mode(query, mode)
            elif action_type == "config":
                await self._handle_config_view(query, reply_markup)
            elif action_type == "logs":
                await self._handle_logs_view(query, reply_markup)
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
                        impact_lines.append("📊 *Impact Preview:*")
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
                # Refresh visual dashboard with fresh 12h chart
                # Delete cached chart to force regeneration
                try:
                    cached_chart = self.exports_dir / "dashboard_latest.png"
                    if cached_chart.exists():
                        cached_chart.unlink()
                except Exception:
                    pass
                await self._show_main_menu_with_chart(query)
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
                    result = await sc.restart_agent(background=True, market=self.active_market)
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
                    result = await sc.stop_agent(market=self.active_market)
                    text = result.get("message", "Stopped agent.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🤖 Bots", callback_data="menu:bots")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif confirm_action == "start_gateway":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    await query.edit_message_text("🟢 Starting IBKR Gateway...\n\n⏱️ This may take 30-60 seconds...", parse_mode="Markdown")
                    result = await sc.start_gateway()
                    text = result.get("message", "Started gateway.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🎛️ System", callback_data="menu:system")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif confirm_action == "stop_gateway":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    await query.edit_message_text("🔴 Stopping IBKR Gateway...", parse_mode="Markdown")
                    result = await sc.stop_gateway()
                    text = result.get("message", "Stopped gateway.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🎛️ System", callback_data="menu:system")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif confirm_action == "restart_gateway":
                sc = getattr(self, "service_controller", None)
                if sc is None:
                    text = "❌ Service controller not available."
                else:
                    await query.edit_message_text("🔄 Restarting IBKR Gateway...\n\n⏱️ This may take 60+ seconds...", parse_mode="Markdown")
                    result = await sc.restart_gateway()
                    text = result.get("message", "Restarted gateway.")
                    details = result.get("details")
                    if details:
                        text = f"{text}\n\n{details}"

                keyboard = [
                    [InlineKeyboardButton("🎛️ System", callback_data="menu:system")],
                    [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            elif confirm_action == "reset_challenge":
                try:
                    from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker = ChallengeTracker(state_dir=self.state_dir)
                    new_attempt = challenge_tracker.manual_reset(reason="telegram_reset")
                    
                    keyboard = [
                        [InlineKeyboardButton("🔄 Refresh Health", callback_data="menu:status")],
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
                        result = await sc.stop_agent(market=self.active_market)
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
                            [InlineKeyboardButton("🛡 Check Health", callback_data="menu:status")],
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
            market_label = state.get("market") or self.active_market

            # Trading bot identity (single source of truth) - surfaced in UI for clarity.
            tb_state = state.get("trading_bot") or {}
            tb_enabled = bool(tb_state.get("enabled", False))
            tb_selected = tb_state.get("selected") or "pearl_bot_auto"
            trading_bot_status = tb_selected if tb_enabled else "OFF (scanner)"
            trading_bot_label = tb_selected if tb_enabled else "Scanner"
            
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
            gateway_running = True
            gateway_unknown = False
            sc = getattr(self, "service_controller", None)
            try:
                fn = getattr(sc, "get_gateway_status", None)
                if callable(fn):
                    gs = fn() or {}
                    gateway_running = bool(gs.get("process_running", True)) and bool(gs.get("port_listening", True))
                else:
                    gateway_unknown = True
            except Exception:
                gateway_unknown = True
            
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
                        session_cfg = config.get("session", {}) or {}
                        session_start = session_cfg.get("start_time")
                        session_end = session_cfg.get("end_time")
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
            challenge_tracker_instance = None
            
            try:
                from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
                
                # Always load/create challenge tracker (will create if doesn't exist)
                challenge_state_file = self.state_dir / "challenge_state.json"
                try:
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()  # Reload from file
                    challenge_status = challenge_tracker_instance.get_status_summary(bot_label=trading_bot_label)
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
            
            # Check AI status
            ai_ready = False
            if OPENAI_AVAILABLE:
                try:
                    OpenAIClient()
                    ai_ready = True
                except Exception:
                    ai_ready = False

            # Build glanceable dashboard message (concise, mobile-first)
            message = format_glanceable_card(
                symbol=symbol,
                time_str=time_str,
                agent_running=agent_running,
                gateway_running=gateway_running,
                latest_price=latest_price,
                daily_pnl=float(state.get("daily_pnl", 0.0) or 0.0),
                active_trades_count=active_trades_count,
                futures_market_open=futures_market_open,
                strategy_session_open=strategy_session_open,
                market=market_label,
                trading_bot=tb_selected if tb_enabled else "scanner",
                ai_ready=ai_ready,
            )
            
            # Add challenge metrics if available (before recent exits)
            # Always show challenge - it should always exist (created automatically if missing)
            if not challenge_status and challenge_tracker_instance:
                try:
                    challenge_tracker_instance.refresh()
                    challenge_status = challenge_tracker_instance.get_status_summary(bot_label=trading_bot_label)
                except Exception as e:
                    logger.error(f"Could not reload challenge status: {e}", exc_info=True)
            
            # If still no challenge_status, try to create/load one more time
            if not challenge_status:
                try:
                    from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()
                    challenge_status = challenge_tracker_instance.get_status_summary(bot_label=trading_bot_label)
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
                            f"🏆 *50k Challenge* ({trading_bot_label})\n"
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
                            f"🏆 *50k Challenge* ({trading_bot_label})\n"
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
            
            # 30d performance (sum across signal types)
            try:
                from pearlalgo.learning.trade_database import TradeDatabase

                db_path = self.state_dir / "trades.db"
                if db_path.exists():
                    trade_db = TradeDatabase(db_path)
                    strategy_perf = trade_db.get_performance_by_signal_type(days=30)
                    if strategy_perf:
                        message += "\n\n*30d Performance:*"

                        total_pnl_all = sum(perf.get("total_pnl", 0.0) for perf in strategy_perf.values())
                        total_wins = sum(perf.get("wins", 0) for perf in strategy_perf.values())
                        total_losses = sum(perf.get("losses", 0) for perf in strategy_perf.values())
                        total_trades = total_wins + total_losses
                        total_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
                        total_emoji = "🟢" if total_pnl_all >= 0 else "🔴"

                        message += (
                            f"\n{total_emoji} *Total:* ${total_pnl_all:,.2f} "
                            f"({total_wins}W/{total_losses}L • {total_wr:.0f}% WR)"
                        )
            except Exception as e:
                logger.debug(f"Could not load 30d by strategy (compact): {e}")

            # Challenge (current run)
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

                    message += "\n\n*Challenge (current run):*"
                    message += (
                        f"\n{pnl_emoji} *{trading_bot_label}:* ${balance:,.2f} | ${pnl:+,.2f} "
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

    async def _handle_signal_detail(self, query: CallbackQuery, signal_id_prefix: str) -> None:
        """
        Display detailed signal information for a specific signal.
        
        Args:
            query: Callback query from button press
            signal_id_prefix: First characters of the signal ID to look up
        """
        keyboard = [
            [InlineKeyboardButton("🎯 Back to Signals", callback_data="menu:signals")],
            [InlineKeyboardButton("🏠 Back to Menu", callback_data="back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if not signal_id_prefix:
            await query.edit_message_text(
                "❌ No signal ID provided.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return
        
        # Search for signal by prefix in signals.jsonl
        signal = self._find_signal_by_prefix(signal_id_prefix)
        
        if not signal:
            await query.edit_message_text(
                f"❌ Signal not found: `{signal_id_prefix}...`\n\n"
                "Signal may have expired or ID prefix is incorrect.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return
        
        # Format signal details
        text = self._format_signal_detail(signal)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    def _find_signal_by_prefix(self, signal_id_prefix: str) -> Optional[dict]:
        """
        Find a signal by ID prefix from signals.jsonl.
        
        Args:
            signal_id_prefix: First characters of signal ID
            
        Returns:
            Signal dict if found, None otherwise
        """
        try:
            signals_file = get_signals_file(self.state_dir)
            if not signals_file.exists():
                return None
            
            # Search backwards (most recent first)
            matching_signal = None
            with open(signals_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                        signal_id = signal.get("signal_id", "")
                        if signal_id and signal_id.startswith(signal_id_prefix):
                            matching_signal = signal
                            # Continue to find the most recent match
                    except json.JSONDecodeError:
                        continue
            
            return matching_signal
        except Exception as e:
            logger.warning(f"Error finding signal by prefix: {e}")
            return None

    def _format_signal_detail(self, signal: dict) -> str:
        """
        Format a signal as a detailed view.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Formatted markdown string
        """
        signal_id = signal.get("signal_id", "")
        symbol = signal.get("symbol", "MNQ")
        signal_type = safe_label(signal.get("type", "unknown"))
        status = signal.get("status", "unknown")
        direction = signal.get("direction", "long")
        
        # Format with helpers
        dir_emoji, dir_label = format_signal_direction(direction)
        
        # Check if exited with P&L
        pnl = signal.get("pnl")
        is_win = pnl > 0 if pnl is not None else None
        status_emoji, status_label = format_signal_status(status, is_win)
        
        # Prices
        entry_price = signal.get("entry_price", 0)
        stop_loss = signal.get("stop_loss", 0)
        take_profit = signal.get("take_profit", 0)
        exit_price = signal.get("exit_price")
        
        # Confidence
        confidence = signal.get("confidence", 0)
        conf_emoji, conf_tier = format_signal_confidence_tier(confidence)
        
        # Timing
        timestamp = signal.get("timestamp", "")
        entry_time = signal.get("entry_time", "")
        exit_time = signal.get("exit_time", "")
        
        # Build message
        lines = [
            f"🔍 *Signal Detail*",
            "",
            f"*{symbol} {dir_emoji} {dir_label}* | {signal_type}",
            f"{status_emoji} Status: *{status_label}*",
            "",
        ]
        
        # Trade Plan
        lines.append("*Trade Plan:*")
        if entry_price:
            lines.append(f"  Entry: ${entry_price:.2f}")
        if stop_loss:
            stop_dist = abs(entry_price - stop_loss) if entry_price else 0
            lines.append(f"  Stop: ${stop_loss:.2f} ({stop_dist:.1f} pts)")
        if take_profit:
            tp_dist = abs(take_profit - entry_price) if entry_price else 0
            lines.append(f"  TP: ${take_profit:.2f} ({tp_dist:.1f} pts)")
        
        # R:R
        if entry_price and stop_loss and take_profit:
            if dir_label == "LONG":
                risk = entry_price - stop_loss
                reward = take_profit - entry_price
            else:
                risk = stop_loss - entry_price
                reward = entry_price - take_profit
            if risk > 0:
                rr = reward / risk
                lines.append(f"  R:R: {rr:.1f}:1")
        
        # Exit info
        if exit_price is not None:
            lines.append("")
            lines.append("*Exit:*")
            lines.append(f"  Price: ${exit_price:.2f}")
            if pnl is not None:
                pnl_emoji, pnl_str = format_pnl(pnl)
                lines.append(f"  P&L: {pnl_emoji} {pnl_str}")
            exit_reason = signal.get("exit_reason", "")
            if exit_reason:
                lines.append(f"  Reason: {safe_label(exit_reason)}")
        
        # Confidence
        lines.append("")
        lines.append(f"{conf_emoji} Confidence: {confidence:.0%} ({conf_tier})")
        
        # Timing
        lines.append("")
        lines.append("*Timing:*")
        if timestamp:
            age = format_time_ago(timestamp)
            lines.append(f"  Generated: {age or timestamp}")
        if entry_time:
            age = format_time_ago(entry_time)
            lines.append(f"  Entered: {age or entry_time}")
        if exit_time:
            age = format_time_ago(exit_time)
            lines.append(f"  Exited: {age or exit_time}")
        
        # Expanded context (check user preference)
        prefs = TelegramPrefs(state_dir=self.state_dir)
        if prefs.signal_detail_expanded:
            # Show regime and MTF context
            regime = signal.get("regime", {})
            mtf = signal.get("mtf_analysis", {})
            
            if regime or mtf:
                lines.append("")
                lines.append("*Context:*")
                if regime:
                    r_regime = regime.get("regime", "")
                    r_volatility = regime.get("volatility", "")
                    r_session = regime.get("session", "")
                    if r_regime:
                        lines.append(f"  Regime: {safe_label(r_regime)}")
                    if r_volatility:
                        lines.append(f"  Volatility: {safe_label(r_volatility)}")
                    if r_session:
                        lines.append(f"  Session: {safe_label(r_session)}")
                if mtf:
                    alignment = mtf.get("alignment", "")
                    if alignment:
                        mtf_emoji = "✅" if alignment == "aligned" else "⚠️" if alignment == "partial" else "❌"
                        lines.append(f"  MTF: {mtf_emoji} {safe_label(alignment)}")
            
            # Reason
            reason = signal.get("reason", "")
            if reason:
                lines.append("")
                lines.append("*Reason:*")
                # Truncate long reasons
                if len(reason) > 200:
                    reason = reason[:197] + "..."
                lines.append(f"  {safe_label(reason)}")
        
        # Signal ID footer
        lines.append("")
        lines.append(f"`ID: {signal_id[:24]}...`")
        
        return "\n".join(lines)

    async def _handle_performance_metrics(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display performance metrics from state file and signals."""
        state = self._read_state()
        signals = self._read_recent_signals(limit=100)
        
        text = "📈 *Performance Metrics*\n\n"
        
        # Get performance from state
        performance = state.get("performance", {}) if state else {}
        
        if performance:
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            total_trades = wins + losses
            win_rate = performance.get("win_rate", 0)
            total_pnl = performance.get("total_pnl", 0)
            avg_pnl = performance.get("avg_pnl", 0)
            avg_hold = performance.get("avg_hold_minutes", 0)
            
            text += "*7-Day Summary:*\n"
            if total_trades > 0:
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                text += f"  Trades: {total_trades} ({wins}W / {losses}L)\n"
                text += f"  Win Rate: {win_rate * 100:.1f}%\n"
                text += f"  Total P&L: {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Avg P&L: ${avg_pnl:,.2f}\n"
                if avg_hold > 0:
                    text += f"  Avg Hold: {avg_hold:.1f} min\n"
            else:
                text += "  No completed trades in the last 7 days.\n"
        else:
            text += "*7-Day Summary:*\n  No performance data available.\n"
        
        # Add signal statistics
        if signals:
            text += f"\n*Signal Statistics:*\n"
            text += f"  Total signals: {len(signals)}\n"
            
            # Count by status
            status_counts = {}
            for s in signals:
                status = s.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
            
            for status, count in sorted(status_counts.items()):
                text += f"  • {status}: {count}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_daily_summary(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display daily trading summary."""
        state = self._read_state()
        signals = self._read_recent_signals(limit=50)
        
        text = "📊 *Daily Summary*\n\n"
        
        # Filter signals from today
        today_signals = []
        if signals:
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date()
            for s in signals:
                ts = s.get("timestamp", "")
                if ts:
                    try:
                        signal_date = parse_utc_timestamp(ts).date() if isinstance(ts, str) else ts.date()
                        if signal_date == today:
                            today_signals.append(s)
                    except Exception:
                        pass
        
        if today_signals:
            # Count stats
            generated = len([s for s in today_signals if s.get("status") == "generated"])
            entered = len([s for s in today_signals if s.get("status") == "entered"])
            exited = len([s for s in today_signals if s.get("status") == "exited"])
            
            # Calculate P&L from exited signals
            total_pnl = sum(float(s.get("pnl", 0) or 0) for s in today_signals if s.get("status") == "exited")
            wins = len([s for s in today_signals if s.get("status") == "exited" and (s.get("pnl") or 0) > 0])
            losses = exited - wins
            
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            
            text += f"*Today's Activity:*\n"
            text += f"  Signals: {len(today_signals)} total\n"
            text += f"  • Generated: {generated}\n"
            text += f"  • Active: {entered}\n"
            text += f"  • Exited: {exited}\n"
            
            if exited > 0:
                text += f"\n*Today's P&L:*\n"
                text += f"  {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Trades: {wins}W / {losses}L\n"
        else:
            text += "No signals generated today.\n"
        
        # Add state info
        if state:
            scans = state.get("cycle_count_session", 0) or 0
            errors = state.get("error_count", 0) or 0
            text += f"\n*Session Activity:*\n"
            text += f"  Scans: {scans:,}\n"
            text += f"  Errors: {errors}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_weekly_summary(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display weekly trading summary."""
        state = self._read_state()
        performance = state.get("performance", {}) if state else {}
        
        text = "📉 *Weekly Summary*\n\n"
        
        if performance:
            total_signals = performance.get("total_signals", 0)
            exited_signals = performance.get("exited_signals", 0)
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            win_rate = performance.get("win_rate", 0) * 100
            total_pnl = performance.get("total_pnl", 0)
            avg_pnl = performance.get("avg_pnl", 0)
            avg_hold = performance.get("avg_hold_minutes", 0)
            
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            
            text += "*Signal Statistics:*\n"
            text += f"  Total Generated: {total_signals}\n"
            text += f"  Completed: {exited_signals}\n"
            
            if exited_signals > 0:
                text += f"\n*Trade Performance:*\n"
                text += f"  Wins: {wins}\n"
                text += f"  Losses: {losses}\n"
                text += f"  Win Rate: {win_rate:.1f}%\n"
                text += f"\n*P&L:*\n"
                text += f"  Total: {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Average: ${avg_pnl:,.2f}\n"
                if avg_hold > 0:
                    text += f"\n*Timing:*\n"
                    text += f"  Avg Hold: {avg_hold:.1f} min\n"
            else:
                text += "\nNo completed trades this week.\n"
        else:
            text += "No performance data available.\n"
            text += "\n💡 Performance data is calculated from the last 7 days of trading activity."
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_pnl_overview(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display P&L overview."""
        state = self._read_state()
        signals = self._read_recent_signals(limit=100)
        
        text = "💰 *P&L Overview*\n\n"
        
        # Get performance data
        performance = state.get("performance", {}) if state else {}
        
        # Calculate from signals
        exited_signals = [s for s in signals if s.get("status") == "exited"] if signals else []
        
        if exited_signals:
            total_pnl = sum(float(s.get("pnl", 0) or 0) for s in exited_signals)
            wins = [s for s in exited_signals if (s.get("pnl") or 0) > 0]
            losses = [s for s in exited_signals if (s.get("pnl") or 0) <= 0]
            
            avg_win = sum(float(s.get("pnl", 0)) for s in wins) / len(wins) if wins else 0
            avg_loss = sum(float(s.get("pnl", 0)) for s in losses) / len(losses) if losses else 0
            
            largest_win = max((float(s.get("pnl", 0)) for s in exited_signals), default=0)
            largest_loss = min((float(s.get("pnl", 0)) for s in exited_signals), default=0)
            
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            
            text += f"*Total P&L:* {pnl_emoji} ${total_pnl:,.2f}\n"
            text += f"*Trades:* {len(exited_signals)} ({len(wins)}W / {len(losses)}L)\n\n"
            
            text += "*Averages:*\n"
            text += f"  Avg Win: 🟢 ${avg_win:,.2f}\n"
            text += f"  Avg Loss: 🔴 ${abs(avg_loss):,.2f}\n\n"
            
            text += "*Extremes:*\n"
            text += f"  Best Trade: 🟢 ${largest_win:,.2f}\n"
            text += f"  Worst Trade: 🔴 ${abs(largest_loss):,.2f}\n"
            
            # Profit factor
            if avg_loss != 0:
                profit_factor = abs(avg_win / avg_loss) if avg_loss else 0
                text += f"\n*Profit Factor:* {profit_factor:.2f}\n"
        else:
            text += "No completed trades to analyze.\n"
            text += "\n💡 P&L data is calculated from exited signals in your trading history."
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_set_trading_mode(self, query: CallbackQuery, mode: str) -> None:
        """Set trading mode (scanner or pearl_bot_auto)."""
        try:
            state_file = self.state_dir / "state.json"
            state = {}
            
            # Load existing state
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
            
            # Update trading_bot settings
            if "trading_bot" not in state:
                state["trading_bot"] = {}
            
            if mode == "scanner":
                state["trading_bot"]["enabled"] = False
                state["trading_bot"]["selected"] = "scanner"
                mode_label = "🔴 Scanner Only"
                mode_desc = "Scanning signals only - no execution"
            else:
                state["trading_bot"]["enabled"] = True
                state["trading_bot"]["selected"] = "pearl_bot_auto"
                mode_label = "🟢 Pearl Bot Auto"
                mode_desc = "Active trading enabled"
            
            # Save state
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            
            keyboard = [
                [InlineKeyboardButton("🤖 Back to Bots", callback_data="menu:bots")],
                [InlineKeyboardButton("🏠 Menu", callback_data="back")],
            ]
            
            await query.edit_message_text(
                f"✅ *Trading Mode Updated*\n\n"
                f"New mode: *{mode_label}*\n"
                f"_{mode_desc}_\n\n"
                f"⚠️ *Note:* Changes take effect on next agent restart.\n"
                f"Use 🎛️ System to restart the agent.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            logger.info(f"Trading mode changed to: {mode}")
            
        except Exception as e:
            logger.error(f"Error setting trading mode: {e}", exc_info=True)
            keyboard = [[InlineKeyboardButton("🤖 Back to Bots", callback_data="menu:bots")]]
            await query.edit_message_text(
                f"❌ Error setting trading mode: {e}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def _handle_config_view(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display current configuration."""
        text = "⚙️ *Configuration*\n\n"
        
        # Try to load config
        try:
            import yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
                
                # Display key settings
                strategy = config.get("strategy", {})
                data = config.get("data", {})
                telegram = config.get("telegram", {})
                
                text += f"*Market:* {self.active_market}\n\n"
                
                text += "*Strategy:*\n"
                text += f"  Timeframe: {strategy.get('timeframe', '1m')}\n"
                text += f"  Scan Interval: {strategy.get('scan_interval', 60)}s\n"
                
                session_start = strategy.get('session_start_time', '')
                session_end = strategy.get('session_end_time', '')
                if session_start and session_end:
                    text += f"  Session: {session_start} - {session_end}\n"
                
                text += "\n*Data:*\n"
                text += f"  Buffer Size: {data.get('buffer_size', 100)} bars\n"
                text += f"  Stale Threshold: {data.get('stale_data_threshold_minutes', 10)} min\n"
                
                text += "\n*Telegram:*\n"
                text += f"  Enabled: {'✅' if telegram.get('enabled', False) else '❌'}\n"
            else:
                text += "❌ Config file not found.\n"
                text += f"Expected at: config/config.yaml"
        except Exception as e:
            text += f"❌ Could not load config: {e}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_logs_view(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display logs information."""
        text = "📋 *Logs*\n\n"
        
        # Find log files
        log_dir = Path("logs")
        if log_dir.exists():
            log_files = list(log_dir.glob("*.log"))
            
            if log_files:
                text += "*Log Files:*\n"
                for lf in sorted(log_files)[:5]:
                    try:
                        size_kb = lf.stat().st_size / 1024
                        text += f"  • `{lf.name}` ({size_kb:.1f} KB)\n"
                    except Exception:
                        text += f"  • `{lf.name}`\n"
                
                text += f"\n*Location:* `{log_dir.absolute()}`\n"
                text += "\n💡 Use SSH or file manager to view full logs."
            else:
                text += "No log files found.\n"
        else:
            text += "Log directory not found.\n"
        
        # Show recent errors from state if available
        state = self._read_state()
        if state:
            error_count = state.get("error_count", 0)
            last_error = state.get("last_error", "")
            
            if error_count > 0:
                text += f"\n*Session Errors:* {error_count}\n"
                if last_error:
                    # Truncate long errors
                    if len(last_error) > 100:
                        last_error = last_error[:97] + "..."
                    text += f"*Last Error:* {safe_label(last_error)}\n"
        
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
            state_dir = Path("data/agent_state/NQ")

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
        if not await self._ensure_openai_ready(update, context):
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
    # Trading bot backtesting removed - using pearl_bot_auto only
    # ---------------------------------------------------------------------
        """Render the trading bot backtest menu (Telegram-first; no CLI)."""
        if not await self._check_authorized(update):
            await self._send_message_or_edit(update, context, "❌ Unauthorized access")
            return

        default_symbols = {"NQ": "MNQ", "ES": "MES", "GC": "MGC"}
        hist_symbol = default_symbols.get(self.active_market, "MNQ")
        lines = [
            "🧪 *Backtest (Advanced)*",
            "",
            "Backtesting functionality removed - using pearl_bot_auto only.",
            "Variants are individual strategy bots.",
            "",
            f"Data source: `data/historical/{hist_symbol}_1m_*.parquet` (resampled to 5m).",
        ]

        keyboard = [
            [
                # Backtesting removed
                InlineKeyboardButton("🏆 Compare All", callback_data="pb:bot:all"),
            ],
            [
                InlineKeyboardButton("📈 Trend (variant)", callback_data="pb:bot:trend"),
                InlineKeyboardButton("⚡ Breakout (variant)", callback_data="pb:bot:break"),
            ],
            [
                InlineKeyboardButton("📉 MeanRev (variant)", callback_data="pb:bot:mean"),
                InlineKeyboardButton("📑 Reports", callback_data="strategy_review:reports"),
            ],
            [
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

    # Backtesting execution methods removed - using pearl_bot_auto only

    def _get_repo_root(self) -> Path:
        """Get repository root from this file location (or cached value)."""
        try:
            root = Path(getattr(self, "_repo_root"))
            return root.resolve()
        except Exception:
            return Path(__file__).resolve().parent.parent.parent.parent

    def _get_reports_dir(self) -> Path:
        """Directory where Telegram backtest reports are stored (shared with report viewer)."""
        try:
            state_dir = Path(getattr(self, "state_dir", "data/agent_state/NQ"))
        except Exception:
            state_dir = Path("data/agent_state/NQ")
        return state_dir.parent / "reports"

    # Backtesting execution methods removed - using pearl_bot_auto only

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
            state_dir = Path(getattr(self, "state_dir", "data/agent_state/NQ"))
        except Exception:
            state_dir = Path("data/agent_state/NQ")

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
            state_dir = Path(getattr(self, "state_dir", "data/agent_state/NQ"))
        except Exception:
            state_dir = Path("data/agent_state/NQ")

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
