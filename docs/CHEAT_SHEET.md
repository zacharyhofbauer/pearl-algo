# PEARLalgo Cheat Sheet

> **Goal:** One-page operational quick reference for daily use.
> For full details, see `MARKET_AGENT_GUIDE.md`, `GATEWAY.md`, and `TELEGRAM_GUIDE.md`.

---

## 🐚 Quick Start (NEW - Recommended)

The `pearl.sh` master script handles everything with simple commands:

```bash
./pearl.sh start      # Start all: Gateway → Agent → Telegram → Chart
./pearl.sh stop       # Stop all services gracefully
./pearl.sh restart    # Restart everything
./pearl.sh status     # Show status of all services
./pearl.sh quick      # One-liner status check
```

**Individual service control:**
```bash
./pearl.sh gateway start|stop|status
./pearl.sh agent start|stop|status
./pearl.sh telegram start|stop|status
./pearl.sh chart start|stop|status    # Live Chart (pearlalgo.io)
```

**Options:**
```bash
./pearl.sh start --market ES        # Different market (default: NQ)
./pearl.sh start --no-telegram      # Skip Telegram handler
./pearl.sh start --no-chart         # Skip Live Chart
./pearl.sh start --foreground       # Run agent in foreground (debugging)
```

---

## 1. Environment & Setup (once per machine)

- **Create venv & install**
  ```bash
  cd ~/pearlalgo-dev-ai-agents
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e .
  ```

- **`.env` essentials**
  ```bash
  # Copy template, then edit real values
  cp env.example .env
  ```

  **Key concepts (don't confuse these):**
  - **StrategySessionOpen**: when the strategy is allowed to generate signals (config-driven session window; see `config/config.yaml` for start_time and end_time).
  - **FuturesMarketOpen**: when CME futures data is generally available (ETH Sun 18:00 ET → Fri 17:00 ET, with Mon–Thu 17:00–18:00 ET maintenance break).
  ```bash
  TELEGRAM_BOT_TOKEN=your_bot_token_here
  TELEGRAM_CHAT_ID=your_chat_id_here

  IBKR_HOST=127.0.0.1
  IBKR_PORT=4002
  IBKR_CLIENT_ID=10
  IBKR_DATA_CLIENT_ID=11

  # Optional: external IBKR Gateway install location
  # PEARLALGO_IBKR_HOME=/opt/ibkr

  PEARLALGO_DATA_PROVIDER=ibkr
  ```

---

## 2. Daily Start-Up Flow

### Option A: One Command (⭐ Recommended)

```bash
cd ~/pearlalgo-dev-ai-agents
./pearl.sh start
```

That's it! This starts Gateway → Agent → Telegram in the correct order.

**Check status anytime:**
```bash
./pearl.sh status     # Detailed view
./pearl.sh quick      # One-liner: PEARL: Gateway ✅ | Agent ✅ | Telegram ✅
```

### Option B: From Telegram (Remote Control)

**Prerequisites:** Telegram Menu Handler must be running (started by `./pearl.sh start`)

- Send `/start` to access the main control panel
- Tap buttons for: Activity, System, Health, Settings
- **UI policy (don't drift):** keep `/start` as the only slash command; keep ops behind buttons.
- **Status semantics:** Agent/Gateway dots = services; Health dot = data/connection.

### Option C: From Terminal (Traditional/Manual)

If you prefer individual control:

1. **Start IBKR Gateway**
   ```bash
   ./scripts/gateway/gateway.sh start
   ./scripts/gateway/gateway.sh status   # expect: RUNNING + API READY
   ```

2. **Start Market Agent Service**
   ```bash
   ./scripts/lifecycle/agent.sh start --market NQ --background
   ./scripts/lifecycle/check_agent_status.sh --market NQ
   ```

3. **Start Telegram Command Handler**
   ```bash
   ./scripts/telegram/start_command_handler.sh --background
   ```

---

## 3. Core Commands You Actually Use

### Master Control (⭐ Recommended)

```bash
./pearl.sh start      # Start everything
./pearl.sh stop       # Stop everything  
./pearl.sh restart    # Restart everything
./pearl.sh status     # Full status dashboard
./pearl.sh quick      # One-liner status
```

### From Telegram (Notifications & Dashboard)

- **Dashboard & Menu:**
  ```
  /start             # Open dashboard + menu buttons
  ```

> **Note:** Telegram is for notifications and dashboard only. For AI assistance, use CLI/terminal with `/pearl`.

### Individual Service Control (if needed)

- **Service lifecycle**
  ```bash
  ./pearl.sh agent start|stop|status        # Via master script
  # Or directly:
  ./scripts/lifecycle/agent.sh start --market NQ --background
  ./scripts/lifecycle/agent.sh stop --market NQ
  ./scripts/lifecycle/check_agent_status.sh --market NQ
  ```

- **Gateway**
  ```bash
  ./pearl.sh gateway start|stop|status      # Via master script
  # Or directly:
  ./scripts/gateway/gateway.sh start
  ./scripts/gateway/gateway.sh stop
  ./scripts/gateway/gateway.sh status
  ```

- **Telegram Menu Handler**
  ```bash
  ./pearl.sh telegram start|stop|status     # Via master script
  # Or directly:
  ./scripts/telegram/start_command_handler.sh --background
  ./scripts/telegram/check_command_handler.sh
  ```

---

## 4. Telegram Usage (what to expect)

- **Works even without menu handler:**
  - Startup / shutdown notifications
  - **Dashboard** hourly by default (consolidated: price sparkline, MTF trends, session stats, performance)
  - Signal alerts, error/circuit‑breaker alerts

> **Note:** Dashboard replaces the old separate Status/Heartbeat messages. One clean message per `dashboard_chart_interval` (default 1h).

- **Menu Handler Features:**
  - Interactive button-based control panel
  - Service management (start/stop agent/gateway)
  - Real-time monitoring and status
  - Performance analytics and reporting

### Menu Handler Features

- **Commands (minimal by design):**
  - `/start` – Main dashboard + button menus (the ONLY slash command)
- **Everything else is via buttons (recommended on mobile):**
  - **📊 Activity** → trades, signals, P&L, history
  - **🎛️ System** → start/stop/restart agent, gateway controls
  - **🛡️ Health** → connection status, data quality, diagnostics
  - **⚙️ Settings** → markets, alert preferences, bots

---

## 5. Quick Troubleshooting

- **No Telegram responses to `/start`:**
  ```bash
  ./scripts/telegram/check_command_handler.sh
  ./scripts/lifecycle/check_agent_status.sh --market NQ
  ```

- **No market data / no signals:**
  ```bash
  ./scripts/gateway/gateway.sh status
  cat data/agent_state/NQ/state.json | jq .buffer_size
  ```

- **Dashboard looks “weird” (e.g., cycles >> bars, signals generated but no alerts):**
  - `buffer_size` is a **rolling window** capped by config (often 100 bars). It will not grow with time.
  - `cycle_count` can be **total since first run** (persisted), while uptime is per-process.
  - Use Telegram **Dashboard** (`/start`) to see **session/total scans** and **signals generated vs sent vs failed**.
- **Service looks stuck / weird:**
  ```bash
  ./scripts/lifecycle/check_agent_status.sh --market NQ
  ./scripts/lifecycle/agent.sh stop --market NQ
  ./scripts/lifecycle/agent.sh start --market NQ
  ```

- **Verify Telegram config quickly:**
  ```bash
  echo $TELEGRAM_BOT_TOKEN
  echo $TELEGRAM_CHAT_ID
  python3 scripts/testing/test_all.py telegram
  ```

- **Check architecture boundaries (for development):**
  ```bash
  python3 scripts/testing/test_all.py arch                          # warn-only
  PEARLALGO_ARCH_ENFORCE=1 python3 scripts/testing/test_all.py arch # strict
  ```

---

## 6. Logs (systemd / journalctl)

When running via systemd, logs go to journald. Use these commands:

```bash
# Follow live logs
journalctl -u pearlalgo-mnq.service -f

# Last 10 minutes
journalctl -u pearlalgo-mnq.service --since -10m

# Since yesterday (for overnight review)
journalctl -u pearlalgo-mnq.service --since yesterday

# Filter by priority (errors only)
journalctl -u pearlalgo-mnq.service -p err
```

**Observability environment variables** (optional, in `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `PEARLALGO_LOG_LEVEL` | `INFO` | Override log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `PEARLALGO_LOG_JSON` | `false` | Set to `true` for JSON logs (useful for log aggregation) |
| `PEARLALGO_LOG_EXTRA` | `false` | Set to `true` to include `extra={...}` context in text logs |

**Notes:**
- When stdout is not a TTY (e.g., under systemd), ANSI colors are automatically disabled.
- Each process start gets a unique `run_id` (first 8 chars of UUID) for log correlation.
- Cycle-by-cycle context (cycle number, freshness, signals) appears in `extra` fields.

---

## 7. Where things live

- **Config**: `config/config.yaml`, `.env`
- **State**: `data/agent_state/<MARKET>/` (`state.json`, `signals.jsonl`, `exports/`)
- **Services & scripts**: `scripts/lifecycle/`, `scripts/gateway/`, `scripts/telegram/`
- **Logs**: stdout/stderr (foreground), journald (systemd), or Docker logs
- **Deep-dive docs**: `MARKET_AGENT_GUIDE.md`, `GATEWAY.md`, `TELEGRAM_GUIDE.md`, `PROJECT_SUMMARY.md`

---

## 8. Live Main Chart

A web-based TradingView-style chart with **real-time IBKR data**, indicators, and trade markers.

> ✅ **Data Source:** Live IBKR market data (often AHEAD of TradingView by 1-2 candles!)  
> ⚠️ **Requires:** Node.js 20.x + IBKR Gateway connected. Shows "No Data" if IBKR is offline.

**First-time setup (Node.js):**

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

**Start/Stop:**

```bash
./scripts/live-chart/start.sh --market NQ   # Start (API + Chart)
./scripts/live-chart/stop.sh                # Stop all
```

**Access:**
- **Local:** http://localhost:3001
- **Public:** https://pearlalgo.io (via Cloudflare Tunnel)

**Features:**

| Feature | Description |
|---------|-------------|
| **Timeframe Selector** | Switch between 1m, 5m, 15m, 1h (header buttons) |
| **Dynamic Viewport** | Bar count adjusts to screen width automatically |
| **Fit All / Go Live** | Quick buttons (top-right) to fit all data or jump to live edge |
| **Indicators** | EMA9 (cyan), EMA21 (yellow), VWAP (purple dashed) |
| **RSI Panel** | Separate RSI(14) panel with overbought/oversold lines |
| **Trade Markers** | Entry arrows and Exit dots with hover tooltips showing signal details |

**Environment Variables (.env):**

| Variable | Default | Description |
|----------|---------|-------------|
| `IB_CLIENT_ID_LIVE_CHART` | `97` | IBKR client ID (must be unique!) |
| `PEARL_MINI_APP_URL` | `https://pearlalgo.io/` | Public HTTPS URL |
| `PEARL_API_PORT` | `8000` | API server port |
| `PEARL_CHART_PORT` | `3001` | Chart web interface port |

⚠️ **Client ID Conflicts:** If you see "Error 326: client id already in use", change `IB_CLIENT_ID_LIVE_CHART` to an unused ID (96, 95, etc.) and restart.

**Telegram Screenshot** (optional):

The dashboard can include a chart screenshot at `data/agent_state/<MARKET>/exports/dashboard_telegram_latest.png`.

```bash
pip install playwright && playwright install chromium
```

### Cloudflare Tunnel (Public Access)

The chart is accessible at **https://pearlalgo.io** via Cloudflare Tunnel.

**Setup:**
- Tunnel: Configured in Cloudflare Zero Trust Dashboard
- Domain: `pearlalgo.io` → localhost:3001
- Service: Automatically routes to Next.js frontend

**Check tunnel status:**
```bash
# Tunnel runs automatically - check Zero Trust dashboard
# Or test: curl https://pearlalgo.io
```

**Troubleshooting:**
- Chart shows "No Data": IBKR Gateway is offline or disconnected
- Chart not loading: Check if live-chart processes are running (`ps aux | grep -E "api_server|next"`)
- Data delayed: This is normal! Chart often shows fresher data than TradingView

---

## 9. AI Assistant (CLI/Terminal)

Pearl AI assistant is available via CLI/terminal only. Telegram is for notifications and dashboard.

**Usage:**

```bash
# In terminal, use /pearl to chat with Pearl AI
/pearl

# Examples:
# - "how am I doing today?"
# - "what's my P&L?"
# - "restart the agent"
# - "show my trades"
```

> **Note:** AI features were removed from Telegram to keep the mobile interface clean and focused on notifications.

---

## 10. Quick Health Check (2-Minute Checklist)

**Fastest check (⭐ Recommended):**
```bash
./pearl.sh quick      # One-liner: PEARL: Gateway ✅ | Agent ✅ | Telegram ✅
./pearl.sh status     # Full dashboard with P&L and trades
```

**Or use the health check script:**
```bash
./scripts/health_check.sh
```

**What it verifies:**
- ✅ NQ Agent running
- ✅ Telegram Handler running
- ✅ IBKR Gateway running
- ✅ State file present and fresh
- ✅ Market & Session gates open
- ✅ Recent signal activity

**Manual checks (if needed):**

```bash
# Check all services running
pgrep -f "pearlalgo.market_agent.main" && echo "✅ Agent OK"
pgrep -f "telegram_command_handler" && echo "✅ Telegram OK"

# Check state freshness
stat data/agent_state/NQ/state.json | grep Modify

# Check signal diagnostics
cat data/agent_state/NQ/state.json | jq '.signal_diagnostics'

# Check today's signals
grep "$(date -u +%Y-%m-%d)" data/agent_state/NQ/signals.jsonl | wc -l
```

---

## 11. Restart Commands Quick Reference

### Using pearl.sh (⭐ Recommended)

```bash
./pearl.sh restart              # Restart everything
./pearl.sh gateway restart      # Restart just Gateway
./pearl.sh agent restart        # Restart just Agent
./pearl.sh telegram restart     # Restart just Telegram
```

### Manual Commands (if needed)

| Service | Stop | Start | Restart |
|---------|------|-------|---------|
| **All** | `./pearl.sh stop` | `./pearl.sh start` | `./pearl.sh restart` |
| **Agent (NQ)** | `./scripts/lifecycle/agent.sh stop --market NQ` | `./scripts/lifecycle/agent.sh start --market NQ --background` | Stop + Start |
| **Telegram** | `pkill -f telegram_command_handler` | `./scripts/telegram/start_command_handler.sh --background` | `./scripts/telegram/restart_command_handler.sh --background` |
| **Gateway** | `./scripts/gateway/gateway.sh stop` | `./scripts/gateway/gateway.sh start` | Stop + Start |

**Common restart scenarios:**

```bash
# After config.yaml change (full restart)
./pearl.sh restart

# Or manually:
./scripts/lifecycle/agent.sh stop --market NQ
./scripts/lifecycle/agent.sh start --market NQ --background

# After code change (full restart all)
./pearl.sh restart

# Or manually:
./scripts/lifecycle/agent.sh stop --market NQ
pkill -f telegram_command_handler
./scripts/lifecycle/agent.sh start --market NQ --background
./scripts/telegram/start_command_handler.sh --background
```

---

## 12. Safe Optimization Workflow (No Opportunity Loss)

> **Golden Rule:** Never tighten filters that reduce signal count without backtesting.

### Step 1: Check Current Performance

```bash
# View 7-day metrics
cat data/agent_state/NQ/signals.jsonl | jq -s '
  [.[] | select(.status == "exited")] |
  {total: length, wins: [.[] | select(.is_win == true)] | length, pnl: [.[].pnl] | add}'
```

Or from Telegram: `/performance 7d`

### Step 2: Identify Improvement Target

- **In-trade adjustments** (safe): trailing stops, breakeven, position sizing
- **Entry filtering** (risky): min_confidence, min_risk_reward, quality scorer

### Step 3: Test with Backtest Gate

For manual testing:
```bash
# Backtesting scripts removed - using pearl_bot_auto only
  # Backtesting scripts removed
  --data-path data/historical/MNQ_1m_2w.parquet
```

### Step 4: Apply Change

Edit `config/config.yaml` and restart:
```bash
./scripts/lifecycle/agent.sh stop --market NQ
./scripts/lifecycle/agent.sh start --market NQ --background
```

### Step 5: Verify No Opportunity Loss

Check signal diagnostics after a few cycles:
```bash
cat data/agent_state/NQ/state.json | jq '.signal_diagnostics_raw'
```

- `raw_signals` should be similar to before
- `validated_signals` should be similar (or higher if loosening)
- `rejected_*` counters show what's filtering

---

## 13. Key Config Paths (config/config.yaml)

| Path | Impact | Safe to Tune? |
|------|--------|---------------|
| `signals.min_confidence` | Filters low-confidence signals | ⚠️ Backtest first |
| `signals.min_risk_reward` | Filters poor R:R signals | ⚠️ Backtest first |
| `signals.quality_score.enabled` | Quality scorer on/off | ⚠️ Can block all signals |
| `risk.signal_type_size_multipliers` | Per-type position sizing | ✅ Safe (keeps signals) |
| `risk.signal_type_max_contracts` | Per-type contract caps | ✅ Safe (keeps signals) |

---

## 14. Direction Gating & Risk Phases (config/config.yaml)

The trading circuit breaker includes multiple phases of risk control that can be individually enabled/disabled.

### Phase 1: Direction Gating (ENABLED by default)
Blocks signals based on market regime alignment:
- **trending_up** → long only
- **trending_down** → short only  
- **ranging/volatile/unknown** → long only (conservative)

**Rollback:** Set `enable_direction_gating: false` under `trading_circuit_breaker`

### Phase 2: Regime Avoidance (OFF by default)
Blocks all signals in poor-performing regimes (ranging, volatile).
Shadow measurement logs "would-have-blocked" counts when OFF.

**Rollback:** Set `enable_regime_avoidance: false` under `trading_circuit_breaker`

### Phase 3: Trigger Filters (OFF by default)
Requires volume confirmation for ema_cross triggers and low-regime entries.

**Rollback:** Set `enable_trigger_filters: false` under `trading_circuit_breaker`

### Phase 4: ML Chop Shield (OFF by default)
Blocks ML FAIL signals in ranging/volatile regimes after lift is proven (50+ scored trades, 15%+ win-rate delta).

**Rollback:** Set `enable_ml_chop_shield: false` under `trading_circuit_breaker`

### Validation Checklist
After enabling any phase:
1. Check Telegram dashboard for `🛡️ Gate:` status line
2. Verify `state.json` shows `trading_circuit_breaker` section with correct flags
3. Monitor `blocks_by_reason` in circuit breaker status
4. Review logs for `Trading circuit breaker blocked signal` entries

---

## 15. Maintenance Scripts

### Reset 30-Day Performance

Reset the 30-day performance to a specific value (useful for prop firm account resets):

```bash
# Reset to $41.14 for market NQ
python3 scripts/maintenance/reset_30d_performance.py 41.14 NQ
```

This:
1. Deletes all trades from the last 30 days
2. Inserts a single trade with the specified PNL to set the 30d performance

### Purge Runtime Artifacts

Clean up runtime files (logs, PID files, cache):

```bash
# Dry run (see what would be deleted)
./scripts/maintenance/purge_runtime_artifacts.sh

# Actually delete (requires --yes)
./scripts/maintenance/purge_runtime_artifacts.sh --yes
```

---

## 16. Troubleshooting & Maintenance

### Clearing Telegram Chat History

If you need to clear the Telegram chat history with the bot to start fresh:

**On Mobile (iOS/Android):**
1. Open the Telegram app
2. Navigate to the chat with your bot (e.g., "PEARLalgo" or "NQ Agent")
3. Tap on the bot's name/header at the top
4. Tap "Clear History" or "Delete Chat" (exact wording varies by platform)
5. Confirm the action

**On Desktop (Telegram Desktop):**
1. Right-click on the bot chat in the chat list
2. Select "Clear History" or "Delete Chat"
3. Confirm the action

**Note:** This only clears the chat history on your device. The bot's state and data (positions, PNL, signals) are stored server-side and are not affected by clearing chat history.

### PNL Not Updating on Refresh

If PNL doesn't update when you tap the Refresh button:
- **Open positions:** The PNL now includes unrealized PNL from open positions. If positions are shown but PNL is stale, the refresh should now recalculate unrealized PNL automatically.
- **Virtual positions:** If using virtual PNL mode, positions shown are from signals.jsonl with status="entered". These are tracked positions, not necessarily broker-executed positions.
- **State file:** The agent service updates the state file with unrealized PNL. If refresh still shows stale data, check that the agent service is running and cycling properly.

---

This cheat sheet is the **primary quick-reference** for PEARLalgo operations. Keep it updated as workflows evolve.