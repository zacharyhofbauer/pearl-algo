# Chart Visualization Guide

## Quick Start

1. **Install matplotlib** (if not already installed):
   ```bash
   pip install matplotlib>=3.8.0
   ```

2. **Charts are automatic**: When signals are generated, charts are sent to Telegram automatically

3. **View charts manually**: Use `/signals` command and tap "📊 Chart" buttons

4. **Test chart generation**:
   ```bash
   python3 scripts/testing/test_chart_generation.py
   ```

## Overview

The NQ Agent includes professional chart visualization capabilities using matplotlib. Charts are automatically generated for trading signals, entries, and exits, providing visual context for all trading decisions.

**Status**: ✅ Fully tested and working
- Entry charts: ✅ Working
- Exit charts: ✅ Working  
- Backtest charts: ✅ Working
- Short signals: ✅ Working
- Test signal generation: ✅ Working
- Error handling: ✅ Working
- Integration: ✅ Working

## Features

### Chart Types

1. **Entry Charts** - Generated when signals are created
   - Shows entry price, stop loss, and take profit levels
   - Displays recent price action (candlesticks)
   - Includes volume bars
   - Color-coded by direction (green for long, red for short)

2. **Exit Charts** - Generated when trades are closed
   - Shows full trade lifecycle
   - Displays entry and exit points
   - Includes P&L visualization
   - Shows stop loss and take profit levels for reference

3. **Backtest Charts** - Generated for strategy backtesting
   - Shows price action over backtest period
   - Displays all signal markers (long/short)
   - Visualizes signal distribution
   - Includes volume bars

### Chart Components

- **Candlestick Chart**: OHLCV price action (last 50-100 bars)
- **Entry Line**: Green (long) or Orange (short) horizontal line
- **Stop Loss Line**: Red dashed line
- **Take Profit Line**: Green dashed line
- **Exit Line**: Cyan line (for exit charts)
- **Volume Bars**: Color-coded volume bars below price chart
- **P&L Display**: Profit/loss annotation (for exit charts)

## Installation

### Dependencies

The chart visualization requires matplotlib:

```bash
pip install matplotlib>=3.8.0
```

Or install the full project:

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e .
```

### Verification

Test that matplotlib is installed correctly:

```bash
python3 -c "import matplotlib; print(f'Matplotlib {matplotlib.__version__} installed')"
```

## Usage

### Automatic Chart Generation

Charts are automatically generated and sent to Telegram when:

1. **Signal Generated**: Entry chart sent with signal notification
2. **Trade Entered**: Entry chart sent with entry confirmation
3. **Trade Exited**: Exit chart sent with exit notification and P&L

### Manual Chart Viewing

View charts for any signal via Telegram:

1. Send `/signals` command
2. Tap "📊 Chart" button for any signal
3. Chart will be sent as an image

### Test Signal Generation

Test chart visualization even when no real signals exist:

1. Send `/test_signal` command in Telegram
2. A test signal with chart will be generated
3. Use "🔄 Generate Another" to create more test signals

### Backtest Visualization

View backtest results with charts:

1. Send `/backtest` command in Telegram
2. System will run demo backtest (if buffer data available)
3. Backtest chart with signal markers will be sent
4. Shows strategy performance visualization

### Chart Generation Process

1. **Data Collection**: System retrieves OHLCV data from buffer
2. **Chart Creation**: matplotlib generates professional chart
3. **Image Export**: Chart saved as PNG (1200x800px)
4. **Telegram Upload**: Image sent to Telegram
5. **Cleanup**: Temporary file deleted

## Configuration

### Chart Settings

Charts are configured in `src/pearlalgo/nq_agent/chart_generator.py`:

- **Figure Size**: 12x8 inches (1200x800px at 100 DPI)
- **Theme**: Dark background for better visibility
- **Bars Displayed**: Last 50-100 bars (entry), 150 bars (exit)
- **Color Scheme**: 
  - Green: Long positions, profitable exits
  - Red: Short positions, losing exits
  - Cyan: Exit points

### Customization

To customize charts, edit `chart_generator.py`:

```python
# Change figure size
self.fig_size = (14, 10)  # Larger charts

# Change DPI (resolution)
self.dpi = 150  # Higher resolution

# Modify color scheme in _plot_candlesticks()
```

## Troubleshooting

### Charts Not Generating

**Issue**: Charts don't appear in Telegram

**Solutions**:
1. Check matplotlib installation:
   ```bash
   pip show matplotlib
   ```

2. Verify chart generator imports:
   ```bash
   python3 -c "from pearlalgo.nq_agent.chart_generator import ChartGenerator; print('OK')"
   ```

3. Check logs for errors:
   ```bash
   tail -f logs/telegram_handler.log | grep -i chart
   ```

### Empty Charts

**Issue**: Charts generated but show no data

**Solutions**:
1. Verify buffer data is available:
   - Check agent is running: `/status`
   - Verify buffer size > 0: Look for "Buffer: X bars"

2. Check data quality:
   - Ensure IBKR Gateway is connected
   - Verify data provider is working

### Chart Generation Errors

**Issue**: Errors in chart generation

**Common Causes**:
- Missing buffer data (agent not running)
- Invalid signal data (missing entry_price, stop_loss, etc.)
- Matplotlib backend issues

**Debug Steps**:
1. Check signal data structure:
   ```python
   # Signal must have: entry_price, stop_loss, take_profit, direction
   ```

2. Verify buffer data format:
   ```python
   # Buffer must have: open, high, low, close, volume, timestamp
   ```

3. Test chart generation directly:
   ```python
   from pearlalgo.nq_agent.chart_generator import ChartGenerator
   import pandas as pd
   
   generator = ChartGenerator()
   # Create test data and signal
   # Generate chart
   ```

## Testing

### Manual Testing

1. **Generate a Test Signal**:
   - Start agent: `/start_agent`
   - Wait for signal generation
   - Check Telegram for chart

2. **View Signal Chart**:
   - Send `/signals`
   - Tap "📊 Chart" button
   - Verify chart displays correctly

3. **Test Exit Chart**:
   - Wait for trade to exit
   - Check Telegram for exit notification with chart
   - Verify P&L is displayed

### Automated Testing

Create test script:

```python
#!/usr/bin/env python3
"""Test chart generation."""

import pandas as pd
from datetime import datetime, timezone, timedelta
from pearlalgo.nq_agent.chart_generator import ChartGenerator

# Create test data
dates = pd.date_range(end=datetime.now(timezone.utc), periods=100, freq='1min')
test_data = pd.DataFrame({
    'timestamp': dates,
    'open': [25000 + i * 0.5 for i in range(100)],
    'high': [25001 + i * 0.5 for i in range(100)],
    'low': [24999 + i * 0.5 for i in range(100)],
    'close': [25000.5 + i * 0.5 for i in range(100)],
    'volume': [1000] * 100,
})

# Create test signal
test_signal = {
    'entry_price': 25050.0,
    'stop_loss': 25000.0,
    'take_profit': 25100.0,
    'direction': 'long',
    'type': 'momentum_breakout',
    'symbol': 'MNQ',
}

# Generate chart
generator = ChartGenerator()
chart_path = generator.generate_entry_chart(test_signal, test_data, 'MNQ')

if chart_path and chart_path.exists():
    print(f"✅ Chart generated: {chart_path}")
    print(f"   Size: {chart_path.stat().st_size / 1024:.1f} KB")
else:
    print("❌ Chart generation failed")
```

Run test:

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python3 test_chart_generation.py
```

## Best Practices

1. **Data Quality**: Ensure buffer has sufficient data (50+ bars) before generating charts
2. **Error Handling**: Charts gracefully fail if data is missing (text notification still sent)
3. **Performance**: Charts are generated asynchronously to avoid blocking
4. **Storage**: Temporary files are automatically cleaned up after sending
5. **Resolution**: Use appropriate DPI (100-150) for Telegram (file size vs quality)

## Integration Points

### Telegram Notifier

Charts are integrated into:
- `send_signal()` - Entry charts for new signals
- `send_entry_notification()` - Entry charts for trade entries
- `send_exit_notification()` - Exit charts for trade exits

### Command Handler

Charts can be viewed via:
- `/signals` command - Chart buttons for each signal
- Callback handlers - `signal_chart_*` callbacks

### Service Integration

Charts receive data from:
- `data_fetcher.get_buffer()` - OHLCV data
- Signal data - Entry/stop/take-profit levels
- Performance tracker - Exit prices and P&L

## File Structure

```
src/pearlalgo/nq_agent/
├── chart_generator.py      # Chart generation module
├── telegram_notifier.py    # Chart integration
└── telegram_command_handler.py  # Chart viewing
```

## API Reference

### ChartGenerator Class

```python
class ChartGenerator:
    def generate_entry_chart(
        self,
        signal: Dict,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
    ) -> Optional[Path]:
        """Generate entry chart with entry/stop/TP levels."""
    
    def generate_exit_chart(
        self,
        signal: Dict,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        buffer_data: pd.DataFrame,
        symbol: str = "MNQ",
    ) -> Optional[Path]:
        """Generate exit chart with full trade lifecycle."""
```

## Examples

### Example Entry Chart

Shows:
- Entry: $25,050.00 (green line)
- Stop: $25,000.00 (red dashed)
- TP: $25,100.00 (green dashed)
- Recent price action (candlesticks)
- Volume bars

### Example Exit Chart

Shows:
- Entry: $25,050.00 (green line)
- Exit: $25,075.00 (cyan line)
- Stop: $25,000.00 (red dashed, reference)
- TP: $25,100.00 (green dashed, reference)
- P&L: +$500.00 (green annotation)
- Full trade duration (candlesticks)

## Support

For issues or questions:
1. Check logs: `logs/telegram_handler.log`
2. Verify dependencies: `pip list | grep matplotlib`
3. Test chart generation: Use test script above
4. Check Telegram bot permissions: Must be able to send photos

## Future Enhancements

Potential improvements:
- Multiple timeframe charts (1m, 5m, 15m)
- Indicator overlays (VWAP, moving averages)
- Support/resistance levels
- Trade annotations (entry/exit markers)
- Interactive charts (if Telegram supports)
- Chart templates for different signal types
