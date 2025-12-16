#!/usr/bin/env python3
"""
Strategy Validation Script

Quick validation to check if the NQ trading strategy is working correctly.
Tests multiple aspects: signal generation, data fetching, service health, etc.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy

# Import mock data provider - add project root to Python path first
import os
os.chdir(project_root)  # Change to project root so imports work
import sys
# Ensure project root is in path
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


def print_header(title):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def print_result(test_name, passed, details=None):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        for detail in details:
            print(f"      {detail}")


async def test_signal_generation():
    """Test 1: Signal generation with mock data."""
    print_header("Test 1: Signal Generation")
    
    try:
        # Create mock data provider with conditions that should generate signals
        # NOTE: Using realistic NQ price range (~17,500) but synthetic data for testing logic only
        mock_provider = MockDataProvider(
            base_price=17500.0,  # Realistic NQ futures price
            volatility=50.0,  # Higher volatility for signal generation
            trend=2.0,  # Strong uptrend
        )
        
        # Generate data
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)
        df = mock_provider.fetch_historical("NQ", start, end, "1m")
        latest_bar = await mock_provider.get_latest_bar("NQ")
        
        # Create strategy
        config = NQIntradayConfig(symbol="NQ", timeframe="1m")
        strategy = NQIntradayStrategy(config=config)
        
        # Generate signals
        market_data = {"df": df, "latest_bar": latest_bar}
        signals = strategy.analyze(market_data)
        
        passed = True
        details = [
            f"Generated {len(df)} bars of mock data",
            f"Latest price: ${latest_bar['close']:.2f}",
            f"Generated {len(signals)} signal(s)",
        ]
        
        if signals:
            signal = signals[0]
            details.extend([
                f"Signal type: {signal.get('type', 'unknown')}",
                f"Direction: {signal.get('direction', 'unknown')}",
                f"Confidence: {signal.get('confidence', 0):.0%}",
                f"Entry: ${signal.get('entry_price', 0):.2f}",
                f"Stop: ${signal.get('stop_loss', 0):.2f}",
                f"Target: ${signal.get('take_profit', 0):.2f}",
            ])
            
            # Validate signal quality
            entry = signal.get('entry_price', 0)
            stop = signal.get('stop_loss', 0)
            target = signal.get('take_profit', 0)
            confidence = signal.get('confidence', 0)
            
            if confidence < 0.50:
                passed = False
                details.append("⚠️  Confidence below 50% threshold")
            
            if entry > 0 and stop > 0 and target > 0:
                risk = entry - stop
                reward = target - entry
                if risk > 0:
                    rr_ratio = reward / risk
                    details.append(f"Risk/Reward: {rr_ratio:.2f}:1")
                    if rr_ratio < 1.5:
                        passed = False
                        details.append("⚠️  R:R ratio below 1.5:1 threshold")
        else:
            details.append("ℹ️  No signals generated (may be normal depending on conditions)")
        
        print_result("Signal Generation", passed, details)
        return passed
        
    except Exception as e:
        print_result("Signal Generation", False, [f"Error: {str(e)}"])
        return False


async def test_data_fetching():
    """Test 2: Data fetching with mock provider."""
    print_header("Test 2: Data Fetching")
    
    try:
        from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
        
        # NOTE: Using synthetic mock data - prices are not real market data
        mock_provider = MockDataProvider(
            base_price=17500.0,  # Realistic NQ futures price
            volatility=25.0,  # Realistic intraday volatility
            trend=0.5,
        )
        
        config = NQIntradayConfig(symbol="NQ", timeframe="1m")
        fetcher = NQAgentDataFetcher(mock_provider, config=config)
        
        market_data = await fetcher.fetch_latest_data()
        
        passed = True
        details = [
            f"Data fetched successfully",
            f"DataFrame size: {len(market_data.get('df', []))} bars",
            f"Latest bar: {'Available' if market_data.get('latest_bar') else 'Not available'}",
            f"Buffer size: {fetcher.get_buffer_size()} bars",
        ]
        
        if market_data.get("df") is None or market_data["df"].empty:
            passed = False
            details.append("⚠️  No data returned")
        
        print_result("Data Fetching", passed, details)
        return passed
        
    except Exception as e:
        print_result("Data Fetching", False, [f"Error: {str(e)}"])
        return False


async def test_service_initialization():
    """Test 3: Service initialization."""
    print_header("Test 3: Service Initialization")
    
    try:
        # NOTE: Using synthetic mock data - prices are not real market data
        mock_provider = MockDataProvider(
            base_price=17500.0,  # Realistic NQ futures price
            volatility=25.0,  # Realistic intraday volatility
            trend=0.5,
        )
        
        config = NQIntradayConfig(symbol="NQ", timeframe="1m", scan_interval=60)
        
        service = NQAgentService(
            data_provider=mock_provider,
            config=config,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        )
        
        passed = True
        details = [
            "Service initialized successfully",
            f"Symbol: {service.config.symbol}",
            f"Timeframe: {service.config.timeframe}",
            f"Scan interval: {service.config.scan_interval}s",
            f"Telegram enabled: {service.telegram_notifier.enabled}",
        ]
        
        # Get status
        status = service.get_status()
        details.extend([
            f"Running: {status.get('running', False)}",
            f"Paused: {status.get('paused', False)}",
        ])
        
        print_result("Service Initialization", passed, details)
        return passed
        
    except Exception as e:
        print_result("Service Initialization", False, [f"Error: {str(e)}"])
        return False


async def test_connection_status():
    """Test 4: Check connection status (if using real provider)."""
    print_header("Test 4: Connection Status")
    
    try:
        # Check if IB Gateway is running (non-blocking check)
        import subprocess
        result = subprocess.run(
            ["pgrep", "-f", "java.*IBC|ibgateway"],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        gateway_running = result.returncode == 0
        
        if gateway_running:
            # Check if port is listening (quick check)
            port_check = subprocess.run(
                ["timeout", "1", "bash", "-c", "echo > /dev/tcp/127.0.0.1/4002"],
                capture_output=True,
                text=True
            )
            port_open = port_check.returncode == 0
            
            passed = port_open
            details = [
                f"IB Gateway: Running",
                f"Port 4002: {'Open' if port_open else 'Not accessible'}",
            ]
            
            if not port_open:
                details.append("⚠️  Check IB Gateway API settings (port 4002)")
                details.append("   Run: ./scripts/check_gateway_status.sh")
            else:
                details.append("✅ IB Gateway appears ready")
            
            print_result("Connection Status", passed, details)
            return passed
        else:
            details = [
                "IB Gateway: Not running",
                "⚠️  Start IB Gateway: ./scripts/start_ibgateway_ibc.sh",
                "ℹ️  Using mock data provider for other tests",
            ]
            print_result("Connection Status", False, details)
            return False
            
    except subprocess.TimeoutExpired:
        details = [
            "IB Gateway: Status check timed out",
            "ℹ️  Gateway may be running but slow to respond",
        ]
        print_result("Connection Status", False, details)
        return False
    except Exception as e:
        details = [
            f"Connection check error: {str(e)}",
            "ℹ️  Using mock data provider for other tests",
        ]
        print_result("Connection Status", False, details)
        return False


async def test_telegram_integration():
    """Test 5: Telegram integration."""
    print_header("Test 5: Telegram Integration")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        details = [
            "Telegram credentials not set",
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to test",
            "ℹ️  Notifications will be disabled",
        ]
        print_result("Telegram Integration", False, details)
        return False
    
    try:
        from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
        
        notifier = NQAgentTelegramNotifier(
            bot_token=bot_token,
            chat_id=chat_id,
        )
        
        passed = notifier.enabled and notifier.telegram is not None
        details = [
            f"Enabled: {notifier.enabled}",
            f"Initialized: {notifier.telegram is not None}",
        ]
        
        if passed:
            details.append("✅ Ready to send notifications")
        else:
            details.append("⚠️  Check bot token and chat ID")
        
        print_result("Telegram Integration", passed, details)
        return passed
        
    except Exception as e:
        print_result("Telegram Integration", False, [f"Error: {str(e)}"])
        return False


async def main():
    """Run all validation tests."""
    print_header("NQ Trading Strategy Validation")
    print("This script validates that your NQ trading strategy is working correctly.")
    print("It tests signal generation, data fetching, service initialization, and more.\n")
    
    results = []
    
    # Run tests
    results.append(await test_signal_generation())
    results.append(await test_data_fetching())
    results.append(await test_service_initialization())
    results.append(await test_connection_status())
    results.append(await test_telegram_integration())
    
    # Summary
    print_header("Validation Summary")
    
    passed_count = sum(results)
    total_count = len(results)
    
    print(f"Tests Passed: {passed_count}/{total_count}")
    print()
    
    if passed_count == total_count:
        print("✅ All tests passed! Strategy appears to be working correctly.")
    elif passed_count >= total_count - 1:
        print("⚠️  Most tests passed. Review failed tests above.")
    else:
        print("❌ Several tests failed. Review errors above and fix issues.")
    
    print()
    print("Next Steps:")
    print("  1. Fix any failed tests")
    print("  2. Run with live data: python3 scripts/test_nq_agent_with_mock.py")
    print("  3. Start service: ./scripts/start_nq_agent_service.sh")
    print("  4. Monitor: tail -f logs/nq_agent.log")
    print()
    
    return passed_count == total_count


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
