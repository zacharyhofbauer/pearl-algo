#!/usr/bin/env python3
"""
Generate a test chart to visually inspect the chart style.

This script generates a chart matching the test picture style:
- Blue VWAP line
- Purple EMA line
- Candlesticks (green up, red down)
- Shaded zones (Entry/Stop/TP)
- Top-left title
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

import pandas as pd
from datetime import datetime, timezone
from pearlalgo.nq_agent.chart_generator import ChartGenerator

def main():
    """Generate a test chart."""
    # Create sample data
    data = pd.DataFrame({
        'timestamp': pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1min'),
        'open': [25000 + i * 0.3 + (i % 3 - 1) * 0.2 for i in range(100)],
        'high': [25001 + i * 0.3 + abs(i % 3 - 1) * 0.3 for i in range(100)],
        'low': [24999 + i * 0.3 - abs(i % 3 - 1) * 0.3 for i in range(100)],
        'close': [25000.5 + i * 0.3 + (i % 3 - 1) * 0.1 for i in range(100)],
        'volume': [1000 + (i % 10) * 100 for i in range(100)]
    })
    
    # Create test signal
    signal = {
        'entry_price': 25025.0,
        'stop_loss': 25000.0,
        'take_profit': 25050.0,
        'direction': 'long',
        'type': 'momentum_breakout',
        'reason': 'test signal'
    }
    
    # Generate chart
    generator = ChartGenerator()
    chart_path = generator.generate_entry_chart(signal, data, 'MNQ', '1m')
    
    if chart_path:
        print(f"✅ Chart generated successfully!")
        print(f"   Path: {chart_path}")
        print(f"   Features:")
        print(f"   - Blue VWAP line (curved)")
        print(f"   - Purple EMA line (curved)")
        print(f"   - Candlesticks (green up, red down)")
        print(f"   - Shaded zones (Entry/Stop/TP)")
        print(f"   - Top-left title")
        print(f"   - Auto-fit to screen")
        return 0
    else:
        print("❌ Chart generation failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
