# MNQ Agent - Operational Guide

**Prop Firm Trading Strategy for Mini NQ (MNQ) Futures**

> **Fast path:** For a one-page operational view (env, startup steps, scripts, Telegram expectations), use `CHEAT_SHEET.md`.
> **Deep dive:** For system architecture, component details, and technical deep-dives, see `PROJECT_SUMMARY.md`.

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
cd /path/to/pearlalgo-dev-ai-agents

# 1. Ensure IBKR Gateway is running
./scripts/gateway/gateway.sh status

# 2. Start MNQ Agent Service (foreground - shows live logs in terminal)
./scripts/lifecycle/agent.sh start --market NQ

# 3. Check status (in another terminal)
./scripts/lifecycle/check_agent_status.sh --market NQ
```

**Note:** The service runs in foreground mode by default, showing all logs directly in your terminal. Press `Ctrl+C` to stop. To run in background (no terminal output), use `--background` flag.

---

## 📋 Prerequisites

- **IBKR Account**: Active Interactive Brokers account
- **IBKR Gateway**: Installed and configured (see `GATEWAY.md`)
- **Python 3.12+**: Installed on system
- **Telegram Bot**: Created and configured (bot token and chat ID)

## 🔧 Installation

### 1. Install Dependencies
```bash
cd /path/to/pearlalgo-dev-ai-agents
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
```

### 3. Setup IBKR Gateway
```bash
# Complete gateway setup (configures API, IBC, etc.)
./scripts/gateway/gateway.sh setup

# Start gateway
./scripts/gateway/gateway.sh start

# Verify gateway is running
./scripts/gateway/gateway.sh status
```

For detailed gateway setup, see `GATEWAY.md`.

---

## ⚙️ Service Management

### Start Service (Foreground - Default)
```bash
./scripts/lifecycle/agent.sh start --market NQ
```
**Default behavior:** Service runs in foreground with live terminal output. All logs appear in your terminal. Press `Ctrl+C` to stop.

### Start Service (Background)
```bash
./scripts/lifecycle/agent.sh start --market NQ --background
```
**Background mode:** Service runs in background with output captured to `logs/nq_agent.log`. Use this if you want to run the service detached from your terminal session.

### Stop Service
```bash
./scripts/lifecycle/agent.sh stop --market NQ

# Or manually:
pkill -f "pearlalgo.nq_agent.main"

# Or using PID file:
kill $(cat logs/nq_agent.pid) 2>/dev/null || true
```

### Check Service Status
```bash
./scripts/lifecycle/check_agent_status.sh --market NQ

# Or manually:
ps aux | grep "pearlalgo.nq_agent.main"
```

### View Logs
**Foreground mode (default):** Logs appear directly in your terminal - no file needed.

**Background mode:** Logs are written to `logs/nq_agent.log` (with basic rotation - previous log saved as `nq_agent.log.1`). View with: `tail -f logs/nq_agent.log`

---

## 🔧 Configuration

### Main Configuration File
Edit `config/config.yaml` to customize behavior:

```yaml
# Trading Symbol
symbol: "MNQ"  # Mini NQ (1/10th size of NQ, better for prop firms)
timeframe: "5m"  # 5-minute bars for intraday swings (primary), with 1-2m for execution pinpointing
scan_interval: 30  # Check for signals every 30 seconds

# Trading Bot (single source of trade intent)
trading_bot:
  enabled: false
  selected: "PearlAutoBot"
  available:
    PearlAutoBot:
      class: "PearlAutoBot"
      enabled: true
      parameters: {}

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
  status_update_interval: 3600  # 1 hour (status interval)
  heartbeat_interval: 86400     # Disabled - dashboard replaces heartbeat
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
- `timeframe`: Bar timeframe (5m primary for swings; 1-2m available for execution pinpointing)
- `scan_interval`: Scan frequency in seconds (30 for faster signals)

**Risk Management:**
- `risk.max_risk_per_trade`: Max risk per trade (0.01 = 1%)
- `risk.stop_loss_atr_multiplier`: ATR multiplier for stops (1.5 for tighter stops)
- `risk.take_profit_risk_reward`: Risk/reward ratio (1.5:1 for quick profits)
- `risk.min_position_size` / `max_position_size`: Contract range (5-15)

**Service Behavior:**
- `service.status_update_interval`: Status update frequency (default: 3600 = 1 hour)
- `service.heartbeat_interval`: Legacy heartbeat (disabled; dashboard replaces it)
- `circuit_breaker.*`: Error threshold settings

For complete configuration reference, see `PROJECT_SUMMARY.md` (Configuration section).

### Scaling to ES/GC (multi-market)

Recommended model: **one agent process per market**, one trading bot per agent.

Example launch for ES (using the market-aware script):
```bash
./scripts/lifecycle/agent.sh start --market ES --background
```

Each market instance should use its own:
- `PEARLALGO_MARKET` (NQ/ES/GC)
- `PEARLALGO_CONFIG_PATH` (per-market config file)
- `PEARLALGO_STATE_DIR` (per-market state directory)

The Telegram UI provides a Markets menu to switch between NQ/ES/GC while keeping each market isolated.

### Prop Firm Trading Configuration

The system is optimized for **prop firm style trading** with MNQ:
- **MNQ Benefits:** 1/10th size of NQ ($2/point vs $20/point), better position sizing
- **Position Sizing:** Configurable via `risk.max_position_size` (default: 50, dynamic sizing enabled)
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
   ./scripts/gateway/gateway.sh status
   ```

2. **Check Service Status:**
   ```bash
   ./scripts/lifecycle/check_agent_status.sh --market NQ
   ```

3. **Review Overnight Activity:**
   - Check Telegram for overnight notifications
   - Review service state: `cat data/agent_state/NQ/state.json | jq`
   - Check recent signals: `tail -20 data/agent_state/NQ/signals.jsonl | jq`

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
- **Dashboard**: Hourly by default with price sparkline, MTF trends, session stats, performance
- **Data quality alerts**: When data issues detected
- **Signal notifications**: When trading signals are generated
- **Service notifications**: Startup/shutdown/recovery alerts

> **Note:** Dashboard replaces the old separate Status/Heartbeat messages. One clean message per `dashboard_chart_interval` (default 1h) with all key info.

### Manual Monitoring Commands

**Check Service Status:**
```bash
./scripts/lifecycle/check_agent_status.sh --market NQ
```

**View Service State:**
```bash
cat data/agent_state/NQ/state.json | jq
```

**View Recent Signals:**
```bash
tail -20 data/agent_state/NQ/signals.jsonl | jq
```

**View Performance Metrics:**
```bash
cat data/agent_state/NQ/performance.json | jq
```

**View Real-time Logs:**
```bash
# Run service in foreground to see live logs:
./scripts/lifecycle/agent.sh start --market NQ
```

**View Real-time Signals:**
```bash
tail -f data/agent_state/NQ/signals.jsonl | jq
```

### External Watchdog (cron/systemd timer) (optional)

If you want an **independent safety net** outside the running agent process (detect stalled state updates / silent failures), use:

```bash
# Local check (prints summary + exit code)
python3 scripts/monitoring/watchdog_agent.py --market NQ --verbose

# Alert to Telegram (requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
python3 scripts/monitoring/watchdog_agent.py --market NQ --telegram
```

The watchdog is designed for cron/systemd timers (e.g., every 5 minutes). It reads `data/agent_state/NQ/state.json` and returns non‑zero exit codes for warning/critical conditions.

**Cron example (every 5 minutes):**
```cron
*/5 * * * * cd /path/to/pearlalgo-dev-ai-agents && python3 scripts/monitoring/watchdog_agent.py --market NQ --telegram
```

### Status Server (optional)

A lightweight localhost HTTP server for standard tooling (curl, Prometheus, systemd health checks):

```bash
# Start on default port (9100)
python3 scripts/monitoring/serve_agent_status.py --market NQ

# Custom port
python3 scripts/monitoring/serve_agent_status.py --market NQ --port 9200
```

**Endpoints:**
- `GET /` - Status page (HTML)
- `GET /healthz` - Health check (JSON, 200 or 503)
- `GET /metrics` - Prometheus text format

**Usage examples:**
```bash
# Health check
curl http://localhost:9100/healthz

# Prometheus scrape
curl http://localhost:9100/metrics
```

The status server reads from `state.json` and does not affect the trading agent.

---

## 🔍 Troubleshooting

### Service Won't Start

1. **Check IBKR Gateway:**
   ```bash
   ./scripts/gateway/gateway.sh status
   ```
   If not running, start it:
   ```bash
   ./scripts/gateway/gateway.sh start
   ```

2. **Check Telegram credentials:**
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

3. **Check for errors:**
   - If running in foreground, check terminal output
   - Check Telegram for error notifications
   - Review service state: `cat data/agent_state/NQ/state.json | jq .error_count`

4. **Verify configuration:**
   ```bash
   cat config/config.yaml
   ```

### No Signals Generated

1. **Check strategy session hours (StrategySessionOpen)**
   - Signals are generated during your configured prop-firm session window (default in `config/config.yaml`: **18:00–16:10 ET**, NY time).
   - Note: this is different from **FuturesMarketOpen** (CME ETH Sun 18:00 ET → Fri 17:00 ET, with Mon–Thu 17:00–18:00 ET maintenance break), which affects data freshness and Error 354 interpretation.
2. **If `/signals` shows signals but you didn’t receive signal alerts**
   - Check Telegram `/status` for **Delivered: X sent • Y failed** and **Last send error**.
   - Run: `python3 scripts/testing/test_all.py telegram` to confirm Telegram delivery is healthy.
3. **Check buffer size:**
   ```bash
   cat data/agent_state/NQ/state.json | jq .buffer_size
   ```
   Should be > 10 bars. If low, check data provider connection.
4. **Check signal confidence threshold** (minimum 50% required, configurable in `config.yaml`)
5. **Verify session is open:**
   ```bash
   # Strategy session hours are defined by config/config.yaml (default: 18:00–16:10 ET)
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
   cat data/agent_state/NQ/state.json | jq .error_count
   ```

2. **Service auto-pauses after 10 consecutive errors** (circuit breaker)
3. **Check for error details:**
   - If running in foreground, check terminal output for ERROR messages
   - Check Telegram for error notifications
   - Review service state: `cat data/agent_state/NQ/state.json | jq`

4. **Check connection failures:**
   ```bash
   cat data/agent_state/NQ/state.json | jq .connection_failures
   ```

### Data Quality Issues

1. **Check for stale data alerts** in Telegram
2. **Verify IBKR Gateway is connected:**
   ```bash
   ./scripts/gateway/gateway.sh status
   ```
3. **Check buffer size** (should be > 10 bars)
4. **Review data quality alerts:**
   - Check Telegram for data quality warnings
   - If running in foreground, check terminal output for warnings
   - Review service state: `cat data/agent_state/NQ/state.json | jq`

### IBKR Error 162: TWS Session Conflict

**Symptom:** Error message: `Error 162: Trading TWS session is connected from a different IP address`

**Cause:** Trader Workstation (TWS) is connected from a different IP address while Gateway is also trying to connect. IBKR doesn't allow both TWS and Gateway to be connected simultaneously from different IPs.

**Solution:**
1. **Check for TWS/Gateway conflicts:**
   ```bash
   ./scripts/gateway/gateway.sh tws-conflict
   ```

2. **Close TWS or disconnect it:**
   - If TWS is running on another machine, close it
   - If TWS is running locally, close the application
   - Or disconnect TWS from IBKR account

3. **Restart Gateway:**
   ```bash
   ./scripts/gateway/gateway.sh stop
   ./scripts/gateway/gateway.sh start
   ```

4. **Restart NQ Agent Service:**
   ```bash
   ./scripts/lifecycle/agent.sh stop --market NQ
   ./scripts/lifecycle/agent.sh start --market NQ
   ```

**Prevention:** Only use Gateway (not TWS) when running the automated service. If you need TWS for manual trading, disconnect Gateway first.

### Multiple Service Processes Running

**Symptom:** `check_agent_status.sh --market NQ` shows multiple PIDs running

**Cause:** Service didn't stop cleanly, leaving orphaned processes

**Solution:**
1. **Stop all service processes:**
   ```bash
   ./scripts/lifecycle/agent.sh stop --market NQ
   ```

2. **Verify all processes are stopped:**
   ```bash
   ./scripts/lifecycle/check_agent_status.sh --market NQ
   ```

3. **If processes persist, manually kill them:**
   ```bash
   # Find all processes
   pgrep -f "pearlalgo.nq_agent.main"
   
   # Kill each PID
   kill -9 <PID>
   ```

4. **Clean up PID file:**
   ```bash
   rm -f logs/nq_agent.pid
   ```

5. **Restart service:**
   ```bash
   ./scripts/lifecycle/agent.sh start --market NQ
   ```

---

## 📁 File Locations

**Configuration:**
- `config/config.yaml` - Main configuration file
- `.env` - Environment variables (not in git)

**Process Management:**
- `logs/nq_agent.pid` - Process ID file (for background mode)

**State & Data:**
- `data/agent_state/NQ/state.json` - Current service state
- `data/agent_state/NQ/signals.jsonl` - Signal history (JSONL format)
- `data/agent_state/NQ/performance.json` - Performance metrics

**Scripts:**
- `scripts/lifecycle/` - Service lifecycle scripts
- `scripts/gateway/` - IBKR Gateway scripts
- `scripts/testing/` - Testing and validation scripts

---

## 📚 Additional Resources

- `CHEAT_SHEET.md` – PEARLalgo quick reference
- `PROJECT_SUMMARY.md` – Complete system reference, architecture, components
- `GATEWAY.md` – IBKR Gateway setup and configuration
- `TESTING_GUIDE.md` – Testing procedures and validation

---

**Last Updated:** 2025-12-18  
**Current Configuration:** MNQ (Mini NQ) - Prop Firm Style Trading
