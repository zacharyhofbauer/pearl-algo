#!/usr/bin/env python3
"""
Test Signal Generation with Mock Data

⚠️ DEPRECATED: This script is deprecated. Use `python3 scripts/testing/test_all.py signals` instead.

Tests signal generation logic with mock data to verify strategy works correctly.

This script will be removed in a future version. Please use the unified test runner:
    python3 scripts/testing/test_all.py signals
"""

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

import pandas as pd

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.strategy import NQIntradayStrategy

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


def test_signal_generation():
    """Test signal generation with mock data."""
    print("=" * 60)
    print("Signal Generation Test with Mock Data")
    print("=" * 60)
    print()
    
    # Create mock data provider
    # NOTE: This uses SYNTHETIC data - prices are fake and for testing logic only
    print("Creating mock data provider...")
    print("⚠️  NOTE: Using synthetic mock data - prices are NOT real market data")
    mock_provider = MockDataProvider(
        base_price=17500.0,  # Realistic NQ futures price (Dec 2024 range)
        volatility=50.0,  # Higher volatility for signal generation
        trend=1.0,  # Uptrend to potentially generate signals
    )
    print("✅ Mock data provider created")
    print()
    
    # Generate historical data
    print("Generating historical data...")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    
    df = mock_provider.fetch_historical("NQ", start, end, "1m")
    print(f"✅ Generated {len(df)} bars")
    print()
    
    # Get latest bar
    import asyncio
    latest_bar = asyncio.run(mock_provider.get_latest_bar("NQ"))
    print(f"✅ Latest bar: ${latest_bar['close']:.2f}")
    print()
    
    # Create strategy
    print("Creating strategy...")
    config = NQIntradayConfig(
        symbol="NQ",
        timeframe="1m",
    )
    strategy = NQIntradayStrategy(config=config)
    print("✅ Strategy created")
    print()
    
    # Prepare market data
    market_data = {
        "df": df,
        "latest_bar": latest_bar,
    }
    
    # Generate signals
    print("Generating signals...")
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
            if signal.get('reason'):
                print(f"    Reason: {signal.get('reason')[:100]}")
    else:
        print("⚠️  No signals generated")
        print("   This may be normal - signals require specific market conditions")
        print("   Try adjusting the mock data provider parameters:")
        print("     - Increase volatility")
        print("     - Add stronger trend")
        print("     - Generate more historical data")
    
    print()
    print("=" * 60)
    print("✅ Signal generation test completed")
    print("=" * 60)


if __name__ == "__main__":
    test_signal_generation()

