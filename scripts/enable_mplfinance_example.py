#!/usr/bin/env python3
"""
Simple example showing how to enable mplfinance chart generator.

Run this script:
    python3 scripts/enable_mplfinance_example.py
"""

from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

# Enable mplfinance by setting use_mplfinance=True
config = ChartConfig(use_mplfinance=True)

# Create generator (will automatically use mplfinance)
generator = ChartGenerator(config)

print("✅ mplfinance is now enabled!")
print("\nTo use in your code:")
print("  config = ChartConfig(use_mplfinance=True)")
print("  generator = ChartGenerator(config)")
print("  chart_path = generator.generate_entry_chart(signal, data, 'MNQ', '1m')")
