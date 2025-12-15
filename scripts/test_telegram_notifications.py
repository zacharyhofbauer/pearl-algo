#!/usr/bin/env python3
"""
Test Telegram Notifications

Quick test script to verify all Telegram notification types work correctly.
Tests all notification types without running the full service.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Try to activate virtual environment if it exists
venv_activate = project_root / ".venv" / "bin" / "activate"
if venv_activate.exists():
    # Virtual environment exists, but we can't activate it in Python script
    # Instead, add it to Python path
    venv_site_packages = project_root / ".venv" / "lib" / "python3.12" / "site-packages"
    if venv_site_packages.exists():
        sys.path.insert(0, str(venv_site_packages))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier


async def test_all_notifications():
    """Test all notification types."""
    print("=" * 60)
    print("Telegram Notifications Test")
    print("=" * 60)
    print()
    
    # Get credentials
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("❌ ERROR: Telegram credentials not set")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False
    
    print(f"✓ Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
    print(f"✓ Chat ID: {chat_id}")
    print()
    
    # Create notifier
    notifier = NQAgentTelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        enabled=True,
    )
    
    if not notifier.enabled:
        print("❌ ERROR: Telegram notifier not enabled")
        return False
    
    print("✅ Telegram notifier initialized")
    print()
    
    # Test 1: Signal notification
    print("Test 1: Signal Notification...")
    signal = {
        "symbol": "NQ",
        "direction": "long",
        "entry_price": 15000.0,
        "stop_loss": 14900.0,
        "take_profit": 15200.0,
        "confidence": 0.75,
        "reason": "Test signal from notification test",
        "strategy": "nq_intraday",
        "type": "breakout",
    }
    result = await notifier.send_signal(signal)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 2: Heartbeat
    print("Test 2: Heartbeat Message...")
    status = {
        "running": True,
        "uptime": {"hours": 1, "minutes": 30},
        "cycle_count": 100,
        "signal_count": 5,
        "error_count": 0,
        "buffer_size": 56,
        "last_successful_cycle": datetime.now(timezone.utc).isoformat(),
    }
    result = await notifier.send_heartbeat(status)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 3: Enhanced Status
    print("Test 3: Enhanced Status Update...")
    status["performance"] = {
        "wins": 3,
        "losses": 2,
        "win_rate": 0.6,
        "total_pnl": 150.0,
        "avg_pnl": 30.0,
        "exited_signals": 5,
    }
    result = await notifier.send_enhanced_status(status)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 4: Data Quality Alert
    print("Test 4: Data Quality Alert (Stale Data)...")
    result = await notifier.send_data_quality_alert(
        "stale_data",
        "Data is 15.3 minutes old (test)",
        {"age_minutes": 15.3},
    )
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 5: Startup Notification
    print("Test 5: Startup Notification...")
    config = {
        "symbol": "NQ",
        "timeframe": "1m",
        "scan_interval": 60,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_risk_reward": 2.0,
        "max_risk_per_trade": 0.02,
    }
    result = await notifier.send_startup_notification(config)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 6: Daily Summary
    print("Test 6: Daily Performance Summary...")
    performance = {
        "total_pnl": 150.0,
        "wins": 5,
        "losses": 3,
        "win_rate": 0.625,
    }
    result = await notifier.send_daily_summary(performance)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 7: Weekly Summary
    print("Test 7: Weekly Performance Summary...")
    weekly_metrics = {
        "total_signals": 25,
        "exited_signals": 10,
        "wins": 6,
        "losses": 4,
        "win_rate": 0.6,
        "total_pnl": 300.0,
        "avg_pnl": 30.0,
        "avg_hold_minutes": 45.2,
    }
    result = await notifier.send_weekly_summary(weekly_metrics)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 8: Circuit Breaker Alert
    print("Test 8: Circuit Breaker Alert...")
    result = await notifier.send_circuit_breaker_alert(
        "Too many consecutive errors (test)",
        {
            "consecutive_errors": 10,
            "error_type": "data_fetch",
            "action_taken": "Service paused",
        },
    )
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 9: Recovery Notification
    print("Test 9: Recovery Notification...")
    result = await notifier.send_recovery_notification({
        "issue": "Consecutive errors resolved (test)",
        "recovery_time_seconds": 30,
    })
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    await asyncio.sleep(1)
    print()
    
    # Test 10: Shutdown Notification
    print("Test 10: Shutdown Notification...")
    summary = {
        "uptime_hours": 2,
        "uptime_minutes": 30,
        "cycle_count": 150,
        "signal_count": 8,
        "error_count": 1,
        "wins": 5,
        "losses": 3,
        "total_pnl": 200.0,
    }
    result = await notifier.send_shutdown_notification(summary)
    print(f"  {'✅ Sent' if result else '❌ Failed'}")
    print()
    
    print("=" * 60)
    print("✅ All notification tests completed!")
    print("=" * 60)
    print()
    print("Check your Telegram to verify all messages were received.")
    print()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_all_notifications())
    sys.exit(0 if success else 1)

