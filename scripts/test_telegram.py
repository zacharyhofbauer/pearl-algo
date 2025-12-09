#!/usr/bin/env python3
"""
Test Telegram Bot Connection

Simple script to verify Telegram bot is configured correctly and can send messages.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from pearlalgo.utils.telegram_alerts import TelegramAlerts

# Load environment variables
load_dotenv()


async def test_telegram():
    """Test Telegram bot connection and send a test message."""
    print("=" * 60)
    print("Telegram Bot Connection Test")
    print("=" * 60)
    print()

    # Get credentials from environment
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not found in environment")
        print("   Please set it in your .env file")
        return False

    if not chat_id:
        print("❌ ERROR: TELEGRAM_CHAT_ID not found in environment")
        print("   Please set it in your .env file")
        return False

    print(f"✓ Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
    print(f"✓ Chat ID: {chat_id}")
    print()

    # Initialize Telegram alerts
    print("Initializing Telegram alerts...")
    try:
        telegram = TelegramAlerts(
            bot_token=bot_token,
            chat_id=chat_id,
            enabled=True,
        )

        if not telegram.enabled:
            print("❌ ERROR: Telegram alerts failed to initialize")
            print("   Check that python-telegram-bot is installed: pip install python-telegram-bot")
            return False

        print("✓ Telegram alerts initialized")
        print()

        # Send test message
        print("Sending test message...")
        test_message = (
            "🧪 *Telegram Bot Test*\n\n"
            "This is a test message from PearlAlgo trading system.\n"
            "If you receive this, your Telegram integration is working correctly!"
        )

        success = await telegram.send_message(test_message)
        if success:
            print("✅ SUCCESS: Test message sent!")
            print("   Check your Telegram chat to verify receipt")
            return True
        else:
            print("❌ ERROR: Failed to send test message")
            print("   Check your bot token and chat ID")
            return False

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main test function."""
    success = await test_telegram()
    print()
    if success:
        print("=" * 60)
        print("✅ Telegram test PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("=" * 60)
        print("❌ Telegram test FAILED")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
