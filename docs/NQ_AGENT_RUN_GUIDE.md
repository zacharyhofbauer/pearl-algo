# NQ Agent Service - Run & Management Guide

## Prerequisites

1. **IBKR Gateway running** (already running headless ✅)
   ```bash
   ./scripts/check_gateway_status.sh
   ```

2. **Environment Variables** (set in `.env` or export):
   ```bash
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   export PEARLALGO_DATA_PROVIDER="ibkr"  # or other provider
   ```

3. **Python Dependencies**:
   ```bash
   pip install python-telegram-bot>=20.0
   ```

## Quick Start

### Start the Service

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/start_nq_agent.sh
```

Or manually:
```bash
cd ~/pearlalgo-dev-ai-agents
python3 -m pearlalgo.nq_agent.main
```

### Run in Background (with nohup)

```bash
cd ~/pearlalgo-dev-ai-agents
nohup python3 -m pearlalgo.nq_agent.main > logs/nq_agent.log 2>&1 &
echo $! > logs/nq_agent.pid
```

### Stop the Service

```bash
# If running in foreground: Ctrl+C

# If running in background:
pkill -f "pearlalgo.nq_agent.main"

# Or using PID file:
kill $(cat logs/nq_agent.pid) 2>/dev/null || true
```

## Service Management Scripts

### Start Service (Background)
```bash
./scripts/start_nq_agent_service.sh
```

### Stop Service
```bash
./scripts/stop_nq_agent_service.sh
```

### Check Service Status
```bash
./scripts/check_nq_agent_status.sh
```

### View Logs
```bash
tail -f logs/nq_agent.log
```

## Interactive Telegram Bot

The service can be controlled via Telegram commands. Start the interactive bot separately:

### Start Interactive Bot

```bash
# Set environment variable
export TELEGRAM_BOT_TOKEN="your_bot_token"

# Run bot
python3 -m pearlalgo.nq_agent.telegram_bot
```

Or in background:
```bash
nohup python3 -m pearlalgo.nq_agent.telegram_bot > logs/telegram_bot.log 2>&1 &
```

### Available Commands

Send these commands to your Telegram bot:

- `/start` - Show available commands
- `/status` - Get current service status
- `/signals` - View recent trading signals
- `/performance` - Get performance metrics (7 days)
- `/config` - View current configuration
- `/pause` - Pause the service (if running)
- `/resume` - Resume the service (if paused)

## Monitoring

### Check Service Status

```bash
# Check if service is running
ps aux | grep "pearlalgo.nq_agent.main"

# Check process details
pgrep -af "pearlalgo.nq_agent.main"
```

### View Service State

The service saves state to: `data/nq_agent_state/state.json`

```bash
cat data/nq_agent_state/state.json | jq
```

### View Recent Signals

```bash
tail -20 data/nq_agent_state/signals.jsonl | jq
```

### View Performance Data

```bash
cat data/nq_agent_state/performance.json | jq
```

## Configuration

### Edit Configuration

Edit `config/config.yaml`:

```yaml
symbol: "NQ"
timeframe: "1m"
scan_interval: 60

risk:
  stop_loss_atr_multiplier: 2.0
  take_profit_risk_reward: 2.0
  max_risk_per_trade: 0.02

telegram:
  enabled: true
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
```

### Environment Variables

Create `.env` file or export:

```bash
# IBKR Connection
export IBKR_HOST="127.0.0.1"
export IBKR_PORT="4002"
export IBKR_CLIENT_ID="10"

# Telegram
export TELEGRAM_BOT_TOKEN="your_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"

# Data Provider
export PEARLALGO_DATA_PROVIDER="ibkr"
```

## Service Behavior

### Automatic Features

- **Scan Interval**: Checks for signals every 60 seconds (configurable)
- **Status Updates**: Sends Telegram status every 30 minutes
- **Signal Generation**: Automatically generates and sends signals during market hours
- **Performance Tracking**: Automatically tracks all signals and outcomes
- **Error Handling**: Circuit breaker pauses service after 10 consecutive errors

### Market Hours

Default trading hours: 09:30 - 16:00 ET
- Signals only generated during market hours
- Service runs 24/7 but only generates signals when market is open

## Troubleshooting

### Service Won't Start

1. Check IBKR Gateway is running:
   ```bash
   ./scripts/check_gateway_status.sh
   ```

2. Check Telegram credentials:
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

3. Check logs:
   ```bash
   tail -50 logs/nq_agent.log
   ```

### No Signals Generated

1. Check market hours (signals only during 09:30-16:00 ET)
2. Check data buffer:
   ```bash
   # Check state file for buffer_size
   cat data/nq_agent_state/state.json | jq .buffer_size
   ```

3. Check signal confidence threshold (minimum 55% required)

### Telegram Not Working

1. Test Telegram connection:
   ```bash
   python3 scripts/test_telegram.py
   ```

2. Verify bot token and chat ID are correct
3. Make sure bot has been started (send `/start` to bot)

### Service Errors

1. Check error count in status:
   ```bash
   # Via Telegram: /status
   # Or check state file
   cat data/nq_agent_state/state.json | jq .error_count
   ```

2. Service auto-pauses after 10 consecutive errors
3. Check logs for details:
   ```bash
   tail -100 logs/nq_agent.log | grep ERROR
   ```

## Logs Location

- Service logs: `logs/nq_agent.log`
- Telegram bot logs: `logs/telegram_bot.log`
- State files: `data/nq_agent_state/`
- Performance data: `data/nq_agent_state/performance.json`

## Daily Operations

### Morning Check
1. Verify IBKR Gateway is running
2. Check service status: `/status` via Telegram or check PID
3. Review overnight logs

### During Trading
1. Monitor Telegram for signals
2. Check `/performance` periodically
3. Watch for error notifications

### End of Day
1. Review daily performance: `/performance`
2. Check signal count and win rate
3. Review any error messages

## Advanced Usage

### Run with Custom Config

```bash
# Modify config/config.yaml first
python3 -m pearlalgo.nq_agent.main
```

### Debug Mode

```bash
# Set log level to DEBUG
export PEARLALGO_LOG_LEVEL=DEBUG
python3 -m pearlalgo.nq_agent.main
```

### View Real-time Signals

```bash
tail -f data/nq_agent_state/signals.jsonl | jq
```

