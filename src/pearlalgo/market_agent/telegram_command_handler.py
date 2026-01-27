"""
Telegram Command Handler for Market Agent.

Provides simple button-based remote control interface for the trading system.

Commands:
  /start - Show the main dashboard (menu)

Simple and intuitive nested button menu system.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_state_file, get_signals_file, parse_utc_timestamp
from pearlalgo.utils.service_controller import ServiceController
from pearlalgo.utils.telegram_alerts import (
    TelegramPrefs,
    sanitize_telegram_markdown,
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

    def _trade_charts_dir(self) -> Path:
        """Directory where per-trade charts are stored (entry/exit)."""
        return self.exports_dir / "trade_charts"

    def _safe_chart_key(self, signal_id: str) -> str:
        """Mirror notifier filename logic for trade charts."""
        s = str(signal_id or "").strip() or "unknown"
        s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
        return s[:120]

    def _trade_chart_path(self, *, signal_id: str, kind: str) -> Path:
        kind_norm = str(kind or "").strip().lower()
        if kind_norm not in {"entry", "exit"}:
            kind_norm = "chart"
        return self._trade_charts_dir() / f"{self._safe_chart_key(signal_id)}_{kind_norm}.png"

    async def _post_init(self, application: Application) -> None:
        """Runs once after the Telegram application initializes."""
        # Keep the slash-command surface minimal: /start is the dashboard/menu.
        try:
            await application.bot.set_my_commands([
                BotCommand("start", "Show main dashboard"),
            ])
        except Exception as e:
            logger.debug(f"Could not set bot commands: {e}")

        # Skip auto-dashboard on startup - user uses /start for full dashboard
        # This keeps startup clean and gives user control
        logger.info("Command handler ready - user can use /start for dashboard")

    def _register_handlers(self) -> None:
        # Minimal command surface: /start is the menu.
        self.application.add_handler(CommandHandler("start", self.handle_menu))

        # Optional aliases (kept for backwards-compatibility; not advertised).
        self.application.add_handler(CommandHandler("menu", self.handle_menu))
        self.application.add_handler(CommandHandler("help", self.handle_menu))
        self.application.add_handler(CommandHandler("settings", self.handle_menu))

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
        agent_healthy: bool | None = None
        gateway_running = False
        # Connection can be absent from state.json; treat it as best-effort.
        connection_ok: bool | None = None
        
        if state:
            # Only count virtual trades for Activity button (transparency - matches Activity tab)
            total_active = state.get("active_trades_count", 0) or 0
            daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
            agent_running = bool(self._is_agent_process_running())
            paused = bool(state.get("paused", False))
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")

            # Prefer explicit connection status when available; fall back to data freshness.
            if "connection_status" in state:
                cs = state.get("connection_status")
                if cs == "connected":
                    connection_ok = True
                elif cs == "disconnected":
                    connection_ok = False
                else:
                    connection_ok = None
            elif "data_fresh" in state:
                connection_ok = bool(state.get("data_fresh"))

            # Staleness override: treat missing or stale bars as unhealthy.
            # (We compute from latest_bar.timestamp, not cached "latest_bar_age_minutes".)
            data_age_minutes = None
            try:
                thr = float(state.get("data_stale_threshold_minutes") or 10.0)
            except Exception:
                thr = 10.0
            try:
                latest_bar = state.get("latest_bar") if isinstance(state.get("latest_bar"), dict) else {}
                ts = (latest_bar or {}).get("timestamp") or state.get("latest_bar_timestamp")
                if ts:
                    dt = parse_utc_timestamp(str(ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        data_age_minutes = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
            except Exception:
                data_age_minutes = None

            should_check_data = not (futures_market_open is False and strategy_session_open is False)
            if agent_running and (not paused) and should_check_data and thr > 0 and data_age_minutes is not None:
                is_stale = data_age_minutes > thr
                if is_stale:
                    connection_ok = False
                elif connection_ok is None:
                    # If we have fresh bars, the end-to-end path is OK.
                    connection_ok = True

            # Agent health (process may be up but not cycling).
            cycle_age_sec = None
            try:
                ts = state.get("last_successful_cycle")
                if ts:
                    dt = parse_utc_timestamp(str(ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        cycle_age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                cycle_age_sec = None

            cycle_thr = 120.0
            try:
                cm = state.get("cadence_metrics") or {}
                interval = cm.get("current_interval_seconds")
                if interval:
                    cycle_thr = max(120.0, float(interval) * 4.0)
            except Exception:
                cycle_thr = 120.0

            if agent_running and cycle_age_sec is not None:
                agent_healthy = float(cycle_age_sec) <= float(cycle_thr)
        
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
        
        # System: agent + gateway status (more accurate detection)
        # Only show green when BOTH are actually running and functional
        # Yellow indicates partial functionality (one running but not both)
        # Red means neither is running or functional
        if agent_running and gateway_running and (agent_healthy is True):
            system_label = "🎛️ System 🟢"
        elif gateway_running and not agent_running:
            # Gateway running but agent not - partial functionality
            system_label = "🎛️ System 🟡"
        elif agent_running and not gateway_running:
            # Agent running but gateway not - partial functionality (agent can't trade)
            system_label = "🎛️ System 🟡"
        elif agent_running and gateway_running and agent_healthy is None:
            # Both processes are up but we can't confirm the agent is cycling.
            system_label = "🎛️ System 🟡"
        elif agent_running and gateway_running and agent_healthy is False:
            # Both processes are up but the agent isn't cycling (hung / stalled).
            system_label = "🎛️ System 🟡"
        else:
            # Neither running - no functionality
            system_label = "🎛️ System 🔴"
        
        # Log status changes for debugging
        logger.debug(f"System status: agent={agent_running}, healthy={agent_healthy}, gateway={gateway_running}, label={system_label}")
        
        # Health: only meaningful when agent is running.
        if not state or not agent_running:
            health_label = "🛡️ Health ⚪"
        elif connection_ok is True:
            health_label = "🛡️ Health 🟢"
        elif connection_ok is False:
            health_label = "🛡️ Health 🔴"
        else:
            health_label = "🛡️ Health 🟡"
        
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

    # =========================================================================
    # CENTRALIZED NAVIGATION HELPERS - Single source of truth for all menus
    # =========================================================================
    
    def _nav_back_row(self) -> list:
        """
        Single source of truth for 'Back to Menu' navigation.
        Use this everywhere instead of creating buttons manually.
        """
        return [InlineKeyboardButton("🏠 Menu", callback_data="back")]
    
    def _nav_footer(self, extra_buttons: list = None) -> list:
        """
        Standard navigation footer for all sub-menus.
        
        Args:
            extra_buttons: Optional list of additional buttons to add before Menu
        
        Returns:
            List containing a single row with Menu button (and extras if provided)
        """
        if extra_buttons:
            return [*extra_buttons, InlineKeyboardButton("🏠 Menu", callback_data="back")]
        return self._nav_back_row()
    
    def _with_nav_footer(self, keyboard: list, extra_buttons: list = None) -> list:
        """
        Append standard navigation footer to any keyboard.
        
        Args:
            keyboard: Existing keyboard rows
            extra_buttons: Optional buttons to add alongside Menu button
        
        Returns:
            Keyboard with navigation footer appended
        """
        result = list(keyboard) if keyboard else []
        result.append(self._nav_footer(extra_buttons))
        return result
    
    def _quick_keyboard(self, *rows, include_nav: bool = True) -> InlineKeyboardMarkup:
        """
        Quick keyboard builder with automatic navigation footer.
        
        Args:
            *rows: Button rows (each row is a list of InlineKeyboardButtons or tuples of (label, callback))
            include_nav: Whether to include the navigation footer (default True)
        
        Returns:
            InlineKeyboardMarkup ready to use
        """
        keyboard = []
        for row in rows:
            if not row:
                continue
            # Convert tuples to buttons if needed
            processed_row = []
            for item in row:
                if isinstance(item, tuple) and len(item) == 2:
                    processed_row.append(InlineKeyboardButton(item[0], callback_data=item[1]))
                else:
                    processed_row.append(item)
            keyboard.append(processed_row)
        
        if include_nav:
            keyboard.append(self._nav_back_row())
        
        return InlineKeyboardMarkup(keyboard)

    async def handle_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send visual dashboard with 12h chart and compact navigation menu."""
        if not update.message:
            return
        if not await self._check_authorized(update):
            await update.message.reply_text("❌ Unauthorized access")
            return

        raw = str(getattr(update.message, "text", "") or "").strip()
        cmd = raw.split()[0] if raw else "/start"
        logger.info(f"Received {cmd} - sending visual dashboard")
        
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
            "🎯 PEARLalgo\n\n"
            "Use /start to open the dashboard.\n\n"
            "Everything else is accessed via the buttons:\n"
            "📊 Activity • 🎛️ System • 🛡️ Health • ⚙️ Settings"
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
            self._nav_back_row(),
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

        # Acknowledge the callback immediately to provide user feedback
        try:
            await query.answer()  # Acknowledge the callback
        except Exception as e:
            logger.warning(f"Failed to answer callback: {e}")
        
        if not await self._check_authorized(update):
            try:
                await query.edit_message_text("❌ Unauthorized access")
            except Exception:
                pass
            return
        
        # Resolve legacy callbacks to canonical form (backward compatibility)
        raw_callback = query.data
        if not raw_callback:
            logger.error("Received empty callback data")
            try:
                await query.answer("❌ Invalid button action", show_alert=True)
            except Exception:
                pass
            return
            
        callback_data = resolve_callback(raw_callback)
        if callback_data != raw_callback:
            logger.debug(f"Resolved legacy callback: {raw_callback} -> {callback_data}")
        logger.info(f"Received callback: {callback_data}")

        # Parse and route callback using canonical format
        try:
            callback_type, action, param = parse_callback(callback_data)
        except Exception as e:
            logger.error(f"Failed to parse callback '{callback_data}': {e}", exc_info=True)
            try:
                await query.answer("❌ Error parsing button action", show_alert=True)
            except Exception:
                pass
            return
        
        logger.debug(f"Parsed callback: type={callback_type}, action={action}, param={param}")
        message = getattr(query, "message", None)
        
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
                logger.warning(f"Unrecognized callback type '{callback_type}', trying legacy handling")
                await self._handle_action(query, callback_data)
        except Exception as e:
            # Handle "no text in message" error by sending new message
            err_str = str(e).lower()
            if "no text in the message" in err_str or "message to edit not found" in err_str:
                logger.warning(f"Edit failed (likely photo message), sending new message: {e}")
                try:
                    keyboard = [self._nav_back_row()]
                    if message and getattr(message, "chat", None):
                        await message.chat.send_message(
                            "⚠️ Navigation error. Tap Back to return to menu.",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                        )
                except Exception as send_err:
                    logger.error(f"Failed to send error message: {send_err}")
            else:
                logger.error(f"Callback error for '{callback_data}': {e}", exc_info=True)
                # Try to show user-friendly error message
                try:
                    keyboard = [self._nav_back_row()]
                    error_msg = f"❌ Error: {str(e)[:100]}"
                    await self._safe_edit_or_send(query, error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
                except Exception:
                    # If we can't even send error message, at least log it
                    logger.error(f"Failed to send error message to user: {e}")

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
        message = getattr(query, "message", None)

        # Always attach a compact support footer (when using Markdown) so ANY screen
        # can be copy/pasted to debug issues without extra back-and-forth.
        try:
            if parse_mode and "markdown" in str(parse_mode).lower():
                text = self._with_support_footer(text)
                text = sanitize_telegram_markdown(text)
        except Exception:
            pass

        # Photo messages can't be edited via edit_message_text. For menu screens,
        # replace the dashboard photo with a text-only message.
        if message and getattr(message, "photo", None):
            try:
                await message.delete()
            except Exception:
                pass
            try:
                if not getattr(message, "chat", None):
                    raise RuntimeError("Missing chat context for photo replacement")
                try:
                    await message.chat.send_message(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                except Exception:
                    # Fallback: strip Markdown formatting to avoid parse errors.
                    plain = str(text).replace("*", "").replace("_", "").replace("`", "")
                    await message.chat.send_message(
                        text=plain,
                        reply_markup=reply_markup,
                        parse_mode=None,
                    )
            except Exception as send_err:
                logger.error(f"Failed to send message after replacing photo: {send_err}")
            return
        
        try:
            # Try to edit text first (works for text messages)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            err_str = str(e).lower()

            # Avoid churning the chat when nothing changed.
            if "message is not modified" in err_str:
                return

            # If edit fails (e.g., deleted/invalid), send new
            if (
                "no text in the message" in err_str
                or "message to edit not found" in err_str
                or "message_id_invalid" in err_str
                or "message can't be edited" in err_str
            ):
                try:
                    if message:
                        await message.delete()
                except Exception:
                    pass
                try:
                    if not message or not getattr(message, "chat", None):
                        raise RuntimeError("Missing chat context for replacement message")
                    try:
                        await message.chat.send_message(
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode=parse_mode
                        )
                    except Exception:
                        plain = str(text).replace("*", "").replace("_", "").replace("`", "")
                        await message.chat.send_message(
                            text=plain,
                            reply_markup=reply_markup,
                            parse_mode=None
                        )
                except Exception as send_err:
                    logger.error(f"Failed to send replacement message: {send_err}")
                return
            else:
                # Re-raise if it's a different error
                raise

    async def _handle_menu_action(self, query: CallbackQuery, action: str) -> None:
        """Handle menu button actions."""
        logger.info(f"Handling menu action: {action}")
        try:
            if action == "status":
                await self._show_status_menu(query)
            elif action == "signals":
                await self._show_activity_menu(query)  # Redirect to unified Activity
            elif action == "performance":
                await self._show_activity_menu(query)  # Redirect to unified Activity
            elif action == "activity":
                await self._show_activity_menu(query)
            elif action == "analytics":
                await self._show_analytics_menu(query)
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
                logger.warning(f"Unknown menu action: {action}")
                await self._safe_edit_or_send(query, f"❌ Unknown menu action: {action}\n\nPlease use the menu buttons to navigate.")
        except Exception as e:
            logger.error(f"Error handling menu action '{action}': {e}", exc_info=True)
            try:
                keyboard = [self._nav_back_row()]
                error_msg = f"❌ Error opening {action} menu: {str(e)[:100]}"
                await self._safe_edit_or_send(query, error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as send_err:
                logger.error(f"Failed to send error message: {send_err}")

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
        keyboard.append(self._nav_back_row())
        text = self._with_support_footer("\n".join(lines), state=active_state if isinstance(active_state, dict) else None)
        await self._safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    async def _show_main_menu_with_chart(self, query: CallbackQuery) -> None:
        """Show the main menu with chart displayed above the menu text."""
        keyboard = self._get_main_menu_keyboard()
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        state = self._read_state()
        if state:
            try:
                message_text = await self._build_status_dashboard_message(state)
                chart_path = await self._generate_or_get_chart(state)

                # Add a compact support footer to make any screenshot/share self-diagnostic.
                caption_text = self._with_support_footer(message_text, state=state, max_chars=1024)
                text_only = self._with_support_footer(message_text, state=state, max_chars=4096)
                caption_md = sanitize_telegram_markdown(caption_text)
                text_md = sanitize_telegram_markdown(text_only)
                
                if chart_path and chart_path.exists():
                    try:
                        message = query.message
                        # Check if message already has a photo
                        if message and message.photo:
                            # Message has photo, edit it
                            from telegram import InputMediaPhoto
                            try:
                                with open(chart_path, 'rb') as f:
                                    await query.edit_message_media(
                                        media=InputMediaPhoto(
                                            media=f,
                                            caption=caption_md,
                                            parse_mode="Markdown"
                                        ),
                                        reply_markup=reply_markup
                                    )
                            except Exception:
                                # Fallback: update media without Markdown parsing.
                                caption_plain = caption_md.replace("*", "").replace("_", "").replace("`", "")
                                with open(chart_path, 'rb') as f:
                                    await query.edit_message_media(
                                        media=InputMediaPhoto(
                                            media=f,
                                            caption=caption_plain,
                                            parse_mode=None
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
                            try:
                                with open(chart_path, 'rb') as f:
                                    await query.message.chat.send_photo(
                                        photo=f,
                                        caption=caption_md,
                                        reply_markup=reply_markup,
                                        parse_mode="Markdown"
                                    )
                            except Exception:
                                caption_plain = caption_md.replace("*", "").replace("_", "").replace("`", "")
                                with open(chart_path, 'rb') as f:
                                    await query.message.chat.send_photo(
                                        photo=f,
                                        caption=caption_plain,
                                        reply_markup=reply_markup,
                                        parse_mode=None
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
                            try:
                                await message.chat.send_message(
                                    text=text_md,
                                    reply_markup=reply_markup,
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                text_plain = text_md.replace("*", "").replace("_", "").replace("`", "")
                                await message.chat.send_message(
                                    text=text_plain,
                                    reply_markup=reply_markup,
                                    parse_mode=None
                                )
                            await query.answer()
                        else:
                            try:
                                await query.edit_message_text(text_md, reply_markup=reply_markup, parse_mode="Markdown")
                            except Exception:
                                text_plain = text_md.replace("*", "").replace("_", "").replace("`", "")
                                await query.edit_message_text(text_plain, reply_markup=reply_markup, parse_mode=None)
                else:
                    # No chart available - just show text menu quickly
                    message = query.message
                    if message and message.photo:
                        # If we have a photo message, delete it first
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        try:
                            await message.chat.send_message(
                                text=text_md,
                                reply_markup=reply_markup,
                                parse_mode="Markdown"
                            )
                        except Exception:
                            text_plain = text_md.replace("*", "").replace("_", "").replace("`", "")
                            await message.chat.send_message(
                                text=text_plain,
                                reply_markup=reply_markup,
                                parse_mode=None
                            )
                        await query.answer()
                    else:
                        try:
                            await query.edit_message_text(text_md, reply_markup=reply_markup, parse_mode="Markdown")
                        except Exception:
                            text_plain = text_md.replace("*", "").replace("_", "").replace("`", "")
                            await query.edit_message_text(text_plain, reply_markup=reply_markup, parse_mode=None)
            except Exception as e:
                logger.error(f"Error showing main menu with chart: {e}", exc_info=True)
                await self._show_main_menu(query)
        else:
            text = self._with_support_footer(
                "🎯 Pearl Algo Bot's\n\n❌ No state data available.\n\nSelect an option:",
                state=None,
                max_chars=4096,
            )
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
                            text=self._with_support_footer(message_text, state=state, max_chars=4096),
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
        """Send visual dashboard with 12h chart to a new message (for /start).

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

            # Always include the support footer on the primary dashboard.
            caption_text = self._with_support_footer(message_text, state=state, max_chars=1024)
            text_only = self._with_support_footer(message_text, state=state, max_chars=4096)
            caption_md = sanitize_telegram_markdown(caption_text)
            text_md = sanitize_telegram_markdown(text_only)
            
            if chart_path and chart_path.exists():
                # Send photo with caption
                try:
                    with open(chart_path, 'rb') as f:
                        await message_obj.reply_photo(
                            photo=f,
                            caption=caption_md,
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                except Exception:
                    caption_plain = caption_md.replace("*", "").replace("_", "").replace("`", "")
                    with open(chart_path, 'rb') as f:
                        await message_obj.reply_photo(
                            photo=f,
                            caption=caption_plain,
                            reply_markup=reply_markup,
                            parse_mode=None
                        )
            else:
                # Fallback to text-only if chart unavailable
                try:
                    await message_obj.reply_text(
                        text_md,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                except Exception:
                    text_plain = text_md.replace("*", "").replace("_", "").replace("`", "")
                    await message_obj.reply_text(
                        text_plain,
                        reply_markup=reply_markup,
                        parse_mode=None
                    )
        except Exception as e:
            logger.error(f"Error sending visual dashboard: {e}", exc_info=True)
            # Fallback to simple menu
            await message_obj.reply_text(
                "🎯 Pearl Algo Bot's\n\nSelect an option:",
                reply_markup=reply_markup
            )

    async def _generate_or_get_chart(self, state: dict) -> Optional[Path]:
        """
        Use the latest exported dashboard chart (no generation—service owns it).

        We intentionally do **not** fall back to any legacy dashboard filenames to avoid
        showing stale/incorrect aspect ratios on mobile.
        """
        telegram_chart = self.exports_dir / "dashboard_telegram_latest.png"
        return telegram_chart if telegram_chart.exists() else None

    async def _show_status_menu(self, query: CallbackQuery) -> None:
        """Show health & diagnostics submenu."""
        state = self._read_state()
        
        # Agent running (best-effort). When agent is off, connection/data are not meaningful.
        try:
            agent_running = bool(self._is_agent_process_running())
        except Exception:
            agent_running = False

        # Determine status indicators
        gw_status = "⚪"
        conn_status = "⚪"
        data_status = "⚪"

        # Gateway = actual service (process + port), not connection state.
        try:
            sc = getattr(self, "service_controller", None)
            if sc:
                gw = sc.get_gateway_status() or {}
                gw_ok = bool(gw.get("process_running")) and bool(gw.get("port_listening"))
                gw_status = "🟢" if gw_ok else "🔴"
        except Exception:
            # keep unknown
            pass
        
        if state and agent_running:
            paused = bool(state.get("paused", False))
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")
            should_check_data = (not paused) and not (futures_market_open is False and strategy_session_open is False)

            # Connection: prefer explicit state when present; fall back to data_fresh.
            if "connection_status" in state:
                cs = state.get("connection_status")
                if cs == "connected":
                    conn_status = "🟢"
                elif cs == "disconnected":
                    conn_status = "🔴"
                else:
                    conn_status = "⚪"
            elif "data_fresh" in state:
                conn_status = "🟢" if bool(state.get("data_fresh")) else "🔴"
            else:
                conn_status = "⚪"
            
            # Data: consider latest_bar presence and/or explicit data_fresh.
            latest_bar = state.get("latest_bar", {}) or {}
            if "data_fresh" in state:
                data_status = "🟢" if bool(state.get("data_fresh")) else "🔴"
            else:
                data_status = "🟢" if bool(latest_bar) else "🔴"

            # Staleness override: mark Data degraded if latest bar is older than the threshold.
            try:
                thr = float(state.get("data_stale_threshold_minutes") or 10.0)
            except Exception:
                thr = 10.0
            try:
                ts = None
                if isinstance(latest_bar, dict):
                    ts = latest_bar.get("timestamp") or state.get("latest_bar_timestamp")
                if ts:
                    dt = parse_utc_timestamp(str(ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
                        if should_check_data and thr > 0 and age_min > thr:
                            data_status = "🔴"
                            # If we don't have an explicit connection state, don't show green when data is stale.
                            if "connection_status" not in state and conn_status == "🟢":
                                conn_status = "🟡"
            except Exception:
                pass
        
        lines = [
            "🛡️ *Health*",
            "",
            f"Gateway: {gw_status} | Connection: {conn_status} | Data: {data_status}",
        ]
        text = self._with_support_footer("\n".join(lines), state=state)
        
        keyboard = [
            [
                InlineKeyboardButton("🔌 Gateway", callback_data="action:gateway_status"),
                InlineKeyboardButton("📡 Connection", callback_data="action:connection_status"),
            ],
            [
                InlineKeyboardButton("📊 Data", callback_data="action:data_quality"),
                InlineKeyboardButton("📋 Status", callback_data="action:system_status"),
            ],
            [InlineKeyboardButton("🩺 Doctor", callback_data="action:ui_doctor")],
            self._nav_back_row(),
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")

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

        # Threshold (minutes) for marking data stale.
        try:
            data_stale_threshold_min = float(state.get("data_stale_threshold_minutes") or 10.0)
        except Exception:
            data_stale_threshold_min = 10.0

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
            is_stale = (
                data_stale_threshold_min > 0
                and data_age_min is not None
                and data_age_min > data_stale_threshold_min
            )
            if is_stale:
                lines.append(
                    f"📡 Data: *{lvl}* • Age: *{data_age_min:.1f}m* 🔴 (thr={data_stale_threshold_min:.0f}m)"
                )
            else:
                lines.append(f"📡 Data: *{lvl}* • Age: *{data_age_min:.1f}m*")

        # Prefs summary
        lines.append("")
        prefs_bits: list[str] = []
        prefs_bits.append(f"Interval {'🟢' if interval_notifications else '🔴'}")
        prefs_bits.append(f"Auto-chart {'🟢' if auto_chart else '🔴'}")
        prefs_bits.append(f"Snooze {'🟢' if snooze_on else '🔴'}")
        if expanded_details:
            prefs_bits.append("Details 🟢")
        if pinned_dashboard:
            prefs_bits.append("Pinned 🟢")
        lines.append(f"*Prefs:* {' | '.join(prefs_bits)}")

        if last_dash:
            lines.append(f"🧾 Last dashboard: {safe_label(str(last_dash_age or last_dash))}")

        keyboard = [
            [
                InlineKeyboardButton("🎛 System", callback_data="menu:system"),
                InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
            ],
            [
                InlineKeyboardButton("🧪 Tests", callback_data="action:ui_doctor:tests"),
                InlineKeyboardButton("🛡 Back", callback_data="menu:status"),
            ],
            self._nav_back_row(),
        ]
        await self._safe_edit_or_send(
            query,
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

        if action == "tests":
            lines = [
                "🧪 *UI Doctor Tests*",
                "",
                "_UI-only test sends (no trading side effects)._",
            ]
            keyboard = [
                [
                    InlineKeyboardButton("🧪 Dashboard", callback_data="action:ui_doctor:test_dashboard"),
                    InlineKeyboardButton("⚠️ Risk Alert", callback_data="action:ui_doctor:test_risk"),
                ],
                [InlineKeyboardButton("🧪 Signal", callback_data="action:ui_doctor:test_signal")],
                [
                    InlineKeyboardButton("🩺 Doctor", callback_data="action:ui_doctor"),
                    self._nav_back_row()[0],
                ],
            ]
            await self._safe_edit_or_send(
                query,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

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
            # Gather data - ONLY virtual trades for transparency
            virtual_trades_count = 0
            daily_signals = 0
            daily_pnl = 0.0
            daily_trades = 0
            daily_wins = 0
            daily_losses = 0
            
            # Extended metrics
            gross_profit = 0.0
            gross_loss = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            max_drawdown = 0.0
            profit_factor = 0.0
            
            if state:
                # Only count virtual trades (signals with status=entered), NOT broker positions
                virtual_trades_count = state.get("active_trades_count", 0) or 0
                daily_signals = state.get("daily_signals", 0) or 0
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                daily_trades = state.get("daily_trades", 0) or 0
                daily_wins = state.get("daily_wins", 0) or 0
                daily_losses = state.get("daily_losses", 0) or 0
            
            # Load extended metrics from performance.json
            try:
                from datetime import datetime, timezone
                perf_file = self.state_dir / "performance.json"
                if perf_file.exists():
                    import json
                    with open(perf_file, 'r') as f:
                        perf_trades = json.load(f)
                    
                    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                    today_trades_list = [
                        t for t in perf_trades 
                        if today_str in str(t.get('exit_time', ''))
                    ]
                    
                    if today_trades_list:
                        # Fallback for basic metrics
                        if daily_trades == 0:
                            daily_pnl = sum(float(t.get('pnl', 0) or 0) for t in today_trades_list)
                            daily_trades = len(today_trades_list)
                            daily_wins = sum(1 for t in today_trades_list if t.get('is_win'))
                            daily_losses = daily_trades - daily_wins
                        
                        # Calculate extended metrics
                        winning_trades = [t for t in today_trades_list if t.get('is_win')]
                        losing_trades = [t for t in today_trades_list if not t.get('is_win')]
                        
                        gross_profit = sum(float(t.get('pnl', 0) or 0) for t in winning_trades)
                        gross_loss = abs(sum(float(t.get('pnl', 0) or 0) for t in losing_trades))
                        
                        if winning_trades:
                            avg_win = gross_profit / len(winning_trades)
                        if losing_trades:
                            avg_loss = gross_loss / len(losing_trades)
                        if gross_loss > 0:
                            profit_factor = gross_profit / gross_loss
                        
                        # Max drawdown
                        running_pnl = 0.0
                        peak_pnl = 0.0
                        for t in today_trades_list:
                            running_pnl += float(t.get('pnl', 0) or 0)
                            if running_pnl > peak_pnl:
                                peak_pnl = running_pnl
                            drawdown = peak_pnl - running_pnl
                            if drawdown > max_drawdown:
                                max_drawdown = drawdown
            except Exception as e:
                logger.debug(f"Could not compute extended metrics in activity menu: {e}")
            
            signals = self._read_recent_signals(limit=10)
            recent_count = len(signals) if signals else 0
            
            # Build detailed activity summary
            lines = ["📊 *Activity* (Virtual Trading)", ""]
            
            # Performance card
            pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
            pnl_sign = "+" if daily_pnl >= 0 else ""
            lines.append(f"*Today:* {pnl_emoji} {pnl_sign}${abs(daily_pnl):.2f}")
            
            if daily_trades > 0:
                wr = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
                lines.append(f"Trades: {daily_trades} ({daily_wins}W/{daily_losses}L) | {wr:.0f}% WR")
            
            # Extended metrics (detailed view)
            if profit_factor > 0:
                pf_emoji = "✨" if profit_factor >= 1.5 else ("📊" if profit_factor >= 1.0 else "⚠️")
                lines.append(f"{pf_emoji} Profit Factor: {profit_factor:.2f}")
            
            if avg_win > 0 or avg_loss > 0:
                lines.append(f"💵 Avg Win: ${avg_win:.2f} | Loss: ${avg_loss:.2f}")
            
            if max_drawdown > 0:
                dd_emoji = "⚠️" if max_drawdown > 500 else "📉"
                lines.append(f"{dd_emoji} Max Drawdown: ${max_drawdown:.2f}")
            
            lines.append("")
            lines.append(f"Signals: {daily_signals} | Virtual Open: {virtual_trades_count}")
            lines.append("")
            
            # Build buttons - use virtual trades count for clarity
            active_label = f"📋 Virtual ({virtual_trades_count})" if virtual_trades_count > 0 else "📋 Virtual"
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
                # Row 3: Analytics (NEW)
                [
                    InlineKeyboardButton("🔬 Analytics", callback_data="menu:analytics"),
                ],
                # Row 4: Actions
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="menu:activity"),
                    self._nav_back_row()[0],
                ],
            ]
            
            # Add Close All if virtual trades exist
            if virtual_trades_count > 0:
                keyboard.insert(2, [
                    InlineKeyboardButton(f"🚫 Close All ({virtual_trades_count})", callback_data="action:close_all_trades"),
                    InlineKeyboardButton("💰 P&L Detail", callback_data="action:pnl_overview"),
                ])
            
            text = self._with_support_footer("\n".join(lines), state=state)
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in _show_activity_menu: {e}", exc_info=True)
            keyboard = [
                [
                    InlineKeyboardButton("🎯 Signals", callback_data="action:recent_signals"),
                    InlineKeyboardButton("📋 Active", callback_data="action:active_trades"),
                ],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(query, "📊 Activity\n\nSelect an option:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def _show_analytics_menu(self, query: CallbackQuery) -> None:
        """Show performance analytics with session and hourly breakdown."""
        try:
            from datetime import datetime, timezone
            from collections import defaultdict
            import json
            
            lines = ["🔬 *Performance Analytics*", ""]
            
            # Load all trades from performance.json
            perf_file = self.state_dir / "performance.json"
            if not perf_file.exists():
                lines.append("No performance data available yet.")
                lines.append("Start trading to see analytics.")
            else:
                with open(perf_file, 'r') as f:
                    all_trades = json.load(f)
                
                if not all_trades:
                    lines.append("No trades recorded yet.")
                else:
                    total_trades = len(all_trades)
                    total_wins = sum(1 for t in all_trades if t.get('is_win'))
                    total_pnl = sum(float(t.get('pnl', 0) or 0) for t in all_trades)
                    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
                    
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    lines.append(f"*Overall:* {total_trades} trades | {overall_wr:.0f}% WR | {pnl_emoji} ${total_pnl:,.2f}")
                    lines.append("")
                    
                    # Session breakdown
                    sessions = {
                        'overnight': (18, 4),      # 6PM - 4AM ET
                        'premarket': (4, 6),       # 4AM - 6AM ET
                        'morning': (6, 10),        # 6AM - 10AM ET
                        'midday': (10, 14),        # 10AM - 2PM ET
                        'afternoon': (14, 17),     # 2PM - 5PM ET
                        'close': (17, 18),         # 5PM - 6PM ET
                    }
                    
                    session_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
                    
                    for t in all_trades:
                        time_str = t.get('exit_time') or t.get('entry_time')
                        if not time_str:
                            continue
                        try:
                            time_str = str(time_str).replace('Z', '+00:00')
                            if '.' in time_str and '+' in time_str:
                                parts = time_str.split('+')
                                base = parts[0].split('.')[0]
                                time_str = base + '+' + parts[1]
                            dt = datetime.fromisoformat(time_str)
                            et_hour = (dt.hour - 5) % 24  # Convert UTC to ET
                            
                            session_name = 'other'
                            for sname, (start, end) in sessions.items():
                                if start > end:  # overnight wraps
                                    if et_hour >= start or et_hour < end:
                                        session_name = sname
                                        break
                                elif start <= et_hour < end:
                                    session_name = sname
                                    break
                            
                            if t.get('is_win'):
                                session_stats[session_name]['wins'] += 1
                            else:
                                session_stats[session_name]['losses'] += 1
                            session_stats[session_name]['pnl'] += float(t.get('pnl', 0) or 0)
                        except Exception:
                            pass
                    
                    lines.append("*📅 Session Performance:*")
                    session_order = ['overnight', 'premarket', 'morning', 'midday', 'afternoon', 'close']
                    for sname in session_order:
                        data = session_stats[sname]
                        count = data['wins'] + data['losses']
                        if count > 0:
                            wr = (data['wins'] / count * 100)
                            pnl = data['pnl']
                            emoji = "🟢" if pnl >= 0 else "🔴"
                            # Highlight best/worst sessions
                            if wr >= 55:
                                indicator = "✅"
                            elif wr <= 30:
                                indicator = "⚠️"
                            else:
                                indicator = "•"
                            lines.append(f"{indicator} {sname.title()}: {wr:.0f}% WR | {emoji} ${pnl:,.0f}")
                    
                    lines.append("")
                    
                    # Top hours
                    hour_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
                    for t in all_trades:
                        time_str = t.get('exit_time') or t.get('entry_time')
                        if not time_str:
                            continue
                        try:
                            time_str = str(time_str).replace('Z', '+00:00')
                            if '.' in time_str and '+' in time_str:
                                parts = time_str.split('+')
                                base = parts[0].split('.')[0]
                                time_str = base + '+' + parts[1]
                            dt = datetime.fromisoformat(time_str)
                            et_hour = (dt.hour - 5) % 24
                            
                            if t.get('is_win'):
                                hour_stats[et_hour]['wins'] += 1
                            else:
                                hour_stats[et_hour]['losses'] += 1
                            hour_stats[et_hour]['pnl'] += float(t.get('pnl', 0) or 0)
                        except Exception:
                            pass
                    
                    # Find best and worst hours
                    hours_with_data = [(h, d) for h, d in hour_stats.items() if d['wins'] + d['losses'] >= 5]
                    if hours_with_data:
                        # Sort by P&L
                        sorted_hours = sorted(hours_with_data, key=lambda x: x[1]['pnl'], reverse=True)
                        
                        lines.append("*⏰ Best Hours (ET):*")
                        for h, data in sorted_hours[:3]:
                            count = data['wins'] + data['losses']
                            wr = (data['wins'] / count * 100) if count > 0 else 0
                            pnl = data['pnl']
                            if pnl > 0:
                                lines.append(f"🔥 {h:02d}:00: {wr:.0f}% WR | +${pnl:,.0f}")
                        
                        lines.append("")
                        lines.append("*⏰ Worst Hours (ET):*")
                        for h, data in sorted_hours[-3:]:
                            count = data['wins'] + data['losses']
                            wr = (data['wins'] / count * 100) if count > 0 else 0
                            pnl = data['pnl']
                            if pnl < 0:
                                lines.append(f"❄️ {h:02d}:00: {wr:.0f}% WR | -${abs(pnl):,.0f}")
                    
                    # Hold duration insight
                    lines.append("")
                    duration_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
                    for t in all_trades:
                        hold_mins = t.get('hold_duration_minutes', 0) or 0
                        if hold_mins < 30:
                            bucket = 'Quick (<30m)'
                        elif hold_mins < 60:
                            bucket = 'Medium (30-60m)'
                        else:
                            bucket = 'Long (60m+)'
                        
                        if t.get('is_win'):
                            duration_stats[bucket]['wins'] += 1
                        else:
                            duration_stats[bucket]['losses'] += 1
                        duration_stats[bucket]['pnl'] += float(t.get('pnl', 0) or 0)
                    
                    lines.append("*⏱️ Hold Duration:*")
                    for bucket in ['Quick (<30m)', 'Medium (30-60m)', 'Long (60m+)']:
                        data = duration_stats[bucket]
                        count = data['wins'] + data['losses']
                        if count > 0:
                            wr = (data['wins'] / count * 100)
                            pnl = data['pnl']
                            emoji = "🟢" if pnl >= 0 else "🔴"
                            lines.append(f"• {bucket}: {wr:.0f}% WR | {emoji} ${pnl:,.0f}")
            
            text = "\n".join(lines)
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="menu:analytics"),
                ],
                [
                    InlineKeyboardButton("📊 Back to Activity", callback_data="menu:activity"),
                    self._nav_back_row()[0],
                ],
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error in _show_analytics_menu: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("📊 Back to Activity", callback_data="menu:activity")],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query, 
                f"🔬 Analytics\n\n❌ Error loading analytics: {str(e)[:100]}", 
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

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
                self._nav_back_row(),
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
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query,
                "💎 Performance\n\nSelect an option:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

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
        if state:
            tb_state = state.get("trading_bot") or {}
            trading_bot_enabled = bool(tb_state.get("enabled", False))
        
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
                self._nav_back_row()[0],
            ],
        ]

        text = self._with_support_footer("\n".join(lines), state=state)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _show_system_menu(self, query: CallbackQuery) -> None:
        """Show system control submenu with comprehensive risk warnings and status."""
        # Get system state for context
        state = self._read_state()
        agent_running = False
        has_positions = False
        positions_count = 0
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
            # Row 2: Restarts
            [
                InlineKeyboardButton("🔄 Restart Agent", callback_data="action:restart_agent"),
                InlineKeyboardButton("🔄 Restart GW", callback_data="action:restart_gateway"),
            ],
            # Row 3: Read-only tools
            [
                InlineKeyboardButton("📋 Logs", callback_data="action:logs"),
                InlineKeyboardButton("⚙️ Config", callback_data="action:config"),
            ],
            # Row 4: Advanced
            [
                InlineKeyboardButton("🏆 Challenge", callback_data="action:reset_challenge"),
                InlineKeyboardButton("🧹 Cache", callback_data="action:clear_cache"),
            ],
        ]
        
        # Emergency stop (only if positions exist)
        if has_positions:
            keyboard.append([
                InlineKeyboardButton(f"🚨 Emergency ({positions_count})", callback_data="action:emergency_stop"),
            ])
        
        # Back
        keyboard.append(self._nav_back_row())
        
        text = self._with_support_footer("\n".join(lines), state=state)
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")


    async def _show_settings_menu(self, query: CallbackQuery) -> None:
        """Show settings submenu with detailed descriptions and recommendations."""
        prefs = TelegramPrefs(state_dir=self.state_dir)
        auto_chart = bool(prefs.get("auto_chart_on_signal", False))
        interval_notifications = bool(prefs.get("interval_notifications", True))
        signal_detail_expanded = bool(prefs.get("signal_detail_expanded", False))
        pinned_dashboard = bool(prefs.get("dashboard_edit_in_place", False))
        snooze_on = bool(getattr(prefs, "snooze_noncritical_alerts", False))

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
                InlineKeyboardButton("🌐 Markets", callback_data="menu:markets"),
                InlineKeyboardButton("🤖 Bots", callback_data="menu:bots"),
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
                    f"📌 Pinned{' ✅' if pinned_dashboard else ''}",
                    callback_data="action:toggle_pref:dashboard_edit_in_place",
                ),
                InlineKeyboardButton(
                    f"🔕 Snooze{' ✅' if snooze_on else ''}",
                    callback_data="action:toggle_pref:snooze_noncritical_alerts",
                ),
            ],
            # Row 5: AI Tools
            [
                InlineKeyboardButton("🧩 AI Patch", callback_data="action:ai_patch_wizard"),
                InlineKeyboardButton("🧠 AI Ops", callback_data="action:ai_ops"),
            ],
            # Row 6: Back
            self._nav_back_row(),
        ]
        text = self._with_support_footer("\n".join(lines))
        await self._safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
            self._nav_back_row(),
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
        keyboard.append(self._nav_back_row())

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
                self._nav_back_row(),
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
                self._nav_back_row(),
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
            self._nav_back_row(),
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
            self._nav_back_row(),
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
            "/start - Show the dashboard\n\n"
            "*Menu Structure:*\n"
            "📊 Activity - Trades, signals, P&L, history\n"
            "🎛️ System - Start/stop agent + gateway, logs, config\n"
            "🛡️ Health - Connectivity, data, diagnostics\n"
            "⚙️ Settings - Markets + alert preferences\n\n"
            "*Quick Tips:*\n"
            "• Use '🏠 Menu' to return to the dashboard\n"
            "• Status indicators show active positions/trades\n"
            "• Emergency Stop closes all positions immediately\n"
            "• All actions are logged for audit trail"
        )
        keyboard = [self._nav_back_row()]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._safe_edit_or_send(query, help_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_action(self, query: CallbackQuery, action: str) -> None:
        """Handle action button presses."""
        logger.info(f"Handling action: {action}")
        try:
            if action.startswith("action:"):
                action_type = action[7:]  # Remove "action:" prefix
            else:
                # Legacy format or already extracted
                action_type = action

            if action_type.startswith("set_market:"):
                market = action_type.split(":", 1)[1]
                self._set_active_market(market)
                await self._show_markets_menu(query)
                return

            # On-demand entry/exit chart view (charts are persisted to disk by the agent).
            if action_type.startswith("trade_chart:"):
                # Format: trade_chart:<entry|exit>:<signal_id_prefix>
                parts = action_type.split(":", 2)
                if len(parts) == 3:
                    _, kind, signal_id_prefix = parts
                    await self._handle_trade_chart(query, kind=kind, signal_id_prefix=signal_id_prefix)
                else:
                    await query.answer("❌ Invalid chart request", show_alert=True)
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

                    # Pinned dashboards: when toggling, reset the stored message_ids so the
                    # next dashboard creates (or stops using) pinned messages cleanly.
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
            
            keyboard = [self._nav_back_row()]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if action_type == "system_status":
                await self._handle_system_status(query, reply_markup)
            elif action_type == "gateway_status":
                await self._handle_gateway_status(query, reply_markup)
            elif action_type == "connection_status":
                await self._handle_connection_status(query, reply_markup)
            elif action_type == "data_quality":
                await self._handle_data_quality(query, reply_markup)
            elif action_type == "ui_doctor":
                await self._show_ui_doctor(query)
                return
            elif action_type.startswith("ui_doctor:"):
                sub_action = action_type.split(":", 1)[1]
                await self._handle_ui_doctor_action(query, sub_action)
                return
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
                    self._nav_back_row(),
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
                # Get detailed position info - ONLY virtual trades for transparency
                state = self._read_state()
                virtual_positions = 0
                daily_pnl = 0.0
                daily_trades = 0
                unrealized_pnl = 0.0
                
                if state:
                    # Only count virtual trades (signals with status=entered)
                    virtual_positions = state.get("active_trades_count", 0) or 0
                    daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                    daily_trades = state.get("daily_trades", 0) or 0
                    unrealized_pnl = float(state.get("active_trades_unrealized_pnl", 0.0) or 0.0)
                
                lines = ["🚫 *Close All Virtual Trades*", ""]
                
                if virtual_positions == 0:
                    lines.extend([
                        "✅ *No open virtual trades*",
                        "",
                        "There are currently no virtual trades to close.",
                    ])
                    keyboard = [self._nav_back_row()]
                else:
                    lines.extend([
                        "📊 *Virtual Position Summary:*",
                        f"• Open Virtual Trades: {virtual_positions}",
                        f"• Completed Trades Today: {daily_trades}",
                    ])
                    
                    # Show unrealized P&L for current positions
                    if unrealized_pnl != 0:
                        unreal_emoji = "🟢" if unrealized_pnl >= 0 else "🔴"
                        unreal_sign = "+" if unrealized_pnl >= 0 else ""
                        lines.append(f"• Unrealized P&L: {unreal_emoji} {unreal_sign}${abs(unrealized_pnl):.2f}")
                    
                    if daily_pnl != 0:
                        pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                        pnl_sign = "+" if daily_pnl >= 0 else ""
                        lines.append(f"• Realized P&L Today: {pnl_emoji} {pnl_sign}${abs(daily_pnl):.2f}")
                    
                    lines.extend([
                        "",
                        "⚠️ *This will:*",
                        f"• Close all {virtual_positions} virtual trade(s) at market price",
                        "• Agent will continue running",
                        "• Can still generate new signals",
                        "",
                        "📝 *Note:* These are simulated trades, not broker positions",
                    ])
                    
                    # Smart warnings based on P&L
                    if unrealized_pnl > 0:
                        lines.append(f"💰 *Locking in:* +${unrealized_pnl:.2f} unrealized profit")
                    elif unrealized_pnl < -50:
                        lines.append("⚠️ *Notice:* Closing with unrealized loss - review strategy")
                    
                    lines.extend(["", "*Confirm to close all virtual trades:*"])
                    
                    keyboard = [
                        [InlineKeyboardButton(f"✅ Yes - Close All ({virtual_positions})", callback_data="confirm:close_all_trades")],
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
                # Refresh visual dashboard—reuse latest exported Telegram chart (dashboard_telegram_latest.png).
                await self._show_main_menu_with_chart(query)
            elif action_type == "toggle_chart":
                # Toggle chart display
                await self._toggle_chart_display(query)
                return
            elif action_type.startswith("confirm:"):
                # Handle confirm: prefix - delegate to confirm handler
                await self._handle_confirm_action(query, action_type[8:])  # Remove "confirm:" prefix
                return
            elif action_type == "activity":
                # Legacy activity callback
                await self._show_signals_menu(query)
                return
            elif action_type == "status":
                # Legacy status callback
                await self._show_status_menu(query)
                return
            elif action_type.startswith("toggle_strategy:"):
                # Legacy toggle strategy callback
                strategy_name = action_type[16:]
                await self._toggle_strategy(query, strategy_name)
                return
            else:
                logger.warning(f"Unhandled action type: {action_type}")
                keyboard = [self._nav_back_row()]
                await self._safe_edit_or_send(query, f"❌ Action not yet implemented: {action_type}", reply_markup=InlineKeyboardMarkup(keyboard))
                return
        except Exception as e:
            logger.error(f"Error in _handle_action for '{action}': {e}", exc_info=True)
            try:
                keyboard = [self._nav_back_row()]
                error_msg = f"❌ Error executing action: {str(e)[:100]}"
                await self._safe_edit_or_send(query, error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as send_err:
                logger.error(f"Failed to send error message: {send_err}")

    async def _handle_confirm_action(self, query: CallbackQuery, confirm_action: str) -> None:
        """Handle confirmed action button presses."""
        logger.info(f"Handling confirm action: {confirm_action}")
        keyboard = [self._nav_back_row()]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
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
                    self._nav_back_row(),
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
                    self._nav_back_row(),
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
                    self._nav_back_row(),
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
                    self._nav_back_row(),
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
                    self._nav_back_row(),
                ]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

            elif confirm_action == "reset_challenge":
                try:
                    from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker = ChallengeTracker(state_dir=self.state_dir)
                    new_attempt = challenge_tracker.manual_reset(reason="telegram_reset")
                    keyboard = [
                        [InlineKeyboardButton("🔄 Refresh Health", callback_data="menu:status")],
                        self._nav_back_row(),
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
                        self._nav_back_row(),
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
                    # Signal to close all virtual trades via state file
                    state_file = get_state_file(self.state_dir)
                    if state_file.exists():
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                        virtual_count = state.get("active_trades_count", 0) or 0
                        state["close_all_requested"] = True
                        state["close_all_requested_time"] = datetime.now(timezone.utc).isoformat()
                        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

                        keyboard = [
                            [InlineKeyboardButton("📊 Check Activity", callback_data="menu:activity")],
                            self._nav_back_row(),
                        ]
                        await query.edit_message_text(
                            f"✅ Close All Virtual Trades Request Sent\n\n"
                            f"Closing {virtual_count} virtual trade(s) at next opportunity (~5 seconds).\n\n"
                            "Tap 'Check Activity' to verify positions are closed.",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        logger.info(f"Close all virtual trades ({virtual_count}) requested via Telegram")
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
                        self._nav_back_row(),
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
                            self._nav_back_row(),
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
        except Exception as e:
            logger.error(f"Error in _handle_confirm_action for '{confirm_action}': {e}", exc_info=True)
            try:
                keyboard = [self._nav_back_row()]
                error_msg = f"❌ Error executing action: {str(e)[:100]}"
                await self._safe_edit_or_send(query, error_msg, reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as send_err:
                logger.error(f"Failed to send error message: {send_err}")

    async def _toggle_strategy(self, query: CallbackQuery, strategy_name: str) -> None:
        """Toggle a strategy on/off by updating config.yaml."""
        config_path = Path("config/config.yaml")
        if not config_path.exists():
            keyboard = [self._nav_back_row()]
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
                self._nav_back_row(),
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
            keyboard = [self._nav_back_row()]
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
        message_text = self._with_support_footer(message_text, state=state, max_chars=4096)
        await message_obj.reply_text(message_text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _build_status_dashboard_message(self, state: dict) -> str:
        """Build the comprehensive status dashboard message from state."""
        try:
            # Canonical dashboard text builder (glanceable + ops/perf blocks).
            symbol = state.get("symbol", "MNQ")
            market_label = state.get("market") or self.active_market

            # Trading bot identity (single source of truth) - surfaced in UI for clarity.
            tb_state = state.get("trading_bot") or {}
            tb_enabled = bool(tb_state.get("enabled", False))
            tb_selected = tb_state.get("selected") or "pearl_bot_auto"
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

            # Uptime (seconds) for glanceable footer (avoid "Agent: OFF" when running).
            agent_uptime_seconds = None
            try:
                start_ts = state.get("start_time")
                if agent_running and start_ts:
                    dt = parse_utc_timestamp(str(start_ts))
                    if dt and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt:
                        agent_uptime_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
            except Exception:
                agent_uptime_seconds = None
            
            # Gateway status
            # Prefer the service controller; fall back to state-derived freshness (better than defaulting to green).
            gateway_running = bool(state.get("data_fresh", False))
            gateway_unknown = True
            sc = getattr(self, "service_controller", None)
            try:
                fn = getattr(sc, "get_gateway_status", None)
                if callable(fn):
                    gs = fn() or {}
                    # Only override the fallback when the controller returns explicit keys.
                    if "process_running" in gs or "port_listening" in gs:
                        gateway_running = bool(gs.get("process_running", False)) and bool(gs.get("port_listening", False))
                        gateway_unknown = False
                else:
                    gateway_unknown = True
            except Exception:
                gateway_unknown = True
            
            # Market gates
            futures_market_open = state.get("futures_market_open")
            strategy_session_open = state.get("strategy_session_open")
            
            # Activity metrics
            # Price
            latest_price = state.get("latest_price")
            
            # Performance
            performance = state.get("performance", {})
            
            # Active trades (virtual positions)
            # NOTE: Some older agent versions did not persist these fields to state.json.
            # We keep a best-effort fallback to derive them from signals.jsonl.
            active_trades_count = state.get("active_trades_count")
            active_trades_unrealized_pnl = state.get("active_trades_unrealized_pnl")
            active_trades_price_source = state.get("latest_price_source")
            
            # Data quality
            latest_bar = state.get("latest_bar", {})
            data_level = latest_bar.get("_data_level") if isinstance(latest_bar, dict) else None

            # Backward-compatible fallback: derive active trades from signals.jsonl.
            if active_trades_count is None:
                try:
                    from pearlalgo.market_agent.state_manager import MarketAgentStateManager

                    sm = MarketAgentStateManager(state_dir=self.state_dir)
                    recent_signals = sm.get_recent_signals(limit=300)
                    active_recs: list[dict] = []
                    for rec in recent_signals:
                        if isinstance(rec, dict) and rec.get("status") == "entered":
                            active_recs.append(rec)
                    active_trades_count = int(len(active_recs))

                    # If we don't have unrealized PnL in state, compute best-effort from latest_bar close.
                    if active_trades_unrealized_pnl is None and active_trades_count > 0 and isinstance(latest_bar, dict):
                        px = latest_bar.get("close")
                        try:
                            current_price = float(px) if px is not None else None
                        except Exception:
                            current_price = None

                        if current_price and current_price > 0:
                            total_upnl = 0.0
                            for rec in active_recs:
                                sig = rec.get("signal", {}) or {}
                                direction = str(sig.get("direction") or "long").lower()
                                try:
                                    entry_price = float(sig.get("entry_price") or 0.0)
                                except Exception:
                                    entry_price = 0.0
                                if entry_price <= 0:
                                    continue
                                try:
                                    tick_value = float(sig.get("tick_value") or 2.0)
                                except Exception:
                                    tick_value = 2.0
                                try:
                                    position_size = float(sig.get("position_size") or 1.0)
                                except Exception:
                                    position_size = 1.0

                                pnl_pts = (current_price - entry_price) if direction == "long" else (entry_price - current_price)
                                total_upnl += float(pnl_pts) * float(tick_value) * float(position_size)

                            active_trades_unrealized_pnl = float(total_upnl)

                    if not active_trades_price_source:
                        active_trades_price_source = data_level
                except Exception:
                    active_trades_count = 0

            try:
                active_trades_count = int(active_trades_count or 0)
            except Exception:
                active_trades_count = 0

            # Raw data age (seconds) for footer (even if we suppress stale warnings elsewhere).
            data_age_seconds = None
            try:
                m = state.get("latest_bar_age_minutes")
                if m is not None:
                    data_age_seconds = float(m) * 60.0
            except Exception:
                data_age_seconds = None
            
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
                            data_age_seconds = age_seconds
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

            # Data stale flag (used for top-line indicators).
            data_stale: bool | None = None
            try:
                if data_age_seconds is None:
                    data_stale = None
                elif not agent_running or paused:
                    data_stale = None
                elif futures_market_open is False and strategy_session_open is False:
                    # Off-hours: stale data is expected.
                    data_stale = None
                else:
                    data_stale = (float(data_age_seconds) / 60.0) > float(data_stale_threshold_minutes)
            except Exception:
                data_stale = None
            
            # Buy/Sell pressure
            # Execution status
            execution = state.get("execution", {}) or {}
            execution_positions = int(execution.get("positions", 0) or 0)
            open_positions_count = max(execution_positions, int(active_trades_count or 0))
            
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

            # Agent health (process may be up, but we also want to know if it's cycling).
            agent_healthy: bool | None = None
            try:
                if not agent_running:
                    agent_healthy = None
                elif last_cycle_seconds is None:
                    agent_healthy = None
                else:
                    cycle_thr = 120.0
                    try:
                        cm = state.get("cadence_metrics") or {}
                        interval = cm.get("current_interval_seconds")
                        if interval:
                            cycle_thr = max(120.0, float(interval) * 4.0)
                    except Exception:
                        cycle_thr = 120.0
                    agent_healthy = float(last_cycle_seconds) <= float(cycle_thr)
            except Exception:
                agent_healthy = None
            
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
                    
                    # Get unrealized PNL from state if available
                    unrealized_pnl = active_trades_unrealized_pnl
                    if unrealized_pnl is not None:
                        try:
                            unrealized_pnl = float(unrealized_pnl)
                        except (ValueError, TypeError):
                            unrealized_pnl = None
                    
                    challenge_status = challenge_tracker_instance.get_status_summary(
                        bot_label=trading_bot_label, 
                        unrealized_pnl=unrealized_pnl
                    )
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
                    # Use same unrealized_pnl for attempt performance
                    unrealized_pnl = active_trades_unrealized_pnl
                    if unrealized_pnl is not None:
                        try:
                            unrealized_pnl = float(unrealized_pnl)
                        except (ValueError, TypeError):
                            unrealized_pnl = None
                    attempt_perf = challenge_tracker_instance.get_attempt_performance(unrealized_pnl=unrealized_pnl)
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

            # P&L shown on the "🎯 Active" line should reflect open positions when available.
            # Fall back to daily_pnl only when it's non-zero (avoid showing "+$0.00" as a false cue).
            pnl_for_active_line = None
            if active_trades_unrealized_pnl is not None:
                try:
                    pnl_for_active_line = float(active_trades_unrealized_pnl)
                except (ValueError, TypeError):
                    pnl_for_active_line = None
            else:
                try:
                    dp = float(state.get("daily_pnl", 0.0) or 0.0)
                    pnl_for_active_line = dp if dp != 0.0 else None
                except (ValueError, TypeError):
                    pnl_for_active_line = None

            # Build glanceable dashboard message (concise, mobile-first)
            message = format_glanceable_card(
                symbol=symbol,
                time_str=time_str,
                agent_running=agent_running,
                gateway_running=(None if gateway_unknown else gateway_running),
                latest_price=latest_price,
                daily_pnl=pnl_for_active_line,
                active_trades_count=open_positions_count,
                futures_market_open=futures_market_open,
                strategy_session_open=strategy_session_open,
                market=market_label,
                trading_bot=tb_selected if tb_enabled else "scanner",
                ai_ready=ai_ready,
                agent_uptime_seconds=agent_uptime_seconds,
                data_age_seconds=data_age_seconds,
                agent_healthy=agent_healthy,
                data_stale=data_stale,
            )

            # ------------------------------------------------------------------
            # Transparent AI/ML status (one-liner; avoids confusion)
            # ------------------------------------------------------------------
            try:
                bandit = state.get("learning") or {}
                bandit_mode = str(bandit.get("mode") or "off").lower()

                ctx = state.get("learning_contextual") or {}
                ctx_mode = str(ctx.get("mode") or "").lower()
                if not ctx_mode:
                    ctx_mode = "off"

                # Source of truth for ML filter "enabled" is config.yaml (service doesn't persist it).
                ml_enabled = None
                ml_mode = None
                try:
                    import yaml

                    cfg_path = Path("config/config.yaml")
                    if cfg_path.exists():
                        with open(cfg_path, "r") as f:
                            cfg = yaml.safe_load(f) or {}
                        ml_cfg = cfg.get("ml_filter", {}) or {}
                        ml_enabled = bool(ml_cfg.get("enabled", False))
                        ml_mode = str(ml_cfg.get("mode") or "").lower()
                except Exception:
                    ml_enabled = None

                if ml_enabled is True:
                    if ml_mode in ("shadow", "live"):
                        ml_label = ml_mode
                    else:
                        ml_label = "on"
                elif ml_enabled is False:
                    ml_label = "off"
                else:
                    ml_label = "?"
                ai_label = "ON" if ai_ready else "OFF"

                # Step 1 transparency: show ML shadow lift scoring progress (scored trades / min)
                lift_progress = ""
                try:
                    ml_state = state.get("ml_filter") or {}
                    lift = ml_state.get("lift") or {}
                    scored = lift.get("scored_trades")
                    min_trades = lift.get("min_trades")
                    if scored is not None and min_trades:
                        lift_progress = f" • Lift {int(scored)}/{int(min_trades)}"
                except Exception:
                    lift_progress = ""

                message += f"\n🧠 AI/ML: AI {ai_label} • Bandit {bandit_mode} • Ctx {ctx_mode} • Filter {ml_label}{lift_progress}"
            except Exception:
                pass
            
            # ==========================================================================
            # 24-HOUR PERFORMANCE (always shown - core daily metrics)
            # ==========================================================================
            try:
                daily_pnl = state.get("daily_pnl")
                daily_trades = state.get("daily_trades")
                daily_wins = state.get("daily_wins")
                daily_losses = state.get("daily_losses")
                
                # Extended metrics (computed from performance.json)
                gross_profit = 0.0
                gross_loss = 0.0
                avg_win = 0.0
                avg_loss = 0.0
                max_drawdown = 0.0
                today_trades_list = []
                perf_trades = []
                
                # Load from performance.json for detailed metrics
                try:
                    perf_file = self.state_dir / "performance.json"
                    if perf_file.exists():
                        import json
                        with open(perf_file, 'r') as f:
                            perf_trades = json.load(f)
                        if not isinstance(perf_trades, list):
                            perf_trades = []
                        
                        # Filter to today's trades (by exit_time)
                        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                        today_trades_list = [
                            t for t in perf_trades 
                            if today_str in str(t.get('exit_time', ''))
                        ]
                        
                        if today_trades_list:
                            # Basic metrics (fallback if not in state)
                            if daily_pnl is None or daily_trades is None:
                                daily_pnl = sum(float(t.get('pnl', 0) or 0) for t in today_trades_list)
                                daily_trades = len(today_trades_list)
                                daily_wins = sum(1 for t in today_trades_list if t.get('is_win'))
                                daily_losses = daily_trades - daily_wins
                            
                            # Calculate Profit Factor (gross profit / gross loss)
                            winning_trades = [t for t in today_trades_list if t.get('is_win')]
                            losing_trades = [t for t in today_trades_list if not t.get('is_win')]
                            
                            gross_profit = sum(float(t.get('pnl', 0) or 0) for t in winning_trades)
                            gross_loss = abs(sum(float(t.get('pnl', 0) or 0) for t in losing_trades))
                            
                            # Average win and loss
                            if winning_trades:
                                avg_win = gross_profit / len(winning_trades)
                            if losing_trades:
                                avg_loss = gross_loss / len(losing_trades)
                            
                            # Calculate max drawdown (peak-to-trough)
                            running_pnl = 0.0
                            peak_pnl = 0.0
                            max_drawdown = 0.0
                            for t in today_trades_list:
                                running_pnl += float(t.get('pnl', 0) or 0)
                                if running_pnl > peak_pnl:
                                    peak_pnl = running_pnl
                                drawdown = peak_pnl - running_pnl
                                if drawdown > max_drawdown:
                                    max_drawdown = drawdown
                            
                except Exception as e:
                    logger.debug(f"Could not compute extended metrics from performance.json: {e}")
                
                # Calculate current win/loss streak from today's trades
                current_streak = 0
                streak_type = None  # 'win' or 'loss'
                if today_trades_list:
                    # Sort by exit_time to get proper order, most recent last
                    sorted_trades = sorted(
                        today_trades_list, 
                        key=lambda t: t.get('exit_time', ''), 
                        reverse=False
                    )
                    # Count consecutive from the end
                    for t in reversed(sorted_trades):
                        is_win = t.get('is_win', False)
                        if streak_type is None:
                            streak_type = 'win' if is_win else 'loss'
                            current_streak = 1
                        elif (streak_type == 'win' and is_win) or (streak_type == 'loss' and not is_win):
                            current_streak += 1
                        else:
                            break
                
                # Convert to proper types
                daily_pnl = float(daily_pnl or 0.0)
                daily_trades = int(daily_trades or 0)
                daily_wins = int(daily_wins or 0)
                daily_losses = int(daily_losses or 0)
                
                # Only show if there's activity today - condensed one-liner like 30d
                if daily_trades > 0 or daily_pnl != 0:
                    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                    pnl_sign = "+" if daily_pnl >= 0 else "-"
                    win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
                    
                    # Build streak indicator (only show if streak >= 3)
                    streak_str = ""
                    if current_streak >= 3:
                        if streak_type == 'win':
                            streak_str = f" • 🔥{current_streak}W"
                        else:
                            streak_str = f" • ❄️{current_streak}L"
                    
                    # Condensed format: "24h: 🟢 +$2,375.00 (73W/74L • 50% WR) • ❄️3L"
                    message += "\n\n*24h:*"
                    message += f"\n{pnl_emoji} {pnl_sign}${abs(daily_pnl):,.2f} ({daily_wins}W/{daily_losses}L • {win_rate:.0f}% WR){streak_str}"

                # ------------------------------------------------------------------
                # 72-HOUR PERFORMANCE (rolling 72h)
                # ------------------------------------------------------------------
                try:
                    from datetime import timedelta

                    if perf_trades:
                        cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
                        trades_72h = []
                        for t in perf_trades:
                            try:
                                ts = str(t.get("exit_time", "") or "")
                                if not ts:
                                    continue
                                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                if dt >= cutoff:
                                    trades_72h.append(t)
                            except Exception:
                                continue

                        if trades_72h:
                            pnl_72h = sum(float(t.get("pnl", 0) or 0) for t in trades_72h)
                            wins_72h = sum(1 for t in trades_72h if t.get("is_win"))
                            losses_72h = int(len(trades_72h) - wins_72h)
                            wr_72h = (wins_72h / len(trades_72h) * 100) if trades_72h else 0.0
                            pnl_emoji_72h = "🟢" if pnl_72h >= 0 else "🔴"
                            pnl_sign_72h = "+" if pnl_72h >= 0 else "-"

                            message += "\n\n*72h:*"
                            message += f"\n{pnl_emoji_72h} {pnl_sign_72h}${abs(pnl_72h):,.2f} ({wins_72h}W/{losses_72h}L • {wr_72h:.0f}% WR)"
                except Exception as e:
                    logger.debug(f"Could not add 72h performance: {e}")
                    
            except Exception as e:
                logger.debug(f"Could not add 24h performance: {e}")
            
            # 30d performance - moved here to be right after 24h for better mobile layout
            try:
                from pearlalgo.learning.trade_database import TradeDatabase
                db_path = self.state_dir / "trades.db"
                if db_path.exists():
                    trade_db = TradeDatabase(db_path)
                    strategy_perf = trade_db.get_performance_by_signal_type(days=30)
                    if strategy_perf:
                        total_pnl_all = sum(perf.get("total_pnl", 0.0) for perf in strategy_perf.values())
                        total_wins = sum(perf.get("wins", 0) for perf in strategy_perf.values())
                        total_losses = sum(perf.get("losses", 0) for perf in strategy_perf.values())
                        total_trades = total_wins + total_losses
                        total_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
                        total_emoji = "🟢" if total_pnl_all >= 0 else "🔴"
                        message += "\n\n*30d Performance:*"
                        message += (
                            f"\n{total_emoji} *Total:* ${total_pnl_all:,.2f} "
                            f"({total_wins}W/{total_losses}L • {total_wr:.0f}% WR)"
                        )
            except Exception as e:
                logger.debug(f"Could not load 30d performance: {e}")
            
            # Add challenge metrics if available (after performance sections)
            # Always show challenge - it should always exist (created automatically if missing)
            if not challenge_status and challenge_tracker_instance:
                try:
                    challenge_tracker_instance.refresh()
                    # Get unrealized PNL from state if available
                    unrealized_pnl = active_trades_unrealized_pnl
                    if unrealized_pnl is not None:
                        try:
                            unrealized_pnl = float(unrealized_pnl)
                        except (ValueError, TypeError):
                            unrealized_pnl = None
                    challenge_status = challenge_tracker_instance.get_status_summary(
                        bot_label=trading_bot_label, 
                        unrealized_pnl=unrealized_pnl
                    )
                except Exception as e:
                    logger.error(f"Could not reload challenge status: {e}", exc_info=True)
            
            # If still no challenge_status, try to create/load one more time
            if not challenge_status:
                try:
                    from pearlalgo.market_agent.challenge_tracker import ChallengeTracker
                    challenge_tracker_instance = ChallengeTracker(state_dir=self.state_dir)
                    challenge_tracker_instance.refresh()
                    # Get unrealized PNL from state if available
                    unrealized_pnl = active_trades_unrealized_pnl
                    if unrealized_pnl is not None:
                        try:
                            unrealized_pnl = float(unrealized_pnl)
                        except (ValueError, TypeError):
                            unrealized_pnl = None
                    challenge_status = challenge_tracker_instance.get_status_summary(
                        bot_label=trading_bot_label,
                        unrealized_pnl=unrealized_pnl
                    )
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
                    # Get unrealized PNL from state if available
                    unrealized_pnl = active_trades_unrealized_pnl
                    if unrealized_pnl is not None:
                        try:
                            unrealized_pnl = float(unrealized_pnl)
                        except (ValueError, TypeError):
                            unrealized_pnl = None
                    attempt_perf = challenge_tracker_instance.get_attempt_performance(unrealized_pnl=unrealized_pnl)
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
                        # Include unrealized PNL if available
                        realized_pnl = current_attempt.get("pnl", 0.0)
                        unrealized_pnl_val = active_trades_unrealized_pnl
                        if unrealized_pnl_val is not None:
                            try:
                                unrealized_pnl_val = float(unrealized_pnl_val)
                            except (ValueError, TypeError):
                                unrealized_pnl_val = 0.0
                        else:
                            unrealized_pnl_val = 0.0
                        pnl = realized_pnl + unrealized_pnl_val
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
            
            # 30d section moved above Challenge for better mobile layout

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
                        if len(recent_exits) >= 2:
                            break

            if isinstance(recent_exits, list) and recent_exits:
                message += "\n\n*Recent exits:*"
                for t in recent_exits[:2]:
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
            
            # "Current Position" section removed from main dashboard - available in Activity tab
            # The header already shows "X Active | $Y.YY" which provides quick visibility
            
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
        """Display active virtual trades."""
        state = self._read_state()
        if not state:
            await query.edit_message_text("❌ Could not read system state.", reply_markup=reply_markup)
            return
        
        # Get virtual trades from state (signals with status=entered)
        virtual_trades_count = state.get("active_trades_count", 0) or 0
        active_trades_unrealized_pnl = state.get("active_trades_unrealized_pnl")
        
        text = "📋 *Active Virtual Trades*\n\n"
        
        if virtual_trades_count == 0:
            text += "No active virtual trades.\n"
            text += "\n_Virtual trades track simulated P&L from signals._"
        else:
            text += f"📊 *Virtual Trades:* {virtual_trades_count}\n"
            
            if active_trades_unrealized_pnl is not None:
                pnl_emoji = "💰" if active_trades_unrealized_pnl >= 0 else "📉"
                pnl_sign = "+" if active_trades_unrealized_pnl >= 0 else ""
                text += f"{pnl_emoji} *Unrealized P&L:* {pnl_sign}${active_trades_unrealized_pnl:,.2f}\n"
            
            text += "\n_These are simulated trades, not broker positions._"
        
        # Try to get detailed trade info from signals
        recent_signals = self._read_recent_signals(limit=50)
        active_signals = [s for s in recent_signals if s.get("status") == "entered"]
        
        if active_signals:
            text += f"\n\n*Open Virtual Positions ({len(active_signals)}):*\n"
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
            self._nav_back_row(),
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

        # If we have persisted trade charts for this signal, offer on-demand view buttons.
        try:
            full_signal_id = str(signal.get("signal_id") or "")
            chart_row = []
            if full_signal_id:
                if self._trade_chart_path(signal_id=full_signal_id, kind="entry").exists():
                    chart_row.append(
                        InlineKeyboardButton(
                            "📈 Entry chart",
                            callback_data=f"action:trade_chart:entry:{signal_id_prefix}",
                        )
                    )
                if self._trade_chart_path(signal_id=full_signal_id, kind="exit").exists():
                    chart_row.append(
                        InlineKeyboardButton(
                            "📉 Exit chart",
                            callback_data=f"action:trade_chart:exit:{signal_id_prefix}",
                        )
                    )
            if chart_row:
                keyboard = [chart_row] + keyboard
                reply_markup = InlineKeyboardMarkup(keyboard)
        except Exception:
            pass
        
        # Format signal details
        text = self._format_signal_detail(signal)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_trade_chart(self, query: CallbackQuery, *, kind: str, signal_id_prefix: str) -> None:
        """
        Display a persisted entry/exit chart for a given signal (on-demand).
        """
        kind_norm = str(kind or "").strip().lower()
        if kind_norm not in {"entry", "exit"}:
            try:
                await query.answer("❌ Unknown chart type", show_alert=True)
            except Exception:
                pass
            return

        # Look up the full signal record by prefix
        signal = self._find_signal_by_prefix(signal_id_prefix)
        if not signal:
            keyboard = [
                [InlineKeyboardButton("🎯 Back to Signals", callback_data="menu:signals")],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query,
                f"❌ Signal not found: `{signal_id_prefix}...`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        signal_id = str(signal.get("signal_id") or "")
        chart_path = self._trade_chart_path(signal_id=signal_id, kind=kind_norm)
        if not chart_path.exists():
            keyboard = [
                [InlineKeyboardButton("🔍 Details", callback_data=f"signal_detail:{signal_id_prefix}")],
                [InlineKeyboardButton("🎯 Back to Signals", callback_data="menu:signals")],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query,
                f"📉 No saved *{kind_norm}* chart found yet for `{signal_id_prefix}...`.\n\n"
                f"Expected at: `{chart_path.name}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        # Keep caption minimal; we want the dashboard chart to be the "see all do all".
        caption_text = f"{'📈' if kind_norm == 'entry' else '📉'} *{kind_norm.title()} chart*  `{signal_id_prefix}...`"
        caption_md = sanitize_telegram_markdown(caption_text)

        keyboard = [
            [
                InlineKeyboardButton("🔍 Details", callback_data=f"signal_detail:{signal_id_prefix}"),
                InlineKeyboardButton("🏠 Menu", callback_data="menu:main"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            message = getattr(query, "message", None)
            # If message already has a photo, edit it; otherwise delete + send a new photo message.
            if message is not None and getattr(message, "photo", None):
                from telegram import InputMediaPhoto
                try:
                    with open(chart_path, "rb") as f:
                        await query.edit_message_media(
                            media=InputMediaPhoto(media=f, caption=caption_md, parse_mode="Markdown"),
                            reply_markup=reply_markup,
                        )
                except Exception:
                    caption_plain = caption_md.replace("*", "").replace("_", "").replace("`", "")
                    with open(chart_path, "rb") as f:
                        await query.edit_message_media(
                            media=InputMediaPhoto(media=f, caption=caption_plain, parse_mode=None),
                            reply_markup=reply_markup,
                        )
            else:
                try:
                    if message is not None:
                        await message.delete()
                except Exception:
                    pass
                try:
                    with open(chart_path, "rb") as f:
                        await query.message.chat.send_photo(
                            photo=f,
                            caption=caption_md,
                            reply_markup=reply_markup,
                            parse_mode="Markdown",
                        )
                except Exception:
                    caption_plain = caption_md.replace("*", "").replace("_", "").replace("`", "")
                    with open(chart_path, "rb") as f:
                        await query.message.chat.send_photo(
                            photo=f,
                            caption=caption_plain,
                            reply_markup=reply_markup,
                            parse_mode=None,
                        )
            try:
                await query.answer()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Error showing trade chart: {e}")
            keyboard = [
                [InlineKeyboardButton("🔍 Details", callback_data=f"signal_detail:{signal_id_prefix}")],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query,
                f"❌ Could not show chart: `{chart_path.name}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )

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
            "🔍 *Signal Detail*",
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
            text += "\n*Signal Statistics:*\n"
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
            
            text += "*Today's Activity:*\n"
            text += f"  Signals: {len(today_signals)} total\n"
            text += f"  • Generated: {generated}\n"
            text += f"  • Active: {entered}\n"
            text += f"  • Exited: {exited}\n"
            
            if exited > 0:
                text += "\n*Today's P&L:*\n"
                text += f"  {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Trades: {wins}W / {losses}L\n"
        else:
            text += "No signals generated today.\n"
        
        # Add state info
        if state:
            scans = state.get("cycle_count_session", 0) or 0
            errors = state.get("error_count", 0) or 0
            text += "\n*Session Activity:*\n"
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
                text += "\n*Trade Performance:*\n"
                text += f"  Wins: {wins}\n"
                text += f"  Losses: {losses}\n"
                text += f"  Win Rate: {win_rate:.1f}%\n"
                text += "\n*P&L:*\n"
                text += f"  Total: {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Average: ${avg_pnl:,.2f}\n"
                if avg_hold > 0:
                    text += "\n*Timing:*\n"
                    text += f"  Avg Hold: {avg_hold:.1f} min\n"
            else:
                text += "\nNo completed trades this week.\n"
        else:
            text += "No performance data available.\n"
            text += "\n💡 Performance data is calculated from the last 7 days of trading activity."
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_pnl_overview(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display P&L overview."""
        signals = self._read_recent_signals(limit=100)
        
        text = "💰 *P&L Overview*\n\n"
        
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
                self._nav_back_row(),
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
                text += "Expected at: config/config.yaml"
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
        
        await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_gateway_status(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display gateway status."""
        state = self._read_state()
        if not state:
            await self._safe_edit_or_send(query, "❌ Could not read system state.", reply_markup=reply_markup)
            return
        
        # Gateway service status (process + port)
        gw_status = {"process_running": False, "port_listening": False}
        try:
            sc = getattr(self, "service_controller", None)
            if sc:
                gw_status = sc.get_gateway_status() or gw_status
        except Exception:
            pass

        gw_proc = bool(gw_status.get("process_running", False))
        gw_port = bool(gw_status.get("port_listening", False))
        gw_ok = gw_proc and gw_port

        # Agent-reported connection status (when available)
        raw_conn = state.get("connection_status", None)
        conn_failures = int(state.get("connection_failures", 0) or 0)

        conn_label = "UNKNOWN"
        try:
            if raw_conn in (True, "connected", "CONNECTED", "ok", "OK"):
                conn_label = "CONNECTED"
            elif raw_conn in (False, "disconnected", "DISCONNECTED", "down", "DOWN"):
                conn_label = "DISCONNECTED"
            elif raw_conn is None:
                conn_label = "UNKNOWN"
            else:
                conn_label = str(raw_conn).upper()
        except Exception:
            conn_label = "UNKNOWN"

        text = "🔌 *Gateway*\n\n"
        text += f"{'🟢' if gw_ok else '🔴'} *Service:* {'ONLINE' if gw_ok else 'OFFLINE'} (proc={gw_proc}, port={gw_port})\n"
        text += f"{'🟢' if conn_label == 'CONNECTED' else ('🔴' if conn_label == 'DISCONNECTED' else '⚪')} *Connection:* {conn_label}\n"
        if conn_failures > 0:
            text += f"⚠️ *Conn failures:* {conn_failures}\n"

        # Data source info
        latest_bar = state.get("latest_bar", {}) or {}
        data_level = latest_bar.get("_data_level", None)
        if data_level:
            text += f"\n📊 *Data Level:* {data_level}\n"

        await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_connection_status(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display connection status."""
        await self._handle_gateway_status(query, reply_markup)  # Same as gateway status

    async def _handle_data_quality(self, query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display data quality information."""
        state = self._read_state()
        if not state:
            await self._safe_edit_or_send(query, "❌ Could not read system state.", reply_markup=reply_markup)
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
        
        latest_bar = state.get("latest_bar", {}) or {}
        agent_running = bool(self._is_agent_process_running())
        paused = bool(state.get("paused", False))
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
                raw_conn = state.get("connection_status", None)
                connection_failures = int(state.get("connection_failures", 0) or 0)

                conn_diag = "unknown"
                try:
                    if raw_conn in (True, "connected", "CONNECTED", "ok", "OK"):
                        conn_diag = "connected"
                    elif raw_conn in (False, "disconnected", "DISCONNECTED", "down", "DOWN"):
                        conn_diag = "disconnected"
                    elif raw_conn is None:
                        conn_diag = "unknown"
                    else:
                        conn_diag = str(raw_conn)
                except Exception:
                    conn_diag = "unknown"
                
                text += "\n🔍 *Diagnostics:*\n"
                # If the agent isn't explicitly reporting connection status, infer from staleness.
                if conn_diag == "unknown":
                    text += "• Connection: unknown (agent not reporting)\n"
                    text += "• Inference: data is stale → likely feed/connection issue\n"
                else:
                    text += f"• Connection: {conn_diag}\n"
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
        
        await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")

    async def _handle_export_performance(self, query: CallbackQuery) -> None:
        """Export performance report."""
        try:
            metrics = self._read_latest_metrics()
            state = self._read_state()
            
            if not metrics and not state:
                keyboard = [self._nav_back_row()]
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
                self._nav_back_row(),
            ]
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Export performance error: {e}", exc_info=True)
            keyboard = [self._nav_back_row()]
            await query.edit_message_text(
                f"❌ Error exporting performance: {e}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    def run(self) -> None:
        logger.info("Starting PEARLalgo Telegram Command Handler")
        logger.info(f"Bot token: {'***' + self.bot_token[-4:] if len(self.bot_token) > 4 else '***'}")
        logger.info(f"Chat ID: {self.chat_id}")
        logger.info("Button-based interface: use /start to open the dashboard")
        logger.info("Press Ctrl+C to stop")
        logger.info("Connecting to Telegram...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

    # ---------------------------------------------------------------------
    # Support footer (copy/paste diagnostics)
    # ---------------------------------------------------------------------

    def _format_support_duration(self, seconds: float | None) -> str:
        """Compact duration like 12s / 3m / 1h43m."""
        try:
            if seconds is None:
                return "?"
            s = float(seconds)
            if s < 0:
                return "?"
        except Exception:
            return "?"

        if s < 60:
            return f"{int(s)}s"
        if s < 3600:
            return f"{int(s // 60)}m"
        hours = int(s // 3600)
        mins = int((s % 3600) // 60)
        return f"{hours}h{mins}m"

    def _build_support_footer(self, state: dict | None = None) -> str:
        """One-line, copy/paste-friendly support footer for debugging."""
        try:
            if not isinstance(state, dict):
                state = self._read_state()
            if not isinstance(state, dict):
                state = {}
        except Exception:
            state = {}

        # Market + symbol (best-effort)
        market = str(state.get("market") or getattr(self, "active_market", "NQ") or "NQ").strip().upper()
        symbol = str(state.get("symbol") or (state.get("config") or {}).get("symbol") or "MNQ").strip()
        run_id = str(state.get("run_id") or "?").strip()
        ver = str(state.get("version") or "").strip()

        # Agent running (process check)
        try:
            agent_running = bool(self._is_agent_process_running())
        except Exception:
            agent_running = False

        # Gateway status (process + port)
        gw = "?"
        try:
            sc = getattr(self, "service_controller", None)
            if sc is not None:
                gs = sc.get_gateway_status() or {}
                proc = bool(gs.get("process_running"))
                port = bool(gs.get("port_listening"))
                gw = "OK" if (proc and port) else "OFF"
        except Exception:
            gw = "?"

        # Data age + level
        data_lvl = None
        age_sec = None
        try:
            thr_min = float(state.get("data_stale_threshold_minutes") or 10.0)
        except Exception:
            thr_min = None
        try:
            latest_bar = state.get("latest_bar") if isinstance(state.get("latest_bar"), dict) else {}
            data_lvl = (latest_bar or {}).get("_data_level")
            ts = (latest_bar or {}).get("timestamp") or state.get("latest_bar_timestamp")
            if ts:
                dt = parse_utc_timestamp(str(ts))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt:
                    age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            age_sec = None

        # Last cycle age
        cycle_sec = None
        try:
            ts = state.get("last_successful_cycle")
            if ts:
                dt = parse_utc_timestamp(str(ts))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt:
                    cycle_sec = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            cycle_sec = None

        lvl_map = {
            "level1": "L1",
            "level2": "L2",
            "historical": "HIST",
            "historical_fallback": "HIST",
            "error": "ERR",
            "unknown": "?",
        }
        lvl_short = lvl_map.get(str(data_lvl).strip().lower(), None)
        if not lvl_short:
            lvl_short = "?" if data_lvl is None else str(data_lvl)[:4].upper()

        age_str = self._format_support_duration(age_sec)
        thr_str = "?" if thr_min is None else f"{thr_min:.0f}m"
        stale_flag = ""
        try:
            paused = bool(state.get("paused", False))
            futures_open = state.get("futures_market_open")
            session_open = state.get("strategy_session_open")
            should_check_data = (not paused) and not (futures_open is False and session_open is False)
            if should_check_data and thr_min and age_sec is not None and float(age_sec) / 60.0 > float(thr_min):
                stale_flag = "!"
        except Exception:
            stale_flag = ""

        a = "ON" if agent_running else "OFF"
        c = self._format_support_duration(cycle_sec)
        v = f" v{ver}" if ver else ""
        
        # Session indicator from circuit breaker status
        session_str = ""
        try:
            cb_status = state.get("trading_circuit_breaker", {})
            if cb_status:
                current_session = cb_status.get("current_session", "")
                session_allowed = cb_status.get("session_allowed", True)
                session_filter_enabled = cb_status.get("session_filter_enabled", False)
                
                if current_session:
                    # Shorten session names for compact display
                    session_map = {
                        "overnight": "OVN",
                        "premarket": "PRE",
                        "morning": "AM",
                        "midday": "MID",
                        "afternoon": "PM",
                        "close": "CLS",
                    }
                    short_session = session_map.get(current_session.lower(), current_session[:3].upper())
                    
                    if session_filter_enabled:
                        # Show if session is allowed or filtered
                        if session_allowed:
                            session_str = f" | 📍{short_session}"
                        else:
                            session_str = f" | 🚫{short_session}"
                    else:
                        session_str = f" | 📍{short_session}"
        except Exception:
            session_str = ""
        
        # Keep this short; it's intended to be pasted into chat for support.
        return f"`🩺 {market}/{symbol}{v} | A:{a}{session_str} | G:{gw} | D:{lvl_short} {age_str}/{thr_str}{stale_flag} | C:{c} | run:{run_id}`"

    def _with_support_footer(self, text: str, *, state: dict | None = None, max_chars: int = 4096) -> str:
        """Append the support footer (always, by trimming when needed)."""
        base = (text or "").rstrip()
        footer = ""
        try:
            footer = self._build_support_footer(state)
        except Exception:
            footer = ""
        if not footer:
            return base
        # Idempotency: if a support footer is already present (even if values differ),
        # do not append another one.
        if "`🩺 " in base:
            return base
        if footer in base:
            return base
        candidate = f"{base}\n\n{footer}"
        if not max_chars:
            return candidate

        try:
            max_len = int(max_chars)
        except Exception:
            max_len = 0

        if max_len <= 0 or len(candidate) <= max_len:
            return candidate

        # Ensure the footer is always present by trimming from the end.
        if len(footer) >= max_len:
            return footer[:max_len]

        # Keep room for "\n\n" + footer.
        avail = max_len - len(footer) - 2
        if avail <= 0:
            return footer

        # Prefer dropping whole lines (safer for Markdown than hard truncation).
        lines = base.splitlines()
        trimmed_base = ""
        while lines:
            trimmed_base = "\n".join(lines).rstrip()
            if len(trimmed_base) <= avail:
                break
            lines.pop()

        trimmed_base = trimmed_base.rstrip()
        if not trimmed_base:
            return footer

        # Last resort: hard truncate (very unlikely).
        if len(trimmed_base) > avail:
            cut = max(0, avail - 1)
            trimmed_base = (trimmed_base[:cut].rstrip() + "…") if cut else "…"
            # Avoid ending with an unmatched code tick.
            trimmed_base = trimmed_base.rstrip("`").rstrip()

        return f"{trimmed_base}\n\n{footer}"


    # ---------------------------------------------------------------------
    # Legacy/test compatibility helpers
    # ---------------------------------------------------------------------

    async def _send_message_or_edit(self, update: Any, context: Any, msg: str, **kwargs) -> None:
        """Send a message or edit an existing one (test-friendly helper)."""
        try:
            parse_mode = kwargs.get("parse_mode")
            if parse_mode and "markdown" in str(parse_mode).lower():
                msg = self._with_support_footer(msg)
        except Exception:
            pass
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
            # Keep /status aligned with the canonical /start dashboard: no legacy Home Card.
            msg = f"📊 *{symbol}* • {time_str}\n\n❌ No state file found.\n\nUse `/start` for the dashboard."
            if len(msg) > 4096:
                msg = msg[:4093] + "..."
            await self._send_message_or_edit(update, context, msg, parse_mode="Markdown")
            return

        # Legacy /status is deprecated: redirect to the canonical visual dashboard.
        msg = await self._build_status_dashboard_message(state)
        msg = self._with_support_footer(msg, state=state, max_chars=4096)

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

    def _get_back_to_menu_button(self):
        """Return a minimal 'Back to Menu' InlineKeyboardMarkup."""
        try:
            return InlineKeyboardMarkup([self._nav_back_row()])
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
            self._nav_back_row(),
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
        rows.append(self._nav_back_row())

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
            self._nav_back_row(),
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
                self._nav_back_row(),
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
        rows.append(self._nav_back_row())

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
        rows.append(self._nav_back_row())

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
