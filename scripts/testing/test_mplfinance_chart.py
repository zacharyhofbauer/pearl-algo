#!/usr/bin/env python3
"""
Test script to test chart generator (mplfinance-based).

Usage:
    python3 scripts/testing/test_mplfinance_chart.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
from pearlalgo.utils.logger import logger

def create_sample_data(num_bars=100):
    """Create sample OHLCV data with realistic MNQ volatility."""
    base_price = 25000.0
    dates = pd.date_range(
        end=datetime.now(timezone.utc),
        periods=num_bars,
        freq='5min'  # 5-minute bars for better visual
    )
    
    # Generate realistic MNQ price data with visible candles
    np.random.seed(42)
    # MNQ typically moves 5-15 points per 5m bar
    price_changes = np.random.randn(num_bars) * 8
    prices = base_price + np.cumsum(price_changes)
    
    data = []
    for i, (date, price) in enumerate(zip(dates, prices)):
        # Realistic candle range: 5-20 points (MNQ typical 5m range)
        candle_range = abs(np.random.randn() * 8) + 5
        
        # Random direction for candle body
        if np.random.random() > 0.5:
            open_price = price - candle_range * 0.3
            close_price = price + candle_range * 0.3
        else:
            open_price = price + candle_range * 0.3
            close_price = price - candle_range * 0.3
        
        # Wicks extend beyond body
        high = max(open_price, close_price) + abs(np.random.randn() * 3) + 2
        low = min(open_price, close_price) - abs(np.random.randn() * 3) - 2
        
        data.append({
            'timestamp': date,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close_price,
            'volume': int(np.random.uniform(1000, 5000))
        })
    
    return pd.DataFrame(data)

def test_mplfinance_chart():
    """Test mplfinance-based chart generator."""
    print("\n" + "="*60)
    print("Testing MPLFINANCE Chart Generator")
    print("="*60)
    
    try:
        # Create sample data
        data = create_sample_data(100)
        
        # Create signal within data range
        data_close = data['close'].iloc[-1]
        signal = {
            'entry_price': data_close,
            'stop_loss': data_close - 20.0,  # 20 point stop
            'take_profit': data_close + 30.0,  # 30 point target (1.5:1 R:R)
            'direction': 'long',
            'type': 'momentum_breakout',
            'timestamp': data['timestamp'].iloc[-20].isoformat()
        }
        
        # Create generator (mplfinance-only implementation)
        config = ChartConfig()
        generator = ChartGenerator(config)
        
        # Generate chart
        print("Generating chart with mplfinance...")
        chart_path = generator.generate_entry_chart(
            signal=signal,
            buffer_data=data,
            symbol="MNQ",
            timeframe="1m"
        )
        
        if chart_path:
            print(f"✅ Chart generated successfully: {chart_path}")
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
    """Run tests."""
    print("\n" + "="*60)
    print("Chart Generator Test")
    print("="*60)
    
    # Test mplfinance chart generator
    chart_path = test_mplfinance_chart()
    
    print("\n" + "="*60)
    print("Summary")
    print("="*60)
    print(f"mplfinance chart: {'✅ Generated' if chart_path else '❌ Failed'}")
    
    if chart_path:
        print(f"\n✅ Chart generated successfully: {chart_path}")
        print("\n📊 Chart features:")
        print("   - Blue VWAP line (curved)")
        print("   - Purple EMA line (curved)")
        print("   - Candlesticks (green up, red down)")
        print("   - Shaded zones (Entry/Stop/TP)")
        print("   - Top-left title")
        print("   - Auto-fit to screen")
    else:
        print("\n⚠️  Chart generation failed. Check error messages above.")

if __name__ == "__main__":
    main()




