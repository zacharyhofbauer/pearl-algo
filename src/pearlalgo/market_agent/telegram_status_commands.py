"""
Telegram Status Commands Mixin

Contains status-related command handlers for the Telegram interface.
Can be composed into TelegramCommandHandler via multiple inheritance.

Usage:
    class TelegramCommandHandler(TelegramStatusCommandsMixin, ...):
        ...
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from telegram import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


class TelegramStatusCommandsMixin:
    """
    Mixin providing status-related command handlers.

    Methods:
    - handle_system_status: Display system health status
    - handle_gateway_status: Display IBKR gateway status
    - handle_connection_status: Display connection health
    - handle_data_quality: Display data quality metrics
    - show_status_menu: Display status menu
    - show_ui_doctor: Display UI diagnostics
    """

    async def handle_system_status(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display comprehensive system health status."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        if not state:
            await self._safe_edit_or_send(
                query,
                "❌ Could not read system state.",
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
            return

        lines: List[str] = ["🖥️ *System Status*", ""]

        # Agent status
        running = state.get("running", False)
        paused = state.get("paused", False)
        if running:
            if paused:
                lines.append("⏸️ Agent: *PAUSED*")
            else:
                lines.append("✅ Agent: *RUNNING*")
        else:
            lines.append("🔴 Agent: *STOPPED*")

        # Gateway status
        gw = state.get("gateway_status", {}) or {}
        gw_status = gw.get("status", "unknown")
        gw_emoji = {"online": "✅", "offline": "🔴", "degraded": "⚠️"}.get(gw_status, "❓")
        lines.append(f"{gw_emoji} Gateway: *{gw_status.upper()}*")

        # Data freshness
        data_fresh = state.get("data_fresh", False)
        data_emoji = "✅" if data_fresh else "⚠️"
        lines.append(f"{data_emoji} Data: {'*FRESH*' if data_fresh else '*STALE*'}")

        # Market status
        market_open = state.get("futures_market_open", None)
        if market_open is not None:
            market_emoji = "🟢" if market_open else "🔴"
            lines.append(f"{market_emoji} Market: {'*OPEN*' if market_open else '*CLOSED*'}")

        # Execution state
        exec_state = state.get("execution_state", {}) or {}
        if exec_state:
            armed = exec_state.get("armed", False)
            mode = exec_state.get("mode", "unknown")
            armed_emoji = "🟢" if armed else "🔴"
            lines.append(f"{armed_emoji} Execution: *{mode.upper()}* {'(ARMED)' if armed else '(DISARMED)'}")

        # Circuit breaker
        cb = state.get("circuit_breaker", {}) or {}
        if cb:
            cb_active = cb.get("active", False)
            cb_emoji = "🔴" if cb_active else "✅"
            trips = cb.get("trips_today", 0)
            lines.append(f"{cb_emoji} Circuit Breaker: {'*ACTIVE*' if cb_active else 'OK'} ({trips} trips)")

        # Error summary
        errors = state.get("error_summary", {}) or {}
        if errors:
            error_count = errors.get("session_error_count", 0)
            if error_count > 0:
                lines.append(f"⚠️ Errors this session: {error_count}")

        lines.append("")
        lines.append("_Updated: now_")

        text = "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:system_status"),
            InlineKeyboardButton("🔧 Doctor", callback_data="menu:ui_doctor"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def handle_gateway_status(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display IBKR gateway connection status."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        gw = state.get("gateway_status", {}) if state else {}

        lines: List[str] = ["🌐 *Gateway Status*", ""]

        if not gw:
            lines.append("❓ Gateway status not available.")
        else:
            status = gw.get("status", "unknown")
            status_emoji = {"online": "✅", "offline": "🔴", "degraded": "⚠️"}.get(status, "❓")
            lines.append(f"{status_emoji} Status: *{status.upper()}*")

            if gw.get("process_running") is not None:
                proc_emoji = "✅" if gw.get("process_running") else "🔴"
                lines.append(f"{proc_emoji} Process: {'Running' if gw.get('process_running') else 'Not Running'}")

            if gw.get("port_listening") is not None:
                port_emoji = "✅" if gw.get("port_listening") else "🔴"
                port = gw.get("port", "?")
                lines.append(f"{port_emoji} Port {port}: {'Listening' if gw.get('port_listening') else 'Not Listening'}")

        text = "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:gateway_status"),
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def handle_connection_status(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display connection health metrics."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        conn = state.get("connection_health", {}) if state else {}

        lines: List[str] = ["🔌 *Connection Health*", ""]

        if not conn:
            lines.append("❓ Connection health not available.")
        else:
            failures = conn.get("connection_failures", 0)
            fetch_errors = conn.get("data_fetch_errors", 0)
            consecutive = conn.get("consecutive_errors", 0)
            data_level = conn.get("data_level", "unknown")

            health_emoji = "✅" if consecutive == 0 else "⚠️" if consecutive < 3 else "🔴"
            lines.append(f"{health_emoji} Health: {'Good' if consecutive == 0 else 'Degraded'}")
            lines.append(f"Data Level: *{data_level}*")
            lines.append(f"Connection Failures: {failures}")
            lines.append(f"Fetch Errors: {fetch_errors}")
            lines.append(f"Consecutive Errors: {consecutive}")

            last_success = conn.get("last_successful_fetch")
            if last_success:
                lines.append(f"Last Success: `{last_success[:19]}`")

        text = "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:connection_status"),
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def handle_data_quality(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display data quality metrics."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        dq = state.get("data_quality", {}) if state else {}

        lines: List[str] = ["📊 *Data Quality*", ""]

        if not dq:
            lines.append("❓ Data quality metrics not available.")
        else:
            is_stale = dq.get("is_stale", False)
            is_expected_stale = dq.get("is_expected_stale", False)

            if is_stale:
                if is_expected_stale:
                    lines.append("⚪ Status: *Expected Stale* (market closed)")
                else:
                    lines.append("⚠️ Status: *STALE*")
            else:
                lines.append("✅ Status: *FRESH*")

            bar_age = dq.get("latest_bar_age_minutes")
            if bar_age is not None:
                lines.append(f"Bar Age: {bar_age:.1f} min")

            threshold = dq.get("stale_threshold_minutes")
            if threshold:
                lines.append(f"Stale Threshold: {threshold} min")

            buffer_size = dq.get("buffer_size")
            buffer_target = dq.get("buffer_target")
            if buffer_size is not None and buffer_target:
                pct = (buffer_size / buffer_target) * 100 if buffer_target else 0
                buffer_emoji = "✅" if pct >= 80 else "⚠️" if pct >= 50 else "🔴"
                lines.append(f"{buffer_emoji} Buffer: {buffer_size}/{buffer_target} ({pct:.0f}%)")

            quiet_reason = dq.get("quiet_reason")
            if quiet_reason:
                lines.append(f"Quiet Reason: _{quiet_reason}_")

        text = "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:data_quality"),
            InlineKeyboardButton("📊 Status", callback_data="menu:status"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    # Note: The following methods should be defined in the main class or other mixins:
    # - _read_state() -> Optional[dict]
    # - _safe_edit_or_send(query, text, reply_markup, parse_mode)
