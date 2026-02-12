"""
Trading handler: start/stop, kill switch, flatten positions.

Sends control commands to the agent API via POST /control.
Dangerous actions (kill switch, flatten) require confirmation.
"""

from __future__ import annotations

import logging
from typing import Any

from pearlalgo.telegram.formatters.messages import (
    format_control_response,
    format_error_message,
)
from pearlalgo.telegram.formatters.keyboards import (
    confirm_keyboard,
    back_to_menu_keyboard,
)
from pearlalgo.telegram.utils import safe_send

logger = logging.getLogger(__name__)


async def handle_start_agent(update: Any, context: Any) -> None:
    """Start the trading agent."""
    await _send_control(update, context, "start")


async def handle_stop_agent(update: Any, context: Any) -> None:
    """Stop the trading agent."""
    await _send_control(update, context, "stop")


async def handle_kill_switch_confirm(update: Any, context: Any) -> None:
    """Show kill switch confirmation dialog."""
    msg = (
        "🚨 <b>Kill Switch</b>\n\n"
        "This will immediately stop the agent and cancel all open orders.\n"
        "Are you sure?"
    )
    keyboard = confirm_keyboard("kill_switch")
    await _reply(update, msg, reply_markup=keyboard)


async def handle_kill_switch(update: Any, context: Any) -> None:
    """Execute kill switch after confirmation."""
    await _send_control(update, context, "kill_switch")


async def handle_flatten_confirm(update: Any, context: Any) -> None:
    """Show flatten all positions confirmation dialog."""
    msg = (
        "📋 <b>Flatten All Positions</b>\n\n"
        "This will close all open positions at market.\n"
        "Are you sure?"
    )
    keyboard = confirm_keyboard("flatten_all")
    await _reply(update, msg, reply_markup=keyboard)


async def handle_flatten(update: Any, context: Any) -> None:
    """Execute flatten all after confirmation."""
    await _send_control(update, context, "flatten_all")


async def _send_control(update: Any, context: Any, action: str) -> None:
    """Send a control command to the agent API."""
    try:
        api_url = context.bot_data.get("api_url", "http://localhost:8001")
        api_key = context.bot_data.get("api_key", "")

        import aiohttp
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        payload = {"action": action}

        async with aiohttp.ClientSession() as session:
            # Try the new /control endpoint first, fall back to specific endpoints
            async with session.post(
                f"{api_url}/api/kill-switch" if action == "kill_switch"
                else f"{api_url}/api/close-all-trades" if action == "flatten_all"
                else f"{api_url}/api/control",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 202):
                    data = await resp.json()
                    detail = data.get("detail", data.get("message", ""))
                    msg = format_control_response(action, True, str(detail))
                else:
                    text = await resp.text()
                    msg = format_control_response(action, False, f"HTTP {resp.status}: {text[:200]}")

        keyboard = back_to_menu_keyboard()
        await _reply(update, msg, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Control handler error ({action}): {e}", exc_info=True)
        await _reply(update, format_error_message(f"Control command failed: {e}"))


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
