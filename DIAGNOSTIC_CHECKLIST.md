# 🔍 Diagnostic Checklist - Why No Trades?

## Quick Diagnostic

Run this first:
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/debug_trading.py
```

This will show you:
- ✅ Settings configuration
- ✅ Live trading enabled status
- ✅ IB Gateway connection
- ✅ Broker initialization

## Common Issues

### Issue 1: Live Trading Disabled (DRY RUN MODE)

**Symptoms:**
- See "DRY RUN MODE" messages
- Orders show "would submit" but don't actually submit
- No actual trades in IB Gateway

**Check:**
```bash
python scripts/debug_trading.py
```

**Fix:**
1. Check `.env` file:
   ```bash
   cat .env | grep PEARLALGO
   ```

2. Ensure these are set:
   ```
   PEARLALGO_PROFILE=live
   PEARLALGO_ALLOW_LIVE_TRADING=true
   ```

3. Or the agent should set them automatically (it does in code), but verify:
   ```bash
   python scripts/debug_trading.py
   ```

### Issue 2: All Signals Are FLAT

**Symptoms:**
- See "⚪ FLAT signal" for every symbol
- No analysis tables showing LONG/SHORT
- Agent says "No trade opportunity"

**Check:**
- Look at the analysis tables - do they show LONG or SHORT signals?
- Check if strategy conditions are being met
- Verify market data is being fetched correctly

**Fix:**
- Strategy might be too conservative
- Market conditions might not meet entry criteria
- Try a different strategy: `--strategy ma_cross`

### Issue 3: Trades Blocked by Risk Management

**Symptoms:**
- See "🚫 TRADE BLOCKED by risk state"
- Analysis shows risk status as HARD_STOP, COOLDOWN, or PAUSED
- Position size shows as 0

**Check:**
- Look at risk status in analysis tables
- Check daily P&L - might have hit loss limit
- Check if max_trades reached

**Fix:**
- Reset daily counters (wait for new day or restart)
- Adjust risk limits in config
- Check cooldown period

### Issue 4: IB Gateway Not Connected

**Symptoms:**
- Connection errors
- "Failed to initialize connections"
- No data being fetched

**Check:**
```bash
sudo systemctl status ibgateway.service
```

**Fix:**
```bash
sudo systemctl start ibgateway.service
# Wait 30 seconds for it to start
sudo systemctl status ibgateway.service
```

### Issue 5: Contract Resolution Errors

**Symptoms:**
- "No matching contract" errors
- "Symbol not found" errors
- Data fetch fails

**Check:**
- Verify symbol names are correct (ES, NQ, GC, etc.)
- Check if micro contracts need different symbols (MGC, MYM, etc.)
- Verify IB Gateway has market data subscriptions

**Fix:**
- Use correct symbol names
- For micro contracts, ensure you have the right symbols
- Check IB Gateway market data permissions

### Issue 6: Orders Submitted But Not Filled

**Symptoms:**
- See "Order submitted" messages
- But no fills appearing
- Positions not updating

**Check:**
- Look in IB Gateway TWS/Gateway for orders
- Check if orders are being rejected
- Verify account has buying power

**Fix:**
- Check IB Gateway for order status
- Verify paper trading account is active
- Check account permissions

## Step-by-Step Debugging

### Step 1: Run Diagnostic
```bash
python scripts/debug_trading.py
```

### Step 2: Check Agent Output
Look for these messages in the agent output:

**Good signs:**
- ✅ "Connected to IB Gateway"
- ✅ "EXECUTING: LONG 1 contract(s)"
- ✅ "Order submitted: [order_id]"
- ✅ Analysis tables showing LONG/SHORT (not FLAT)

**Bad signs:**
- ❌ "DRY RUN MODE"
- ❌ "TRADE BLOCKED"
- ❌ "FLAT signal"
- ❌ "Connection error"
- ❌ "No data available"

### Step 3: Check Logs
```bash
# If logging to file
tail -f logs/automated_trading.log

# Or check journal if running as service
sudo journalctl -u automated_trading.service -f
```

### Step 4: Check IB Gateway
1. Open IB Gateway/TWS
2. Check "Orders" tab - are orders appearing?
3. Check "Positions" tab - are positions being created?
4. Check for any error messages

### Step 5: Test Manual Order
Try submitting a test order manually through IB Gateway to verify:
- Account is active
- Permissions are correct
- Paper trading is enabled

## Quick Fixes

### Fix 1: Ensure Live Trading Enabled
The agent code sets this automatically, but verify:
```python
# In automated_trading_agent.py line 122-124
self.ib_settings = Settings(
    allow_live_trading=True,  # ✅ Should be True
    profile="live",            # ✅ Should be "live"
    ...
)
```

### Fix 2: Check Broker Initialization
The broker should be initialized with these settings. Check logs for:
- "Live trading disabled" warnings
- "DRY RUN MODE" messages

### Fix 3: Verify Signal Generation
Run a quick test:
```bash
python -c "
from pearlalgo.futures.signals import generate_signal
import pandas as pd
# Create test data
df = pd.DataFrame({
    'Close': [100, 101, 102, 103, 104],
    'High': [101, 102, 103, 104, 105],
    'Low': [99, 100, 101, 102, 103],
    'Volume': [1000, 1100, 1200, 1300, 1400]
})
signal = generate_signal('ES', df, strategy_name='sr')
print(f'Signal: {signal[\"side\"]}')
"
```

## Still Not Working?

1. **Check the exact error messages** in the agent output
2. **Run the diagnostic script**: `python scripts/debug_trading.py`
3. **Check IB Gateway** for any order rejections
4. **Review logs** for detailed error messages
5. **Verify market hours** - might be outside trading hours

---

**Most common issue: Live trading is disabled (dry-run mode). Run the diagnostic script to check!**

