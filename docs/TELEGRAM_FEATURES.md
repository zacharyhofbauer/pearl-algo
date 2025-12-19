# Telegram Bot Features Summary

## Overview

The NQ Agent Telegram bot provides a comprehensive UI-driven interface for monitoring and controlling the trading agent, with professional chart visualization capabilities.

## Core Features

### 1. UI-Driven Navigation
- **100% Button-Based**: No need to type commands
- **Contextual Buttons**: Adapt based on current state
- **Status Indicators**: Visual feedback (✅/❌) on buttons
- **Quick Actions**: Refresh, shortcuts, and navigation

### 2. Chart Visualization
- **Entry Charts**: Automatic charts with signals
- **Exit Charts**: Trade lifecycle with P&L
- **Backtest Charts**: Strategy performance visualization
- **Test Signals**: Generate test charts for testing

### 3. Service Control
- Start/Stop Agent and Gateway
- Restart functionality
- Status monitoring
- Health checks

### 4. Monitoring & Analysis
- Real-time status updates
- Signal tracking and viewing
- Performance metrics
- Active trades monitoring
- Backtest results

## Quick Reference

### Commands (Still Available)
- `/start` - Welcome message with main menu
- `/status` - Agent status with buttons
- `/signals` - Signal list with chart buttons
- `/test_signal` - Generate test signal with chart
- `/backtest` - Run backtest with chart
- `/performance` - Performance metrics
- `/last_signal` - Most recent signal
- `/active_trades` - Open positions

### Button Navigation

**Main Menu**:
- Service control (Start/Stop/Restart)
- Gateway status
- Monitoring (Status, Signals, Performance)
- Analysis (Backtest)
- Testing (Test Signal)
- Configuration (Config, Health, Help)

**Signals View**:
- Chart buttons for each signal
- Refresh and Last Signal shortcuts
- Navigation to Performance and Main Menu

**Gateway View**:
- Start/Stop Gateway
- Refresh status
- Navigation buttons

## Testing Features

### Test Signal Generation

**Purpose**: Test chart visualization when no real signals exist

**Usage**:
1. Send `/test_signal` or tap "🧪 Test Signal" button
2. System generates a test signal with realistic data
3. Chart is automatically sent
4. Use "🔄 Generate Another" to create more

**Features**:
- Realistic price action simulation
- Entry/Stop/TP levels displayed
- Professional chart formatting
- Instant feedback

### Backtest Visualization

**Purpose**: Visualize strategy performance on historical data

**Usage**:
1. Send `/backtest` or tap "📉 Backtest" button
2. System runs demo backtest (if data available)
3. Results and chart are sent
4. Shows signal markers on price chart

**Features**:
- Signal markers (long/short)
- Price action visualization
- Performance metrics
- Chart with all signals

## Chart Types

### Entry Chart
- Candlestick price action
- Entry line (green/orange)
- Stop loss line (red dashed)
- Take profit line (green dashed)
- Volume bars

### Exit Chart
- Full trade lifecycle
- Entry and exit points
- P&L annotation
- Reference stop/TP levels
- Color-coded by win/loss

### Backtest Chart
- Historical price action
- Signal markers (triangles)
- Long signals (green ▲)
- Short signals (orange ▼)
- Entry lines for each signal

## Best Practices

1. **Use Buttons First**: Navigate via UI buttons
2. **Test Charts**: Use `/test_signal` to verify chart generation
3. **Monitor Performance**: Check `/performance` regularly
4. **Backtest Strategy**: Use `/backtest` to visualize strategy
5. **Check Status**: Use `/status` as home base

## Troubleshooting

### Charts Not Generating
- Check matplotlib is installed: `pip install matplotlib`
- Verify chart generator: `/test_signal` should work
- Check logs: `tail -f logs/telegram_handler.log`

### Buttons Not Appearing
- Restart handler: `./scripts/telegram/start_command_handler.sh --background`
- Check handler status: `./scripts/telegram/check_command_handler.sh`
- Verify authorization (chat ID)

### Test Signal Not Working
- Ensure matplotlib installed
- Check handler logs for errors
- Try `/status` first to verify bot is responsive

## Integration Points

- **Service**: Automatically sends charts with signals
- **Command Handler**: Chart viewing via buttons
- **Performance Tracker**: Exit charts with P&L
- **Backtest Adapter**: Backtest chart generation

## File Locations

- Chart Generator: `src/pearlalgo/nq_agent/chart_generator.py`
- Command Handler: `src/pearlalgo/nq_agent/telegram_command_handler.py`
- Notifier: `src/pearlalgo/nq_agent/telegram_notifier.py`
- Documentation: `docs/CHART_VISUALIZATION.md`, `docs/TELEGRAM_MENU_GUIDE.md`
