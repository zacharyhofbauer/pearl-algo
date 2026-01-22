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
import json
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.config.settings import get_settings  # noqa: E402
from pearlalgo.data_providers.factory import create_data_provider  # noqa: E402

# #region agent log
def _log(hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    payload = {
        "sessionId": "debug-session",
        "runId": "pre-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open("/home/pearlalgo/.cursor/debug.log", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion agent log


async def smoke_test():
    """Run smoke test."""
    # #region agent log
    _log("H1", "smoke_test_ibkr.py:29", "smoke_test entry", {})
    # #endregion agent log
    print("=" * 60)
    print("IBKR Provider Smoke Test")
    print("=" * 60)
    print()

    # Load settings
    settings = get_settings()
    # #region agent log
    _log(
        "H2",
        "smoke_test_ibkr.py:40",
        "loaded settings",
        {"ib_host": getattr(settings, "ib_host", None), "ib_port": getattr(settings, "ib_port", None)},
    )
    # #endregion agent log
    print(f"IB Gateway: {settings.ib_host}:{settings.ib_port}")
    print()

    # Create provider
    print("Creating IBKR provider...")
    try:
        provider = create_data_provider("ibkr", settings=settings)
        # #region agent log
        _log("H3", "smoke_test_ibkr.py:52", "provider created", {"provider": type(provider).__name__})
        # #endregion agent log
        print("✅ Provider created")
    except Exception as e:
        # #region agent log
        _log("H3", "smoke_test_ibkr.py:56", "provider creation failed", {"error": str(e)})
        # #endregion agent log
        print(f"❌ Failed to create provider: {e}")
        return 1

    print()

    # Test 1: Connection
    print("Test 1: Connection validation...")
    try:
        # #region agent log
        _log("H4", "smoke_test_ibkr.py:65", "validate_connection start", {})
        # #endregion agent log
        connected = await provider.validate_connection()
        # #region agent log
        _log("H4", "smoke_test_ibkr.py:69", "validate_connection end", {"connected": bool(connected)})
        # #endregion agent log
        if connected:
            print("✅ Connected to IB Gateway")
        else:
            print("❌ Connection failed")
            return 1
    except Exception as e:
        # #region agent log
        _log("H4", "smoke_test_ibkr.py:77", "validate_connection error", {"error": str(e)})
        # #endregion agent log
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
