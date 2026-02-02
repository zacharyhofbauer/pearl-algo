"""
Telegram Config Commands Mixin

Contains configuration-related command handlers for the Telegram interface.
Can be composed into TelegramCommandHandler via multiple inheritance.

Usage:
    class TelegramCommandHandler(TelegramConfigCommandsMixin, ...):
        ...
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from telegram import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


class TelegramConfigCommandsMixin:
    """
    Mixin providing configuration-related command handlers.

    Methods:
    - handle_config_view: Display current configuration
    - handle_set_trading_mode: Change trading mode
    - handle_logs_view: Display recent logs
    - show_settings_menu: Display settings menu
    - show_bots_menu: Display bots/strategies menu
    - show_system_menu: Display system menu
    """

    async def handle_config_view(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display current configuration summary."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        config = state.get("config", {}) if state else {}

        lines: List[str] = ["⚙️ *Configuration*", ""]

        if not config:
            lines.append("❓ Configuration not available.")
        else:
            symbol = config.get("symbol", "?")
            market = config.get("market", "?")
            timeframe = config.get("timeframe", "?")
            scan_interval = config.get("scan_interval", "?")
            mode = config.get("mode", "?")

            lines.append(f"*Symbol:* {symbol}")
            lines.append(f"*Market:* {market}")
            lines.append(f"*Timeframe:* {timeframe}")
            lines.append(f"*Scan Interval:* {scan_interval}s")
            lines.append(f"*Mode:* {mode.upper()}")

            session_start = config.get("session_start")
            session_end = config.get("session_end")
            if session_start and session_end:
                lines.append(f"*Session:* {session_start} - {session_end}")

        text = "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:config_view"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def handle_set_trading_mode(
        self,
        query: "CallbackQuery",
        mode: str,
    ) -> None:
        """
        Handle trading mode change request.

        Args:
            query: Telegram callback query
            mode: New mode ('live', 'paper', 'shadow', 'paused')
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        valid_modes = ["live", "paper", "shadow", "paused"]
        if mode not in valid_modes:
            await self._safe_edit_or_send(
                query,
                f"❌ Invalid mode: {mode}",
                reply_markup=self._settings_nav_keyboard(),
                parse_mode="Markdown",
            )
            return

        # Confirmation for live mode
        if mode == "live":
            text = (
                "⚠️ *Enable LIVE Trading?*\n\n"
                "This will enable real order execution.\n\n"
                "Are you sure?"
            )
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, Go Live", callback_data=f"confirm:set_mode_{mode}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="menu:settings"),
                ]
            ]
            await self._safe_edit_or_send(
                query,
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        # Direct mode change for other modes
        await self._apply_trading_mode(query, mode)

    async def _apply_trading_mode(
        self,
        query: "CallbackQuery",
        mode: str,
    ) -> None:
        """Apply trading mode change."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        # Write mode to control file
        try:
            mode_file = self._get_control_file("trading_mode")
            if mode_file:
                mode_file.write_text(mode)
                await self._safe_edit_or_send(
                    query,
                    f"✅ Trading mode set to *{mode.upper()}*\n\n_Changes will take effect on next scan cycle._",
                    reply_markup=self._settings_nav_keyboard(),
                    parse_mode="Markdown",
                )
            else:
                await self._safe_edit_or_send(
                    query,
                    "❌ Could not write mode file.",
                    reply_markup=self._settings_nav_keyboard(),
                    parse_mode="Markdown",
                )
        except Exception as e:
            await self._safe_edit_or_send(
                query,
                f"❌ Error setting mode: {str(e)[:100]}",
                reply_markup=self._settings_nav_keyboard(),
                parse_mode="Markdown",
            )

    async def handle_logs_view(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display recent log entries."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        lines: List[str] = ["📋 *Recent Logs*", ""]

        try:
            log_file = self._get_log_file()
            if log_file and log_file.exists():
                content = log_file.read_text()
                log_lines = content.strip().split("\n")
                recent = log_lines[-20:]  # Last 20 lines

                for line in recent:
                    # Truncate long lines
                    if len(line) > 80:
                        line = line[:77] + "..."
                    # Escape special characters
                    line = line.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
                    lines.append(f"`{line}`")
            else:
                lines.append("❓ Log file not found.")
        except Exception as e:
            lines.append(f"❌ Error reading logs: {str(e)[:50]}")

        text = "\n".join(lines)

        # Telegram message limit
        if len(text) > 4000:
            text = text[:3997] + "..."

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:logs_view"),
            InlineKeyboardButton("🔧 System", callback_data="menu:system"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    def _settings_nav_keyboard(self) -> "InlineKeyboardMarkup":
        """Return standard settings navigation keyboard."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]])

    def _get_control_file(self, name: str):
        """Get path to a control file. Override in main class."""
        return None

    def _get_log_file(self):
        """Get path to log file. Override in main class."""
        return None

    # Note: The following methods should be defined in the main class or other mixins:
    # - _read_state() -> Optional[dict]
    # - _safe_edit_or_send(query, text, reply_markup, parse_mode)
