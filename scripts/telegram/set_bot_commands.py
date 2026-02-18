#!/usr/bin/env python3
"""
Set Telegram Bot Commands via BotFather API.

Run once after changing commands to update the / menu in Telegram.
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

try:
    from dotenv import load_dotenv
    secrets_path = Path.home() / ".config" / "pearlalgo" / "secrets.env"
    if secrets_path.exists():
        load_dotenv(secrets_path, override=False)
    load_dotenv(project_root / ".env", override=False)
except ImportError:
    pass

try:
    from telegram import Bot, BotCommand
except ImportError:
    print("ERROR: python-telegram-bot not installed")
    sys.exit(1)


def set_bot_commands():
    """Set bot commands via Telegram API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found")
        sys.exit(1)

    bot = Bot(token=bot_token)

    commands = [
        BotCommand("start", "Main menu"),
        BotCommand("status", "Balance, P&L, positions"),
        BotCommand("stats", "Performance by period"),
        BotCommand("trades", "Recent trade history"),
        BotCommand("health", "System health & connectivity"),
        BotCommand("doctor", "Risk metrics & analytics"),
        BotCommand("signals", "Signal rejections & decisions"),
        BotCommand("settings", "Current configuration"),
        BotCommand("help", "Show all commands"),
    ]

    import asyncio

    async def _set():
        await bot.set_my_commands(commands)

    try:
        asyncio.run(_set())
        print("Bot commands updated!\n")
        for cmd in commands:
            print(f"  /{cmd.command} — {cmd.description}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    set_bot_commands()
