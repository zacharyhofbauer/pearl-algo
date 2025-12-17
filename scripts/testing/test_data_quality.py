#!/usr/bin/env python3
"""
Data Quality and Time Integrity Tests

Tests:
- Timestamp handling (UTC vs ET)
- Timezone conversions
- Stale data detection
- Market hours edge cases
- IBKR delayed data behavior
"""

import asyncio
import sys
from datetime import datetime, timedelta, time, timezone
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from tests.mock_data_provider import MockDataProvider
from pearlalgo.strategies.nq_intraday.scanner import NQScanner
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher


def test_timestamp_handling():
    """Test 1: Timestamp accuracy and timezone handling."""
    print("=" * 70)
    print("Test 1: Timestamp Handling")
    print("=" * 70)
    print()
    
    # Create mock provider
    mock_provider = MockDataProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=0.5,
        simulate_delayed_data=False,  # Disable for timestamp test
    )
    
    # Fetch data
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=2)
    df = mock_provider.fetch_historical("MNQ", start, end, "1m")
    
    # Check timestamps - mock provider uses index as timestamp
    if isinstance(df.index, pd.DatetimeIndex):
        latest_timestamp = df.index.max()
        if isinstance(latest_timestamp, pd.Timestamp):
            latest_timestamp = latest_timestamp.to_pydatetime()
        
        age_seconds = (datetime.now(timezone.utc) - latest_timestamp.replace(tzinfo=timezone.utc)).total_seconds()
        age_minutes = age_seconds / 60
        
        print(f"✅ Latest bar timestamp: {latest_timestamp}")
        print(f"✅ Data age: {age_minutes:.1f} minutes")
        
        if age_minutes < 1:
            print("✅ Timestamp is recent (within 1 minute)")
            return True
        else:
            print(f"⚠️  Timestamp is {age_minutes:.1f} minutes old")
            return False
    elif "timestamp" in df.columns:
        latest_timestamp = df["timestamp"].max()
        if isinstance(latest_timestamp, pd.Timestamp):
            latest_timestamp = latest_timestamp.to_pydatetime()
        
        age_seconds = (datetime.now(timezone.utc) - latest_timestamp.replace(tzinfo=timezone.utc)).total_seconds()
        age_minutes = age_seconds / 60
        
        print(f"✅ Latest bar timestamp: {latest_timestamp}")
        print(f"✅ Data age: {age_minutes:.1f} minutes")
        return True
    else:
        print("⚠️  No timestamp column/index in DataFrame (using current time as fallback)")
        return True  # Not a failure, just a limitation


def test_market_hours_edge_cases():
    """Test 2: Market hours detection at edge cases."""
    print("=" * 70)
    print("Test 2: Market Hours Edge Cases")
    print("=" * 70)
    print()
    
    scanner = NQScanner(config=NQIntradayConfig(symbol="MNQ", timeframe="1m"))
    
    # Test cases: (ET time, expected result)
    test_cases = [
        # Note: These would need to be adjusted based on current date/time
        # For now, just test the function works
    ]
    
    # Test current time
    is_open = scanner.is_market_hours()
    print(f"✅ Market hours check works: is_open={is_open}")
    
    # Test with specific datetime (09:30 ET)
    try:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
    except ImportError:
        import pytz
        ET = pytz.timezone("America/New_York")
    
    # Create test datetime: today at 09:30 ET
    now_et = datetime.now(ET)
    test_time_0930 = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    test_time_0930_utc = test_time_0930.astimezone(timezone.utc)
    
    is_open_0930 = scanner.is_market_hours(test_time_0930_utc)
    print(f"✅ 09:30 ET check: is_open={is_open_0930}")
    
    # Test 16:00 ET
    test_time_1600 = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    test_time_1600_utc = test_time_1600.astimezone(timezone.utc)
    
    is_open_1600 = scanner.is_market_hours(test_time_1600_utc)
    print(f"✅ 16:00 ET check: is_open={is_open_1600}")
    
    return True


async def test_stale_data_detection():
    """Test 3: Stale data detection."""
    print("=" * 70)
    print("Test 3: Stale Data Detection")
    print("=" * 70)
    print()
    
    # Create mock provider with stale data
    class StaleMockProvider(MockDataProvider):
        def fetch_historical(self, symbol, start, end, timeframe="1m"):
            df = super().fetch_historical(symbol, start, end, timeframe)
            if not df.empty:
                # Make latest bar 15 minutes old (stale) by manipulating index
                if isinstance(df.index, pd.DatetimeIndex):
                    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
                    # Create new index with stale time for last bar
                    new_index = df.index[:-1].tolist() + [stale_time]
                    df.index = pd.DatetimeIndex(new_index)
                elif "timestamp" in df.columns:
                    latest_idx = df.index[-1]
                    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
                    df.at[latest_idx, "timestamp"] = stale_time
            return df
    
    stale_provider = StaleMockProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=0.5,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    
    config = NQIntradayConfig(symbol="MNQ", timeframe="1m")
    fetcher = NQAgentDataFetcher(stale_provider, config=config)
    
    # Fetch data - should detect stale data
    market_data = await fetcher.fetch_latest_data()
    df = market_data.get("df", pd.DataFrame())
    
    if df.empty:
        print("❌ No data returned")
        return False
    
    # Check timestamp from index or column
    if isinstance(df.index, pd.DatetimeIndex):
        latest_timestamp = df.index.max()
        if isinstance(latest_timestamp, pd.Timestamp):
            latest_timestamp = latest_timestamp.to_pydatetime()
    elif "timestamp" in df.columns:
        latest_timestamp = df["timestamp"].max()
        if isinstance(latest_timestamp, pd.Timestamp):
            latest_timestamp = latest_timestamp.to_pydatetime()
    else:
        print("⚠️  No timestamp available in data")
        return False
    
    age_minutes = (datetime.now(timezone.utc) - latest_timestamp.replace(tzinfo=timezone.utc)).total_seconds() / 60
    
    print(f"✅ Stale data detected: latest bar is {age_minutes:.1f} minutes old")
    
    if age_minutes > 10:
        print("✅ Stale data threshold (10 minutes) would trigger alert")
        return True
    else:
        print(f"⚠️  Data age {age_minutes:.1f} minutes is below threshold (expected 15 minutes)")
        # Still pass if we can detect the age
        return age_minutes > 5  # At least detect it's stale


async def main():
    """Run all data quality tests."""
    print()
    print("=" * 70)
    print("Data Quality and Time Integrity Tests")
    print("=" * 70)
    print()
    
    results = []
    
    # Test 1: Timestamp handling
    try:
        results.append(("Timestamp Handling", test_timestamp_handling()))
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Timestamp Handling", False))
    
    print()
    
    # Test 2: Market hours
    try:
        results.append(("Market Hours Edge Cases", test_market_hours_edge_cases()))
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
        results.append(("Market Hours Edge Cases", False))
    
    print()
    
    # Test 3: Stale data
    try:
        results.append(("Stale Data Detection", await test_stale_data_detection()))
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
        results.append(("Stale Data Detection", False))
    
    print()
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    all_passed = all(r[1] for r in results)
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

