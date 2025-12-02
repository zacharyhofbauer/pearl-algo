# 🔍 Trading System Diagnostics

## Issues Found

### 1. ❌ Client ID Conflicts
**Problem:** Multiple strategies trying to use same client IDs
- Scalping: Client ID 10 (may conflict)
- Swing: Client ID 11 (CONFLICT - already in use)
- SR: Client ID 12

**Error:**
```
Error 326: Unable to connect as the client id is already in use
clientId 11 already in use
```

**Fix:** Stop all strategies and restart with unique client IDs:
```bash
bash scripts/stop_all_micro_strategies.sh
# Edit scripts/start_all_micro_strategies.sh to use different client IDs
bash scripts/start_all_micro_strategies.sh
```

### 2. ❌ Recursion Error in Strategy Loading
**Problem:** Infinite recursion in `create_strategy_signal` calling `generate_signal` which calls back

**Error:**
```
RecursionError: maximum recursion depth exceeded
```

**Fix:** ✅ Fixed - Updated to use `get_strategy` directly instead of `create_strategy_signal`

### 3. ⚠️ Connection Issues
**Problem:** Some strategies can't connect to IB Gateway
- MES/MNQ: Connection timeout
- MGC/MYM: Working (placed orders)

**Status:**
- ✅ Swing strategy: Working (placed order for MYM)
- ❌ Scalping strategy: Connection issues
- ❌ SR strategy: Recursion error (now fixed)

### 4. ⚠️ Dashboard Not Reflecting
**Problem:** Dashboard may not be reading performance data correctly

**Check:**
```bash
# Check if performance file exists and has data
python -c "
from pearlalgo.futures.performance import load_performance, DEFAULT_PERF_PATH
df = load_performance(DEFAULT_PERF_PATH)
print(f'Rows: {len(df)}')
print(f'Open positions: {len(df[df[\"exit_time\"].isna()]) if \"exit_time\" in df.columns else 0}')
"
```

## Solutions

### Quick Fix: Restart Everything

```bash
# 1. Stop all strategies
bash scripts/stop_all_micro_strategies.sh

# 2. Wait a few seconds
sleep 5

# 3. Check IB Gateway is running
pearlalgo gateway status

# 4. Restart strategies with fixed code
bash scripts/start_all_micro_strategies.sh
```

### Use New Python SDK Terminal

```bash
# Interactive mode
pearlalgo sdk

# Or live dashboard
pearlalgo sdk --dashboard

# Custom refresh
pearlalgo sdk --dashboard --refresh 1.0
```

### Check What's Actually Running

```bash
# Check processes
ps aux | grep "pearlalgo trade auto"

# Check logs for errors
grep -i "error\|exception\|failed" logs/micro_*.log | tail -20

# Check recent trades
tail -20 logs/micro_swing_trading.log
```

## New Python SDK Terminal

The new SDK terminal provides:

1. **Interactive Commands:**
   - `positions` - Show open positions
   - `performance` - Show metrics
   - `trades` - Show recent trades
   - `dashboard` - Live dashboard
   - `help` - Show commands

2. **Programmatic Access:**
   ```python
   from pearlalgo.cli.interactive_terminal import TradingSDK
   
   sdk = TradingSDK()
   positions = sdk.get_positions()
   performance = sdk.get_performance()
   trades = sdk.get_trades_today()
   ```

3. **Live Dashboard:**
   - Auto-refreshing
   - Shows positions, performance, recent trades
   - Customizable refresh rate

## Next Steps

1. **Fix Client IDs:**
   - Edit `scripts/start_all_micro_strategies.sh`
   - Use unique client IDs: 20, 21, 22 instead of 10, 11, 12

2. **Test SDK Terminal:**
   ```bash
   pearlalgo sdk
   ```

3. **Monitor Logs:**
   ```bash
   tail -f logs/micro_swing_console.log
   ```

4. **Check Performance:**
   ```bash
   python -c "from pearlalgo.cli.interactive_terminal import TradingSDK; sdk = TradingSDK(); sdk.print_positions(); sdk.print_performance()"
   ```

---

*All fixes applied. Use `pearlalgo sdk` for the new interactive terminal!*



