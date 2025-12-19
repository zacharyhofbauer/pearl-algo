#!/usr/bin/env python3
"""
Test script to verify chart visualization upgrades.

Tests:
1. Backtest chart with performance metrics panel
2. Entry chart with indicators
3. Signal positioning
4. Candlestick rendering
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

import pandas as pd
from datetime import datetime, timezone
from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig


def test_backtest_chart_with_metrics():
    """Test backtest chart with performance metrics panel."""
    print("=" * 60)
    print("TEST 1: Backtest Chart with Performance Metrics")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        # Create test data
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=200, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25000 + i * 0.3 + (i % 5 - 2) * 0.5 for i in range(200)],
            'high': [25001 + i * 0.3 + abs(i % 5 - 2) * 0.7 for i in range(200)],
            'low': [24999 + i * 0.3 - abs(i % 5 - 2) * 0.7 for i in range(200)],
            'close': [25000.5 + i * 0.3 + (i % 5 - 2) * 0.3 for i in range(200)],
            'volume': [1000 + (i % 20) * 50 for i in range(200)],
        })
        test_data = test_data.set_index('timestamp').reset_index()
        
        # Create test signals
        signals = []
        for i in range(5):
            idx = int(len(test_data) * (i + 1) / 6)
            signal_time = test_data.iloc[idx]['timestamp']
            close_price = float(test_data.iloc[idx]['close'])
            signals.append({
                'entry_price': close_price,
                'stop_loss': close_price - 50,
                'take_profit': close_price + 75,
                'direction': 'long' if i % 2 == 0 else 'short',
                'type': 'momentum_breakout',
                'timestamp': signal_time.isoformat() if hasattr(signal_time, 'isoformat') else str(signal_time),
                'confidence': 0.7 + (i % 3) * 0.1,
            })
        
        # Performance data
        performance_data = {
            'total_signals': 5,
            'avg_confidence': 0.75,
            'avg_risk_reward': 1.5,
            'win_rate': None,  # Would be calculated in full backtest
            'total_pnl': None,  # Would be calculated in full backtest
        }
        
        chart_path = generator.generate_backtest_chart(
            test_data,
            signals,
            'MNQ',
            'Backtest Results - Demo Visualization',
            performance_data=performance_data
        )
        
        if chart_path and chart_path.exists():
            size_kb = chart_path.stat().st_size / 1024
            print(f"✅ Backtest chart generated: {chart_path.name}")
            print(f"   Size: {size_kb:.1f} KB")
            print(f"   Path: {chart_path}")
            print(f"   ⚠️  Check if performance metrics panel is visible at bottom")
            # Don't delete - let user see it
            return chart_path
        else:
            print("❌ Chart generation failed")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_entry_chart_candlesticks():
    """Test entry chart with proper candlestick rendering."""
    print("\n" + "=" * 60)
    print("TEST 2: Entry Chart with Candlesticks")
    print("=" * 60)
    
    try:
        generator = ChartGenerator()
        
        # Create test data
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25000 + i * 0.5 + (i % 3 - 1) * 0.2 for i in range(100)],
            'high': [25001 + i * 0.5 + abs(i % 3 - 1) * 0.3 for i in range(100)],
            'low': [24999 + i * 0.5 - abs(i % 3 - 1) * 0.3 for i in range(100)],
            'close': [25000.5 + i * 0.5 + (i % 3 - 1) * 0.1 for i in range(100)],
            'volume': [1000 + (i % 10) * 100 for i in range(100)],
        })
        
        # Test signal
        test_signal = {
            'entry_price': 25050.0,
            'stop_loss': 25000.0,
            'take_profit': 25100.0,
            'direction': 'long',
            'type': 'momentum_breakout',
            'symbol': 'MNQ',
            'confidence': 0.75,
            'reason': 'Test signal for chart visualization',
        }
        
        chart_path = generator.generate_entry_chart(test_signal, test_data, 'MNQ')
        
        if chart_path and chart_path.exists():
            size_kb = chart_path.stat().st_size / 1024
            print(f"✅ Entry chart generated: {chart_path.name}")
            print(f"   Size: {size_kb:.1f} KB")
            print(f"   Path: {chart_path}")
            print(f"   ⚠️  Check if candlesticks render properly (not '+' markers)")
            # Don't delete - let user see it
            return chart_path
        else:
            print("❌ Chart generation failed")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_config_disabled():
    """Test that disabling indicators works."""
    print("\n" + "=" * 60)
    print("TEST 3: Chart Config (Disabled Indicators)")
    print("=" * 60)
    
    try:
        config = ChartConfig(show_vwap=False, show_ma=False)
        generator = ChartGenerator(config=config)
        
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1min')
        test_data = pd.DataFrame({
            'timestamp': dates,
            'open': [25000 + i * 0.5 for i in range(100)],
            'high': [25001 + i * 0.5 for i in range(100)],
            'low': [24999 + i * 0.5 for i in range(100)],
            'close': [25000.5 + i * 0.5 for i in range(100)],
            'volume': [1000] * 100,
        })
        
        test_signal = {
            'entry_price': 25050.0,
            'stop_loss': 25000.0,
            'take_profit': 25100.0,
            'direction': 'long',
            'type': 'test',
        }
        
        chart_path = generator.generate_entry_chart(test_signal, test_data, 'MNQ')
        
        if chart_path and chart_path.exists():
            print(f"✅ Chart with disabled indicators generated: {chart_path.name}")
            print(f"   Config: VWAP={config.show_vwap}, MA={config.show_ma}")
            return chart_path
        else:
            print("❌ Chart generation failed")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CHART UPGRADES TEST SUITE")
    print("=" * 60)
    print()
    
    results = []
    
    chart1 = test_backtest_chart_with_metrics()
    results.append(("Backtest with Metrics", chart1 is not None))
    
    chart2 = test_entry_chart_candlesticks()
    results.append(("Entry Chart Candlesticks", chart2 is not None))
    
    chart3 = test_config_disabled()
    results.append(("Config Disabled", chart3 is not None))
    
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
    
    if chart1:
        print(f"\n📊 Backtest chart: {chart1}")
    if chart2:
        print(f"📊 Entry chart: {chart2}")
    if chart3:
        print(f"📊 Config test chart: {chart3}")
    
    print("\n💡 Check the generated charts visually to verify:")
    print("   1. Performance metrics panel at bottom of backtest chart")
    print("   2. Proper candlesticks (not '+' markers) on entry chart")
    print("   3. Indicators (VWAP, MA) are visible")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
