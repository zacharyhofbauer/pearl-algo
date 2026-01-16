# TradingView Chart Sync Guide

This guide explains how to keep your Python chart generator in sync with your TradingView setup.

## Quick Sync Methods

### Method 1: Share TradingView Chart Link

1. **In TradingView:**
   - Open your chart with all indicators and settings
   - Click the share icon (or go to Chart Layout > Share)
   - Copy the chart URL

2. **Sync to Python:**
   ```bash
   python scripts/sync_tradingview_chart.py
   # Choose option 1 and paste your URL
   ```

### Method 2: Export Chart Template

1. **In TradingView:**
   - Settings > Chart > Export Template
   - Save the template file

2. **Update Pine Scripts:**
   - Copy any updated Pine scripts to `resources/indicators/`
   - The Python implementations will need manual updates to match

### Method 3: Manual Indicator Sync

For each indicator you use in TradingView:

1. **Copy Pine Script:**
   - In TradingView, open the indicator
   - Click "Source" to view Pine code
   - Copy to `resources/indicators/<indicator_name>.pine`

2. **Update Python Implementation:**
   - Edit the corresponding file in `src/pearlalgo/strategies/nq_intraday/indicators/`
   - Match the logic from the Pine script

## Current Indicators

Your chart generator supports these TradingView-style indicators:

- ✅ **VWAP** (Volume Weighted Average Price) with bands
- ✅ **Moving Averages** (MA20, MA50, MA200)
- ✅ **RSI** (Relative Strength Index)
- ✅ **Buy/Sell Pressure** (volume-based)
- ✅ **Session Shading** (Tokyo/London/New York)
- ✅ **Key Levels** (RTH/ETH PDH/PDL/Open)
- ✅ **Supply/Demand Zones** (LuxAlgo style)
- ✅ **Power Channel** (ChartPrime style)
- ✅ **TBT Targets** (ChartPrime Trendline Breakouts)
- ✅ **Spaceman Key Levels** (higher timeframe levels)

## Chart Style Settings

Your chart generator uses TradingView dark theme colors:
- Background: `#0e1013`
- Grid: `#1e2127`
- Text: `#d1d4dc`
- Candles: Green `#26a69a` / Red `#ef5350`

These are hardcoded in `src/pearlalgo/nq_agent/chart_generator.py` to match TradingView.

## Keeping Indicators Updated

When you update an indicator in TradingView:

1. **Export the Pine script** from TradingView
2. **Save it** to `resources/indicators/`
3. **Update the Python port** in `src/pearlalgo/strategies/nq_intraday/indicators/`
4. **Test** by generating a chart via Telegram (📊 button)

## Automated Sync (Future)

For true live sync, you would need:
- TradingView API access (requires paid plan)
- Webhook integration
- Custom sync service

Currently, manual sync is the most reliable method.

## Troubleshooting

**Chart doesn't match TradingView:**
- Check that indicator settings match (periods, colors, etc.)
- Verify Pine script logic matches Python implementation
- Compare chart output side-by-side

**Missing indicators:**
- Add Pine script to `resources/indicators/`
- Port to Python in `src/pearlalgo/strategies/nq_intraday/indicators/`
- Register in `indicators/__init__.py`
