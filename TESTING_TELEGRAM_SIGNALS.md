# Testing Telegram Signal Generation

## Quick Test Guide

### Step 1: Test Telegram Connection (2 minutes)

First, verify your Telegram bot is configured correctly:

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/test_telegram.py
```

**Expected Output:**
```
==========================================
Telegram Bot Connection Test
==========================================

✓ Bot Token: 8423504611...UFio
✓ Chat ID: 1724557528

Initializing Telegram alerts...
✓ Telegram alerts initialized

Sending test message...
✅ SUCCESS: Test message sent!
   Check your Telegram chat to verify receipt

==========================================
✅ Telegram test PASSED
==========================================
```

**If it fails:**
- Check that `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`
- Verify bot token is correct (get from @BotFather on Telegram)
- Verify chat ID is correct (send a message to your bot, then visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`)

---

### Step 2: Run Signal Generation (5 minutes)

Run the system in signal-only mode to generate signals and send Telegram notifications:

```bash
# Option 1: Use the convenience script
./scripts/run_signal_generation.sh ES NQ sr

# Option 2: Run directly
python -m pearlalgo.live.langgraph_trader \
    --symbols ES NQ \
    --strategy sr \
    --mode paper
```

**What to expect:**
1. System will start and initialize agents
2. Market data will be fetched (may use dummy data if no API keys)
3. Signals will be generated for each symbol
4. Telegram notifications will be sent for:
   - Each signal generated (from QuantResearchAgent)
   - Each signal logged with PnL (from PortfolioExecutionAgent)
   - Any risk warnings (from RiskManagerAgent)

**Monitor in real-time:**
- Watch your Telegram chat for notifications
- Check console output for signal generation logs
- System will run continuously (press Ctrl+C to stop)

---

### Step 3: Verify Signal Logging

Check that signals are being logged to CSV:

```bash
# View the performance log
cat data/performance/futures_decisions.csv | tail -20

# Or use a CSV viewer
python -c "
import pandas as pd
df = pd.read_csv('data/performance/futures_decisions.csv')
print(df.tail(10).to_string())
"
```

**Expected CSV columns:**
- `timestamp` - When signal was generated
- `symbol` - Trading symbol (ES, NQ, etc.)
- `side` - LONG or SHORT
- `strategy_name` - Strategy used (sr, ma_cross, etc.)
- `requested_size` - Position size
- `filled_size` - Should be 0 (signal-only mode)
- `entry_price` - Signal entry price
- `unrealized_pnl` - Calculated potential P&L
- `notes` - Should say "Signal-only mode - no trade executed"

---

### Step 4: Test with Different Symbols/Strategies

Try different configurations:

```bash
# Test with micro futures
./scripts/run_signal_generation.sh MES MNQ sr

# Test with different strategy
./scripts/run_signal_generation.sh ES NQ ma_cross

# Test with single symbol
python -m pearlalgo.live.langgraph_trader --symbols ES --strategy sr --mode paper
```

---

### Step 5: Test Risk Warnings

To test risk warning notifications, you can:

1. **Simulate high drawdown:**
   - Modify portfolio equity in code temporarily
   - Or wait for actual drawdown to trigger

2. **Check risk state blocking:**
   - System will send Telegram notification if signals are blocked due to risk state

---

## Troubleshooting

### Telegram Not Working

**Issue:** No messages received in Telegram

**Solutions:**
1. Run `python scripts/test_telegram.py` first to verify connection
2. Check `.env` file has correct `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
3. Verify bot is not blocked (send `/start` to your bot)
4. Check logs for errors: `grep -i telegram logs/*.log`

### No Signals Generated

**Issue:** System runs but no signals appear

**Solutions:**
1. Check market data is available (may need API keys)
2. Verify symbols are correct (ES, NQ, etc.)
3. Check strategy name is valid (sr, ma_cross, breakout, mean_reversion)
4. Look at console output for errors

### Signals Generated But No Telegram Notifications

**Issue:** Signals appear in CSV but no Telegram messages

**Solutions:**
1. Verify `alerts.telegram.enabled: true` in `config/config.yaml`
2. Check that `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
3. Check logs for Telegram errors: `grep -i "telegram\|failed to send" logs/*.log`
4. Verify `python-telegram-bot` is installed: `pip install python-telegram-bot`

### Signal-Only Mode Not Working

**Issue:** Trades are being executed instead of just logged

**Solutions:**
1. Verify `trading.signal_only: true` in `config/config.yaml`
2. Check console output for "Signal-only mode" message
3. Verify `filled_size=0` in CSV (not actual trade size)

---

## Expected Telegram Message Formats

### Signal Generated (from QuantResearchAgent)
```
📊 *Signal Generated*

Symbol: ES
Direction: LONG
Strategy: sr
Confidence: 75.0%
@ $4500.00

Reasoning: [LLM reasoning if available]...
```

### Signal Logged (from PortfolioExecutionAgent)
```
📈 *Signal Logged*

Symbol: ES
Direction: LONG
Strategy: sr
Entry Price: $4500.00
Size: 2 contracts
Stop Loss: $4480.00
Take Profit: $4540.00
Risk: 2.00%
Potential P&L: $100.00

Reasoning: [signal reasoning]...
```

### Risk Warning (from RiskManagerAgent)
```
⚠️ *Risk Warning*

Signal for ES BLOCKED: risk state = HARD_STOP
Risk Status: HARD_STOP
```

### Kill-Switch Activated
```
🛑 *KILL-SWITCH ACTIVATED*

Drawdown 15.50% >= 15%
```

---

## Quick Test Commands

```bash
# 1. Test Telegram connection
python scripts/test_telegram.py

# 2. Run signal generation (single cycle)
python -m pearlalgo.live.langgraph_trader \
    --symbols ES \
    --strategy sr \
    --mode paper

# 3. Check logged signals
tail -5 data/performance/futures_decisions.csv

# 4. View logs
tail -f logs/langgraph_trading.log | grep -E "(Signal|Telegram|PnL)"
```

---

## Success Criteria

✅ Telegram test passes  
✅ Signals are generated and logged to CSV  
✅ Telegram notifications received for signals  
✅ `filled_size=0` in CSV (no trades executed)  
✅ PnL calculated and included in notifications  
✅ Risk warnings trigger Telegram alerts  

---

## Next Steps

Once testing is successful:
1. Run system continuously to collect signal data
2. Analyze signal performance from CSV
3. Optimize signal generation for maximum returns
4. Add more sophisticated PnL tracking with mark-to-market updates

