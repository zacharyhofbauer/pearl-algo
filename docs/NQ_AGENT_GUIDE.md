# MNQ Agent - Complete Guide

**Prop Firm Trading Strategy for Mini NQ (MNQ) Futures**

## 📋 Table of Contents

1. [Quick Start](#-quick-start)
2. [Prerequisites](#-prerequisites)
3. [Service Management](#-service-management)
4. [Configuration](#-configuration)
5. [Prop Firm Trading](#-prop-firm-trading)
6. [Monitoring](#-monitoring)
7. [Telegram Notifications](#-telegram-notifications)
8. [Troubleshooting](#-troubleshooting)
9. [File Locations](#-file-locations)
10. [Daily Operations](#-daily-operations)
11. [Advanced Usage](#-advanced-usage)

---

## 🚀 Quick Start

```bash
cd ~/pearlalgo-dev-ai-agents

# 1. Ensure IBKR Gateway is running
./scripts/check_gateway_status.sh

# 2. Start MNQ Agent Service
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
# Prop Firm Style: MNQ (Mini NQ) - 5-15 contracts per trade
symbol: "MNQ"  # Mini NQ (1/10th size of NQ, better for prop firms)
timeframe: "1m"
scan_interval: 30  # Faster for scalping

risk:
  max_risk_per_trade: 0.01  # 1% (prop firm conservative)
  max_drawdown: 0.10  # 10%
  stop_loss_atr_multiplier: 1.5  # Tighter stops for scalping
  take_profit_risk_reward: 1.5  # 1.5:1 for quick profits
  min_position_size: 5  # Minimum contracts
  max_position_size: 15  # Maximum contracts

telegram:
  enabled: true
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
```

### Key Settings
- `symbol`: Trading symbol (default: "MNQ" for prop firm trading)
- `timeframe`: Bar timeframe (default: "1m" for scalping)
- `scan_interval`: Scan frequency in seconds (default: 30 for faster signals)
- `risk.max_risk_per_trade`: Max risk per trade (default: 0.01 = 1%)
- `risk.stop_loss_atr_multiplier`: ATR multiplier (default: 1.5 for tighter stops)
- `risk.take_profit_risk_reward`: Risk/reward ratio (default: 1.5:1 for quick profits)
- `risk.min_position_size`: Minimum contracts (default: 5)
- `risk.max_position_size`: Maximum contracts (default: 15)

### Prop Firm Trading (MNQ)
**Optimized for intraday swings and quick scalps:**
- **MNQ Benefits:** 1/10th size of NQ ($2/point vs $20/point), better for prop firm accounts
- **Position Sizing:** 5-15 contracts per trade (default: 10)
- **Risk Management:** 1% max risk per trade, 10% max drawdown
- **Scalping Focus:** Tighter stops (1.5x ATR), quicker profits (1.5:1 R:R), faster scanning (30s)
- **Example Trade:** 10 MNQ @ $17,500, Stop: 3.75 pts ($75 risk), Target: 5.5 pts ($110 reward)

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

## 💼 Prop Firm Trading

### Overview
Strategy optimized for **prop firm style trading** with **Mini NQ (MNQ)**:
- **Intraday swings** (15-60 minute holds)
- **Quick scalps** (5-15 minute holds)
- **Conservative risk** (1% per trade, 10% max drawdown)

### MNQ vs NQ
- **MNQ:** $2 per point, 1/10th size of NQ
- **NQ:** $20 per point
- **Better for prop firms:** Lower margin, better position sizing (5-15 contracts)

### Position Sizing
- **Minimum:** 5 MNQ contracts
- **Default:** 10 MNQ contracts
- **Maximum:** 15 MNQ contracts
- **Risk Calculation:** Stop Loss Points × $2 × Contracts

### Example Trade
```
Entry: $17,500.00
Stop: $17,496.25 (3.75 points)
Target: $17,505.50 (5.5 points)
Position: 10 contracts

Risk: 3.75 × $2 × 10 = $75 (0.15% of $50k account)
Reward: 5.5 × $2 × 10 = $110
R:R: 1.47:1
```

### Risk Rules
- **Max Risk/Trade:** 1% of account
- **Max Drawdown:** 10% daily
- **Stop Loss:** 1.5x ATR (tighter for scalping)
- **Take Profit:** 1.5:1 R:R (quicker profits)
- **Avoid Lunch:** 11:30 AM - 1:00 PM ET (low volume)

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

### Prop Firm Trading Setup
The strategy is configured for **prop firm style trading** with MNQ:
- **Symbol:** MNQ (Mini NQ - 1/10th size of NQ)
- **Position Size:** 5-15 contracts per trade
- **Risk:** 1% max per trade, 10% max drawdown
- **Style:** Quick scalps (5-15 min) and intraday swings (15-60 min)
- **Stops:** Tighter (1.5x ATR) for scalping
- **Targets:** Quicker profits (1.5:1 R:R)

**Contract Specs:**
- MNQ: $2 per point (vs NQ $20 per point)
- Example: 10 contracts, 3.75 point stop = $75 risk

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
- **Scan Interval**: Checks for signals every 30 seconds (MNQ scalping) or 60 seconds (configurable)
- **Status Updates**: Sends Telegram status every 30 minutes
- **Signal Generation**: Automatically generates and sends signals during market hours
- **Performance Tracking**: Automatically tracks all signals and outcomes
- **Error Handling**: Circuit breaker pauses service after 10 consecutive errors
- **Lunch Lull Filter**: Avoids signals during 11:30 AM - 1:00 PM ET (low volume)

#### Market Hours
Default trading hours: 09:30 - 16:00 ET
- Signals only generated during market hours
- Service runs 24/7 but only generates signals when market is open
- Avoids lunch lull period for better signal quality

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

**Last Updated:** 2025-12-16  
**Current Configuration:** MNQ (Mini NQ) - Prop Firm Style Trading



