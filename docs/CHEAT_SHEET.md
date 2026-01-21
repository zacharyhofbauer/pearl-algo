# PEARLalgo Cheat Sheet

> **Goal:** One-page operational quick reference for daily use.
> For full details, see `NQ_AGENT_GUIDE.md`, `GATEWAY.md`, and `TELEGRAM_GUIDE.md`.

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
   - Send `/start` or `/menu` to access the main control panel
   - Tap buttons for: Start/Stop Agent, Gateway Status, System Status, Signals & Trades, Performance, Tools, AI Features

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

3. **Start NQ Agent Service**
   - **Foreground (see logs)**
     ```bash
     ./scripts/lifecycle/start_nq_agent_service.sh
     ```
   - **Background**
     ```bash
     ./scripts/lifecycle/start_nq_agent_service.sh --background
     ./scripts/lifecycle/check_nq_agent_status.sh
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
  /help              # List available commands
  ```

### From Terminal (Traditional)

- **Service lifecycle**
  ```bash
  ./scripts/lifecycle/start_nq_agent_service.sh          # start (fg)
  ./scripts/lifecycle/start_nq_agent_service.sh --background
  ./scripts/lifecycle/start_nq_agent_service.sh --execution-dry-run  # ATS (dry_run, disarmed; logs only)
  ./scripts/lifecycle/stop_nq_agent_service.sh           # stop
  ./scripts/lifecycle/check_nq_agent_status.sh           # status
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
  - **Dashboard** every 15 minutes (consolidated: price sparkline, MTF trends, session stats, performance)
  - Signal alerts, error/circuit‑breaker alerts

> **Note:** Dashboard replaces the old separate Status/Heartbeat messages. One clean message every 15m.

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
  python scripts/backtesting/backtest_cli.py signal --data-path data/historical/<pick_one>.parquet
  ```

- **Requires command handler running:**
  - **Service Control:**
    - `/start_gateway` – Start IBKR Gateway
    - `/stop_gateway` – Stop IBKR Gateway
    - `/gateway_status` – Check Gateway status
    - `/start_agent` – Start NQ Agent Service
    - `/stop_agent` – Stop NQ Agent Service
    - `/restart_agent` – Restart NQ Agent Service
  - **Monitoring:**
    - `/status` – Agent Status card with inline buttons (includes Start/Stop controls)
    - `/signals` – Recent signals list
    - `/signal <id>` – Detailed view of specific signal (entry/SL/TP/exit/P&L)
    - `/performance` – 7‑day performance summary with export buttons
    - `/performance <lookback>` – Custom lookback: `24h`, `7d`, `30d`
    - `/config` – Show key configuration values
    - `/health` – Basic health check
    - `/settings` – UI preferences (dashboard buttons, auto-chart, snooze alerts)
    - `/help` – Command help
  - **Feedback & Learning:**
    - `/grade <signal_id> win|loss [pnl] [note]` – Record manual outcome for learning

---

## 5. Quick Troubleshooting

- **No Telegram responses to `/status`:**
  ```bash
  ./scripts/telegram/check_command_handler.sh
  ./scripts/lifecycle/check_nq_agent_status.sh
  ```

- **No market data / no signals:**
  ```bash
  ./scripts/gateway/gateway.sh status
  cat data/nq_agent_state/state.json | jq .buffer_size
  ```

- **Status looks “weird” (e.g., cycles >> bars, signals generated but no alerts):**
  - `buffer_size` is a **rolling window** capped by config (often 100 bars). It will not grow with time.
  - `cycle_count` can be **total since first run** (persisted), while uptime is per-process.
  - Use Telegram `/status` to see **session/total cycles** and **signals generated vs delivered vs failed**.
- **Service looks stuck / weird:**
  ```bash
  ./scripts/lifecycle/check_nq_agent_status.sh
  ./scripts/lifecycle/stop_nq_agent_service.sh
  ./scripts/lifecycle/start_nq_agent_service.sh
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
- **State**: `data/nq_agent_state/` (`state.json`, `signals.jsonl`, `exports/`)
- **Services & scripts**: `scripts/lifecycle/`, `scripts/gateway/`, `scripts/telegram/`
- **Logs**: stdout/stderr (foreground), journald (systemd), or Docker logs
- **Deep-dive docs**: `NQ_AGENT_GUIDE.md`, `GATEWAY.md`, `TELEGRAM_GUIDE.md`, `PROJECT_SUMMARY.md`

---

## 8. AI Patch Setup (Optional)

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

## 9. Quick Health Check (2-Minute Checklist)

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
pgrep -f "pearlalgo.nq_agent.main" && echo "✅ Agent OK"
pgrep -f "telegram_command_handler" && echo "✅ Telegram OK"

# Check state freshness
stat data/nq_agent_state/state.json | grep Modify

# Check signal diagnostics
cat data/nq_agent_state/state.json | jq '.signal_diagnostics'

# Check today's signals
grep "$(date -u +%Y-%m-%d)" data/nq_agent_state/signals.jsonl | wc -l
```

---

## 10. Restart Commands Quick Reference

| Service | Stop | Start | Restart |
|---------|------|-------|---------|
| **NQ Agent** | `./scripts/lifecycle/stop_nq_agent_service.sh` | `./scripts/lifecycle/start_nq_agent_service.sh --background` | Stop + Start |
| **Telegram** | `pkill -f telegram_command_handler` | `./scripts/telegram/start_command_handler.sh --background` | `./scripts/telegram/restart_command_handler.sh --background` |
| **Gateway** | `./scripts/gateway/gateway.sh stop` | `./scripts/gateway/gateway.sh start` | Stop + Start |

**Common restart scenarios:**

```bash
# After config.yaml change (full restart)
./scripts/lifecycle/stop_nq_agent_service.sh
./scripts/lifecycle/start_nq_agent_service.sh --background

# After code change (full restart all)
./scripts/lifecycle/stop_nq_agent_service.sh
pkill -f telegram_command_handler
./scripts/lifecycle/start_nq_agent_service.sh --background
./scripts/telegram/start_command_handler.sh --background
```

---

## 11. Safe Optimization Workflow (No Opportunity Loss)

> **Golden Rule:** Never tighten filters that reduce signal count without backtesting.

### Step 1: Check Current Performance

```bash
# View 7-day metrics
cat data/nq_agent_state/signals.jsonl | jq -s '
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
python scripts/backtesting/backtest_cli.py signal \
  --data-path data/historical/MNQ_1m_2w.parquet \
  --config-override "signals.min_confidence=0.5"
```

### Step 4: Apply Change

Edit `config/config.yaml` and restart:
```bash
./scripts/lifecycle/stop_nq_agent_service.sh
./scripts/lifecycle/start_nq_agent_service.sh --background
```

### Step 5: Verify No Opportunity Loss

Check signal diagnostics after a few cycles:
```bash
cat data/nq_agent_state/state.json | jq '.signal_diagnostics_raw'
```

- `raw_signals` should be similar to before
- `validated_signals` should be similar (or higher if loosening)
- `rejected_*` counters show what's filtering

---

## 12. Key Config Paths (config/config.yaml)

| Path | Impact | Safe to Tune? |
|------|--------|---------------|
| `signals.min_confidence` | Filters low-confidence signals | ⚠️ Backtest first |
| `signals.min_risk_reward` | Filters poor R:R signals | ⚠️ Backtest first |
| `signals.quality_score.enabled` | Quality scorer on/off | ⚠️ Can block all signals |
| `trailing_stop.enabled` | In-trade stop management | ✅ Safe |
| `trailing_stop.min_profit_before_be` | Breakeven threshold | ✅ Safe |
| `risk.signal_type_size_multipliers` | Per-type position sizing | ✅ Safe (keeps signals) |
| `risk.signal_type_max_contracts` | Per-type contract caps | ✅ Safe (keeps signals) |
| `drift_guard.enabled` | Auto-throttle on poor performance | ✅ Safe |

---

This cheat sheet is the **primary quick-reference** for PEARLalgo operations. Keep it updated as workflows evolve.