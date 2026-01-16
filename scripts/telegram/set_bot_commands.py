#!/usr/bin/env python3
"""
Set Telegram Bot Commands via BotFather API

This script sets up bot commands for the NQ Agent Telegram bot.
You can run this script to programmatically set commands, or set them manually via BotFather.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")
except ImportError:
    pass

try:
    from telegram import Bot, BotCommand
except ImportError:
    print("ERROR: python-telegram-bot not installed")
    print("Install it with: pip install python-telegram-bot")
    sys.exit(1)


def set_bot_commands():
    """Set bot commands via Telegram API."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found in environment")
        print("Please set it in your .env file or environment")
        sys.exit(1)
    
    bot = Bot(token=bot_token)
    
    # Menu-based command surface
    commands = [
        BotCommand('start', 'Show main control menu'),
        BotCommand('menu', 'Show main control menu'),
        BotCommand('help', 'Show help information'),
    ]
    
    try:
        bot.set_my_commands(commands)
        print("✅ Bot commands set successfully!")
        print("\nCommands available:")
        for cmd in commands:
            print(f"  /{cmd.command} - {cmd.description}")
    except Exception as e:
        print(f"❌ Error setting commands: {e}")
        sys.exit(1)


if __name__ == "__main__":
    set_bot_commands()



