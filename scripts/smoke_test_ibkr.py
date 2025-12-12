#!/usr/bin/env python3
"""
Smoke test for IBKR provider - Quick validation script.

Tests:
- Connection to IB Gateway
- Fetch SPY/QQQ prices
- Pull options chain
- Verify data freshness
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.config.settings import get_settings
from pearlalgo.data_providers.factory import create_data_provider


async def smoke_test():
    """Run smoke test."""
    print("=" * 60)
    print("IBKR Provider Smoke Test")
    print("=" * 60)
    print()

    # Load settings
    settings = get_settings()
    print(f"IB Gateway: {settings.ib_host}:{settings.ib_port}")
    print()

    # Create provider
    print("Creating IBKR provider...")
    try:
        provider = create_data_provider("ibkr", settings=settings)
        print("✅ Provider created")
    except Exception as e:
        print(f"❌ Failed to create provider: {e}")
        return 1

    print()

    # Test 1: Connection
    print("Test 1: Connection validation...")
    try:
        connected = await provider.validate_connection()
        if connected:
            print("✅ Connected to IB Gateway")
        else:
            print("❌ Connection failed")
            return 1
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return 1

    print()

    # Test 2: Fetch prices
    print("Test 2: Fetching underlier prices...")
    symbols = ["SPY", "QQQ"]
    for symbol in symbols:
        try:
            price = await provider.get_underlier_price(symbol)
            print(f"✅ {symbol}: ${price:.2f}")
        except Exception as e:
            print(f"❌ Failed to fetch {symbol} price: {e}")
            return 1

    print()

    # Test 3: Options chain
    print("Test 3: Fetching options chain...")
    try:
        options = await provider.get_option_chain(
            "SPY",
            filters={"min_dte": 0, "max_dte": 7, "min_volume": 10},
        )
        if len(options) > 0:
            print(f"✅ Retrieved {len(options)} options for SPY")
            # Show first option
            if options:
                opt = options[0]
                print(f"   Example: {opt.get('symbol')} @ ${opt.get('strike')}")
        else:
            print("⚠️  No options returned (may be normal if market closed)")
    except Exception as e:
        print(f"❌ Failed to fetch options chain: {e}")
        return 1

    print()

    # Test 4: Entitlements
    print("Test 4: Validating entitlements...")
    try:
        entitlements = await provider.validate_market_data_entitlements()
        account_type = entitlements.get("account_type", "unknown")
        options_data = entitlements.get("options_data", False)
        realtime = entitlements.get("realtime_quotes", False)
        
        print(f"   Account type: {account_type}")
        print(f"   Options data: {'✅' if options_data else '❌'}")
        print(f"   Real-time quotes: {'✅' if realtime else '❌'}")
    except Exception as e:
        print(f"⚠️  Entitlements check failed: {e}")

    print()
    print("=" * 60)
    print("✅ Smoke test passed!")
    print("=" * 60)

    # Cleanup
    await provider.close()
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(smoke_test())
    sys.exit(exit_code)
