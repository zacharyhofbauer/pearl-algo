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

**Prerequisites:** Telegram Command Handler must be running (one-time setup)

1. **Start Telegram Command Handler** (if not already running)
   ```bash
   ./scripts/telegram/start_command_handler.sh
   ```
   **Restart (stop + start):**
   ```bash
   ./scripts/telegram/restart_command_handler.sh --background
   ```

2. **From Telegram, run:**
   ```
   /gateway_status    # Check Gateway
   /start_gateway      # Start Gateway (wait for 2FA approval)
   /start_agent        # Start Agent
   /status             # Verify everything is running
   ```

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

### From Telegram (Remote Control) ⭐

- **Service Control:**
  ```
  /start_gateway      # Start IBKR Gateway
  /stop_gateway       # Stop IBKR Gateway
  /gateway_status     # Check Gateway status
  /start_agent        # Start NQ Agent
  /stop_agent         # Stop NQ Agent
  /restart_agent      # Restart Agent (for config changes)
  ```

- **Monitoring:**
  ```
  /status             # Full status with inline buttons
  /signals            # Recent signals
  /performance        # 7-day performance
  /config             # Configuration values
  /health             # Health check
  /settings           # UI preferences (dashboard buttons, auto-chart, etc.)
  ```

- **AI Code Generation** (requires setup, see below):
  ```
  /ai_patch <file(s)> <task>   # Generate code patch via Claude
  ```
  Example: `/ai_patch src/pearlalgo/utils/retry.py add jitter to backoff`

- **Claude Monitor** (AI-powered monitoring, requires setup):
  ```
  /claude_status       # Claude monitor health & insights
  /analyze_now         # Force immediate analysis
  /analyze_signals     # Signal quality deep dive
  /analyze_system      # System health report
  /analyze_market      # Market conditions & regime
  /suggest_config      # Configuration suggestions
  /suggestions         # List active suggestions
  /apply_suggestion    # Apply a suggestion
  /claude_reports      # Report settings
  ```
  See `docs/CLAUDE_MONITOR_GUIDE.md` for full documentation.

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

- **Telegram Command Handler**
  ```bash
  ./scripts/telegram/start_command_handler.sh            # listen to commands
  ./scripts/telegram/check_command_handler.sh            # is it running?
  python3 scripts/telegram/set_bot_commands.py           # (re)push commands
  ```

---

## 4. Telegram Usage (what to expect)

- **Works even without command handler:**
  - Startup / shutdown notifications
  - **Dashboard** every 15 minutes (consolidated: price sparkline, MTF trends, session stats, performance)
  - Signal alerts, error/circuit‑breaker alerts

> **Note:** Dashboard replaces the old separate Status/Heartbeat messages. One clean message every 15m.

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
    - `/performance` – 7‑day performance summary
    - `/config` – Show key configuration values
    - `/health` – Basic health check
    - `/settings` – UI preferences (dashboard buttons, auto-chart, snooze alerts)
    - `/help` – Command help

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

Generate code patches from Telegram using Claude AI. Useful for quick fixes when mobile.

> **Full guide:** See [AI_PATCH_GUIDE.md](AI_PATCH_GUIDE.md) for detailed documentation.

**One-time setup:**

```bash
# Install LLM extra
pip install -e .[llm]

# Add to .env (get key from https://console.anthropic.com/)
echo 'ANTHROPIC_API_KEY=sk-ant-api03-...' >> .env

# Restart command handler
pkill -f telegram_command_handler
./scripts/telegram/start_command_handler.sh --background
```

**Usage from Telegram:**

```
/ai_patch <file(s)> <task>
```

**Examples:**

```
/ai_patch src/pearlalgo/utils/retry.py add jitter to backoff
/ai_patch src/foo.py,src/bar.py refactor X to Y
```

**Apply the patch:**

```bash
# Save the .diff file from Telegram, then:
git apply patch.diff
```

**Blocked paths** (for security): `data/`, `logs/`, `.env`, `ibkr/`, `.venv/`

---

This cheat sheet is the **primary quick-reference** for PEARLalgo operations. Keep it updated as workflows evolve.