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
from pearlalgo.telegram.utils import reply_html as _reply

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


