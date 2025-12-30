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
    
    # Define commands (grouped by category for better UX)
    commands = [
        # Service Control
        BotCommand('start_gateway', 'Start IBKR Gateway'),
        BotCommand('stop_gateway', 'Stop IBKR Gateway'),
        BotCommand('gateway_status', 'Check Gateway status'),
        BotCommand('start_agent', 'Start NQ Agent Service'),
        BotCommand('stop_agent', 'Stop NQ Agent Service'),
        BotCommand('restart_agent', 'Restart NQ Agent Service'),
        # Monitoring
        BotCommand('status', 'Get current agent status'),
        BotCommand('quick_status', 'Ultra-compact status'),
        BotCommand('activity', 'Is the bot doing anything?'),
        BotCommand('signals', 'Show recent signals'),
        BotCommand('last_signal', 'Show most recent signal with chart'),
        BotCommand('active_trades', 'Show currently open positions'),
        BotCommand('backtest', 'Run strategy backtest with chart'),
        BotCommand('test_signal', 'Generate test signal with chart'),
        BotCommand('performance', 'Show performance metrics'),
        BotCommand('data_quality', 'Check data freshness and quality'),
        BotCommand('config', 'Show key configuration values'),
        BotCommand('health', 'Check agent health status'),
        BotCommand('help', 'Show available commands'),
        # AI/LLM (requires [llm] extra)
        BotCommand('ai_patch', 'Generate code patch via Claude'),
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



