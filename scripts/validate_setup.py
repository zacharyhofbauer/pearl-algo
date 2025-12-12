#!/usr/bin/env python3
"""
Standalone startup validation script.

Run this to validate your IBKR setup before starting the trading system.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from pearlalgo.config.settings import get_settings
from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.utils.startup_validation import StartupValidator


async def main():
    """Run startup validation."""
    print("=" * 60)
    print("PearlAlgo Startup Validation")
    print("=" * 60)
    print()

    # Load settings
    settings = get_settings()
    print(f"IB Gateway: {settings.ib_host}:{settings.ib_port}")
    print(f"Client ID: {settings.ib_data_client_id or settings.ib_client_id}")
    print()

    # Create data provider
    print("Creating IBKR data provider...")
    try:
        data_provider = create_data_provider("ibkr", settings=settings)
        print("✅ Data provider created")
    except Exception as e:
        print(f"❌ Failed to create data provider: {e}")
        return 1

    print()

    # Run validation
    validator = StartupValidator(data_provider)
    passed = await validator.validate_all(test_symbols=["SPY", "QQQ"])

    print()
    print("=" * 60)
    if passed:
        print("✅ All validation checks passed!")
        print("System is ready to start trading.")
        return 0
    else:
        print("❌ Some validation checks failed.")
        print("Please fix the issues above before starting trading.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
