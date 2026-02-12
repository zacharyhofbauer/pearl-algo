"""
Analytics handler: performance stats, recent trades.

Fetches data from the agent API and formats for display.
"""

from __future__ import annotations

import logging
from typing import Any

from pearlalgo.telegram.formatters.messages import (
    format_trades_message,
    format_pnl,
    format_win_rate,
    format_error_message,
)
from pearlalgo.telegram.formatters.keyboards import back_to_menu_keyboard
from pearlalgo.telegram.utils import escape_html, safe_send

logger = logging.getLogger(__name__)


async def handle_trades(update: Any, context: Any) -> None:
    """Handle /trades command -- show recent trade history."""
    try:
        api_url = context.bot_data.get("api_url", "http://localhost:8001")
        api_key = context.bot_data.get("api_key", "")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/api/trades",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    await _reply(update, format_error_message(f"Agent returned {resp.status}"))
                    return
                data = await resp.json()

        # data may be a list of trades or a dict with "trades" key
        trades = data if isinstance(data, list) else data.get("trades", [])
        msg = format_trades_message(trades, limit=20)
        keyboard = back_to_menu_keyboard()
        await _reply(update, msg, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Trades handler error: {e}", exc_info=True)
        await _reply(update, format_error_message(f"Unable to fetch trades: {e}"))


async def handle_performance(update: Any, context: Any) -> None:
    """Handle /performance command -- show performance summary."""
    try:
        api_url = context.bot_data.get("api_url", "http://localhost:8001")
        api_key = context.bot_data.get("api_key", "")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/api/performance-summary",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    await _reply(update, format_error_message(f"Agent returned {resp.status}"))
                    return
                data = await resp.json()

        total_pnl = data.get("total_pnl", 0.0)
        wins = data.get("wins", 0)
        losses = data.get("losses", 0)
        avg_pnl = data.get("avg_pnl", 0.0)
        total = data.get("exited_signals", wins + losses)

        lines = [
            "<b>Performance Summary</b>\n",
            f"<b>Total P&amp;L:</b> {format_pnl(total_pnl)}",
            f"<b>Trades:</b> {total}",
            f"<b>Win Rate:</b> {format_win_rate(wins, losses)}",
            f"<b>Avg P&amp;L:</b> {format_pnl(avg_pnl)}",
        ]

        # By signal type breakdown
        by_type = data.get("by_signal_type", {})
        if by_type:
            lines.append("\n<b>By Signal Type:</b>")
            for sig_type, metrics in by_type.items():
                t_pnl = metrics.get("total_pnl", 0)
                t_count = metrics.get("count", 0)
                t_wr = metrics.get("win_rate", 0)
                lines.append(
                    f"  {escape_html(sig_type)}: {format_pnl(t_pnl)} "
                    f"({t_count} trades, {t_wr:.0%} WR)"
                )

        keyboard = back_to_menu_keyboard()
        await _reply(update, "\n".join(lines), reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Performance handler error: {e}", exc_info=True)
        await _reply(update, format_error_message(f"Unable to fetch performance: {e}"))


async def _reply(update: Any, text: str, **kwargs) -> None:
    """Send a reply using either message.reply_html or callback_query.edit."""
    try:
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=text, parse_mode="HTML", **kwargs,
                )
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    if update.effective_chat:
                        await safe_send(
                            update.effective_chat.send_message,
                            text,
                            **kwargs,
                        )
        elif update.message:
            await safe_send(update.message.reply_html, text, **kwargs)
    except Exception as e:
        logger.error(f"Reply failed: {e}")
