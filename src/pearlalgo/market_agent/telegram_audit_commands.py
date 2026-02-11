"""
Telegram Audit Commands Mixin

Provides audit commands for the Telegram bot command handler.
Uses the canonical callback format: action:audit_trades, action:audit_signals, etc.

Required attributes from the composing TelegramCommandHandler:
    - _audit_logger: AuditLogger instance (or None)
    - _safe_edit_or_send: Method for safe message editing
    - _nav_back_row: Method returning back navigation row
    - chat_id: Telegram chat ID
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger

if TYPE_CHECKING:
    from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False
    InlineKeyboardButton = None  # type: ignore
    InlineKeyboardMarkup = None  # type: ignore


class TelegramAuditCommandsMixin:
    """Mixin providing audit commands for TelegramCommandHandler."""

    async def _handle_audit_menu(self, query: "CallbackQuery", chat_id: int) -> None:
        """Show audit sub-menu."""
        if not _TG_AVAILABLE:
            return
        keyboard = [
            [InlineKeyboardButton("📋 Recent Trades (7d)", callback_data="action:audit_trades_7d")],
            [InlineKeyboardButton("🔍 Signal Decisions (7d)", callback_data="action:audit_signals_7d")],
            [InlineKeyboardButton("🏥 System Health (7d)", callback_data="action:audit_health_7d")],
            [InlineKeyboardButton("⚖️ Reconciliation", callback_data="action:audit_reconcile")],
            [self._nav_back_row()],
        ]
        await self._safe_edit_or_send(
            query,
            "📋 *Audit Menu*\n\nSelect an audit report:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def _handle_audit_trades(self, query: "CallbackQuery", period: str = "7d") -> None:
        """Show recent trade audit for period."""
        audit_logger = getattr(self, "_audit_logger", None)
        if audit_logger is None:
            await self._safe_edit_or_send(query, "⚠️ Audit logger not available.")
            return

        try:
            days = 7 if period == "7d" else (30 if period == "30d" else 365)
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            exits = audit_logger.query_events(
                event_type="trade_exited", start_date=start_date, limit=200,
            )
            entries = audit_logger.query_events(
                event_type="trade_entered", start_date=start_date, limit=200,
            )

            total_trades = len(exits)
            total_pnl = sum(float((e.get("data") or {}).get("pnl", 0)) for e in exits)
            wins = sum(1 for e in exits if (e.get("data") or {}).get("is_win", False))
            losses = total_trades - wins
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            pnl_sign = "+" if total_pnl >= 0 else ""
            msg = (
                f"📋 *Trade Audit ({period})*\n\n"
                f"Total Trades: {total_trades}\n"
                f"P&L: {pnl_sign}${total_pnl:,.2f}\n"
                f"Wins: {wins} | Losses: {losses}\n"
                f"Win Rate: {win_rate:.0f}%\n"
                f"Entries Logged: {len(entries)}\n"
                f"Exits Logged: {len(exits)}"
            )
            keyboard = [
                [
                    InlineKeyboardButton("📋 30d", callback_data="action:audit_trades_30d"),
                    InlineKeyboardButton("📋 Audit", callback_data="menu:audit"),
                ],
                [self._nav_back_row()],
            ]
            await self._safe_edit_or_send(query, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit trades error: {e}")
            await self._safe_edit_or_send(query, f"❌ Audit error: {e}")

    async def _handle_audit_signals(self, query: "CallbackQuery", period: str = "7d") -> None:
        """Show signal decision audit for period."""
        audit_logger = getattr(self, "_audit_logger", None)
        if audit_logger is None:
            await self._safe_edit_or_send(query, "⚠️ Audit logger not available.")
            return

        try:
            days = 7 if period == "7d" else 30
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            generated = audit_logger.count_events(event_type="signal_generated", start_date=start_date)
            rejected = audit_logger.count_events(event_type="signal_rejected", start_date=start_date)

            # Top rejection reasons
            rejections = audit_logger.query_events(
                event_type="signal_rejected", start_date=start_date, limit=200,
            )
            reason_counts: Dict[str, int] = {}
            for r in rejections:
                reason = (r.get("data") or {}).get("reason", "unknown")
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            top_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            accept_rate = ((generated / max(1, generated + rejected)) * 100)
            msg = (
                f"🔍 *Signal Decisions ({period})*\n\n"
                f"Generated: {generated}\n"
                f"Rejected: {rejected}\n"
                f"Acceptance Rate: {accept_rate:.0f}%\n"
            )
            if top_reasons:
                msg += "\n*Top Rejection Reasons:*\n"
                for reason, count in top_reasons:
                    msg += f"  • `{reason}`: {count}\n"

            keyboard = [
                [
                    InlineKeyboardButton("🔍 30d", callback_data="action:audit_signals_30d"),
                    InlineKeyboardButton("📋 Audit", callback_data="menu:audit"),
                ],
                [self._nav_back_row()],
            ]
            await self._safe_edit_or_send(query, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit signals error: {e}")
            await self._safe_edit_or_send(query, f"❌ Audit error: {e}")

    async def _handle_audit_health(self, query: "CallbackQuery", period: str = "7d") -> None:
        """Show system health audit for period."""
        audit_logger = getattr(self, "_audit_logger", None)
        if audit_logger is None:
            await self._safe_edit_or_send(query, "⚠️ Audit logger not available.")
            return

        try:
            days = 7 if period == "7d" else 30
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            starts = audit_logger.count_events(event_type="system_start", start_date=start_date)
            stops = audit_logger.count_events(event_type="system_stop", start_date=start_date)
            cb_trips = audit_logger.count_events(event_type="circuit_breaker_trip", start_date=start_date)
            conn_drops = audit_logger.count_events(event_type="connection_drop", start_date=start_date)
            errors = audit_logger.count_events(event_type="error_threshold", start_date=start_date)

            msg = (
                f"🏥 *System Health ({period})*\n\n"
                f"Restarts: {starts} starts / {stops} stops\n"
                f"Circuit Breaker Trips: {cb_trips}\n"
                f"Connection Drops: {conn_drops}\n"
                f"Error Thresholds: {errors}"
            )
            keyboard = [
                [
                    InlineKeyboardButton("🏥 30d", callback_data="action:audit_health_30d"),
                    InlineKeyboardButton("📋 Audit", callback_data="menu:audit"),
                ],
                [self._nav_back_row()],
            ]
            await self._safe_edit_or_send(query, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit health error: {e}")
            await self._safe_edit_or_send(query, f"❌ Audit error: {e}")

    async def _handle_audit_reconcile(self, query: "CallbackQuery") -> None:
        """Show latest reconciliation report."""
        audit_logger = getattr(self, "_audit_logger", None)
        if audit_logger is None:
            await self._safe_edit_or_send(query, "⚠️ Audit logger not available.")
            return

        try:
            results = audit_logger.query_reconciliation()
            if not results:
                keyboard = [[self._nav_back_row()]]
                await self._safe_edit_or_send(
                    query, "⚖️ No reconciliation data yet.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return

            msg = "⚖️ *Reconciliation*\n\n"
            for r in results[:3]:
                data = r.get("data", {})
                status_emoji = "✅" if data.get("status") == "within_tolerance" else "⚠️"
                msg += (
                    f"{status_emoji} {r.get('timestamp', '')[:10]}\n"
                    f"  Agent: ${data.get('agent_pnl', 0):,.2f} | "
                    f"Broker: ${data.get('broker_pnl', 0):,.2f}\n"
                    f"  Drift: ${data.get('drift', 0):,.2f} "
                    f"({data.get('drift_pct', 0):.1f}%)\n\n"
                )
            keyboard = [
                [InlineKeyboardButton("📋 Audit", callback_data="menu:audit")],
                [self._nav_back_row()],
            ]
            await self._safe_edit_or_send(query, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit reconcile error: {e}")
            await self._safe_edit_or_send(query, f"❌ Audit error: {e}")
