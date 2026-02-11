"""
Telegram Audit Commands Mixin

Provides /audit commands for the Telegram bot command handler.
Commands: trades, signals, health, reconcile, export.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pearlalgo.utils.logger import logger


class TelegramAuditCommandsMixin:
    """Mixin providing audit commands for TelegramCommandHandler."""

    async def _handle_audit_menu(self, query, chat_id: int) -> None:
        """Show audit sub-menu."""
        keyboard = [
            [{"text": "📋 Recent Trades", "callback_data": "audit_trades_7d"}],
            [{"text": "🔍 Signal Decisions", "callback_data": "audit_signals_7d"}],
            [{"text": "🏥 System Health", "callback_data": "audit_health_7d"}],
            [{"text": "⚖️ Reconciliation", "callback_data": "audit_reconcile"}],
            [{"text": "📤 Export CSV", "callback_data": "audit_export"}],
            [{"text": "⬅️ Back", "callback_data": "main_menu"}],
        ]

        await self._edit_or_send(
            query,
            chat_id,
            "📊 *Audit Menu*\n\nSelect an audit report:",
            reply_markup={"inline_keyboard": keyboard},
            parse_mode="Markdown",
        )

    async def _handle_audit_trades(self, query, chat_id: int, period: str = "7d") -> None:
        """Show recent trade audit for period."""
        try:
            audit_logger = getattr(self, "_audit_logger", None)
            if audit_logger is None:
                await self._reply_text(query, chat_id, "Audit logger not available.")
                return

            days = 7 if period == "7d" else (30 if period == "30d" else 365)
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            entries = audit_logger.query_events(
                event_type="trade_entered", start_date=start_date, limit=100,
            )
            exits = audit_logger.query_events(
                event_type="trade_exited", start_date=start_date, limit=100,
            )

            total_trades = len(exits)
            total_pnl = sum(
                float((e.get("data") or {}).get("pnl", 0)) for e in exits
            )
            wins = sum(
                1 for e in exits if (e.get("data") or {}).get("is_win", False)
            )
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
            await self._reply_text(query, chat_id, msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit trades error: {e}")
            await self._reply_text(query, chat_id, f"Error: {e}")

    async def _handle_audit_signals(self, query, chat_id: int, period: str = "7d") -> None:
        """Show signal decision audit for period."""
        try:
            audit_logger = getattr(self, "_audit_logger", None)
            if audit_logger is None:
                await self._reply_text(query, chat_id, "Audit logger not available.")
                return

            days = 7 if period == "7d" else 30
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            generated = audit_logger.count_events(
                event_type="signal_generated", start_date=start_date,
            )
            rejected = audit_logger.count_events(
                event_type="signal_rejected", start_date=start_date,
            )

            # Get top rejection reasons
            rejections = audit_logger.query_events(
                event_type="signal_rejected", start_date=start_date, limit=200,
            )
            reason_counts: Dict[str, int] = {}
            for r in rejections:
                reason = (r.get("data") or {}).get("reason", "unknown")
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

            top_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            msg = (
                f"🔍 *Signal Decisions ({period})*\n\n"
                f"Generated: {generated}\n"
                f"Rejected: {rejected}\n"
                f"Acceptance Rate: {((generated - rejected) / max(1, generated) * 100):.0f}%\n"
            )
            if top_reasons:
                msg += "\n*Top Rejection Reasons:*\n"
                for reason, count in top_reasons:
                    msg += f"  • {reason}: {count}\n"

            await self._reply_text(query, chat_id, msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit signals error: {e}")
            await self._reply_text(query, chat_id, f"Error: {e}")

    async def _handle_audit_health(self, query, chat_id: int, period: str = "7d") -> None:
        """Show system health audit for period."""
        try:
            audit_logger = getattr(self, "_audit_logger", None)
            if audit_logger is None:
                await self._reply_text(query, chat_id, "Audit logger not available.")
                return

            days = 7 if period == "7d" else 30
            start_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            starts = audit_logger.count_events(
                event_type="system_start", start_date=start_date,
            )
            stops = audit_logger.count_events(
                event_type="system_stop", start_date=start_date,
            )
            cb_trips = audit_logger.count_events(
                event_type="circuit_breaker_trip", start_date=start_date,
            )
            conn_drops = audit_logger.count_events(
                event_type="connection_drop", start_date=start_date,
            )
            errors = audit_logger.count_events(
                event_type="error_threshold", start_date=start_date,
            )

            msg = (
                f"🏥 *System Health ({period})*\n\n"
                f"Restarts: {starts} starts / {stops} stops\n"
                f"Circuit Breaker Trips: {cb_trips}\n"
                f"Connection Drops: {conn_drops}\n"
                f"Error Thresholds: {errors}"
            )
            await self._reply_text(query, chat_id, msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit health error: {e}")
            await self._reply_text(query, chat_id, f"Error: {e}")

    async def _handle_audit_reconcile(self, query, chat_id: int) -> None:
        """Show latest reconciliation report."""
        try:
            audit_logger = getattr(self, "_audit_logger", None)
            if audit_logger is None:
                await self._reply_text(query, chat_id, "Audit logger not available.")
                return

            results = audit_logger.query_reconciliation(limit=5)
            if not results:
                await self._reply_text(query, chat_id, "No reconciliation data yet.")
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
            await self._reply_text(query, chat_id, msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Audit reconcile error: {e}")
            await self._reply_text(query, chat_id, f"Error: {e}")

    # Helper methods that the main command handler should provide:
    # - _edit_or_send(query, chat_id, text, reply_markup, parse_mode)
    # - _reply_text(query, chat_id, text, parse_mode)
