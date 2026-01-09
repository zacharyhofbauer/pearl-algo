# When Do I Need to Restart?

## Quick Answer

**Agent Restart Needed For:**
- ✅ Config changes (risk settings, strategy, signals, etc.)
- ✅ When config.yaml is modified
- ✅ After applying suggestions that change config

**NO Restart Needed For:**
- ❌ Telegram handler updates (auto-reloads)
- ❌ Just viewing suggestions
- ❌ Applying suggestions (handled automatically)

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
./scripts/lifecycle/stop_nq_agent_service.sh
./scripts/lifecycle/start_nq_agent_service.sh --background
```

Or via Telegram:
- Send `/start` → **System** → **Restart Agent**

### ❌ NO Restart Needed

**Telegram Handler:**
- Command updates (like new `/suggest` command)
- Menu changes
- Button updates
- Handler automatically reloads on code changes

**Viewing/Applying Suggestions:**
- `/suggest` command
- Viewing suggestions
- Applying suggestions (changes config automatically)
- The agent picks up config changes on next scan cycle

### 🤔 How to Know If It Worked?

**For Config Changes:**
1. Check agent logs:
   ```bash
   tail -f logs/nq_agent.log | grep -E "Config loaded|stop_loss|risk_reward"
   ```
2. Look for your new values in the logs

**For Suggestions:**
1. Run `/suggest` in Telegram
2. If you see suggestions → ✅ Working
3. If you see "not available" → Monitor needs to be started

**For Telegram Commands:**
1. Try the command
2. If you get a response → ✅ Working
3. If you get "unknown command" → Handler needs restart

### 📊 Status Check Commands

**Check Agent Status:**
```bash
ps aux | grep "pearlalgo.nq_agent.main" | grep -v grep
cat logs/nq_agent.pid
```

**Check Telegram Handler:**
```bash
ps aux | grep "telegram_command_handler" | grep -v grep
cat logs/telegram_handler.pid
```

**Via Telegram:**
- `/start` → Shows agent status in main menu

### 🐛 Troubleshooting

**"Claude monitor not available"**
→ Start it: `/start` → **AI Hub** → **🔍 AI Monitor** → **▶️ Start Monitor**

**Config changes not taking effect**
→ Agent needs restart (see above)

**Command not found**
→ Telegram handler needs restart:
```bash
./scripts/telegram/restart_command_handler.sh --background
```

**Suggestions not showing**
→ Run `/suggest new` to generate fresh suggestions

### ⚡ Quick Restart Script

Create this script for easy restarts:

```bash
#!/bin/bash
# File: ~/restart_agent.sh

cd /home/pearlalgo/pearlalgo-dev-ai-agents

echo "🔄 Restarting Agent..."
./scripts/lifecycle/stop_nq_agent_service.sh
sleep 2
./scripts/lifecycle/start_nq_agent_service.sh --background

echo "✅ Agent restarted!"
echo "PID: $(cat logs/nq_agent.pid)"
```

Then just run: `~/restart_agent.sh`

### 📝 Summary Table

| Change Type | Agent Restart? | Handler Restart? |
|-------------|---------------|------------------|
| `config.yaml` changes | ✅ YES | ❌ NO |
| Apply suggestion (config) | ❌ NO* | ❌ NO |
| Apply suggestion (code) | ✅ YES | ❌ NO |
| New Telegram command | ❌ NO | ✅ YES |
| Telegram menu update | ❌ NO | ✅ YES (auto) |
| View suggestions | ❌ NO | ❌ NO |

*Config suggestions applied via ActionExecutor reload config automatically
