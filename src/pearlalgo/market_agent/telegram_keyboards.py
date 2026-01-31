"""
Telegram Keyboard Builders for Market Agent.

This module provides mixin methods for building inline keyboards and button layouts.
These are extracted from TelegramCommandHandler to improve modularity.

Architecture Note:
------------------
This is a mixin class designed to be composed with TelegramCommandHandler.
It provides keyboard-building utilities while keeping the main handler class
focused on routing and orchestration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Any

if TYPE_CHECKING:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore


class TelegramKeyboardsMixin:
    """
    Mixin providing keyboard building utilities for Telegram bot.

    This mixin is designed to be used with TelegramCommandHandler and provides:
    - Navigation button builders
    - Standard keyboard layouts
    - Quick keyboard construction utilities

    Usage:
        class TelegramCommandHandler(TelegramKeyboardsMixin, ...):
            ...
    """

    def _nav_back_row(self) -> list:
        """
        Single source of truth for 'Back to Menu' navigation.
        Use this everywhere instead of creating buttons manually.
        """
        if not TELEGRAM_AVAILABLE:
            return []
        return [InlineKeyboardButton("🏠 Menu", callback_data="back")]

    def _activity_nav_keyboard(self, extra_buttons: list = None) -> Any:
        """
        Standard navigation for Activity sub-views.
        Returns keyboard with Activity back button and Menu button.
        """
        if not TELEGRAM_AVAILABLE:
            return None
        row = []
        if extra_buttons:
            row.extend(extra_buttons)
        row.append(InlineKeyboardButton("📊 Activity", callback_data="menu:activity"))
        row.append(InlineKeyboardButton("🏠 Menu", callback_data="back"))
        return InlineKeyboardMarkup([row])

    def _nav_footer(self, extra_buttons: list = None) -> list:
        """
        Standard navigation footer for all sub-menus.

        Args:
            extra_buttons: Optional list of additional buttons to add before Menu

        Returns:
            List containing a single row with Menu button (and extras if provided)
        """
        if extra_buttons:
            if TELEGRAM_AVAILABLE:
                return [*extra_buttons, InlineKeyboardButton("🏠 Menu", callback_data="back")]
            return extra_buttons
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

    def _quick_keyboard(self, *rows, include_nav: bool = True) -> Any:
        """
        Quick keyboard builder with automatic navigation footer.

        Args:
            *rows: Button rows (each row is a list of InlineKeyboardButtons or tuples of (label, callback))
            include_nav: Whether to include the navigation footer (default True)

        Returns:
            InlineKeyboardMarkup ready to use
        """
        if not TELEGRAM_AVAILABLE:
            return None

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

    def _build_confirmation_keyboard(
        self,
        confirm_action: str,
        confirm_label: str = "✅ Confirm",
        cancel_callback: str = "back",
        cancel_label: str = "❌ Cancel",
    ) -> Any:
        """
        Build a standard confirmation keyboard with confirm/cancel buttons.

        Args:
            confirm_action: The action to confirm (will be prefixed with "confirm:")
            confirm_label: Label for confirm button
            cancel_callback: Callback data for cancel button
            cancel_label: Label for cancel button

        Returns:
            InlineKeyboardMarkup with confirm/cancel buttons
        """
        if not TELEGRAM_AVAILABLE:
            return None

        keyboard = [
            [InlineKeyboardButton(confirm_label, callback_data=f"confirm:{confirm_action}")],
            [InlineKeyboardButton(cancel_label, callback_data=cancel_callback)],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _build_settings_toggle_row(
        self,
        label: str,
        pref_key: str,
        is_enabled: bool,
        icon_on: str = "🟢",
        icon_off: str = "🔴",
    ) -> Any:
        """
        Build a settings toggle button.

        Args:
            label: Base label for the setting
            pref_key: Preference key for toggle callback
            is_enabled: Current state of the setting
            icon_on: Icon when enabled
            icon_off: Icon when disabled

        Returns:
            InlineKeyboardButton for the toggle
        """
        if not TELEGRAM_AVAILABLE:
            return None

        status = icon_on if is_enabled else icon_off
        full_label = f"{label}: {status}"
        return InlineKeyboardButton(
            full_label,
            callback_data=f"action:toggle_pref:{pref_key}",
        )

    def _build_system_control_keyboard(
        self,
        agent_running: bool,
        gateway_running: bool,
        has_positions: bool = False,
        positions_count: int = 0,
    ) -> list:
        """
        Build the system control keyboard with dynamic button states.

        Args:
            agent_running: Whether agent is currently running
            gateway_running: Whether gateway is currently running
            has_positions: Whether there are open positions
            positions_count: Number of open positions

        Returns:
            List of keyboard rows for system menu
        """
        if not TELEGRAM_AVAILABLE:
            return []

        # Dynamic button labels
        agent_btn = "🛑 Stop Agent" if agent_running else "🚀 Start Agent"
        agent_action = "action:stop_agent" if agent_running else "action:start_agent"

        gw_btn = "🛑 Stop Gateway" if gateway_running else "🚀 Start Gateway"
        gw_action = "action:stop_gateway" if gateway_running else "action:start_gateway"

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
                InlineKeyboardButton("🏆 Challenge", callback_data="action:challenge_menu"),
                InlineKeyboardButton("🧹 Cache", callback_data="action:clear_cache"),
            ],
        ]

        # Emergency stop (only if positions exist)
        if has_positions:
            keyboard.append([
                InlineKeyboardButton(
                    f"🚨 Emergency ({positions_count})",
                    callback_data="action:emergency_stop",
                ),
            ])

        # Back
        keyboard.append(self._nav_back_row())

        return keyboard

    def _build_activity_keyboard(
        self,
        virtual_open: int = 0,
        recent_count: int = 0,
    ) -> list:
        """
        Build the activity menu keyboard with dynamic labels.

        Args:
            virtual_open: Number of open virtual trades
            recent_count: Number of recent signals

        Returns:
            List of keyboard rows for activity menu
        """
        if not TELEGRAM_AVAILABLE:
            return []

        # Dynamic labels
        trades_label = f"📋 Trades ({virtual_open})" if virtual_open > 0 else "📋 Trades"
        close_all_label = f"🚫 Close All ({virtual_open})" if virtual_open > 0 else "🚫 Close All"

        keyboard = [
            # Row 1: Unified Trades
            [
                InlineKeyboardButton(trades_label, callback_data="action:trades_overview"),
                InlineKeyboardButton("📊 History", callback_data="action:signal_history"),
            ],
            # Row 2: Reports
            [
                InlineKeyboardButton("📈 Performance", callback_data="action:performance_metrics"),
                InlineKeyboardButton("💰 P&L Detail", callback_data="action:pnl_overview"),
            ],
            # Row 3: Risk/Incident
            [
                InlineKeyboardButton("🧯 Risk Report", callback_data="action:risk_report"),
            ],
        ]

        # Row 4: Actions (conditional)
        if virtual_open > 0:
            keyboard.append([
                InlineKeyboardButton(close_all_label, callback_data="action:close_all_trades"),
            ])

        # Row 5: Analytics
        keyboard.append([
            InlineKeyboardButton("🔬 Analytics", callback_data="menu:analytics"),
        ])

        # Row 6: Navigation
        keyboard.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="menu:activity"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ])

        return keyboard

    def _build_health_menu_keyboard(self) -> list:
        """
        Build the health/status menu keyboard.

        Returns:
            List of keyboard rows for health menu
        """
        if not TELEGRAM_AVAILABLE:
            return []

        from pearlalgo.utils.telegram_ui_contract import (
            callback_action,
            ACTION_GATEWAY_STATUS,
            ACTION_CONNECTION_STATUS,
            ACTION_DATA_QUALITY,
            ACTION_SYSTEM_STATUS,
        )

        return [
            [
                InlineKeyboardButton("🔌 Gateway", callback_data=callback_action(ACTION_GATEWAY_STATUS)),
                InlineKeyboardButton("📡 Connection", callback_data=callback_action(ACTION_CONNECTION_STATUS)),
            ],
            [
                InlineKeyboardButton("📊 Data", callback_data=callback_action(ACTION_DATA_QUALITY)),
                InlineKeyboardButton("📋 Status", callback_data=callback_action(ACTION_SYSTEM_STATUS)),
            ],
            [InlineKeyboardButton("🩺 Doctor", callback_data=callback_action("ui_doctor"))],
            self._nav_back_row(),
        ]
