#!/usr/bin/env python
"""
Debug IBKR Connection Script

Tests IBKR Gateway connection and provides troubleshooting information.
Use this to verify IBKR connectivity before trading.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.config.settings import get_settings
from pearlalgo.data_providers.ibkr_data_provider import IBKRDataProvider


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main() -> int:
    """Main function."""
    print_section("IBKR Connection Debug")
    
    try:
        settings = get_settings()
    except Exception as e:
        print(f"\n❌ ERROR: Failed to load settings: {e}")
        print("Run 'python scripts/debug_env.py' first to check configuration")
        return 1
    
    # Show configuration
    print_section("IBKR Configuration")
    print(f"  Host:        {settings.ib_host}")
    print(f"  Port:        {settings.ib_port}")
    print(f"  Client ID:   {settings.ib_client_id}")
    print(f"  Data Client ID: {settings.ib_data_client_id or '(auto)'}")
    print(f"  Profile:     {settings.profile}")
    print(f"  Dummy Mode:  {settings.dummy_mode}")
    
    # Check if dummy mode is enabled
    if settings.dummy_mode:
        print("\n⚠️  WARNING: Dummy mode is enabled.")
        print("   Connection test will be skipped.")
        print("   Set PEARLALGO_DUMMY_MODE=false to test real IBKR connection")
        return 0
    
    # Test connection
    print_section("Connection Test")
    print("Attempting to connect to IBKR Gateway...")
    print("(This may take a few seconds)")
    
    try:
        provider = IBKRDataProvider(settings=settings)
        # Try to connect
        ib = provider._connect()
        
        if ib.isConnected():
            actual_client_id = ib.client.clientId if hasattr(ib, 'client') and hasattr(ib.client, 'clientId') else 'unknown'
            print("\n✅ SUCCESS: Connected to IBKR Gateway!")
            print(f"   Connected to {settings.ib_host}:{settings.ib_port}")
            print(f"   Client ID: {actual_client_id}")
            
            # Try to disconnect
            try:
                ib.disconnect()
            except:
                pass
            
            return 0
        else:
            print("\n❌ ERROR: Connection established but not connected")
            return 1
            
    except RuntimeError as e:
        error_msg = str(e)
        print(f"\n❌ ERROR: {error_msg}")
        
        if "not available" in error_msg.lower():
            print("\nTroubleshooting:")
            print("  1. Is IB Gateway or TWS running?")
            print("  2. Is API enabled in Gateway/TWS settings?")
            print("  3. Check the port number (4002 for Gateway paper, 7497 for TWS paper)")
            print("  4. See IBKR_CONNECTION_FIXES.md for detailed help")
        elif "client id" in error_msg.lower() or "already in use" in error_msg.lower():
            print("\nTroubleshooting:")
            print("  1. Another connection is using the same client ID")
            print(f"  2. Try changing IBKR_CLIENT_ID in .env (current: {settings.ib_client_id})")
            print("  3. Close other IBKR connections")
            print("  4. See IBKR_CONNECTION_FIXES.md for detailed help")
        else:
            print("\nTroubleshooting:")
            print("  1. Check IBKR_CONNECTION_FIXES.md for help")
            print("  2. Run 'python scripts/debug_env.py' to verify configuration")
        
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: Unexpected error: {e}")
        print("\nTroubleshooting:")
        print("  1. Check IBKR_CONNECTION_FIXES.md for help")
        print("  2. Run 'python scripts/debug_env.py' to verify configuration")
        return 1


if __name__ == "__main__":
    sys.exit(main())

