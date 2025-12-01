# PearlAlgo Futures Trading Dashboard

## Overview

The PearlAlgo Futures Trading Dashboard is a quant-grade terminal-based dashboard designed for professional futures traders. It provides real-time monitoring of trading performance, risk metrics, and signal context.

## Running the Dashboard

### Basic Usage

```bash
# Show dashboard once and exit
python scripts/status_dashboard.py

# Live updating dashboard (refreshes every 5 seconds)
python scripts/status_dashboard.py --live
```

### Command-Line Options

- `--live`: Enable live updating mode (refreshes every 5 seconds)
- `--once`: Show dashboard once and exit (default behavior)

## Dashboard Sections

### Header Section

Displays:
- System name and branding
- Current UTC timestamp
- US Eastern time (EST/EDT)
- IB Gateway status (✅ Running / ❌ Not Running)
- IB Gateway version information

### Risk Summary Panel

Comprehensive risk metrics including:

- **Risk State**: Current risk status with color coding
  - ✅ **OK** (green): Drawdown < 50% of daily loss limit
  - ⚠️ **NEAR_LIMIT** (yellow): Drawdown 50-80% of daily loss limit
  - ❌ **HARD_STOP** (red): Drawdown > 80% of daily loss limit or trading halted

- **Remaining Drawdown**: Available loss buffer before hitting daily limit
- **Daily Loss Limit**: Maximum allowed loss per day (from PropProfile)
- **Drawdown Used**: Percentage of daily loss limit consumed
- **Sharpe Ratio**: Risk-adjusted return metric (higher is better)
- **Sortino Ratio**: Downside risk-adjusted return (focuses on negative returns)
- **Total P&L**: Realized and unrealized P&L breakdown

### Per-Symbol Metrics Table

For each traded symbol, displays:

- **Symbol**: Trading symbol (ES, NQ, GC, etc.)
- **Contract**: Contract month (if available)
- **Last Signal**: Timestamp of most recent signal
- **Side**: Signal direction (LONG/SHORT/FLAT) with color coding
- **Realized P&L**: Cumulative realized profit/loss for the symbol
- **Unrealized P&L**: Current unrealized profit/loss from open positions
- **Risk**: Risk state indicator (✅/⚠️/❌)
- **Position**: Current position size
- **Trades**: Number of trades executed today
- **Max**: Maximum contracts allowed per symbol (from PropProfile)

### Latest Signal Context Table

Shows the last 2-3 signals per symbol with technical analysis context:

- **Symbol**: Trading symbol
- **Strategy**: Strategy type (ma_cross, sr)
- **Direction**: Signal direction (LONG/SHORT/FLAT)
- **Entry**: Entry price for the signal
- **Stop**: Stop-loss price
- **Target**: Target/profit-taking price
- **VWAP**: Volume-Weighted Average Price
- **Pivots**: Support and resistance levels (S1, R1)
- **Reason**: Trade reasoning/context from strategy

### Trade Statistics Panel

Comprehensive trade performance metrics:

- **Total Trades**: Number of completed trades
- **Winners**: Count and percentage of winning trades
- **Losers**: Count and percentage of losing trades
- **Avg Hold Time**: Average time in trade (minutes)
- **Largest Winner**: Best trade P&L
- **Largest Loser**: Worst trade P&L
- **Avg P&L/Trade**: Average profit/loss per trade

### Files & Logs Panel

Shows paths to key workflow files:

- **Signals**: Latest signals CSV file (`signals/YYYYMMDD_signals.csv`)
- **Report**: Latest daily report (`reports/YYYYMMDD_report.md`)
- **Perf CSV**: Performance log (`data/performance/futures_decisions.csv`)

Files are marked with ✅ if they exist, ❌ if missing.

## Risk Formulas

### Drawdown Calculation

```
Remaining Drawdown = Daily Loss Limit + Net P&L
Drawdown Used % = ((Daily Loss Limit - Remaining Drawdown) / Daily Loss Limit) × 100
```

Where Net P&L = Realized P&L + Unrealized P&L

### Sharpe Ratio

```
Sharpe Ratio = (Mean Return - Risk-Free Rate) / Standard Deviation of Returns
```

- Computed from P&L returns (differences between consecutive realized P&L values)
- Risk-free rate defaults to 0.0 for intraday trading
- Higher values indicate better risk-adjusted returns

### Sortino Ratio

```
Sortino Ratio = (Mean Return - Risk-Free Rate) / Downside Deviation
```

- Similar to Sharpe but uses only negative returns (downside deviation)
- Better metric for traders concerned about downside risk
- Higher values indicate better downside risk-adjusted returns

### Risk State Logic

The dashboard automatically computes risk state based on:

1. **Drawdown Percentage**:
   - < 50%: OK (green)
   - 50-80%: NEAR_LIMIT (yellow)
   - > 80%: HARD_STOP (red)

2. **Daily Loss Limit**: If net P&L <= -daily_loss_limit, status is HARD_STOP

3. **Trade Limits**: If max_trades reached, status is COOLDOWN

4. **Session Times**: If outside allowed trading hours, status is PAUSED

## Interpreting Per-Symbol Metrics

### Position Size

- Shows current position size from latest filled orders
- Positive = long position, negative = short position
- Zero = flat/no position

### Realized vs Unrealized P&L

- **Realized P&L**: Profit/loss from closed positions (cumulative)
- **Unrealized P&L**: Current profit/loss from open positions (mark-to-market)

### Risk Indicators

- ✅ Green: Symbol is within normal risk parameters
- ⚠️ Yellow: Symbol approaching risk limits
- ❌ Red: Symbol at or beyond risk limits

## Data Sources

The dashboard reads from:

1. **Performance Log**: `data/performance/futures_decisions.csv`
   - Contains all trading decisions, fills, and P&L data
   - Updated in real-time during trading

2. **Signals CSV**: `signals/YYYYMMDD_signals.csv`
   - Latest signals generated by strategies
   - Contains symbol, direction, size_hint, timestamp

3. **Reports**: `reports/YYYYMMDD_report.md`
   - Daily summary reports
   - Contains trade history and performance summaries

4. **PropProfile**: `config/prop_profile.yaml` (or defaults)
   - Risk limits, position sizing, trade limits
   - Loaded via `pearlalgo.futures.config.load_profile()`

## Troubleshooting

### Dashboard Shows "No data"

- Ensure trading has been executed (performance log exists)
- Check that `data/performance/futures_decisions.csv` exists and has data
- Verify date filtering (dashboard shows today's data by default)

### Missing Signals

- Check that signals CSV exists in `signals/` directory
- Verify signal generation is running
- Look for files matching pattern `*_signals.csv`

### Gateway Status Shows "Not Running"

- Start IB Gateway: `pearlalgo gateway start`
- Check if process is running: `pgrep -f IbcGateway`
- Verify port 4002 is listening: `ss -tlnp | grep 4002`

### Incorrect P&L Values

- Verify performance log has correct `realized_pnl` and `unrealized_pnl` columns
- Check that timestamps are in UTC
- Ensure data is being logged correctly by trading system

## Advanced Usage

### Custom Refresh Rate

Modify the `time.sleep(5)` value in the `--live` mode to change refresh interval.

### Filtering by Date

The dashboard automatically filters to today's data. To view historical data, modify the `today` variable in the dashboard code.

### Adding Custom Metrics

Extend the dashboard by adding new functions and panels:

1. Create computation function (e.g., `compute_custom_metric()`)
2. Create panel function (e.g., `create_custom_panel()`)
3. Add to layout in `create_dashboard()`

## Performance Considerations

- Dashboard refresh rate: 5 seconds in live mode
- Data loading: Performance log is loaded on each refresh
- Memory usage: Minimal (pandas DataFrames are small for daily data)

## Related Documentation

- `QUICK_START.md`: Quick start guide for the trading system
- `CHEAT_SHEET.txt`: Quick reference for common commands
- `src/pearlalgo/futures/risk.py`: Risk calculation implementation
- `src/pearlalgo/futures/performance.py`: Performance logging implementation

