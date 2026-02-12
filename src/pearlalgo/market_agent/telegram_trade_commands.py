"""
Telegram Trade Commands Mixin

Contains trade-related command handlers for the Telegram interface.
Can be composed into TelegramCommandHandler via multiple inheritance.

Usage:
    class TelegramCommandHandler(TelegramTradeCommandsMixin, ...):
        ...
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pearlalgo.utils.formatting import pnl_emoji

if TYPE_CHECKING:
    from telegram import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton


class TelegramTradeCommandsMixin:
    """
    Mixin providing trade-related command handlers.

    Methods:
    - handle_trades_overview: Display virtual trades overview
    - handle_signal_history: Display trade history summary
    - handle_signal_detail: Display detailed trade information
    - handle_trade_chart: Display trade entry/exit charts
    - show_activity_menu: Display activity menu
    """

    async def handle_trades_overview(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """
        Unified Trades view (Virtual entry/exit history + drill-down).

        Displays:
        - Number of open virtual trades
        - Unrealized P&L
        - List of open positions
        - Recent trade history with drill-down buttons
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        if not state:
            await self._safe_edit_or_send(
                query,
                "❌ Could not read system state.\n\nState file not found or invalid.",
                reply_markup=self._activity_nav_keyboard(),
                parse_mode="Markdown",
            )
            return

        virtual_trades_count = int(state.get("active_trades_count", 0) or 0)
        active_trades_unrealized_pnl = state.get("active_trades_unrealized_pnl")

        recent_signals = self._read_recent_signals(limit=50)
        recent_10 = recent_signals[-10:] if recent_signals else []
        active_signals = [s for s in recent_signals if s.get("status") == "entered"]

        lines: List[str] = ["📋 *Trades* (Virtual)", ""]
        lines.append(f"Open: *{virtual_trades_count}*")

        if active_trades_unrealized_pnl is not None:
            try:
                upnl = float(active_trades_unrealized_pnl)
                upnl_emoji = "💰" if upnl >= 0 else "📉"
                pnl_sign = "+" if upnl >= 0 else ""
                lines.append(f"{upnl_emoji} Unrealized: {pnl_sign}${abs(upnl):,.2f}")
            except Exception:
                pass

        lines.append("")
        lines.append("_Virtual trades are simulated (not broker positions)._")

        if active_signals:
            lines.append("")
            lines.append(f"*Open Positions ({len(active_signals)}):*")
            for i, signal in enumerate(active_signals[-5:], 1):
                signal_id_short = str(signal.get("signal_id") or "unknown")[:8]
                direction = str(signal.get("direction") or "").upper()
                signal_type = str(signal.get("type") or "unknown")
                lines.append(f"{i}. {direction} {signal_type}  `{signal_id_short}`")
                entry_price = signal.get("entry_price")
                if entry_price:
                    try:
                        lines.append(f"   Entry: ${float(entry_price):,.2f}")
                    except Exception:
                        pass

        lines.append("")
        if not recent_10:
            lines.append("*Recent:* none")
        else:
            lines.append(f"*Recent ({len(recent_10)}):*")
            for i, signal in enumerate(reversed(recent_10), 1):
                lines.extend(self._format_trade_line(signal, i))

        text = "\n".join(lines)

        keyboard_rows: List[List["InlineKeyboardButton"]] = []

        if virtual_trades_count > 0:
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"🚫 Close All ({virtual_trades_count})",
                    callback_data="action:close_all_trades"
                )
            ])

        detail_buttons: List["InlineKeyboardButton"] = []
        for signal in reversed(recent_10):
            sig_id = str(signal.get("signal_id") or "").strip()
            if not sig_id:
                continue
            sid_short = sig_id[:8]
            detail_buttons.append(
                InlineKeyboardButton(f"ℹ️ {sid_short}", callback_data=f"signal_detail:{sig_id[:16]}")
            )

        for i in range(0, len(detail_buttons), 2):
            keyboard_rows.append(detail_buttons[i:i + 2])

        keyboard_rows.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="action:trades_overview"),
            InlineKeyboardButton("📊 Activity", callback_data="menu:activity"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ])

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard_rows),
            parse_mode="Markdown",
        )

    def _format_trade_line(self, signal: Dict, index: int) -> List[str]:
        """Format a single trade line for display."""
        from pearlalgo.utils.paths import parse_utc_timestamp

        signal_id = str(signal.get("signal_id") or "unknown")
        signal_id_short = signal_id[:8]
        direction = str(signal.get("direction") or "").upper()
        signal_type = str(signal.get("type") or "unknown")
        status = str(signal.get("status") or "unknown")
        entry_price = signal.get("entry_price")
        pnl = signal.get("pnl")
        timestamp = signal.get("timestamp", "")

        time_str = ""
        if timestamp:
            try:
                ts = parse_utc_timestamp(timestamp) if isinstance(timestamp, str) else timestamp
                time_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(timestamp)[:5]
            except Exception:
                time_str = str(timestamp)[:5] if timestamp else ""

        status_emoji = {
            "entered": "🟢",
            "exited": "⚪",
            "generated": "🟡",
            "cancelled": "❌"
        }.get(status, "⚪")

        dir_emoji = "📈" if direction == "LONG" else "📉" if direction == "SHORT" else ""

        line = f"{index}. {dir_emoji} {direction} {signal_type} {status_emoji}"
        if entry_price:
            try:
                line += f"  ${float(entry_price):,.2f}"
            except Exception:
                pass
        if time_str:
            line += f" @ {time_str}"
        if pnl is not None and status == "exited":
            try:
                pnl_val = float(pnl)
                pe = "🟢" if pnl_val >= 0 else "🔴"
                line += f" | {pe} ${pnl_val:+.2f}"
            except Exception:
                pass

        return [line, f"   `{signal_id_short}`"]

    async def handle_signal_history(
        self,
        query: "CallbackQuery",
        reply_markup: "InlineKeyboardMarkup",
    ) -> None:
        """Display trade history summary with statistics."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        signals = self._read_recent_signals(limit=100)

        text = "📊 *Trade History*\n\n"

        if not signals:
            text += "No trades in history.\n"
        else:
            stats = self._compute_trade_stats(signals)

            text += f"*Total Trades:* {stats['total']}\n"
            if stats['exited_count'] > 0:
                pnl_emoji_str = pnl_emoji(stats['total_pnl'])
                text += f"*Total P&L:* {pnl_emoji_str} ${stats['total_pnl']:,.2f}\n"
            text += "\n"

            text += "*By Status:*\n"
            status_emoji = {"entered": "🟢", "exited": "⚪", "generated": "🟡", "cancelled": "❌"}
            for status, count in sorted(stats['by_status'].items()):
                emoji = status_emoji.get(status, "⚪")
                text += f"  {emoji} {status}: {count}\n"

            text += "\n*By Direction:*\n"
            for direction, count in sorted(stats['by_direction'].items()):
                dir_emoji = "📈" if direction == "LONG" else "📉" if direction == "SHORT" else "❓"
                text += f"  {dir_emoji} {direction}: {count}\n"

            text += "\n*By Type:*\n"
            for sig_type, count in sorted(stats['by_type'].items()):
                text += f"  • {sig_type}: {count}\n"

        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="action:signal_history"),
            InlineKeyboardButton("📊 Activity", callback_data="menu:activity"),
            InlineKeyboardButton("🏠 Menu", callback_data="back"),
        ]]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    def _compute_trade_stats(self, signals: List[Dict]) -> Dict[str, Any]:
        """Compute statistics from a list of signals."""
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        by_direction: Dict[str, int] = {}
        total_pnl = 0.0

        for signal in signals:
            status = signal.get("status", "unknown")
            signal_type = signal.get("type", "unknown")
            direction = signal.get("direction", "unknown").upper()

            by_status[status] = by_status.get(status, 0) + 1
            by_type[signal_type] = by_type.get(signal_type, 0) + 1
            by_direction[direction] = by_direction.get(direction, 0) + 1

            if status == "exited":
                total_pnl += float(signal.get("pnl", 0) or 0)

        return {
            'total': len(signals),
            'exited_count': by_status.get("exited", 0),
            'total_pnl': total_pnl,
            'by_status': by_status,
            'by_type': by_type,
            'by_direction': by_direction,
        }

    async def handle_close_all_trades(self, query: "CallbackQuery") -> None:
        """
        Handle close all trades request.

        Shows confirmation dialog before closing.
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        state = self._read_state()
        active_count = int(state.get("active_trades_count", 0) or 0) if state else 0

        if active_count == 0:
            await self._safe_edit_or_send(
                query,
                "ℹ️ No open trades to close.",
                reply_markup=self._activity_nav_keyboard(),
                parse_mode="Markdown",
            )
            return

        text = (
            f"⚠️ *Close All Trades*\n\n"
            f"This will close all {active_count} open virtual trades.\n\n"
            f"Are you sure?"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Close All", callback_data="confirm:close_all_trades"),
                InlineKeyboardButton("❌ Cancel", callback_data="action:trades_overview"),
            ]
        ]

        await self._safe_edit_or_send(
            query,
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    # Note: The following methods should be defined in the main class or other mixins:
    # - _read_state() -> Optional[dict]
    # - _read_recent_signals(limit: int) -> list
    # - _safe_edit_or_send(query, text, reply_markup, parse_mode)
    # - _activity_nav_keyboard() -> InlineKeyboardMarkup
