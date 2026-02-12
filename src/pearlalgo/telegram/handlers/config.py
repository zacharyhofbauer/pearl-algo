"""
Config handler: view current configuration.
"""

from __future__ import annotations

import logging
from typing import Any

from pearlalgo.telegram.formatters.messages import format_error_message
from pearlalgo.telegram.formatters.keyboards import back_to_menu_keyboard
from pearlalgo.telegram.utils import escape_html, safe_send

logger = logging.getLogger(__name__)


async def handle_settings(update: Any, context: Any) -> None:
    """Handle /settings command -- show current config summary."""
    try:
        api_url = context.bot_data.get("api_url", "http://localhost:8001")
        api_key = context.bot_data.get("api_key", "")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{api_url}/api/state",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    await _reply(update, format_error_message(f"Agent returned {resp.status}"))
                    return
                data = await resp.json()

        config = data.get("config", {})
        execution = config.get("execution", {})
        strategy = config.get("strategy", {})

        lines = [
            "<b>Agent Configuration</b>\n",
            f"<b>Symbol:</b> {escape_html(str(data.get('symbol', 'MNQ')))}",
            f"<b>Timeframe:</b> {escape_html(str(data.get('timeframe', '1m')))}",
            f"<b>Agent State:</b> {escape_html(str(data.get('agent_state', '?')))}",
            "",
            "<b>Execution:</b>",
            f"  Adapter: {escape_html(str(execution.get('adapter', '?')))}",
            f"  Enabled: {execution.get('enabled', False)}",
            f"  Armed: {execution.get('armed', False)}",
            f"  Mode: {escape_html(str(execution.get('mode', '?')))}",
            "",
            "<b>Strategy:</b>",
            f"  Signals: {escape_html(', '.join(strategy.get('enabled_signals', [])))}",
            f"  Min Confidence: {config.get('signals', {}).get('min_confidence', '?')}",
        ]

        keyboard = back_to_menu_keyboard()
        await _reply(update, "\n".join(lines), reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Settings handler error: {e}", exc_info=True)
        await _reply(update, format_error_message(f"Unable to fetch config: {e}"))


async def _reply(update: Any, text: str, **kwargs) -> None:
    """Send a reply."""
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
