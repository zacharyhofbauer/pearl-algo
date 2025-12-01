# Live Trading Guide

## Quick Start - Test Trading Works

### Step 1: Start Trading (Terminal 1)

**Option A: Test with single symbol (recommended first)**
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Test with MES only, 30 second intervals
pearlalgo --verbosity VERBOSE trade auto \
  --symbols MES \
  --strategy sr \
  --interval 30 \
  --tiny-size 1 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 11 \
  --log-file logs/test_trading.log
```

**Option B: Full micro strategy**
```bash
bash scripts/start_micro.sh
```

### Step 2: Monitor Live Activity (Terminal 2)

**NEW: Live Trading Monitor (Best for real-time activity)**
```bash
pearlalgo monitor
```

This shows:
- ✅ Latest trades as they execute (with P&L, prices, status)
- ✅ Latest signals in real-time
- ✅ Performance summary (P&L, trade counts, risk status)
- ✅ Auto-refreshes every 2 seconds

**Alternative: Status Dashboard**
```bash
pearlalgo dashboard
```

### Step 3: Watch Logs (Terminal 3 - Optional)

```bash
# Watch trading decisions
tail -f logs/micro_trading.log

# Or for test
tail -f logs/test_trading.log
```

## What to Look For

### In the Monitor (`pearlalgo monitor`):

1. **Latest Trades Panel**: Should show new rows appearing as trades execute
   - Time, Symbol, Side (LONG/SHORT), Size, Price, P&L, Risk Status
   - Green = profit, Red = loss
   - Updates every 2 seconds

2. **Latest Signals Panel**: Shows signals being generated
   - BUY/SELL/FLAT signals
   - Updates when new signals are generated

3. **Performance Summary**: Shows running totals
   - Daily P&L updates in real-time
   - Trade counts increment
   - Risk status changes

### In the Console Output:

You should see:
```
🔍 Analyzing MES...
📊 Fetching market data for MES...
✅ Data received: 288 bars, latest price: $X,XXX.XX
🧠 Generating sr signal...
💰 Computing position size...
✅ EXECUTING: LONG 1 contract(s) @ $X,XXX.XX
```

## Troubleshooting

### No Trades Appearing?

1. **Check Gateway is running:**
   ```bash
   pearlalgo gateway status
   ```

2. **Check if process is running:**
   ```bash
   ps aux | grep "pearlalgo trade auto" | grep -v grep
   ```

3. **Check logs for errors:**
   ```bash
   tail -50 logs/micro_console.log
   tail -50 logs/micro_trading.log
   ```

4. **Verify signals are being generated:**
   ```bash
   pearlalgo signals --strategy sr --symbols MES
   ```

5. **Check if market is open:**
   - Futures trade nearly 24/5, but check your timezone
   - Some symbols may have limited hours

### Process Keeps Dying?

1. **Check for errors in console log:**
   ```bash
   cat logs/micro_console.log
   ```

2. **Try running in foreground to see errors:**
   ```bash
   pearlalgo --verbosity VERBOSE trade auto --symbols MES --strategy sr --interval 30 --tiny-size 1
   ```

3. **Check Gateway connection:**
   ```bash
   pearlalgo gateway status
   ```

### Monitor Not Updating?

1. **Make sure trading is actually running:**
   ```bash
   ps aux | grep "pearlalgo trade auto"
   ```

2. **Check if performance log exists:**
   ```bash
   ls -lh data/performance/futures_decisions.csv
   ```

3. **Try refreshing manually:**
   ```bash
   pearlalgo status  # Should show latest data
   ```

## Expected Behavior

### When Trading is Working:

1. **Every 30-60 seconds** (depending on interval):
   - Console shows analysis for each symbol
   - Signal is generated (LONG/SHORT/FLAT)
   - If signal is not FLAT, trade may execute

2. **Monitor updates every 2 seconds:**
   - New trades appear in "Latest Trades" panel
   - Performance numbers update
   - Signal panel shows latest signals

3. **Logs show activity:**
   - `micro_trading.log` shows performance rows
   - `micro_console.log` shows detailed output

### When No Trades:

- Signals show "FLAT" - this is normal, means no trade opportunity
- Risk status might be blocking trades (check risk panel)
- Market might be closed or low volatility

## Commands Reference

```bash
# Start trading
pearlalgo trade auto --symbols MES --strategy sr --interval 30

# Monitor live activity
pearlalgo monitor

# Check status
pearlalgo status

# View dashboard
pearlalgo dashboard

# Stop trading
pkill -f "pearlalgo trade auto"
```

## Next Steps

Once you verify trading works:

1. **Increase symbols**: Add more micro contracts
2. **Adjust interval**: Change from 30s to 60s for less frequent checks
3. **Monitor risk**: Use `pearlalgo trade monitor` to watch risk limits
4. **Review performance**: Check `pearlalgo report` for daily summary

