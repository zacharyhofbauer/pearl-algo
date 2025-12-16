# NQ Agent - Complete Guide

## 📋 Table of Contents

1. [Quick Start](#-quick-start)
2. [Prerequisites](#-prerequisites)
3. [Service Management](#-service-management)
4. [Configuration](#-configuration)
5. [Monitoring](#-monitoring)
6. [Telegram Notifications](#-telegram-notifications)
7. [Troubleshooting](#-troubleshooting)
8. [Current Status & Known Issues](#-current-status--known-issues)
9. [File Locations](#-file-locations)
10. [Daily Operations](#-daily-operations)
11. [Advanced Usage](#-advanced-usage)

---

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

---

## 📋 Prerequisites

### 1. IBKR Gateway Running
```bash
./scripts/check_gateway_status.sh
```

### 2. Environment Variables
Set in `.env` file or export:
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export PEARLALGO_DATA_PROVIDER="ibkr"

# IBKR Connection
export IBKR_HOST="127.0.0.1"
export IBKR_PORT="4002"
export IBKR_CLIENT_ID="10"
```

### 3. Python Dependencies
```bash
pip install -e .
```

---

## ⚙️ Service Management

### Start Service (Background)
```bash
./scripts/start_nq_agent_service.sh
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

### Stop Service
```bash
# If running in foreground: Ctrl+C

# If running in background:
./scripts/stop_nq_agent_service.sh

# Or manually:
pkill -f "pearlalgo.nq_agent.main"

# Or using PID file:
kill $(cat logs/nq_agent.pid) 2>/dev/null || true
```

### Check Service Status
```bash
./scripts/check_nq_agent_status.sh

# Or manually:
ps aux | grep "pearlalgo.nq_agent.main"
```

### View Logs
```bash
tail -f logs/nq_agent.log
```

---

## 🔧 Configuration

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

### Key Settings
- `symbol`: Trading symbol (default: "NQ")
- `timeframe`: Bar timeframe (default: "1m")
- `scan_interval`: Scan frequency in seconds (default: 60)
- `risk.stop_loss_atr_multiplier`: ATR multiplier (default: 2.0)
- `risk.take_profit_risk_reward`: Risk/reward ratio (default: 2.0)

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

---

## 📊 Monitoring

### Automatic Monitoring
- **Heartbeat messages**: Every 1 hour with service status
- **Status updates**: Every 30 minutes with performance metrics
- **Data quality alerts**: When data issues detected
- **Daily summary**: At market close
- **Weekly summary**: Sunday evening

### Manual Monitoring

#### Check if Running
```bash
ps aux | grep "pearlalgo.nq_agent.main"
```

#### View Service State
```bash
cat data/nq_agent_state/state.json | jq
```

#### View Recent Signals
```bash
tail -20 data/nq_agent_state/signals.jsonl | jq
```

#### View Performance
```bash
cat data/nq_agent_state/performance.json | jq
```

#### View Real-time Signals
```bash
tail -f data/nq_agent_state/signals.jsonl | jq
```

---

## 📱 Telegram Notifications

All notifications are automatic - no bot commands needed. You'll receive:

### Notification Types
- **Heartbeat messages**: Every hour with service status
- **Status updates**: Every 30 minutes with performance metrics
- **Signal notifications**: When trading signals are generated
- **Data quality alerts**: When data issues are detected
- **Performance summaries**: Daily/weekly statistics
- **Service notifications**: Startup/shutdown/recovery alerts

### What You'll See
- Service health status
- Market status (open/closed)
- Cycle and signal counts
- Buffer size and error counts
- Performance metrics (win rate, P&L, etc.)
- Trading signals with entry, stop, and target prices

---

## 🔍 Troubleshooting

### Service Won't Start

1. **Check IBKR Gateway:**
   ```bash
   ./scripts/check_gateway_status.sh
   ```

2. **Check Telegram credentials:**
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

3. **Check logs:**
   ```bash
   tail -50 logs/nq_agent.log
   ```

### No Signals Generated

1. **Check market hours** (signals only during 09:30-16:00 ET)
2. **Check buffer size:**
   ```bash
   cat data/nq_agent_state/state.json | jq .buffer_size
   ```
3. **Check signal confidence threshold** (minimum 55% required)

### Telegram Not Working

1. **Test Telegram connection:**
   ```bash
   python3 scripts/test_telegram.py
   ```

2. **Verify bot token and chat ID are correct**
3. **Check that notifications are enabled in config**

### Service Errors

1. **Check error count:**
   ```bash
   cat data/nq_agent_state/state.json | jq .error_count
   ```

2. **Service auto-pauses after 10 consecutive errors**
3. **Check logs for details:**
   ```bash
   tail -100 logs/nq_agent.log | grep ERROR
   ```

---

## 📈 Current Status & Known Issues

### ✅ What's Working

- **Service**: RUNNING and stable
- **IBKR Gateway**: Connected and operational
- **Data Flow**: Historical data retrieval working (54-56 bars in buffer)
- **Contract Resolution**: NQ front month automatically selected
- **Telegram Integration**: Status updates working perfectly
- **All Components**: Initialized and functioning

### 🔧 Known Limitations

#### Market Data Subscription
- **Issue**: Real-time market data subscription not available (Error 354)
- **Impact**: Using delayed/historical data instead
- **Workaround**: Currently using last bar from historical data (working)
- **Solution Options**:
  1. Subscribe to market data in IBKR account
  2. Use delayed data (available, just needs configuration)
  3. Continue with historical data approach (current - working)

#### Signal Generation
- **Current**: Only generates signals during market hours (09:30-16:00 ET)
- **Status**: Working as designed
- **During Market Hours**: Will automatically generate and send signals

### 🎯 Future Enhancements

#### High Priority
- Improve market hours detection (timezone handling)
- Fine-tune confidence thresholds based on backtesting
- Add more confirmation signals
- Better error messages formatting

#### Medium Priority
- Add detailed analytics dashboard
- Track win rate by signal type
- Add risk-adjusted returns (Sharpe ratio)
- Multiple timeframe analysis

#### Low Priority / Future
- Historical backtesting framework
- Multi-symbol support
- Portfolio-level risk management
- Machine learning signal filters

---

## 📁 File Locations

- **Logs**: `logs/nq_agent.log`
- **State**: `data/nq_agent_state/state.json`
- **Signals**: `data/nq_agent_state/signals.jsonl`
- **Performance**: `data/nq_agent_state/performance.json`
- **PID**: `logs/nq_agent.pid`
- **Config**: `config/config.yaml`

---

## 📅 Daily Operations

### Morning Check
1. Verify IBKR Gateway is running
2. Check service status: `./scripts/check_nq_agent_status.sh`
3. Review overnight logs: `tail -100 logs/nq_agent.log`

### During Trading
1. Monitor Telegram for signals
2. Check performance periodically via Telegram notifications
3. Watch for error notifications

### End of Day
1. Review daily performance via Telegram summary
2. Check signal count and win rate
3. Review any error messages

---

## 🚀 Advanced Usage

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

### Service Behavior

#### Automatic Features
- **Scan Interval**: Checks for signals every 60 seconds (configurable)
- **Status Updates**: Sends Telegram status every 30 minutes
- **Signal Generation**: Automatically generates and sends signals during market hours
- **Performance Tracking**: Automatically tracks all signals and outcomes
- **Error Handling**: Circuit breaker pauses service after 10 consecutive errors

#### Market Hours
Default trading hours: 09:30 - 16:00 ET
- Signals only generated during market hours
- Service runs 24/7 but only generates signals when market is open

---

## 🎯 Ready for Production

The service is production-ready and will automatically:
- ✅ Generate signals during market hours
- ✅ Send rich Telegram notifications
- ✅ Track performance
- ✅ Handle errors gracefully
- ✅ Provide status updates

When markets open, the service will begin generating and sending trading signals automatically.

---

**Last Updated:** 2025-12-12



