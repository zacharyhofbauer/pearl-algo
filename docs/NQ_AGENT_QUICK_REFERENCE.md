# NQ Agent - Quick Reference Card

## 🚀 Quick Start

```bash
cd ~/pearlalgo-dev-ai-agents

# 1. Ensure IBKR Gateway is running
./scripts/check_gateway_status.sh

# 2. Start NQ Agent Service
./scripts/start_nq_agent_service.sh

# 3. Check status
./scripts/check_nq_agent_status.sh

# 4. View logs
tail -f logs/nq_agent.log
```

## 📋 Essential Commands

### Service Management
```bash
# Start service (background)
./scripts/start_nq_agent_service.sh

# Stop service
./scripts/stop_nq_agent_service.sh

# Check status
./scripts/check_nq_agent_status.sh

# View logs
tail -f logs/nq_agent.log
```

### Interactive Telegram Bot
```bash
# Start bot
export TELEGRAM_BOT_TOKEN="your_token"
./scripts/start_telegram_bot.sh

# Stop bot
pkill -f telegram_bot
```

### Telegram Commands (send to your bot)
```
/start       - Show commands
/status      - Service status
/signals     - Recent signals
/performance - 7-day metrics
/config      - Configuration
/pause       - Pause service
/resume      - Resume service
```

## 🔍 Monitoring

```bash
# Check if running
ps aux | grep "pearlalgo.nq_agent.main"

# View state
cat data/nq_agent_state/state.json | jq

# View recent signals
tail -20 data/nq_agent_state/signals.jsonl | jq

# View performance
cat data/nq_agent_state/performance.json | jq
```

## ⚙️ Configuration

Edit: `config/config.yaml`

Key settings:
- `symbol`: Trading symbol (default: "NQ")
- `timeframe`: Bar timeframe (default: "1m")
- `scan_interval`: Scan frequency in seconds (default: 60)
- `risk.stop_loss_atr_multiplier`: ATR multiplier (default: 2.0)
- `risk.take_profit_risk_reward`: Risk/reward ratio (default: 2.0)

## 🔧 Troubleshooting

### Service won't start
1. Check IBKR Gateway: `./scripts/check_gateway_status.sh`
2. Check Telegram env vars: `echo $TELEGRAM_BOT_TOKEN`
3. Check logs: `tail -50 logs/nq_agent.log`

### No signals
- Signals only during market hours (09:30-16:00 ET)
- Check buffer size in state file
- Minimum confidence threshold: 55%

### Telegram not working
1. Test: `python3 scripts/test_telegram.py`
2. Verify bot token/chat ID
3. Send `/start` to bot first

## 📊 File Locations

- **Logs**: `logs/nq_agent.log`
- **State**: `data/nq_agent_state/state.json`
- **Signals**: `data/nq_agent_state/signals.jsonl`
- **Performance**: `data/nq_agent_state/performance.json`
- **PID**: `logs/nq_agent.pid`

