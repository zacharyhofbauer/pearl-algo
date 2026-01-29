# PEARLalgo Cheat Sheet

> **Goal:** One-page operational quick reference for daily use.
> For full details, see `MARKET_AGENT_GUIDE.md`, `GATEWAY.md`, and `TELEGRAM_GUIDE.md`.

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

### Option A: From Telegram (Remote Control) ⭐ Recommended

**Prerequisites:** Telegram Menu Handler must be running (one-time setup)

1. **Start Telegram Menu Handler** (if not already running)
   ```bash
   ./scripts/telegram/start_command_handler.sh
   ```
   **Restart (stop + start):**
   ```bash
   ./scripts/telegram/restart_command_handler.sh --background
   ```

2. **From Telegram, use the menu:**
   - Send `/start` to access the main control panel
   - Tap buttons for: Start/Stop Agent, Gateway Status, System Status, Signals & Trades, Performance, Tools, AI Features
   - **UI policy (don’t drift):** keep `/start` as the only slash command; keep ops behind buttons. If Telegram shows extra commands, run `python3 scripts/telegram/set_bot_commands.py` and restart the handler.
   - **Status semantics:** Agent/Gateway dots = services; Health dot = data/connection (grey when agent is off). Footer shows `Agent: <uptime> | Gateway: OK/DOWN | Data: <age>`.

### Option B: From Terminal (Traditional)

1. **Open terminal & activate venv**
   ```bash
   cd /path/to/pearlalgo-dev-ai-agents
   source .venv/bin/activate
   ```

2. **Start IBKR Gateway**
   ```bash
   ./scripts/gateway/gateway.sh start
   ./scripts/gateway/gateway.sh status   # expect: RUNNING + API READY
   ```

3. **Start Market Agent Service**
   - **Foreground (see logs)**
     ```bash
     ./scripts/lifecycle/agent.sh start --market NQ
     ```
   - **Background**
     ```bash
     ./scripts/lifecycle/agent.sh start --market NQ --background
     ./scripts/lifecycle/check_agent_status.sh --market NQ
     ```

4. **Start Telegram Command Handler** (for remote control)
   ```bash
   ./scripts/telegram/start_command_handler.sh              # foreground
   ./scripts/telegram/start_command_handler.sh --background # background with logs
   ```

---

## 3. Core Commands You Actually Use

### From Telegram (AI Insights) ⭐

- **AI Strategy Report:**
  ```
  /analyze           # Performance summary + strategy recommendation
  /start             # Open dashboard + menu buttons
  ```

### From Terminal (Traditional)

- **Service lifecycle**
  ```bash
  ./scripts/lifecycle/agent.sh start --market NQ         # start (fg)
  ./scripts/lifecycle/agent.sh start --market NQ --background
  ./scripts/lifecycle/agent.sh stop --market NQ          # stop
  ./scripts/lifecycle/check_agent_status.sh --market NQ  # status
  ```

- **Gateway**
  ```bash
  ./scripts/gateway/gateway.sh start        # start (headless, IBC)
  ./scripts/gateway/gateway.sh stop         # stop
  ./scripts/gateway/gateway.sh status       # status (process + port + logs)
  ./scripts/gateway/gateway.sh api-ready    # exit 0 when API is ready
  ```

- **Telegram Menu Handler**
  ```bash
  ./scripts/telegram/start_command_handler.sh            # show menu with buttons
  ./scripts/telegram/check_command_handler.sh            # is it running?
  python3 scripts/telegram/set_bot_commands.py           # (re)push menu commands
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

### Backtesting (Telegram) ✅

- **Command**:
  - `/backtest` → pick duration (1–6 months)
- **Primary timeframe**: **1m** (default decision stream; configurable in `config.yaml`)
- **MTF context**: 5m/15m used for trend alignment and dashboard charts
- **Caching (important)**:
  - Historical data is cached to: `data/historical/`
  - Files look like: `MNQ_1m_2m.parquet`, `MNQ_1m_6m.parquet`
  - The bot will **reuse cache first** and only hit IBKR if missing
  - Smaller windows can be **derived from larger caches** (ex: 2m sliced from 6m)

- **Offline quick-run** (fast sanity check):
  ```bash
  ls -1 data/historical/*.parquet
  # Backtesting scripts removed - using pearl_bot_auto only
  ```

- **Requires command handler running:**
  - **Commands (minimal by design):**
    - `/start` – Main dashboard + button menus
  - **Everything else is via buttons (recommended on mobile):**
    - **Signals & Trades** → recent signals, active trades, details, close-all
    - **Performance** → daily/weekly summaries and metrics
    - **Health** → system status, gateway status, connection, data quality
    - **System** → start/stop/restart agent, emergency stop
    - **Markets** → switch NQ/ES/GC context
    - **Bots** → bot selection/backtests/reports (if enabled)

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

## 8. Live Main Chart (Optional)

A web-based TradingView chart interface for real-time market visualization.

**Start the Live Main Chart:**

```bash
./scripts/live-chart/start.sh --market NQ
```

**View in browser:** http://localhost:3001

**Stop the chart:**

```bash
./scripts/live-chart/stop.sh
```

**Enable Telegram screenshot capture** (uses the web chart instead of matplotlib):

```bash
export PEARL_USE_LIVE_CHART=1
./scripts/telegram/restart_command_handler.sh --background
```

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `PEARL_USE_LIVE_CHART` | `0` | Set to `1` to capture screenshots from web chart |
| `PEARL_LIVE_CHART_URL` | `http://localhost:3001` | URL of the Live Main Chart |
| `PEARL_API_PORT` | `8000` | Port for the chart API server |
| `PEARL_CHART_PORT` | `3001` | Port for the chart web interface |

**Requirements:**
- Node.js 18+ (for Next.js)
- Playwright (`pip install playwright && playwright install chromium`) for screenshot capture

---

## 9. AI Patch Setup (Optional)

Generate code patches from Telegram using OpenAI. Useful for quick fixes when mobile.

> **Full guide:** See [AI_PATCH_GUIDE.md](AI_PATCH_GUIDE.md) for detailed documentation.

**One-time setup:**

```bash
# Install LLM extra
pip install -e ".[llm]"

# Add to .env (get key from https://platform.openai.com/)
# OPENAI_API_KEY=sk-...

# Restart command handler
./scripts/telegram/restart_command_handler.sh --background
```

**Usage from Telegram (recommended):**

- `/start` → **⚙️ Settings** → **🧩 AI Patch Wizard**
- Pick a file (or “Other file (type path)”), then send the instruction text

**Apply the patch:**

```bash
# Save the diff text from Telegram, then apply it locally.
# If this repo is in git:
git apply patch.diff
#
# If not using git:
patch -p1 < patch.diff
```

**Blocked paths** (for security): `data/`, `logs/`, `.env`, `ibkr/`, `.venv/`

---

## 10. Quick Health Check (2-Minute Checklist)

Run the health check script for a fast sanity check:

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

**Manual checks (if health_check.sh unavailable):**

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

| Service | Stop | Start | Restart |
|---------|------|-------|---------|
| **Agent (NQ)** | `./scripts/lifecycle/agent.sh stop --market NQ` | `./scripts/lifecycle/agent.sh start --market NQ --background` | Stop + Start |
| **Telegram** | `pkill -f telegram_command_handler` | `./scripts/telegram/start_command_handler.sh --background` | `./scripts/telegram/restart_command_handler.sh --background` |
| **Gateway** | `./scripts/gateway/gateway.sh stop` | `./scripts/gateway/gateway.sh start` | Stop + Start |

**Common restart scenarios:**

```bash
# After config.yaml change (full restart)
./scripts/lifecycle/agent.sh stop --market NQ
./scripts/lifecycle/agent.sh start --market NQ --background

# After code change (full restart all)
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

## 15. Troubleshooting & Maintenance

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