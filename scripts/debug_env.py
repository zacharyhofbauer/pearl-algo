#!/usr/bin/env python
"""
Debug Environment Configuration Script

Prints parsed settings, validates configuration, and warns about misconfigurations.
Use this to verify your .env file is set up correctly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.config.settings import get_settings, Settings


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_setting(key: str, value: any, status: str = "✓") -> None:
    """Print a setting with status indicator."""
    value_str = str(value) if value is not None else "(not set)"
    print(f"  {status} {key:30s} = {value_str}")


def validate_ibkr_config(settings: Settings) -> list[str]:
    """Validate IBKR configuration and return list of warnings/errors."""
    issues = []
    
    if settings.profile in {"paper", "live"}:
        if not settings.ib_host or settings.ib_host == "":
            issues.append("ERROR: IBKR_HOST is required for paper/live trading")
        elif settings.ib_host not in {"127.0.0.1", "localhost"}:
            issues.append(f"WARNING: IBKR_HOST is {settings.ib_host} (expected 127.0.0.1 for local Gateway)")
        
        if settings.ib_port <= 0 or settings.ib_port > 65535:
            issues.append(f"ERROR: Invalid IBKR_PORT: {settings.ib_port}")
        elif settings.ib_port not in {4001, 4002, 7496, 7497}:
            issues.append(f"WARNING: IBKR_PORT is {settings.ib_port} (common: 4002=Gateway paper, 7497=TWS paper)")
        
        if settings.ib_client_id < 0 or settings.ib_client_id > 100:
            issues.append(f"ERROR: Invalid IBKR_CLIENT_ID: {settings.ib_client_id}")
        elif settings.ib_client_id == 0:
            issues.append("WARNING: IBKR_CLIENT_ID is 0 (may cause conflicts)")
        
        if settings.ib_data_client_id is not None:
            if settings.ib_data_client_id < 0 or settings.ib_data_client_id > 100:
                issues.append(f"ERROR: Invalid IBKR_DATA_CLIENT_ID: {settings.ib_data_client_id}")
            elif settings.ib_data_client_id == settings.ib_client_id:
                issues.append("WARNING: IBKR_DATA_CLIENT_ID equals IBKR_CLIENT_ID (may cause conflicts)")
    
    return issues


def main() -> int:
    """Main function."""
    print_section("PearlAlgo Environment Configuration Debug")
    
    try:
        settings = get_settings()
    except Exception as e:
        print(f"\n❌ ERROR: Failed to load settings: {e}")
        print("\nThis usually means:")
        print("  - Invalid .env file format")
        print("  - Missing required configuration")
        print("  - See IBKR_CONNECTION_FIXES.md for help")
        return 1
    
    # Basic Settings
    print_section("Basic Settings")
    print_setting("Profile", settings.profile)
    print_setting("Data Directory", settings.data_dir)
    print_setting("Log Level", settings.log_level)
    print_setting("Allow Live Trading", settings.allow_live_trading)
    print_setting("Dummy Mode", settings.dummy_mode)
    
    # IBKR Settings
    print_section("IBKR Configuration")
    print_setting("IBKR Host", settings.ib_host)
    print_setting("IBKR Port", settings.ib_port)
    print_setting("IBKR Client ID", settings.ib_client_id)
    print_setting("IBKR Data Client ID", settings.ib_data_client_id or "(auto)")
    print_setting("IB Enable", settings.ib_enable)
    
    # Environment Variables (raw)
    print_section("Environment Variables (Raw)")
    ibkr_vars = {
        "IBKR_HOST": os.getenv("IBKR_HOST"),
        "IBKR_PORT": os.getenv("IBKR_PORT"),
        "IBKR_CLIENT_ID": os.getenv("IBKR_CLIENT_ID"),
        "IBKR_DATA_CLIENT_ID": os.getenv("IBKR_DATA_CLIENT_ID"),
    }
    pearlalgo_vars = {
        "PEARLALGO_PROFILE": os.getenv("PEARLALGO_PROFILE"),
        "PEARLALGO_IB_HOST": os.getenv("PEARLALGO_IB_HOST"),
        "PEARLALGO_IB_PORT": os.getenv("PEARLALGO_IB_PORT"),
        "PEARLALGO_IB_CLIENT_ID": os.getenv("PEARLALGO_IB_CLIENT_ID"),
        "PEARLALGO_IB_DATA_CLIENT_ID": os.getenv("PEARLALGO_IB_DATA_CLIENT_ID"),
        "PEARLALGO_DUMMY_MODE": os.getenv("PEARLALGO_DUMMY_MODE"),
    }
    
    print("\n  IBKR_* variables (take precedence):")
    for key, value in ibkr_vars.items():
        status = "✓" if value else "○"
        print_setting(key, value or "(not set)", status)
    
    print("\n  PEARLALGO_* variables:")
    for key, value in pearlalgo_vars.items():
        status = "✓" if value else "○"
        print_setting(key, value or "(not set)", status)
    
    # Validation
    print_section("Validation")
    issues = validate_ibkr_config(settings)
    
    if not issues:
        print("  ✓ All checks passed!")
    else:
        for issue in issues:
            if issue.startswith("ERROR"):
                print(f"  ❌ {issue}")
            else:
                print(f"  ⚠️  {issue}")
    
    # Recommendations
    print_section("Recommendations")
    
    if settings.profile == "live" and not settings.allow_live_trading:
        print("  ⚠️  Profile is 'live' but PEARLALGO_ALLOW_LIVE_TRADING is false")
        print("     Set PEARLALGO_ALLOW_LIVE_TRADING=true to enable live trading")
    
    if settings.dummy_mode:
        print("  ℹ️  Dummy mode is enabled - system will use dummy data if IBKR unavailable")
    elif settings.profile in {"paper", "live"}:
        print("  ℹ️  Dummy mode is disabled - system will raise errors if IBKR unavailable")
        print("     Set PEARLALGO_DUMMY_MODE=true to enable dummy data fallback")
    
    if settings.profile not in {"paper", "live", "backtest", "dummy"}:
        print(f"  ⚠️  Unknown profile: {settings.profile}")
        print("     Valid profiles: paper, live, backtest, dummy")
    
    # Optional API Keys
    print_section("Optional API Keys")
    optional_keys = {
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "MASSIVE_API_KEY": os.getenv("MASSIVE_API_KEY"),
    }
    
    for key, value in optional_keys.items():
        if value:
            print_setting(key, "***set***", "✓")
        else:
            print_setting(key, "(not set)", "○")
    
    print("\n" + "=" * 60)
    if issues and any(i.startswith("ERROR") for i in issues):
        print("❌ Configuration has ERRORS - fix before trading!")
        return 1
    elif issues:
        print("⚠️  Configuration has WARNINGS - review before trading")
        return 0
    else:
        print("✓ Configuration looks good!")
        return 0


if __name__ == "__main__":
    sys.exit(main())

