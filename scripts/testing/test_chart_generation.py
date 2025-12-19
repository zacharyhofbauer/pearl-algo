#!/usr/bin/env python3
"""
Test Chart Generation

Comprehensive tests for chart visualization functionality.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

import pandas as pd
from datetime import datetime, timezone
from pearlalgo.nq_agent.chart_generator import ChartGenerator


def test_entry_chart():
    """Test entry chart generation."""
    print("=" * 60)
    print("TEST 1: Entry Chart Generation")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        # Create realistic test data
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25000 + i * 0.5 + (i % 3 - 1) * 0.2 for i in range(100)],
            'high': [25001 + i * 0.5 + abs(i % 3 - 1) * 0.3 for i in range(100)],
            'low': [24999 + i * 0.5 - abs(i % 3 - 1) * 0.3 for i in range(100)],
            'close': [25000.5 + i * 0.5 + (i % 3 - 1) * 0.1 for i in range(100)],
            'volume': [1000 + (i % 10) * 100 for i in range(100)],
        })
        
        # Test long signal
        long_signal = {
            'entry_price': 25050.0,
            'stop_loss': 25000.0,
            'take_profit': 25100.0,
            'direction': 'long',
            'type': 'momentum_breakout',
            'symbol': 'MNQ',
        }
        
        chart_path = generator.generate_entry_chart(long_signal, test_data, 'MNQ')
        
        if chart_path and chart_path.exists():
            size_kb = chart_path.stat().st_size / 1024
            print(f"✅ Entry chart generated: {chart_path.name}")
            print(f"   Size: {size_kb:.1f} KB")
            chart_path.unlink()
            return True
        else:
            print("❌ Chart generation failed")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_exit_chart():
    """Test exit chart generation."""
    print("\n" + "=" * 60)
    print("TEST 2: Exit Chart Generation")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        # Create test data
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=150, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25000 + i * 0.3 + (i % 3 - 1) * 0.2 for i in range(150)],
            'high': [25001 + i * 0.3 + abs(i % 3 - 1) * 0.3 for i in range(150)],
            'low': [24999 + i * 0.3 - abs(i % 3 - 1) * 0.3 for i in range(150)],
            'close': [25000.5 + i * 0.3 + (i % 3 - 1) * 0.1 for i in range(150)],
            'volume': [1000 + (i % 10) * 100 for i in range(150)],
        })
        
        signal = {
            'entry_price': 25050.0,
            'stop_loss': 25000.0,
            'take_profit': 25100.0,
            'direction': 'long',
            'type': 'momentum_breakout',
            'symbol': 'MNQ',
        }
        
        # Test profitable exit
        chart_path = generator.generate_exit_chart(
            signal, 25075.0, 'take_profit', 500.0, test_data, 'MNQ'
        )
        
        if chart_path and chart_path.exists():
            size_kb = chart_path.stat().st_size / 1024
            print(f"✅ Exit chart (profit) generated: {chart_path.name}")
            print(f"   Size: {size_kb:.1f} KB")
            chart_path.unlink()
            
            # Test losing exit
            chart_path = generator.generate_exit_chart(
                signal, 25025.0, 'stop_loss', -500.0, test_data, 'MNQ'
            )
            
            if chart_path and chart_path.exists():
                size_kb = chart_path.stat().st_size / 1024
                print(f"✅ Exit chart (loss) generated: {chart_path.name}")
                print(f"   Size: {size_kb:.1f} KB")
                chart_path.unlink()
                return True
            else:
                print("❌ Loss chart generation failed")
                return False
        else:
            print("❌ Profit chart generation failed")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_short_signal():
    """Test short signal chart generation."""
    print("\n" + "=" * 60)
    print("TEST 3: Short Signal Chart")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25100 - i * 0.5 + (i % 3 - 1) * 0.2 for i in range(100)],
            'high': [25101 - i * 0.5 + abs(i % 3 - 1) * 0.3 for i in range(100)],
            'low': [25099 - i * 0.5 - abs(i % 3 - 1) * 0.3 for i in range(100)],
            'close': [25100.5 - i * 0.5 + (i % 3 - 1) * 0.1 for i in range(100)],
            'volume': [1000 + (i % 10) * 100 for i in range(100)],
        })
        
        short_signal = {
            'entry_price': 25050.0,
            'stop_loss': 25100.0,  # Above entry for short
            'take_profit': 25000.0,  # Below entry for short
            'direction': 'short',
            'type': 'mean_reversion',
            'symbol': 'MNQ',
        }
        
        chart_path = generator.generate_entry_chart(short_signal, test_data, 'MNQ')
        
        if chart_path and chart_path.exists():
            size_kb = chart_path.stat().st_size / 1024
            print(f"✅ Short signal chart generated: {chart_path.name}")
            print(f"   Size: {size_kb:.1f} KB")
            chart_path.unlink()
            return True
        else:
            print("❌ Short chart generation failed")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_empty_data():
    """Test handling of empty data."""
    print("\n" + "=" * 60)
    print("TEST 4: Empty Data Handling")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        # Empty dataframe
        empty_data = pd.DataFrame()
        signal = {
            'entry_price': 25050.0,
            'stop_loss': 25000.0,
            'take_profit': 25100.0,
            'direction': 'long',
            'type': 'test',
            'symbol': 'MNQ',
        }
        
        chart_path = generator.generate_entry_chart(signal, empty_data, 'MNQ')
        
        if chart_path is None:
            print("✅ Empty data handled gracefully (returns None)")
            return True
        else:
            print("⚠️  Empty data should return None")
            if chart_path.exists():
                chart_path.unlink()
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_invalid_signal():
    """Test handling of invalid signal data."""
    print("\n" + "=" * 60)
    print("TEST 5: Invalid Signal Handling")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25000] * 50,
            'high': [25001] * 50,
            'low': [24999] * 50,
            'close': [25000.5] * 50,
            'volume': [1000] * 50,
        })
        
        # Signal with invalid entry price
        invalid_signal = {
            'entry_price': 0,  # Invalid
            'stop_loss': 25000.0,
            'take_profit': 25100.0,
            'direction': 'long',
            'type': 'test',
            'symbol': 'MNQ',
        }
        
        chart_path = generator.generate_entry_chart(invalid_signal, test_data, 'MNQ')
        
        if chart_path is None:
            print("✅ Invalid signal handled gracefully (returns None)")
            return True
        else:
            print("⚠️  Invalid signal should return None")
            if chart_path.exists():
                chart_path.unlink()
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CHART GENERATION TEST SUITE")
    print("=" * 60)
    print()
    
    results = []
    
    results.append(("Entry Chart", test_entry_chart()))
    results.append(("Exit Chart", test_exit_chart()))
    results.append(("Short Signal", test_short_signal()))
    results.append(("Empty Data", test_empty_data()))
    results.append(("Invalid Signal", test_invalid_signal()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
