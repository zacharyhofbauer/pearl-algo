#!/usr/bin/env python3
"""
Test NQ Agent with Mock Data

⚠️ DEPRECATED: This script is deprecated. Use `python3 scripts/testing/test_all.py service` instead.

Runs the NQ agent service with mock data provider for testing without live market data.
Perfect for testing notifications, signal generation, and service behavior.

This script will be removed in a future version. Please use the unified test runner:
    python3 scripts/testing/test_all.py service
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
# Add project root first for tests module, then src for pearlalgo
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Try to activate virtual environment if it exists
venv_activate = project_root / ".venv" / "bin" / "activate"
if venv_activate.exists():
    # Virtual environment exists, add it to Python path
    venv_site_packages = project_root / ".venv" / "lib" / "python3.12" / "site-packages"
    if venv_site_packages.exists():
        sys.path.insert(0, str(venv_site_packages))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig

# Import mock data provider - ensure project root is in path
import os
os.chdir(project_root)  # Change to project root so imports work
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from tests.mock_data_provider import MockDataProvider
except ImportError:
    # Fallback: direct file import
    import importlib.util
    mock_provider_file = project_root / "tests" / "mock_data_provider.py"
    spec = importlib.util.spec_from_file_location("mock_data_provider", mock_provider_file)
    mock_data_provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock_data_provider)
    MockDataProvider = mock_data_provider.MockDataProvider


async def test_service_with_mock():
    """Test NQ agent service with mock data."""
    print("=" * 60)
    print("NQ Agent Test with Mock Data")
    print("=" * 60)
    print()
    
    # Get Telegram credentials
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not telegram_bot_token or not telegram_chat_id:
        print("⚠️  WARNING: Telegram credentials not set")
        print("   Notifications will be disabled")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to test notifications")
        print()
    
    # Create mock data provider
    # NOTE: This uses SYNTHETIC data - prices are fake and for testing logic only
    print("Creating mock data provider...")
    print("⚠️  NOTE: Using synthetic mock data - prices are NOT real market data")
    mock_provider = MockDataProvider(
        base_price=17500.0,  # Realistic NQ futures price (Dec 2024 range)
        volatility=25.0,  # Realistic intraday volatility
        trend=0.5,  # Slight uptrend
    )
    print("✅ Mock data provider created")
    print()
    
    # Create configuration
    print("Creating configuration...")
    config = NQIntradayConfig(
        symbol="NQ",
        timeframe="1m",
        scan_interval=5,  # Fast for testing (5 seconds)
    )
    print("✅ Configuration created")
    print()
    
    # Create service
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
    print()
    print("You should see:")
    print("  • Startup notification in Telegram")
    print("  • Heartbeat messages (every hour, but first one may come early)")
    print("  • Status updates (every 30 minutes)")
    print("  • Signal notifications (if signals are generated)")
    print()
    print("Press Ctrl+C to stop early")
    print()
    
    try:
        # Run for 2 minutes (120 seconds)
        # In real usage, service runs indefinitely
        start_task = asyncio.create_task(service.start())
        
        # Wait for 120 seconds or until interrupted
        try:
            await asyncio.wait_for(start_task, timeout=120.0)
        except asyncio.TimeoutError:
            print()
            print("=" * 60)
            print("Test completed (2 minutes elapsed)")
            print("=" * 60)
            print()
            print("Service statistics:")
            status = service.get_status()
            print(f"  Cycles: {status.get('cycle_count', 0)}")
            print(f"  Signals: {status.get('signal_count', 0)}")
            print(f"  Errors: {status.get('error_count', 0)}")
            print(f"  Buffer: {status.get('buffer_size', 0)} bars")
            print()
            
            # Stop service
            service.shutdown_requested = True
            await service.stop()
            
            print("✅ Service stopped")
            print()
            print("Check your Telegram for:")
            print("  • Startup notification")
            print("  • Any heartbeat/status messages")
            print("  • Signal notifications (if any generated)")
            print("  • Shutdown notification")
            
    except KeyboardInterrupt:
        print()
        print("=" * 60)
        print("Interrupted by user")
        print("=" * 60)
        service.shutdown_requested = True
        await service.stop()
        print("✅ Service stopped")


if __name__ == "__main__":
    asyncio.run(test_service_with_mock())

