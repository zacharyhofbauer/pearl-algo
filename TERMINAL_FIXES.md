# Terminal Fixes & Improvements

## Issues Fixed

### 1. ✅ Strategy Recognition
**Problem:** Scalping and intraday_swing strategies weren't recognized
**Fix:** Updated `generate_signal()` to check strategy registry first before falling back to built-in strategies

### 2. ✅ Terminal Layout - Positions Priority
**Problem:** Positions panel was too narrow
**Fix:** 
- Increased left panel ratio from 1 to 2 (positions get more width)
- Increased positions panel ratio from 2 to 3 (positions get more vertical space)
- Added `expand=True` to positions table for better use of space

### 3. ✅ Position Aggregation
**Problem:** Only showing one position, not all positions from all strategies
**Fix:**
- Improved `get_positions()` to aggregate positions by symbol and side
- Now shows all open positions from all strategies
- Aggregates multiple positions of same symbol/side into one row
- Shows strategy name for each position

### 4. ✅ Terminal Refresh
**Problem:** Terminal not updating properly, stuck on 1s refresh
**Fix:**
- Added `auto_refresh=True` to Live context
- Force update on each iteration
- Proper refresh rate calculation

### 5. ✅ Better Position Display
**Added:**
- Position count in title: "Open Positions (N)"
- Strategy column to show which strategy opened the position
- Wider columns for better readability
- Better formatting for prices and P&L

## Multiple Ports/Client IDs

If you see 5 ports open, that's because:
- Each strategy uses a different IB client ID to avoid conflicts
- Scalping: Client ID 10
- Intraday Swing: Client ID 11
- SR: Client ID 12
- Plus any other processes you might have running

This is **normal and expected**. Each strategy needs its own client ID.

## How to Verify Everything Works

### 1. Check Strategies Are Running
```bash
ps aux | grep "pearlalgo trade auto"
```

### 2. Check Logs for Errors
```bash
tail -f logs/micro_scalping_console.log
tail -f logs/micro_swing_console.log
tail -f logs/micro_sr_console.log
```

### 3. Check Performance Log for Positions
```bash
# View all open positions
python -c "
from pearlalgo.futures.performance import load_performance, DEFAULT_PERF_PATH
from datetime import datetime, timezone
import pandas as pd

df = load_performance(DEFAULT_PERF_PATH)
today = datetime.now(timezone.utc).strftime('%Y%m%d')
today_df = df[df['timestamp'].dt.strftime('%Y%m%d') == today] if 'timestamp' in df.columns and not df.empty else pd.DataFrame()
open_positions = today_df[today_df['exit_time'].isna()] if 'exit_time' in today_df.columns else pd.DataFrame()
print(f'Open positions: {len(open_positions)}')
for _, row in open_positions.iterrows():
    print(f\"  {row.get('symbol')} {row.get('side')} {row.get('filled_size')} @ {row.get('entry_price')}\")
"
```

### 4. Restart Strategies
```bash
# Stop all
bash scripts/stop_all_micro_strategies.sh

# Start all
bash scripts/start_all_micro_strategies.sh

# Wait a minute, then check terminal
pearlalgo terminal
```

## Terminal Usage

### Start Terminal
```bash
pearlalgo terminal
```

### Custom Refresh Rate
```bash
# Faster updates (0.5 seconds)
pearlalgo terminal --refresh 0.5

# Slower updates (2 seconds)
pearlalgo terminal --refresh 2.0
```

## What You Should See

1. **Header:** Shows current time and LIVE status
2. **Open Positions Panel (Left, Large):**
   - All positions from all strategies
   - Aggregated by symbol/side
   - Shows P&L, entry, mark price
   - Shows which strategy opened it
3. **Active Orders Panel:** Shows pending orders
4. **Chart Panel:** Placeholder for now
5. **Signals Panel:** Latest trading signals
6. **Market Data Panel:** Live market prices (when connected)
7. **Performance Panel:** Daily P&L, win rate, risk status

## Troubleshooting

### Terminal Not Updating
1. Check refresh rate: `pearlalgo terminal --refresh 0.5`
2. Restart terminal
3. Check if strategies are actually running

### Not Seeing All Positions
1. Check performance log exists: `ls -la data/performance/futures_decisions.csv`
2. Check for open positions in log (see command above)
3. Make sure strategies are running and trading

### Too Many Ports
- This is normal - each strategy needs its own client ID
- If you want fewer, stop some strategies
- Or edit the start script to use fewer strategies

## Next Steps

1. **Restart all strategies:**
   ```bash
   bash scripts/stop_all_micro_strategies.sh
   bash scripts/start_all_micro_strategies.sh
   ```

2. **Start terminal:**
   ```bash
   pearlalgo terminal
   ```

3. **Monitor for a few minutes** to see positions appear as trades execute

---

*All fixes are now in place! 🚀*

