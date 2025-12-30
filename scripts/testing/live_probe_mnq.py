#!/usr/bin/env python3
"""
Live MNQ Data Probe - Read-only IBKR verification script.

Tests:
- MNQ contract resolution (localSymbol, expiry)
- Latest bar fetch (data_level, timestamp, freshness)
- Historical data fetch (small window)
- Data staleness detection
- Error 354 / Error 162 handling

This script is read-only and does NOT place any orders.

Usage:
    python3 scripts/testing/live_probe_mnq.py [--verbose]
"""

import asyncio
import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def parse_timestamp(ts_str: str) -> datetime | None:
    """Parse various timestamp formats to datetime."""
    if not ts_str:
        return None
    
    # Try ISO format first
    try:
        from dateutil import parser as dateutil_parser
        dt = dateutil_parser.parse(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    
    # Try pandas
    try:
        import pandas as pd
        ts = pd.to_datetime(ts_str)
        if ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        return ts.to_pydatetime()
    except Exception:
        pass
    
    return None


def compute_staleness(timestamp: datetime) -> float:
    """Compute staleness in minutes from timestamp."""
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    delta = now - timestamp
    return delta.total_seconds() / 60


async def probe_mnq(verbose: bool = False) -> int:
    """
    Run MNQ data probe against live IBKR.
    
    Returns:
        0 on success, non-zero on failure
    """
    from pearlalgo.config.settings import get_settings
    from pearlalgo.data_providers.factory import create_data_provider
    
    print("=" * 70)
    print("MNQ Live Data Probe")
    print("=" * 70)
    print()
    print("⚠️  This script is READ-ONLY and does NOT place any orders.")
    print()
    
    # Load settings
    settings = get_settings()
    print(f"IB Gateway: {settings.ib_host}:{settings.ib_port}")
    print(f"Client ID: {settings.ib_data_client_id or settings.ib_client_id}")
    print()
    
    # Track results for summary
    results = {
        "connection": None,
        "contract_resolution": None,
        "latest_bar": None,
        "historical_data": None,
        "data_freshness": None,
    }
    
    provider = None
    exit_code = 0
    
    try:
        # Create provider
        print("Creating IBKR provider...")
        provider = create_data_provider("ibkr", settings=settings)
        print("✅ Provider created")
        print()
        
        # Test 1: Connection
        print("-" * 70)
        print("Test 1: Connection Validation")
        print("-" * 70)
        try:
            connected = await provider.validate_connection()
            if connected:
                print("✅ Connected to IB Gateway")
                results["connection"] = "PASS"
            else:
                print("❌ Connection failed (validate_connection returned False)")
                results["connection"] = "FAIL"
                exit_code = 1
        except Exception as e:
            print(f"❌ Connection error: {e}")
            results["connection"] = f"FAIL: {e}"
            exit_code = 1
        print()
        
        # Test 2: Contract Resolution
        print("-" * 70)
        print("Test 2: MNQ Contract Resolution")
        print("-" * 70)
        try:
            # Access internal contract resolution if available
            if hasattr(provider, '_resolve_contract'):
                contract = await provider._resolve_contract("MNQ")
                if contract:
                    local_symbol = getattr(contract, 'localSymbol', None)
                    expiry = getattr(contract, 'lastTradeDateOrContractMonth', None)
                    exchange = getattr(contract, 'exchange', None)
                    
                    print(f"✅ Contract resolved:")
                    print(f"   localSymbol: {local_symbol}")
                    print(f"   expiry: {expiry}")
                    print(f"   exchange: {exchange}")
                    
                    # Validate localSymbol looks correct (e.g., MNQH25, MNQZ24)
                    if local_symbol and local_symbol.startswith("MNQ"):
                        results["contract_resolution"] = "PASS"
                    else:
                        print(f"⚠️  localSymbol '{local_symbol}' doesn't look like MNQ contract")
                        results["contract_resolution"] = "WARN"
                else:
                    print("❌ Contract resolution returned None")
                    results["contract_resolution"] = "FAIL"
                    exit_code = 1
            else:
                print("⚠️  _resolve_contract not available, skipping contract resolution test")
                results["contract_resolution"] = "SKIP"
        except Exception as e:
            error_msg = str(e)
            if "162" in error_msg or "Historical market data Service error" in error_msg:
                print(f"❌ Error 162 (Historical data service error): {e}")
                print("   → This may indicate market data subscription issues")
            elif "354" in error_msg or "not subscribed" in error_msg.lower():
                print(f"❌ Error 354 (Not subscribed to market data): {e}")
                print("   → Check docs/MARKET_DATA_SUBSCRIPTION.md for subscription requirements")
            else:
                print(f"❌ Contract resolution error: {e}")
            results["contract_resolution"] = f"FAIL: {e}"
            exit_code = 1
        print()
        
        # Test 3: Latest Bar
        print("-" * 70)
        print("Test 3: MNQ Latest Bar")
        print("-" * 70)
        try:
            latest_bar = await provider.get_latest_bar("MNQ")
            
            if latest_bar:
                close_price = latest_bar.get('close')
                data_level = latest_bar.get('_data_level', 'unknown')
                timestamp = latest_bar.get('timestamp')
                market_open = latest_bar.get('_market_open_assumption')
                
                print(f"✅ Latest bar retrieved:")
                print(f"   close: ${close_price:.2f}" if close_price else "   close: N/A")
                print(f"   data_level: {data_level}")
                print(f"   timestamp: {timestamp}")
                if market_open is not None:
                    print(f"   market_open_assumption: {market_open}")
                
                # Validate data_level
                if data_level in ('level1', 'historical', 'snapshot'):
                    print(f"✅ data_level '{data_level}' is valid")
                else:
                    print(f"⚠️  data_level '{data_level}' is unusual")
                
                results["latest_bar"] = "PASS"
                
                # Compute freshness if timestamp available
                if timestamp:
                    ts_dt = parse_timestamp(str(timestamp))
                    if ts_dt:
                        staleness = compute_staleness(ts_dt)
                        print(f"   staleness: {staleness:.1f} minutes")
                        
                        if staleness < 5:
                            print("✅ Data is fresh (< 5 minutes)")
                            results["data_freshness"] = "PASS"
                        elif staleness < 15:
                            print(f"⚠️  Data is slightly stale ({staleness:.1f} minutes)")
                            results["data_freshness"] = "WARN"
                        else:
                            print(f"❌ Data is stale ({staleness:.1f} minutes > 15 min threshold)")
                            results["data_freshness"] = "FAIL"
                    else:
                        print(f"⚠️  Could not parse timestamp: {timestamp}")
                        results["data_freshness"] = "WARN"
            else:
                print("❌ Latest bar returned None")
                print("   → Check if market data subscription is active")
                print("   → See docs/MARKET_DATA_SUBSCRIPTION.md for troubleshooting")
                results["latest_bar"] = "FAIL"
                exit_code = 1
                
        except Exception as e:
            error_msg = str(e)
            if "354" in error_msg or "not subscribed" in error_msg.lower():
                print(f"❌ Error 354 (Not subscribed to MNQ market data): {e}")
                print()
                print("   TROUBLESHOOTING:")
                print("   1. Check IBKR account has 'CME' market data subscription")
                print("   2. Verify futures trading permissions are enabled")
                print("   3. See docs/MARKET_DATA_SUBSCRIPTION.md for details")
            elif "162" in error_msg:
                print(f"❌ Error 162 (Historical data service error): {e}")
            else:
                print(f"❌ Error fetching latest bar: {e}")
            results["latest_bar"] = f"FAIL: {e}"
            exit_code = 1
        print()
        
        # Test 4: Historical Data
        print("-" * 70)
        print("Test 4: MNQ Historical Data (15 bars)")
        print("-" * 70)
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=1)
            
            # Use synchronous fetch_historical with care in async context
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                df = await asyncio.get_event_loop().run_in_executor(
                    pool, 
                    lambda: provider.fetch_historical("MNQ", start, end, "1m")
                )
            
            if df is not None and not df.empty:
                print(f"✅ Historical data retrieved: {len(df)} bars")
                print(f"   Columns: {list(df.columns)}")
                
                if verbose and len(df) > 0:
                    print()
                    print("   Latest 3 bars:")
                    for i, (idx, row) in enumerate(df.tail(3).iterrows()):
                        close = row.get('close', 'N/A')
                        volume = row.get('volume', 'N/A')
                        print(f"   [{i+1}] {idx} | close: {close} | volume: {volume}")
                
                results["historical_data"] = "PASS"
                
                # Check if we got a reasonable number of bars
                if len(df) < 5:
                    print(f"⚠️  Only {len(df)} bars returned (expected more for 1-hour window)")
                    results["historical_data"] = "WARN"
            else:
                print("❌ Historical data returned empty DataFrame")
                results["historical_data"] = "FAIL"
                exit_code = 1
                
        except Exception as e:
            error_msg = str(e)
            if "354" in error_msg or "not subscribed" in error_msg.lower():
                print(f"❌ Error 354: {e}")
            elif "162" in error_msg:
                print(f"❌ Error 162 (Historical data service error): {e}")
            else:
                print(f"❌ Error fetching historical data: {e}")
            results["historical_data"] = f"FAIL: {e}"
            exit_code = 1
        print()
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1
        
    finally:
        # Cleanup
        if provider:
            try:
                await provider.close()
                print("Connection closed.")
            except Exception:
                pass
    
    # Summary
    print("=" * 70)
    print("PROBE SUMMARY")
    print("=" * 70)
    
    for test_name, result in results.items():
        if result is None:
            status = "⏭️  SKIP"
        elif result == "PASS":
            status = "✅ PASS"
        elif result == "WARN":
            status = "⚠️  WARN"
        elif result == "SKIP":
            status = "⏭️  SKIP"
        elif isinstance(result, str) and result.startswith("FAIL"):
            status = "❌ FAIL"
        else:
            status = f"❓ {result}"
        
        print(f"  {test_name:25} {status}")
    
    print()
    
    if exit_code == 0:
        print("=" * 70)
        print("✅ MNQ LIVE PROBE PASSED")
        print("=" * 70)
    else:
        print("=" * 70)
        print("❌ MNQ LIVE PROBE FAILED")
        print("=" * 70)
        print()
        print("NEXT STEPS:")
        print("  1. Verify IB Gateway is running and API enabled")
        print("  2. Check market data subscriptions in Account Management")
        print("  3. Review docs/MARKET_DATA_SUBSCRIPTION.md")
        print("  4. Run: python3 scripts/testing/smoke_test_ibkr.py")
    
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="MNQ Live Data Probe")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output")
    args = parser.parse_args()
    
    exit_code = asyncio.run(probe_mnq(verbose=args.verbose))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

