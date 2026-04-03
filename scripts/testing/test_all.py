#!/usr/bin/env python3
# ============================================================================
# Category: Testing
# Purpose: Unified test runner for Market Agent (canonical entry point)
# Usage: python3 scripts/testing/test_all.py [mode]
# Modes: all (default), signals, service, arch
# ============================================================================
"""
Unified Test Runner for Market Agent

Runs the canonical test/validation modes for this repo:
- Strategy signal generation with the mock provider
- Short-run service lifecycle with the mock provider
- Architecture boundary enforcement

Usage:
    python3 scripts/testing/test_all.py [mode]
    
Modes:
    all          - Run all tests (default)
    signals      - Test signal generation only
    service      - Test full service with mock data
    arch         - Test module boundary rules

Environment:
    PEARLALGO_ARCH_ENFORCE=1  - Make architecture check fail on violations
                               (default: warn-only)
"""

import argparse
import asyncio
import os
import subprocess
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

from pearlalgo.market_agent.service import MarketAgentService  # noqa: E402
from pearlalgo.strategies import create_strategy, get_strategy_defaults  # noqa: E402
from pearlalgo.utils.logging_config import setup_logging  # noqa: E402


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
    config = get_strategy_defaults()
    config["symbol"] = "MNQ"
    config["timeframe"] = "1m"
    strategy = create_strategy(config)
    print("✅ Strategy created")
    print()
    
    print("Generating signals...")
    signals = strategy.analyze(df)
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
    """Test Market Agent service with mock data."""
    print("=" * 60)
    print("Market Agent Test with Mock Data")
    print("=" * 60)
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
    config = get_strategy_defaults()
    config["symbol"] = "MNQ"
    config["timeframe"] = "1m"
    print("✅ Configuration created")
    print()
    
    print("Creating NQ agent service...")
    service = MarketAgentService(
        data_provider=mock_provider,
        config=config,
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


def test_architecture_boundaries() -> bool:
    """
    Test module boundary rules using the AST-based boundary checker.
    
    By default, runs in warn-only mode (violations are reported but don't fail).
    Set PEARLALGO_ARCH_ENFORCE=1 to make violations fail the test.
    
    Returns:
        True if no violations (or warn-only mode), False if violations in enforce mode.
    """
    print("=" * 60)
    print("Architecture Boundary Check")
    print("=" * 60)
    print()
    
    # Determine enforcement mode from environment
    enforce = os.getenv("PEARLALGO_ARCH_ENFORCE", "").lower() in ("1", "true", "yes")
    
    if enforce:
        print("Mode: ENFORCE (violations will fail the test)")
    else:
        print("Mode: WARN-ONLY (violations are reported but don't fail)")
        print("      Set PEARLALGO_ARCH_ENFORCE=1 to enable strict mode")
    print()
    
    # Build command
    checker_script = project_root / "scripts" / "testing" / "check_architecture_boundaries.py"
    
    if not checker_script.exists():
        print(f"❌ ERROR: Boundary checker not found at {checker_script}")
        return False
    
    cmd = [sys.executable, str(checker_script)]
    if enforce:
        cmd.append("--enforce")
    
    # Run the checker
    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=False,  # Let output flow to stdout/stderr
        )
        
        if result.returncode == 0:
            print()
            print("=" * 60)
            print("✅ Architecture boundary check passed")
            print("=" * 60)
            return True
        else:
            print()
            print("=" * 60)
            if enforce:
                print("❌ Architecture boundary check FAILED")
            else:
                print("⚠️  Architecture boundary check found issues (warn-only)")
            print("=" * 60)
            # In warn-only mode, we still return True (don't fail the test suite)
            return not enforce
            
    except Exception as e:
        print(f"❌ ERROR running boundary checker: {e}")
        return False


async def main():
    """Main entry point."""
    # Setup logging for consistent console output (matches production)
    setup_logging(level="INFO")
    
    parser = argparse.ArgumentParser(description="Unified test runner for Market Agent")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["all", "signals", "service", "arch"],
        help="Test mode to run (default: all)",
    )
    args = parser.parse_args()
    
    print()
    print("=" * 60)
    print("Market Agent Test Suite")
    print("=" * 60)
    print()
    
    results = {}
    
    if args.mode in ["all", "signals"]:
        print("\n" + "=" * 60)
        results["signals"] = await test_signal_generation()
        print()
    
    if args.mode in ["all", "service"]:
        print("\n" + "=" * 60)
        results["service"] = await test_service_with_mock()
        print()
    
    if args.mode in ["all", "arch"]:
        print("\n" + "=" * 60)
        results["arch"] = test_architecture_boundaries()
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




