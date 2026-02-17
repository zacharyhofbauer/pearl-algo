"""
PearlAlgo Telegram Bot -- Main Router

Thin UI layer that routes commands to the agent API via HTTP.
No direct access to agent state files or strategy code.

Usage:
    python -m pearlalgo.telegram.main

Environment:
    TELEGRAM_BOT_TOKEN  -- Bot token from @BotFather
    TELEGRAM_CHAT_ID    -- Authorized chat ID
    PEARLALGO_API_URL   -- Agent API URL (default: http://localhost:8001)
    PEARLALGO_API_KEY   -- API key for agent auth (optional)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from pearlalgo.telegram.utils import check_authorized

logger = logging.getLogger(__name__)

# Project root for .env loading
project_root = Path(__file__).parent.parent.parent.parent

# Load secrets
try:
    from dotenv import load_dotenv
    secrets_path = Path.home() / ".config" / "pearlalgo" / "secrets.env"
    if secrets_path.exists():
        load_dotenv(secrets_path, override=False)
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
except ImportError:
    pass


def _register_handlers(app) -> None:
    """Register all command and callback handlers."""
    from telegram.ext import CommandHandler, CallbackQueryHandler

    from pearlalgo.telegram.handlers.status import handle_status, handle_menu
    from pearlalgo.telegram.handlers.trading import (
        handle_start_agent,
        handle_stop_agent,
        handle_kill_switch,
        handle_kill_switch_confirm,
        handle_flatten,
        handle_flatten_confirm,
    )
    from pearlalgo.telegram.handlers.analytics import handle_trades, handle_performance
    from pearlalgo.telegram.handlers.config import handle_settings
    from pearlalgo.telegram.handlers.health import handle_health
    from pearlalgo.telegram.handlers.doctor import handle_doctor

    # Command handlers
    app.add_handler(CommandHandler("start", handle_menu))
    app.add_handler(CommandHandler("menu", handle_menu))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("trades", handle_trades))
    app.add_handler(CommandHandler("performance", handle_performance))
    app.add_handler(CommandHandler("settings", handle_settings))
    app.add_handler(CommandHandler("health", handle_health))
    app.add_handler(CommandHandler("doctor", handle_doctor))
    app.add_handler(CommandHandler("help", _handle_help))

    # Callback query handler for inline keyboard buttons
    app.add_handler(CallbackQueryHandler(_handle_callback))


async def _handle_help(update, context) -> None:
    """Handle /help -- show available commands."""
    msg = (
        "<b>PearlAlgo Commands</b>\n\n"
        "<b>Monitoring</b>\n"
        "/status — Balance, P&amp;L, positions, AI status\n"
        "/trades — Recent trade history\n"
        "/performance — Performance by period\n\n"
        "<b>Diagnostics</b>\n"
        "/health — System health, connectivity, data quality\n"
        "/doctor — Signal rejections, risk metrics, ML filter\n\n"
        "<b>Controls</b>\n"
        "/settings — Current configuration\n"
        "/menu — Main menu with buttons\n"
        "/help — This message"
    )
    await update.message.reply_html(msg)


async def _handle_callback(update, context) -> None:
    """Route inline keyboard callbacks to the appropriate handler."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()  # Acknowledge the callback

    data = query.data

    # Route callbacks
    from pearlalgo.telegram.handlers.status import handle_status, handle_menu
    from pearlalgo.telegram.handlers.trading import (
        handle_start_agent,
        handle_stop_agent,
        handle_kill_switch,
        handle_kill_switch_confirm,
        handle_flatten,
        handle_flatten_confirm,
    )
    from pearlalgo.telegram.handlers.analytics import handle_trades, handle_performance
    from pearlalgo.telegram.handlers.config import handle_settings
    from pearlalgo.telegram.handlers.health import handle_health
    from pearlalgo.telegram.handlers.doctor import handle_doctor

    routes = {
        "cmd:menu": handle_menu,
        "cmd:status": handle_status,
        "cmd:trades": handle_trades,
        "cmd:performance": handle_performance,
        "cmd:settings": handle_settings,
        "cmd:health": handle_health,
        "cmd:doctor": handle_doctor,
        "cmd:start": handle_start_agent,
        "cmd:stop": handle_stop_agent,
        "cmd:kill_switch": handle_kill_switch_confirm,
        "cmd:flatten": handle_flatten_confirm,
        "confirm:kill_switch": handle_kill_switch,
        "confirm:flatten_all": handle_flatten,
    }

    handler = routes.get(data)
    if handler:
        await handler(update, context)
    else:
        logger.warning(f"Unknown callback data: {data}")


def main() -> None:
    """Start the Telegram bot."""
    try:
        from telegram.ext import ApplicationBuilder
    except ImportError:
        print("python-telegram-bot not installed. Install with: pip install python-telegram-bot")
        sys.exit(1)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    api_url = os.getenv("PEARLALGO_API_URL", "http://localhost:8001")
    api_key = os.getenv("PEARLALGO_API_KEY", "")

    if not bot_token:
        print("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    if not chat_id:
        print("TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    logger.info(f"Starting PearlAlgo Telegram bot | api_url={api_url}")

    app = ApplicationBuilder().token(bot_token).build()

    # Store config in bot_data for handlers to access
    app.bot_data["api_url"] = api_url
    app.bot_data["api_key"] = api_key
    app.bot_data["chat_id"] = chat_id

    _register_handlers(app)

    logger.info("Telegram bot started, polling for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
