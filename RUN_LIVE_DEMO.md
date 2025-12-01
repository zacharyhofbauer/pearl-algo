# 🚀 Run the Enhanced Agent Live - See It Think!

## Quick Start - See It In Action

### Option 1: Full Production Run
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Run with all symbols, 5-minute intervals
python scripts/automated_trading.py \
  --symbols ES NQ GC \
  --strategy sr \
  --interval 300 \
  --tiny-size 1
```

### Option 2: Quick Test (Faster Cycles)
```bash
# Test with one symbol, 1-minute intervals to see more cycles quickly
python scripts/automated_trading.py \
  --symbols NQ \
  --strategy sr \
  --interval 60 \
  --tiny-size 1
```

### Option 3: Use Test Script
```bash
# Pre-configured quick test
python scripts/test_agent_live.py
```

## What You'll See

The agent now shows **detailed reasoning** for every decision:

### 1. **Startup**
```
┌─────────────────────────────────────────────┐
│  🤖 Automated Trading Agent Starting       │
│  Strategy: SR                              │
│  Symbols: NQ, ES, GC                       │
│  Interval: 300s (5.0 minutes)             │
│  Profile: default                          │
└─────────────────────────────────────────────┘

🔌 Connecting to IB Gateway...
✅ Connected to IB Gateway
   Data Client ID: 2
   Orders Client ID: 1
   Host: 127.0.0.1:4002
```

### 2. **Each Trading Cycle**
```
┌─────────────────────────────────────────────┐
│  Cycle #1 - 2025-01-27 14:30:00 UTC        │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  🔍 Analyzing NQ                            │
└─────────────────────────────────────────────┘

📊 Fetching market data for NQ...
✅ Data received: 192 bars, latest price: $25,473.50
🧠 Generating sr signal...
```

### 3. **Detailed Analysis Table**
```
┌─────────────────────────────────────────────────────────────────────┐
│                    🤔 Analysis: NQ                                  │
├──────────────┬─────────────────────────────┬───────────────────────┤
│ Metric       │ Value                       │ Reasoning             │
├──────────────┼─────────────────────────────┼───────────────────────┤
│ Signal       │ 🟢 LONG                     │ Bullish pivot + above │
│              │                             │ VWAP + 20EMA          │
│ Current Price│ $25,473.50                  │                       │
│ VWAP         │ $25,418.79 (Above 0.21%)   │ Price above VWAP =   │
│              │                             │ bullish               │
│ 20 EMA       │ $25,450.00 (Above 0.09%)    │ Trend filter: long   │
│              │                             │ only above EMA        │
│ Support 1    │ $25,273.48 (0.79% away)     │ Near support =       │
│              │                             │ bounce zone          │
│ Risk Status  │ ✅ OK                       │ Remaining buffer:    │
│              │                             │ $2,500.00            │
│ Position Size│ 1 contract(s)               │ Based on risk taper: │
│              │                             │ 100% buffer remaining│
│ Daily P&L    │ $0.00 (R: $0.00, U: $0.00)  │ Trades today: 0      │
└──────────────┴─────────────────────────────┴───────────────────────┘

✅ EXECUTING: LONG 1 contract(s) @ $25,473.50
✅ Trade executed successfully!
```

### 4. **Position Exits**
```
📤 EXIT: NQ 1 contracts @ $25,480.00
   Entry: $25,473.50 | Exit: $25,480.00
   P&L: $130.00 | Reason: opposite signal
```

### 5. **Cycle Summary**
```
┌─────────────────────────────────────────────┐
│  📊 Summary                                │
│  Cycle Complete                            │
│  Trades Today: 2                           │
│  Daily P&L: $130.00                        │
│  Next cycle in 300s                       │
└─────────────────────────────────────────────┘

💤 Sleeping for 300s until next cycle...
```

## Understanding the Output

### Signal Types
- 🟢 **LONG**: Bullish setup detected
- 🔴 **SHORT**: Bearish setup detected  
- ⚪ **FLAT**: No clear signal or blocked by filters

### Risk Status
- ✅ **OK**: Safe to trade, full sizing available
- ⚠️ **NEAR_LIMIT**: Approaching daily loss limit
- 🛑 **HARD_STOP**: Daily loss limit hit
- ⏸️ **COOLDOWN**: Waiting period active
- ⏸️ **PAUSED**: Outside market hours

### Trade Reasoning
The agent explains **why** it's making each trade:
- **"Bullish pivot + above VWAP + 20EMA"**: Price near support, above VWAP, and above EMA
- **"Bearish pivot + below VWAP + below 20EMA"**: Price near resistance, below VWAP, and below EMA
- **"flat (below EMA filter)"**: Signal blocked because price is below EMA (for long) or above EMA (for short)

## Tips for Watching

1. **Watch the Analysis Tables**: They show the complete reasoning
2. **Check Indicator Distances**: See how close price is to key levels
3. **Monitor Risk State**: Track remaining loss buffer
4. **Review Trade Reasons**: Understand what triggered each decision
5. **Track P&L**: See realized vs unrealized gains/losses

## Stopping the Agent

Press `Ctrl+C` to stop gracefully. The agent will:
- Close any open positions (if configured)
- Save final state
- Show summary statistics

## Troubleshooting

**No output?** 
- Make sure IB Gateway is running: `sudo systemctl status ibgateway.service`
- Check you're in the virtual environment: `source .venv/bin/activate`

**Connection errors?**
- Verify IB Gateway is on port 4002
- Check firewall settings
- Ensure client IDs don't conflict

**No trades?**
- Check if market hours (Monday-Friday)
- Review risk state - might be in cooldown
- Verify data is being fetched (check logs)

---

**Ready to see it think? Run the command above and watch the agent make decisions!** 🎯

