# Trading Diagnostic Guide

## Current Status

**✅ Trading IS Running!** 

Your trading process is active (PID 195346), but you're seeing FLAT signals, which means:
- ✅ Gateway connection: Working
- ✅ Data fetching: Working  
- ✅ Signal generation: Working
- ⚠️ Trade opportunities: None right now (signals are FLAT)

## Why No Trades?

The strategy is generating signals, but they're all "FLAT" which means:
- No clear LONG or SHORT opportunity detected
- Strategy is being conservative (this is good!)
- Market conditions don't meet entry criteria

This is **normal and expected** - the strategy only trades when there's a clear opportunity.

## How to See What's Happening

### Option 1: Watch Live Activity
```bash
bash scripts/show_live_activity.sh
```

### Option 2: Check Recent Signals
```bash
# See what signals were generated
tail -20 data/performance/futures_decisions.csv | cut -d',' -f1,2,5,6

# Or use the monitor
pearlalgo monitor
```

### Option 3: Run in Foreground (See All Output)
```bash
# Stop current process first
pkill -f "pearlalgo trade auto"

# Run in foreground to see everything
pearlalgo --verbosity VERBOSE trade auto \
  --symbols MES \
  --strategy sr \
  --interval 30 \
  --tiny-size 1 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 11
```

This will show you:
- 🔍 Analysis for each symbol
- 📊 Data fetching status
- 🧠 Signal generation
- ⚪ FLAT signals (when no opportunity)
- ✅ Trade execution (when opportunity found)

## What You Should See

### When Strategy is Working:

**Every 30 seconds:**
```
🔍 Analyzing MES...
📊 Fetching market data for MES...
✅ Data received: 240 bars, latest price: $6,834.25
🧠 Generating sr signal...
⚪ MES: FLAT signal - No trade opportunity
```

**When Trade Opportunity Found:**
```
🔍 Analyzing MES...
📊 Fetching market data for MES...
✅ Data received: 240 bars, latest price: $6,834.25
🧠 Generating sr signal...
💰 Computing position size...
✅ EXECUTING: LONG 1 contract(s) @ $6,834.25
```

## Verify Everything is Working

### 1. Check Process is Running
```bash
ps aux | grep "pearlalgo trade auto" | grep -v grep
```

### 2. Check Gateway Connection
```bash
pearlalgo gateway status
```

### 3. Check Recent Activity
```bash
# See last 10 signals
tail -10 data/performance/futures_decisions.csv

# See if any trades executed
grep -v "flat" data/performance/futures_decisions.csv | tail -5
```

### 4. Test Signal Generation Manually
```bash
pearlalgo signals --strategy sr --symbols MES
```

## Understanding FLAT Signals

FLAT signals are **normal** and mean:
- Strategy analyzed the market
- No clear entry signal detected
- Better to wait than force a trade

The strategy will trade when:
- Price breaks support/resistance
- Clear trend direction
- Risk parameters allow it

## Force a Test Trade (For Testing Only)

If you want to see a trade execute for testing:

1. **Modify strategy temporarily** to be more aggressive
2. **Use a different strategy** that's more active:
   ```bash
   pearlalgo trade auto --symbols MES --strategy ma_cross --interval 30
   ```
3. **Wait for market conditions** to change (volatility, trends)

## Summary

✅ **Everything is working correctly!**
- Trading process: Running
- Gateway: Connected
- Signals: Being generated
- Trades: Will execute when opportunity found

The system is being conservative (showing FLAT signals) which is actually **good risk management**. Trades will execute automatically when the strategy detects a clear opportunity.

