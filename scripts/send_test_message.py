#!/usr/bin/env python3
"""
Simple script to send a test message to Telegram.
Just sends "Hello from PearlAlgo!" to verify Telegram works.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pearlalgo.utils.telegram_alerts import TelegramAlerts


async def send_test_message():
    """Send a simple test message."""
    print("Sending test message to Telegram...")
    
    # Try to load from .env file directly
    env_file = project_root / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key.strip()] = value.strip()
    
    # Get credentials
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not found")
        print(f"   Checked: {env_file}")
        print("   Set it in your .env file: TELEGRAM_BOT_TOKEN=your_token")
        return False
    
    if not chat_id:
        print("❌ ERROR: TELEGRAM_CHAT_ID not found")
        print(f"   Checked: {env_file}")
        print("   Set it in your .env file: TELEGRAM_CHAT_ID=your_chat_id")
        return False
    
    print(f"✓ Found bot token: {bot_token[:10]}...{bot_token[-5:]}")
    print(f"✓ Found chat ID: {chat_id}")
    
    # Initialize Telegram
    telegram = TelegramAlerts(
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=True,
    )
    
    if not telegram.enabled:
        print("❌ ERROR: Telegram alerts not initialized")
        return False
    
    # Send simple message
    message = "Hello from PearlAlgo! 🚀\n\nThis is a test message to verify Telegram integration is working."
    
    try:
        success = await telegram.send_message(message)
        if success:
            print("✅ SUCCESS: Message sent!")
            print("   Check your Telegram chat")
            return True
        else:
            print("❌ FAILED: Could not send message")
            return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(send_test_message())
    sys.exit(0 if success else 1)

