# Quick Start: Using mplfinance Chart Generator

## Problem Solved

The mplfinance implementation fixes all the issues with the matplotlib-based charts:
- ✅ Proper candlestick rendering (not '+' markers)
- ✅ Correct candle spacing (80% of interval)
- ✅ Automatic volume panel with color-coding
- ✅ Proper gridlines
- ✅ Better axis styling

## Installation

```bash
pip install mplfinance
```

Or it's already added to `pyproject.toml` dependencies.

## Usage

### Option 1: Use mplfinance by default

```python
from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig

# Enable mplfinance
config = ChartConfig(use_mplfinance=True)
generator = ChartGenerator(config)

# Generate chart (automatically uses mplfinance)
chart_path = generator.generate_entry_chart(
    signal=signal_dict,
    buffer_data=dataframe,
    symbol="MNQ",
    timeframe="1m"
)
```

### Option 2: Use mplfinance directly

```python
from pearlalgo.nq_agent.chart_generator_mplfinance import (
    MplfinanceChartGenerator,
    MplfinanceChartConfig
)

# Create generator
config = MplfinanceChartConfig(
    show_vwap=True,
    show_ma=True,
    ma_periods=[20, 50],
    show_entry_sl_tp_bands=True
)
generator = MplfinanceChartGenerator(config)

# Generate chart
chart_path = generator.generate_entry_chart(
    signal=signal_dict,
    buffer_data=dataframe,
    symbol="MNQ",
    timeframe="1m"
)
```

## Configuration

The `MplfinanceChartConfig` supports:
- `show_vwap`: Show VWAP line
- `show_ma`: Show moving averages
- `ma_periods`: List of MA periods (e.g., [20, 50])
- `signal_marker_size`: Size of signal markers
- `max_signals_displayed`: Maximum signals to show
- `cluster_signals`: Enable signal clustering
- `show_performance_metrics`: Show performance stats
- `timeframe`: Chart timeframe
- `show_entry_sl_tp_bands`: Show shaded bands for Entry/SL/TP
- `candle_width`: Candle width (default 0.8 = 80% of interval)

## Comparison

### Before (matplotlib)
- ❌ Candles appear as '+' markers
- ❌ Incorrect spacing
- ❌ Missing gridlines
- ❌ Manual volume panel setup
- ❌ Signal marker offset issues

### After (mplfinance)
- ✅ Proper candlestick rendering
- ✅ Correct spacing automatically
- ✅ Gridlines included
- ✅ Volume panel built-in
- ✅ Professional appearance

## Migration

1. **Install mplfinance**: `pip install mplfinance`
2. **Update your code**: Add `use_mplfinance=True` to ChartConfig
3. **Test**: Generate a chart and compare
4. **Deploy**: If satisfied, keep the setting enabled

## Troubleshooting

### Import Error
```
ImportError: mplfinance required. Install with: pip install mplfinance
```
**Solution**: `pip install mplfinance`

### Chart looks different
This is expected - mplfinance uses a different rendering engine that produces more accurate financial charts.

### Need more customization
mplfinance has extensive customization options. See the `_create_tradingview_style()` method in `chart_generator_mplfinance.py` for examples.

## Next Steps

1. Test the mplfinance implementation
2. Compare output with matplotlib version
3. If satisfied, set `use_mplfinance=True` as default
4. Consider removing matplotlib implementation if no longer needed
