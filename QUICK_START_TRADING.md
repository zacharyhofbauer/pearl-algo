# Quick Start - See Trading in Action

## The Problem
The trading process keeps stopping or you can't see what's happening.

## Solution: Run in Foreground

**This is the BEST way to see trading activity:**

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Start trading - you'll see ALL output
bash scripts/start_trading_foreground.sh
```

Or manually:
```bash
pearlalgo --verbosity VERBOSE trade auto \
  --symbols MES \
  --strategy sr \
  --interval 30 \
  --tiny-size 1 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 11
```

## What You'll See

Every 30 seconds, you'll see:

```
┌─────────────────────────────────────────────────────────┐
│ 🔍 Analyzing MES                                        │
└─────────────────────────────────────────────────────────┘

📊 Fetching market data for MES...
✅ Data received: 240 bars, latest price: $6,834.25
🧠 Generating sr signal...

┌─────────────────────────────────────────────────────────┐
│ 🧠 Analysis: MES                                        │
├─────────────────────────────────────────────────────────┤
│ Signal        ⚪ FLAT                                    │
│ Current Price $6,834.25                                  │
│ VWAP          $6,834.12 (Above 0.00%)                   │
│ 20 EMA        $6,836.68 (Below 0.04%)                   │
│ Support 1     $6,826.50 (0.11% away)                    │
│ Risk Status   ✅ OK                                      │
│ Position Size 0 (BLOCKED)                                │
└─────────────────────────────────────────────────────────┘

⚪ MES: FLAT signal - No trade opportunity
```

**When a trade opportunity is found:**
```
✅ EXECUTING: LONG 1 contract(s) @ $6,834.25
✅ Trade executed successfully!
```

## Two Terminal Setup (Recommended)

**Terminal 1 - Trading:**
```bash
bash scripts/start_trading_foreground.sh
```

**Terminal 2 - Monitor:**
```bash
pearlalgo monitor
```

This gives you:
- Terminal 1: Detailed analysis and reasoning
- Terminal 2: Live feed of trades and signals

## Troubleshooting

### Process Keeps Stopping?

1. **Check Gateway:**
   ```bash
   pearlalgo gateway status
   ```

2. **Check for errors:**
   ```bash
   tail -50 logs/test_trading.log
   ```

3. **Run in foreground** (so you see errors immediately):
   ```bash
   bash scripts/start_trading_foreground.sh
   ```

### No Output Showing?

The verbose output goes to console, not logs. You MUST run in foreground to see it.

### Want to Run in Background?

If you want it in background but still see activity:

```bash
# Start in background
nohup bash scripts/start_trading_foreground.sh > logs/trading_console.log 2>&1 &

# Watch the output
tail -f logs/trading_console.log
```

## Expected Behavior

✅ **Working correctly:**
- Every 30 seconds: Analysis appears
- Signal generated (usually FLAT)
- If opportunity: Trade executes
- Cycle summary shows P&L

❌ **Not working:**
- No output at all
- Errors about Gateway connection
- Process dies immediately

## Quick Test

1. **Start trading:**
   ```bash
   bash scripts/start_trading_foreground.sh
   ```

2. **Wait 30-60 seconds** - you should see analysis

3. **If you see analysis** = ✅ Working! (FLAT signals are normal)

4. **If no output** = Check Gateway connection

## Summary

**Best way to see trading:**
```bash
bash scripts/start_trading_foreground.sh
```

This shows you everything in real-time. FLAT signals are normal - trades will execute when opportunities are found!

