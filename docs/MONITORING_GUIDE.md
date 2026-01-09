# Monitoring Your Optimized Trading Agent

## ✅ Agent Restarted Successfully

**PID**: 210044  
**Status**: Running in background  
**Config**: Optimized settings applied

## Quick Monitoring Commands

### View Live Logs
```bash
# Follow logs in real-time
tail -f logs/nq_agent.log

# Check last 50 lines
tail -n 50 logs/nq_agent.log

# Search for trades
tail -f logs/nq_agent.log | grep -E "ENTRY|EXIT|P/L"
```

### Check Agent Status
```bash
# Check if running
ps aux | grep "pearlalgo.nq_agent.main" | grep -v grep

# Check PID file
cat logs/nq_agent.pid
```

### Check Recent Performance
```bash
# Via Telegram (recommended)
# Send command: /status

# Or check database directly
cd /home/pearlalgo/pearlalgo-dev-ai-agents
python3 -c "
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('data/nq_agent_state/trades.db')
cursor = conn.cursor()

# Get last 10 trades
cursor.execute('''
    SELECT signal_type, entry_price, exit_price, pnl, is_win, exit_time
    FROM trades 
    ORDER BY exit_time DESC 
    LIMIT 10
''')

trades = cursor.fetchall()
print(f'Last 10 trades:\n')
for t in trades:
    sig, entry, exit, pnl, is_win, t_time = t
    status = '✅ WIN' if is_win else '❌ LOSS'
    print(f'{status} | {sig} | \${pnl:.2f} | Entry: \${entry} Exit: \${exit}')

conn.close()
"
```

## What to Monitor

### 1. Win Rate (Critical)
- **Target**: 35-40%+ (currently 31.25%)
- **Check**: After 20-30 trades with new settings
- **Action**: If still below 35%, may need to increase minimum confidence threshold

### 2. Average P/L Per Trade
- **Target**: +$50 to +$100 per winning trade
- **Current**: -$44/trade average
- **Monitor**: Individual trade sizes should increase with new position sizing

### 3. Stop Loss Effectiveness
- **Watch for**: Fewer premature stop-outs
- **Old behavior**: Stops hitting too quickly (20-point stops)
- **New behavior**: Trades should have room to breathe (30-35 point stops)
- **Indicator**: If you see stops hitting immediately, may need to widen further

### 4. Position Sizing
- **Expected**: 5-10 contracts on normal trades
- **High confidence**: 10-15 contracts
- **Verify**: Check contract counts in trade logs

### 5. Signal Performance
- **Best Signal**: `mean_reversion_long` (47% WR, +$116 avg) ✅
- **Watch**: `mean_reversion_short` (33% WR) - should improve with wider stops
- **Monitor**: `sr_bounce_long` (33% WR) - marginal but enabled

## Expected Changes in Behavior

### Before Optimization
- ❌ Tight 20-point stops → premature exits
- ❌ 1.5:1 R:R → unprofitable with 31% WR
- ❌ Small positions (3 contracts) → small profits
- ❌ High Claude API costs → draining credits

### After Optimization
- ✅ Wider 30-35 point stops → trades can develop
- ✅ 2.0:1 R:R → better match for win rate
- ✅ Larger positions (5-10 contracts) → $100+ targets
- ✅ Reduced API costs → ~80% reduction

## Daily Performance Review

### Check Daily Stats via Telegram
Send `/status` or check daily report (runs at 9 AM ET)

### Key Metrics to Track
1. **Win Rate**: Should improve from 31% to 35-40%+
2. **Total P/L**: Should trend positive
3. **Avg Win**: Target $100+ per winning trade
4. **Avg Loss**: Should be controlled (wider stops help)
5. **Signal Breakdown**: Focus on what's working

## Troubleshooting

### If Still Losing Money After 30+ Trades

1. **Check Win Rate**
   - If < 35%: Increase `signals.min_confidence` from 0.4 to 0.5-0.6
   - If < 30%: Consider disabling more signal types

2. **Review Signal Performance**
   - Disable any signal type with < 30% WR after 10+ trades
   - Focus on `mean_reversion_long` (best performer)

3. **Adjust R:R Further**
   - If WR stays ~33%: Increase `take_profit_risk_reward` to 2.5:1

4. **Consider Session Filtering**
   - Focus on NY session only (best liquidity)
   - Disable Tokyo/London if they're underperforming

### If Getting Stopped Out Too Much
- Further widen stops: Increase `stop_loss_atr_multiplier` to 3.0
- Increase `max_stop_points` to 40-50

### If Position Sizes Too Small
- Increase `base_contracts` from 5 to 7-8
- Increase `max_position_size` from 15 to 20

## Claude Monitor Status

**Current Settings**:
- ✅ Daily reports enabled (9 AM ET)
- ✅ Weekly reports enabled (Monday 9 AM ET)
- ❌ Real-time monitoring disabled (was expensive)
- ❌ Auto-apply disabled (was making things worse)

**Check Monitor Status**:
```bash
./scripts/lifecycle/start_claude_monitor.sh --background
cat logs/claude_monitor.pid
```

**Review Monitor Logs**:
```bash
tail -f logs/claude_monitor.log
```

## Quick Reference

### Restart Agent
```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./scripts/lifecycle/stop_nq_agent_service.sh
./scripts/lifecycle/start_nq_agent_service.sh --background
```

### Stop Agent
```bash
./scripts/lifecycle/stop_nq_agent_service.sh
```

### View Config
```bash
cat config/config.yaml | grep -A 5 "risk:"
cat config/config.yaml | grep -A 10 "strategy:"
```

### Telegram Commands
- `/status` - Agent status
- `/trades` - Recent trades
- `/signals` - Signal statistics
- `/performance` - Performance metrics

## Next Review Point

**After 20-30 trades** (typically 2-5 days):
1. Check win rate improvement
2. Review average P/L per trade
3. Verify stop loss effectiveness
4. Assess signal type performance
5. Adjust if needed

---

**Documentation**: Full optimization details in `docs/OPTIMIZATION_SUMMARY.md`
