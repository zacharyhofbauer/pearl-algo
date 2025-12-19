# Chart Visualization System - Build Explanation

## Overview

This is a professional TradingView-style candlestick chart visualization system built for a trading bot (PEARLalgo NQ Agent) that generates real-time and backtest trading charts. The system is implemented in Python using matplotlib and provides TradingView-quality visualizations with signal markers, technical indicators, and performance metrics.

## Architecture

### Core Components

**1. ChartGenerator Class** (`src/pearlalgo/nq_agent/chart_generator.py`)
- Main chart generation engine
- Supports entry charts, exit charts, and backtest charts
- Implements TradingView-style candlestick rendering
- Handles technical indicators (VWAP, Moving Averages)
- Manages signal marker positioning and clustering

**2. ChartConfig Dataclass**
- Configuration system for chart customization
- Controls indicator visibility, timeframe, signal display limits
- Default settings optimized for TradingView aesthetics

**3. Integration Points**
- Telegram command handler for user interaction
- Backtest adapter for historical analysis
- Real-time data feed integration

## Key Features

### Chart Types

**Entry Charts**
- Shows entry price, stop loss, and take profit levels
- Displays recent price action (50-100 bars)
- Includes VWAP and moving averages
- Color-coded by trade direction

**Exit Charts**
- Shows full trade lifecycle
- Displays entry and exit points
- Includes P&L visualization
- Shows stop loss and take profit levels for reference

**Backtest Charts**
- Shows price action over backtest period
- Displays all signal markers (long/short triangles)
- Includes performance metrics panel
- Supports multiple timeframes (1m, 5m, 15m)

### Technical Implementation

**Candlestick Rendering**
- Uses matplotlib Rectangle patches for candle bodies
- Vlines for wicks (high-low lines)
- TradingView color scheme:
  - Green (#089981) for bullish candles (close >= open)
  - Red (#f23645) for bearish candles (close < open)
- Proper z-ordering: wicks (zorder=1), bodies (zorder=3)
- Candle width: 0.8 for optimal visibility

**Signal Markers**
- Green upward triangles for LONG signals
- Red downward triangles for SHORT signals
- Dynamic positioning with collision detection
- Clustering for dense signal regions
- Smart offset calculation based on price range

**Technical Indicators**
- VWAP (Volume-Weighted Average Price) - orange line
- Moving Averages (SMA) - configurable periods (default: 20, 50)
- Color-coded indicators matching TradingView style

**Performance Metrics Panel**
- Displays at bottom of backtest charts
- Shows: Total signals, Avg confidence, Avg R:R, Win rate, Total P&L
- Positioned in reserved 12% bottom space
- Bold text with dark background for visibility

## Styling & Aesthetics

**Color Scheme (TradingView Dark Theme)**
- Background: #131722 (dark blue-gray)
- Text: #d1d4dc (light gray)
- Labels/Axes: #787b86 (medium gray)
- Grid: #2a2e39 (subtle dark gray)
- Bullish: #089981 (green)
- Bearish: #f23645 (red)

**Layout**
- Figure size: 12x8 inches
- DPI: 150 (optimized for Telegram)
- Subplot layout: Price chart (75%), Volume chart (25%)
- Performance panel: 12% bottom space reserved

## Data Flow

**Chart Generation Process:**
1. Data preparation: OHLCV data with timestamps
2. Timeframe resampling (if needed): Converts 1m to 5m, 15m, etc.
3. Candlestick rendering: Draws rectangles and wicks
4. Indicator calculation: VWAP and MA overlays
5. Signal positioning: Calculates optimal marker positions
6. Metadata addition: Timeframe, bar count, time range
7. Performance metrics: Adds stats panel (backtest only)
8. Export: Saves as PNG to temporary file

## Key Algorithms

**Signal Marker Positioning:**
- Binary search for timestamp matching
- Fallback to price-based positioning
- Dynamic offset calculation (3% of price range)
- Collision detection to prevent overlap
- Clustering for dense regions (signals within threshold distance)

**Candlestick Color Logic:**
- `is_bullish = closes[i] >= opens[i]`
- Bullish → Green (#089981)
- Bearish → Red (#f23645)
- OHLC validation ensures: High >= max(Open, Close), Low <= min(Open, Close)

**Data Resampling:**
- Supports 1m, 5m, 15m, 1h timeframes
- OHLC aggregation: Open (first), High (max), Low (min), Close (last)
- Volume: Summed across period

## Configuration

**ChartConfig Options:**
- `show_vwap: bool = True`
- `show_ma: bool = True`
- `ma_periods: List[int] = [20, 50]`
- `signal_marker_size: int = 300`
- `max_signals_displayed: int = 50`
- `cluster_signals: bool = True`
- `show_performance_metrics: bool = True`
- `timeframe: str = "1m"`

## Integration

**Telegram Bot Integration:**
- `/backtest` command generates backtest charts
- `/test_signal` command generates test entry charts
- Charts sent as PNG images
- Performance data passed from backtest results

**Backtest Integration:**
- Receives signals and OHLCV data from backtest adapter
- Calculates performance metrics (win rate, P&L, R:R)
- Supports demo data for testing

## Recent Improvements

**Fixed Issues:**
1. **Green bars only**: Fixed demo data generation to create realistic mixed bullish/bearish candles
2. **Timeframe display**: Added timeframe to both chart title and metadata (always visible, including "1m")
3. **Signal positioning**: Implemented collision detection and smart positioning
4. **Performance panel**: Fixed positioning to be visible at bottom of charts
5. **TradingView styling**: Applied exact color scheme and styling

**Enhancements:**
- Proper candlestick rendering with filled rectangles
- Signal clustering for dense regions
- Enhanced visual hierarchy
- Improved legend and metadata display
- Multi-timeframe support with resampling

## File Structure

```
src/pearlalgo/nq_agent/
├── chart_generator.py       # Core chart generation (1300+ lines)
│   ├── ChartConfig          # Configuration dataclass
│   ├── ChartGenerator       # Main chart generation class
│   │   ├── draw_candles()   # Candlestick rendering
│   │   ├── generate_entry_chart()
│   │   ├── generate_exit_chart()
│   │   ├── generate_backtest_chart()
│   │   ├── _plot_backtest_price_action()
│   │   ├── _plot_vwap()
│   │   ├── _plot_moving_averages()
│   │   └── _add_performance_panel()
│   └── _add_chart_metadata()

src/pearlalgo/nq_agent/
└── telegram_command_handler.py
    ├── _handle_backtest()   # Backtest chart generation
    └── _handle_test_signal() # Test signal charts

src/pearlalgo/strategies/nq_intraday/
└── backtest_adapter.py
    ├── BacktestResult       # Performance metrics dataclass
    └── run_signal_backtest()
```

## Technical Stack

- **Language**: Python 3.x
- **Visualization**: matplotlib (Agg backend for non-interactive)
- **Data**: pandas DataFrames (OHLCV)
- **Integration**: python-telegram-bot
- **Configuration**: dataclasses

## Usage Example

```python
from pearlalgo.nq_agent.chart_generator import ChartGenerator, ChartConfig
import pandas as pd

# Initialize chart generator
generator = ChartGenerator()

# Or with custom config
config = ChartConfig(timeframe="5m", show_vwap=True, show_ma=True)
generator = ChartGenerator(config=config)

# Generate backtest chart
chart_path = generator.generate_backtest_chart(
    backtest_data=df,  # DataFrame with OHLCV + timestamp
    signals=signals_list,  # List of signal dicts
    symbol="MNQ",
    title="Backtest Results",
    performance_data={
        "total_signals": 10,
        "avg_confidence": 0.75,
        "avg_risk_reward": 1.5,
        "win_rate": 60.0,
        "total_pnl": 1250.0
    }
)
```

## Data Requirements

**Input DataFrame Structure:**
- Columns: `timestamp`, `open`, `high`, `low`, `close`, `volume`
- `timestamp`: pandas DatetimeIndex or datetime column (UTC)
- OHLC: float values
- Volume: float values
- Must have valid OHLC relationships: High >= max(Open, Close), Low <= min(Open, Close)

**Signal Dictionary Structure:**
```python
{
    "entry_price": float,
    "stop_loss": float,
    "take_profit": float,
    "direction": "long" | "short",
    "type": str,
    "timestamp": str,  # ISO format datetime
    "confidence": float,  # Optional
}
```

## Performance Considerations

- Charts generated asynchronously to avoid blocking
- Temporary files automatically cleaned up after sending
- Efficient rendering using categorical x-axis indices (prevents diagonal banding)
- Signal clustering reduces rendering overhead for dense signal sets
- Configurable signal display limits prevent visual clutter

## Testing

Unit tests in `tests/test_chart_generator.py` verify:
- Rectangle count matches bar count
- Wick count matches bar count
- Categorical x-axis (no datetime floats)
- Candle spacing (no overlapping)
- Background color correctness
- Price axis positioning

## Future Enhancements (Planned/Mentioned)

- Multiple timeframe subplot layouts
- Additional indicators (RSI, MACD, Bollinger Bands)
- Trade annotations with P&L per trade
- Interactive chart support (if Telegram allows)
- Chart templates for different signal types
- Customizable color schemes

## Research References

This implementation follows TradingView's visual style and uses similar approaches to:
- mplfinance library for candlestick charting concepts
- Professional trading platforms for signal visualization
- Industry-standard color schemes and layouts

The codebase is production-ready and handles both real-time trading signals and historical backtest visualization with professional-grade aesthetics matching TradingView's dark theme.
