# MNQ Agent - Operational Guide

**Prop Firm Trading Strategy for Mini NQ (MNQ) Futures**

> **Note:** For system architecture, component details, and technical deep-dives, see [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md).

## 📋 Table of Contents

1. [Quick Start](#-quick-start)
2. [Prerequisites](#-prerequisites)
3. [Installation](#-installation)
4. [Service Management](#-service-management)
5. [Configuration](#-configuration)
6. [Daily Operations](#-daily-operations)
7. [Monitoring](#-monitoring)
8. [Troubleshooting](#-troubleshooting)
9. [File Locations](#-file-locations)

---

## 🚀 Quick Start

```bash
cd ~/pearlalgo-dev-ai-agents

# 1. Ensure IBKR Gateway is running
./scripts/gateway/check_gateway_status.sh

# 2. Start MNQ Agent Service
./scripts/lifecycle/start_nq_agent_service.sh

# 3. Check status
./scripts/lifecycle/check_nq_agent_status.sh

# 4. View logs
tail -f logs/nq_agent.log
```

---

## 📋 Prerequisites

- **IBKR Account**: Active Interactive Brokers account
- **IBKR Gateway**: Installed and configured (see [GATEWAY.md](GATEWAY.md))
- **Python 3.12+**: Installed on system
- **Telegram Bot**: Created and configured (bot token and chat ID)

## 🔧 Installation

### 1. Install Dependencies
```bash
cd ~/pearlalgo-dev-ai-agents
pip install -e .
```

### 2. Configure Environment Variables
Create `.env` file in project root:
```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# IBKR Connection
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11

# Data Provider
PEARLALGO_DATA_PROVIDER=ibkr

# Optional: Logging
PEARLALGO_LOG_LEVEL=INFO
```

### 3. Setup IBKR Gateway
```bash
# Complete gateway setup (configures API, IBC, etc.)
./scripts/gateway/setup_ibgateway.sh

# Start gateway
./scripts/gateway/start_ibgateway_ibc.sh

# Verify gateway is running
./scripts/gateway/check_gateway_status.sh
```

For detailed gateway setup, see [GATEWAY.md](GATEWAY.md).

---

## ⚙️ Service Management

### Start Service (Background)
```bash
./scripts/lifecycle/start_nq_agent_service.sh
```

### Start Service (Foreground)
```bash
cd ~/pearlalgo-dev-ai-agents
python3 -m pearlalgo.nq_agent.main
```

### Stop Service
```bash
./scripts/lifecycle/stop_nq_agent_service.sh

# Or manually:
pkill -f "pearlalgo.nq_agent.main"

# Or using PID file:
kill $(cat logs/nq_agent.pid) 2>/dev/null || true
```

### Check Service Status
```bash
./scripts/lifecycle/check_nq_agent_status.sh

# Or manually:
ps aux | grep "pearlalgo.nq_agent.main"
```

### View Logs
```bash
tail -f logs/nq_agent.log
```

---

## 🔧 Configuration

### Main Configuration File
Edit `config/config.yaml` to customize behavior:

```yaml
# Trading Symbol
symbol: "MNQ"  # Mini NQ (1/10th size of NQ, better for prop firms)
timeframe: "1m"  # 1-minute bars for scalping/swings
scan_interval: 30  # Check for signals every 30 seconds

# Risk Management (Prop Firm Style)
risk:
  max_risk_per_trade: 0.01  # 1% max risk per trade
  max_drawdown: 0.10  # 10% account drawdown limit
  stop_loss_atr_multiplier: 1.5  # Tighter stops for scalping
  take_profit_risk_reward: 1.5  # 1.5:1 R/R for quick scalps
  min_position_size: 5  # Minimum contracts per trade
  max_position_size: 15  # Maximum contracts per trade

# Service Intervals
service:
  status_update_interval: 1800  # 30 minutes
  heartbeat_interval: 3600  # 1 hour
  state_save_interval: 10  # cycles

# Circuit Breaker
circuit_breaker:
  max_consecutive_errors: 10
  max_connection_failures: 10
  max_data_fetch_errors: 5

# Telegram Notifications
telegram:
  enabled: true
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
```

### Key Configuration Sections

**Trading Settings:**
- `symbol`: Trading symbol (MNQ for prop firm trading)
- `timeframe`: Bar timeframe (1m for scalping)
- `scan_interval`: Scan frequency in seconds (30 for faster signals)

**Risk Management:**
- `risk.max_risk_per_trade`: Max risk per trade (0.01 = 1%)
- `risk.stop_loss_atr_multiplier`: ATR multiplier for stops (1.5 for tighter stops)
- `risk.take_profit_risk_reward`: Risk/reward ratio (1.5:1 for quick profits)
- `risk.min_position_size` / `max_position_size`: Contract range (5-15)

**Service Behavior:**
- `service.status_update_interval`: Status update frequency (seconds)
- `service.heartbeat_interval`: Heartbeat message frequency (seconds)
- `circuit_breaker.*`: Error threshold settings

For complete configuration reference, see [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md#configuration).

### Prop Firm Trading Configuration

The system is optimized for **prop firm style trading** with MNQ:
- **MNQ Benefits:** 1/10th size of NQ ($2/point vs $20/point), better position sizing
- **Position Sizing:** 5-15 contracts per trade (default: 10)
- **Risk Management:** 1% max risk per trade, 10% max drawdown
- **Scalping Focus:** Tighter stops (1.5x ATR), quicker profits (1.5:1 R:R), faster scanning (30s)

**Example Trade:**
```
Entry: $17,500.00
Stop: $17,496.25 (3.75 points)
Target: $17,505.50 (5.5 points)
Position: 10 contracts

Risk: 3.75 × $2 × 10 = $75 (0.15% of $50k account)
Reward: 5.5 × $2 × 10 = $110
R:R: 1.47:1
```

---

## 📅 Daily Operations

### Morning Checklist
1. **Verify IBKR Gateway:**
   ```bash
   ./scripts/gateway/check_gateway_status.sh
   ```

2. **Check Service Status:**
   ```bash
   ./scripts/lifecycle/check_nq_agent_status.sh
   ```

3. **Review Overnight Logs:**
   ```bash
   tail -100 logs/nq_agent.log
   ```

### During Trading Hours
- Monitor Telegram for signals
- Check performance via Telegram notifications
- Watch for error notifications
- Review signal quality and market conditions

### End of Day
1. Review daily performance via Telegram summary
2. Check signal count and win rate
3. Review any error messages
4. Verify service is still running

---

## 📊 Monitoring

### Automatic Monitoring (via Telegram)
- **Heartbeat messages**: Every 1 hour with service status
- **Status updates**: Every 30 minutes with performance metrics
- **Data quality alerts**: When data issues detected
- **Signal notifications**: When trading signals are generated
- **Service notifications**: Startup/shutdown/recovery alerts

### Manual Monitoring Commands

**Check Service Status:**
```bash
./scripts/lifecycle/check_nq_agent_status.sh
```

**View Service State:**
```bash
cat data/nq_agent_state/state.json | jq
```

**View Recent Signals:**
```bash
tail -20 data/nq_agent_state/signals.jsonl | jq
```

**View Performance Metrics:**
```bash
cat data/nq_agent_state/performance.json | jq
```

**View Real-time Logs:**
```bash
tail -f logs/nq_agent.log
```

**View Real-time Signals:**
```bash
tail -f data/nq_agent_state/signals.jsonl | jq
```

---

## 🔍 Troubleshooting

### Service Won't Start

1. **Check IBKR Gateway:**
   ```bash
   ./scripts/gateway/check_gateway_status.sh
   ```
   If not running, start it:
   ```bash
   ./scripts/gateway/start_ibgateway_ibc.sh
   ```

2. **Check Telegram credentials:**
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

3. **Check logs for errors:**
   ```bash
   tail -50 logs/nq_agent.log
   ```

4. **Verify configuration:**
   ```bash
   cat config/config.yaml
   ```

### No Signals Generated

1. **Check market hours** (signals only during 09:30-16:00 ET)
2. **Check buffer size:**
   ```bash
   cat data/nq_agent_state/state.json | jq .buffer_size
   ```
   Should be > 10 bars. If low, check data provider connection.
3. **Check signal confidence threshold** (minimum 50% required, configurable in `config.yaml`)
4. **Verify market is open:**
   ```bash
   # Check if current time is between 09:30-16:00 ET
   ```

### Telegram Not Working

1. **Test Telegram connection:**
   ```bash
   python3 scripts/testing/test_all.py telegram
   ```

2. **Verify bot token and chat ID are correct** in `.env` or `config.yaml`
3. **Check that notifications are enabled** in `config.yaml`:
   ```yaml
   telegram:
     enabled: true
   ```

### Service Errors

1. **Check error count:**
   ```bash
   cat data/nq_agent_state/state.json | jq .error_count
   ```

2. **Service auto-pauses after 10 consecutive errors** (circuit breaker)
3. **Check logs for details:**
   ```bash
   tail -100 logs/nq_agent.log | grep ERROR
   ```

4. **Check connection failures:**
   ```bash
   cat data/nq_agent_state/state.json | jq .connection_failures
   ```

### Data Quality Issues

1. **Check for stale data alerts** in Telegram
2. **Verify IBKR Gateway is connected:**
   ```bash
   ./scripts/gateway/check_gateway_status.sh
   ```
3. **Check buffer size** (should be > 10 bars)
4. **Review data quality alerts** in logs:
   ```bash
   tail -100 logs/nq_agent.log | grep -i "data quality\|stale\|buffer"
   ```

---

## 📁 File Locations

**Configuration:**
- `config/config.yaml` - Main configuration file
- `.env` - Environment variables (not in git)

**Logs:**
- `logs/nq_agent.log` - Service logs
- `logs/nq_agent.pid` - Process ID file

**State & Data:**
- `data/nq_agent_state/state.json` - Current service state
- `data/nq_agent_state/signals.jsonl` - Signal history (JSONL format)
- `data/nq_agent_state/performance.json` - Performance metrics

**Scripts:**
- `scripts/lifecycle/` - Service lifecycle scripts
- `scripts/gateway/` - IBKR Gateway scripts
- `scripts/testing/` - Testing and validation scripts

---

## 📚 Additional Resources

- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Complete system reference, architecture, components
- **[GATEWAY.md](GATEWAY.md)** - IBKR Gateway setup and configuration
- **[TESTING_GUIDE.md](TESTING_GUIDE.md)** - Testing procedures and validation

---

**Last Updated:** 2025-12-16  
**Current Configuration:** MNQ (Mini NQ) - Prop Firm Style Trading



