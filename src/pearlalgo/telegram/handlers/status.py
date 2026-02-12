"""
Status handler: agent status, P&L, open positions.

All data is fetched from the agent's API server via HTTP.
"""

from __future__ import annotations

import logging
from typing import Any

from pearlalgo.telegram.formatters.messages import (
    format_status_message,
    format_error_message,
)
from pearlalgo.telegram.formatters.keyboards import (
    back_to_menu_keyboard,
    main_menu_keyboard,
)
from pearlalgo.telegram.utils import safe_send

logger = logging.getLogger(__name__)


async def handle_status(update: Any, context: Any) -> None:
    """Handle /status command -- show agent state, P&L, positions."""
    try:
        api_url = context.bot_data.get("api_url", "http://localhost:8001")
        api_key = context.bot_data.get("api_key", "")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_url}/api/state", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    await _reply(update, format_error_message(f"Agent returned {resp.status}: {text[:200]}"))
                    return
                data = await resp.json()

        msg = format_status_message(data)
        agent_state = data.get("agent_state", "unknown")
        keyboard = main_menu_keyboard(agent_state)

        await _reply(update, msg, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Status handler error: {e}", exc_info=True)
        await _reply(update, format_error_message(f"Unable to reach agent: {e}"))


async def handle_menu(update: Any, context: Any) -> None:
    """Handle /menu or /start -- show the main menu."""
    msg = "📊 <b>PearlAlgo</b> — What would you like to do?"
    keyboard = main_menu_keyboard()
    await _reply(update, msg, reply_markup=keyboard)


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
                    # Fall back to sending a new message
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
