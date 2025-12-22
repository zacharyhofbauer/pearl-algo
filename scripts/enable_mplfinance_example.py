#!/usr/bin/env python3
"""
Simple example showing how to use the chart generator.

The chart generator now uses mplfinance by default.

Run this script:
    python3 scripts/enable_mplfinance_example.py
"""

from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

# Create generator (uses mplfinance by default)
config = ChartConfig()
generator = ChartGenerator(config)

print("✅ Chart generator is ready!")
print("\nTo use in your code:")
print("  from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig")
print("  generator = ChartGenerator()")
print("  chart_path = generator.generate_entry_chart(signal, data, 'MNQ', '1m')")

