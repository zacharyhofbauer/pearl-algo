#!/usr/bin/env python3
# ============================================================================
# Category: Testing
# Purpose: Unified test runner for NQ Agent (combines multiple test scripts)
# Usage: python3 scripts/testing/test_all.py [mode]
# Modes: all (default), telegram, signals, service
# ============================================================================
"""
Unified Test Runner for NQ Agent

Combines functionality from:
- test_telegram_notifications.py
- test_signal_generation.py
- test_nq_agent_with_mock.py

Usage:
    python3 scripts/testing/test_all.py [mode]
    
Modes:
    all          - Run all tests (default)
    telegram     - Test Telegram notifications only
    signals      - Test signal generation only
    service      - Test full service with mock data
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Try to activate virtual environment if it exists
venv_activate = project_root / ".venv" / "bin" / "activate"
if venv_activate.exists():
    venv_site_packages = project_root / ".venv" / "lib" / "python3.12" / "site-packages"
    if venv_site_packages.exists():
        sys.path.insert(0, str(venv_site_packages))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import mock data provider
os.chdir(project_root)
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from tests.mock_data_provider import MockDataProvider
except ImportError:
    import importlib.util
    mock_provider_file = project_root / "tests" / "mock_data_provider.py"
    spec = importlib.util.spec_from_file_location("mock_data_provider", mock_provider_file)
    mock_data_provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock_data_provider)
    MockDataProvider = mock_data_provider.MockDataProvider

from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy
from pearlalgo.utils.logging_config import setup_logging


async def test_telegram_notifications():
    """Test all Telegram notification types."""
    print("=" * 60)
    print("Telegram Notifications Test")
    print("=" * 60)
    print()
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("❌ ERROR: Telegram credentials not set")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False
    
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
    
    # Test all notification types
    tests = [
        ("Signal", lambda: notifier.send_signal({
            "symbol": "MNQ", "direction": "long", "entry_price": 17500.0,
            "stop_loss": 17450.0, "take_profit": 17600.0, "confidence": 0.75,
            "reason": "Test signal", "strategy": "nq_intraday", "type": "breakout",
        })),
        ("Heartbeat", lambda: notifier.send_heartbeat({
            "running": True, "uptime": {"hours": 1, "minutes": 30},
            "cycle_count": 100, "signal_count": 5, "error_count": 0,
            "buffer_size": 56, "last_successful_cycle": datetime.now(timezone.utc).isoformat(),
        })),
        ("Enhanced Status", lambda: notifier.send_enhanced_status({
            "running": True, "uptime": {"hours": 1, "minutes": 30},
            "cycle_count": 100, "signal_count": 5, "error_count": 0,
            "buffer_size": 56, "performance": {"wins": 3, "losses": 2, "win_rate": 0.6},
        })),
        ("Data Quality Alert", lambda: notifier.send_data_quality_alert(
            "stale_data", "Data is 15.3 minutes old (test)", {"age_minutes": 15.3}
        )),
        ("Startup", lambda: notifier.send_startup_notification({
            "symbol": "MNQ", "timeframe": "1m", "scan_interval": 30,
        })),
        ("Daily Summary", lambda: notifier.send_daily_summary({
            "total_pnl": 150.0, "wins": 5, "losses": 3, "win_rate": 0.625,
        })),
        ("Weekly Summary", lambda: notifier.send_weekly_summary({
            "total_signals": 25, "exited_signals": 10, "wins": 6, "losses": 4,
            "win_rate": 0.6, "total_pnl": 300.0, "avg_pnl": 30.0, "avg_hold_minutes": 45.2,
        })),
        ("Circuit Breaker", lambda: notifier.send_circuit_breaker_alert(
            "Too many consecutive errors (test)", {"consecutive_errors": 10}
        )),
        ("Recovery", lambda: notifier.send_recovery_notification({
            "issue": "Consecutive errors resolved (test)", "recovery_time_seconds": 30,
        })),
        ("Shutdown", lambda: notifier.send_shutdown_notification({
            "uptime_hours": 2, "uptime_minutes": 30, "cycle_count": 150,
            "signal_count": 8, "error_count": 1,
        })),
    ]
    
    for name, test_func in tests:
        print(f"Test: {name}...", end=" ")
        try:
            result = await test_func()
            print("✅" if result else "❌")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print()
    print("=" * 60)
    print("✅ Telegram notification tests completed!")
    print("=" * 60)
    return True


async def test_signal_generation():
    """Test signal generation with mock data."""
    print("=" * 60)
    print("Signal Generation Test with Mock Data")
    print("=" * 60)
    print()
    
    print("Creating mock data provider...")
    print("⚠️  NOTE: Using synthetic mock data - prices are NOT real market data")
    mock_provider = MockDataProvider(
        base_price=17500.0,
        volatility=50.0,
        trend=1.0,
        simulate_timeouts=False,  # Disable for testing
        simulate_connection_issues=False,  # Disable for testing
    )
    print("✅ Mock data provider created")
    print()
    
    print("Generating historical data...")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    df = mock_provider.fetch_historical("MNQ", start, end, "1m")
    print(f"✅ Generated {len(df)} bars")
    
    # Get latest bar - use await since we're in async context
    latest_bar = await mock_provider.get_latest_bar("MNQ")
    print(f"✅ Latest bar: ${latest_bar['close']:.2f}")
    print()
    
    print("Creating strategy...")
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m")
    strategy = NQIntradayStrategy(config=config)
    print("✅ Strategy created")
    print()
    
    print("Generating signals...")
    market_data = {"df": df, "latest_bar": latest_bar}
    signals = strategy.analyze(market_data)
    print(f"✅ Generated {len(signals)} signal(s)")
    print()
    
    if signals:
        print("Signal Details:")
        for i, signal in enumerate(signals, 1):
            print(f"\n  Signal {i}:")
            print(f"    Type: {signal.get('type', 'unknown')}")
            print(f"    Direction: {signal.get('direction', 'unknown')}")
            print(f"    Entry: ${signal.get('entry_price', 0):.2f}")
            print(f"    Stop Loss: ${signal.get('stop_loss', 0):.2f}")
            print(f"    Take Profit: ${signal.get('take_profit', 0):.2f}")
            print(f"    Confidence: {signal.get('confidence', 0):.0%}")
    else:
        print("⚠️  No signals generated (may be normal - requires specific conditions)")
    
    print()
    print("=" * 60)
    print("✅ Signal generation test completed")
    print("=" * 60)
    return True


async def test_service_with_mock():
    """Test NQ agent service with mock data."""
    print("=" * 60)
    print("NQ Agent Test with Mock Data")
    print("=" * 60)
    print()
    
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not telegram_bot_token or not telegram_chat_id:
        print("⚠️  WARNING: Telegram credentials not set")
        print("   Notifications will be disabled")
        print()
    
    print("Creating mock data provider...")
    print("⚠️  NOTE: Using synthetic mock data - prices are NOT real market data")
    mock_provider = MockDataProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=0.5,
    )
    print("✅ Mock data provider created")
    print()
    
    print("Creating configuration...")
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m", scan_interval=5)
    print("✅ Configuration created")
    print()
    
    print("Creating NQ agent service...")
    service = NQAgentService(
        data_provider=mock_provider,
        config=config,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
    print("✅ Service created")
    print()
    
    print("=" * 60)
    print("Starting service (will run for 2 minutes for testing)...")
    print("=" * 60)
    print("Press Ctrl+C to stop early")
    print()
    
    try:
        start_task = asyncio.create_task(service.start())
        try:
            await asyncio.wait_for(start_task, timeout=120.0)
        except asyncio.TimeoutError:
            print()
            print("=" * 60)
            print("Test completed (2 minutes elapsed)")
            print("=" * 60)
            status = service.get_status()
            print(f"  Cycles: {status.get('cycle_count', 0)}")
            print(f"  Signals: {status.get('signal_count', 0)}")
            print(f"  Errors: {status.get('error_count', 0)}")
            print()
            service.shutdown_requested = True
            await service.stop()
            print("✅ Service stopped")
    except KeyboardInterrupt:
        print()
        print("Interrupted by user")
        service.shutdown_requested = True
        await service.stop()
        print("✅ Service stopped")
    
    return True


async def main():
    """Main entry point."""
    # Setup logging for consistent console output (matches production)
    setup_logging(level="INFO")
    
    parser = argparse.ArgumentParser(description="Unified test runner for NQ Agent")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["all", "telegram", "signals", "service"],
        help="Test mode to run (default: all)",
    )
    args = parser.parse_args()
    
    print()
    print("=" * 60)
    print("NQ Agent Test Suite")
    print("=" * 60)
    print()
    
    results = {}
    
    if args.mode in ["all", "telegram"]:
        print("\n" + "=" * 60)
        results["telegram"] = await test_telegram_notifications()
        print()
    
    if args.mode in ["all", "signals"]:
        print("\n" + "=" * 60)
        results["signals"] = await test_signal_generation()
        print()
    
    if args.mode in ["all", "service"]:
        print("\n" + "=" * 60)
        results["service"] = await test_service_with_mock()
        print()
    
    print()
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {test_name:15} {status}")
    print("=" * 60)
    print()
    
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())



