# 🔧 Troubleshooting - Agent Status

## "Sleeping" After First Cycle - Is This Normal?

**YES! This is completely normal.** Here's what's happening:

### What "Sleeping" Means

After the agent processes all symbols in a cycle, it:
1. ✅ Shows a summary of what happened
2. ⏳ Waits for the next cycle (sleeps)
3. 🔄 Starts the next cycle when the interval is up

### Example Flow

```
Cycle #1 - 2025-01-27 14:30:00 UTC
  🔍 Analyzing NQ
  📊 Fetching data...
  🤔 Analysis table...
  ✅ Trade executed (or ⚪ FLAT signal)

📊 Cycle Summary
  ✅ Cycle #1 Complete
  Symbols Processed: 1
  Trades Today: 1
  Daily P&L: $0.00
  Next cycle in 60s

⏳ Waiting for Cycle #2... [████████░░] 80% (12s remaining)
```

**This is working correctly!** It's just waiting for the next cycle.

## How to Tell If It's Working

### ✅ Working Correctly:
- You see "Cycle #1", "Cycle #2", etc.
- You see analysis tables for each symbol
- You see "Cycle Complete" summary
- Progress bar shows countdown to next cycle
- It processes symbols every cycle

### ❌ Not Working (Stuck):
- No cycle numbers incrementing
- No analysis tables appearing
- Stuck on "Connecting..." or "Fetching data..."
- Error messages repeating
- No progress bar during sleep

## Common Issues

### Issue 1: "Outside market hours, sleeping..."
**Solution**: This is normal if it's weekend or outside trading hours. The agent checks market hours and waits.

### Issue 2: No trades executing
**Possible reasons**:
- All signals are FLAT (no trading opportunities)
- Risk state is COOLDOWN/PAUSED
- Position size is 0 (blocked by risk limits)

**Check**: Look at the analysis tables - they show why trades are/aren't happening.

### Issue 3: "No data available"
**Solution**: 
- Check IB Gateway is running: `sudo systemctl status ibgateway.service`
- Verify connection: Check the startup messages
- Try restarting IB Gateway

### Issue 4: Stuck on "Connecting..."
**Solution**:
- IB Gateway might not be running
- Port might be wrong (check it's 4002)
- Firewall blocking connection

## Quick Health Check

Run this in another terminal:
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/health_check.py
```

## What You Should See

### Normal Operation:
```
Cycle #1 - 2025-01-27 14:30:00 UTC

🔍 Analyzing NQ
📊 Fetching market data for NQ...
✅ Data received: 192 bars, latest price: $25,473.50
🧠 Generating sr signal...

🤔 Analysis: NQ
[Analysis table with indicators]

✅ EXECUTING: LONG 1 contract(s) @ $25,473.50
✅ Trade executed successfully!

📊 Cycle Summary
✅ Cycle #1 Complete
Symbols Processed: 1
Trades Today: 1
Daily P&L: $0.00
Next cycle in 60s

⏳ Waiting for Cycle #2... [████████░░] 80% (12s remaining)
```

### If You See This, It's Working! ✅

The "sleeping" message is just the agent waiting for the next cycle interval. This is expected behavior.

## Still Not Sure?

1. **Check the cycle number**: Is it incrementing? (Cycle #1, #2, #3...)
2. **Check for analysis tables**: Do you see the "🤔 Analysis" tables?
3. **Check the summary**: Do you see "Cycle Complete" after each cycle?
4. **Check the progress bar**: During sleep, do you see a progress bar?

If all of these are happening, **it's working perfectly!** The "sleeping" is just waiting for the next cycle.

---

**TL;DR**: "Sleeping" = Normal. It's waiting for the next cycle. If you see cycle numbers incrementing and analysis tables, everything is working! ✅

