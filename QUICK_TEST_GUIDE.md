# Quick Testing Guide - Telegram Signal Generation

## 🚀 Fastest Way to Test (3 Steps)

### Step 1: Test Telegram Connection (30 seconds)

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate  # If using venv
python scripts/test_telegram.py
```

**What to check:**
- ✅ Should see "SUCCESS: Test message sent!"
- ✅ Check your Telegram chat - you should receive a test message
- ❌ If it fails, check your `.env` file has `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`

---

### Step 2: Run Signal Generation (2 minutes)

```bash
# Simple way - use the script
./scripts/run_signal_generation.sh ES NQ sr

# Or run directly
python -m pearlalgo.live.langgraph_trader --symbols ES NQ --strategy sr --mode paper
```

**What happens:**
1. System starts and initializes
2. Fetches market data (may use dummy data)
3. Generates signals for ES and NQ
4. Sends Telegram notifications for each signal
5. Logs signals to CSV without executing trades

**Watch for:**
- 📱 Telegram notifications appearing in your chat
- 📊 Console output showing signal generation
- 📝 Signals logged to `data/performance/futures_decisions.csv`

---

### Step 3: Verify Results (1 minute)

```bash
# Check CSV file
tail -5 data/performance/futures_decisions.csv

# Or view in Python
python3 -c "
import pandas as pd
df = pd.read_csv('data/performance/futures_decisions.csv')
print('Last 3 signals:')
print(df[['timestamp', 'symbol', 'side', 'entry_price', 'unrealized_pnl', 'filled_size']].tail(3))
"
```

**What to verify:**
- ✅ `filled_size` should be `0` (no trades executed)
- ✅ `unrealized_pnl` should have a value (calculated P&L)
- ✅ `notes` should say "Signal-only mode - no trade executed"

---

## 📱 Expected Telegram Messages

You should receive messages like:

**Signal Generated:**
```
📊 *Signal Generated*

Symbol: ES
Direction: LONG
Strategy: sr
Confidence: 75.0%
@ $4500.00
```

**Signal Logged with PnL:**
```
📈 *Signal Logged*

Symbol: ES
Direction: LONG
Entry Price: $4500.00
Size: 2 contracts
Potential P&L: $100.00
```

---

## 🔧 Troubleshooting

### No Telegram Messages?

1. **Test connection first:**
   ```bash
   python scripts/test_telegram.py
   ```

2. **Check environment variables:**
   ```bash
   grep TELEGRAM .env
   ```

3. **Check config:**
   ```bash
   grep -A 3 "telegram:" config/config.yaml
   ```
   Should show `enabled: true`

### No Signals Generated?

1. **Check console output** for errors
2. **Verify symbols** are correct (ES, NQ, MES, MNQ, etc.)
3. **Check strategy name** (sr, ma_cross, breakout, mean_reversion)

### Signals But No Telegram?

1. **Check logs:**
   ```bash
   grep -i telegram logs/*.log | tail -10
   ```

2. **Verify python-telegram-bot installed:**
   ```bash
   pip list | grep telegram
   ```

---

## ✅ Success Checklist

- [ ] Telegram test passes
- [ ] Telegram notifications received
- [ ] Signals logged to CSV
- [ ] `filled_size=0` in CSV (signal-only mode working)
- [ ] PnL calculated in notifications

---

## 🎯 Next: Run Continuously

Once testing works, run continuously to collect signal data:

```bash
# Run for multiple cycles
python -m pearlalgo.live.langgraph_trader \
    --symbols ES NQ \
    --strategy sr \
    --mode paper

# Press Ctrl+C to stop
```

Monitor Telegram for real-time signal notifications!
