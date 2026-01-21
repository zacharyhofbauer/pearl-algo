# When Do I Need to Restart?

## Quick Answer

**Agent Restart Needed For:**
- ✅ Config changes (risk settings, strategy, signals, etc.)
- ✅ When config.yaml is modified

**NO Restart Needed For:**
- ❌ Telegram handler updates (auto-reloads)

## Detailed Guide

### 🔄 Agent Restart Required

The **trading agent** needs restart when you change `config/config.yaml`:

**Risk Settings:**
- `risk.stop_loss_atr_multiplier`
- `risk.take_profit_risk_reward`
- `risk.max_risk_per_trade`
- `signals.min_confidence`
- `signals.max_stop_points`

**Strategy Settings:**
- `strategy.enabled_signals`
- `strategy.disabled_signals`
- `strategy.base_contracts`
- `adaptive_stops.*`
- `adaptive_sizing.*`

**How to Restart:**
```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./scripts/lifecycle/agent.sh stop --market NQ
./scripts/lifecycle/agent.sh start --market NQ --background
```

Or via Telegram:
- Send `/start` → **System** → **Restart Agent**

### ❌ NO Restart Needed

**Telegram Handler:**
- Command updates
- Menu changes
- Button updates
- Handler automatically reloads on code changes

### 🤔 How to Know If It Worked?

**For Config Changes:**
1. Check agent logs:
   ```bash
   tail -f logs/agent_NQ.log | grep -E "Config loaded|stop_loss|risk_reward"
   ```
2. Look for your new values in the logs

**For Telegram Commands:**
1. Try the command
2. If you get a response → ✅ Working
3. If you get "unknown command" → Handler needs restart

### 📊 Status Check Commands

**Check Agent Status:**
```bash
ps aux | grep "pearlalgo.market_agent.main" | grep -v grep
cat logs/agent_NQ.pid
```

**Check Telegram Handler:**
```bash
ps aux | grep "telegram_command_handler" | grep -v grep
cat logs/telegram_handler.pid
```

**Via Telegram:**
- `/start` → Shows agent status in main menu

### 🐛 Troubleshooting

**Config changes not taking effect**
→ Agent needs restart (see above)

**Command not found**
→ Telegram handler needs restart:
```bash
./scripts/telegram/restart_command_handler.sh --background
```

### ⚡ Quick Restart Script

Create this script for easy restarts:

```bash
#!/bin/bash
# File: ~/restart_agent.sh

cd /home/pearlalgo/pearlalgo-dev-ai-agents

echo "🔄 Restarting Agent..."
./scripts/lifecycle/agent.sh stop --market NQ
sleep 2
./scripts/lifecycle/agent.sh start --market NQ --background

echo "✅ Agent restarted!"
echo "PID: $(cat logs/agent_NQ.pid)"
```

Then just run: `~/restart_agent.sh`

### 📝 Summary Table

| Change Type | Agent Restart? | Handler Restart? |
|-------------|---------------|------------------|
| `config.yaml` changes | ✅ YES | ❌ NO |
| New Telegram command | ❌ NO | ✅ YES |
| Telegram menu update | ❌ NO | ✅ YES (auto) |

