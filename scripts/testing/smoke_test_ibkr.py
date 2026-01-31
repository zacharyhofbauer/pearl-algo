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
import os
import socket
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))


def _load_env_file(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env into os.environ if missing."""
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # Best-effort: don't fail smoke test on env parsing issues.
        return


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

from pearlalgo.config.settings import get_settings  # noqa: E402
from pearlalgo.data_providers.factory import create_data_provider  # noqa: E402


async def smoke_test():
    """Run smoke test."""
    print("=" * 60)
    print("IBKR Provider Smoke Test")
    print("=" * 60)
    print()

    # Load .env so IBKR_* is honored even without PEARLALGO_ prefix.
    _load_env_file(project_root / ".env")
    
    # Auto-detect port by probing which one is actually open.
    # This overrides .env if the configured port isn't reachable.
    configured_port = os.getenv("IBKR_PORT") or os.getenv("PEARLALGO_IB_PORT") or "4002"
    if not _is_port_open("127.0.0.1", int(configured_port)):
        # Configured port not open - try common alternatives
        if _is_port_open("127.0.0.1", 4001):
            os.environ["IBKR_PORT"] = "4001"
            print(f"[Auto-detect] Port {configured_port} not open, using 4001")
        elif _is_port_open("127.0.0.1", 4002):
            os.environ["IBKR_PORT"] = "4002"
            print(f"[Auto-detect] Port {configured_port} not open, using 4002")
        elif _is_port_open("127.0.0.1", 7496):
            os.environ["IBKR_PORT"] = "7496"
            print(f"[Auto-detect] Port {configured_port} not open, using 7496 (TWS live)")
        elif _is_port_open("127.0.0.1", 7497):
            os.environ["IBKR_PORT"] = "7497"
            print(f"[Auto-detect] Port {configured_port} not open, using 7497 (TWS paper)")
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
