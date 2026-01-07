# Telegram Integration Guide

This guide is the **canonical reference** for using Telegram with the NQ Agent.
It combines quick start steps, command setup, and command behavior.

---

## 1. Quick Start: Get Commands Working

### 1.1 Requirements

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set in `.env`
- Bot created via [@BotFather](https://t.me/botfather)
- NQ Agent service configured and working

### 1.2 Set Commands via BotFather (recommended)

1. Open Telegram and start a chat with `@BotFather`.
2. Send `/setcommands`.
3. Select your bot.
4. Paste this command list:
   ```
   start_gateway - Start IBKR Gateway
   stop_gateway - Stop IBKR Gateway
   gateway_status - Check Gateway status
   start_agent - Start NQ Agent Service
   stop_agent - Stop NQ Agent Service
   restart_agent - Restart NQ Agent Service
   start_monitor - Start Claude monitor service
   stop_monitor - Stop Claude monitor service
   monitor_status - Show monitor service status
   status - Get current agent status
   activity - Is the bot doing anything?
   signals - Show recent signals
   doctor - 24h rollup (signals, rejects, stops, sizing)
   signal - Show details for a specific signal by ID prefix
   last_signal - Show most recent signal with chart
   active_trades - Show currently open positions
   grade - Record manual outcome feedback for learning
   backtest - Run strategy backtest with chart
   reports - Browse saved backtest reports
   performance - Show performance metrics
   data_quality - Check data freshness and quality
   config - Show key configuration values (read-only)
   health - Show basic agent health (read-only)
   glossary - Explain key terms (Scans, Signals, Gates, etc.)
   chart - Generate on-demand price chart
   settings - Customize Telegram UI preferences
   ai - Open Claude AI hub
   ai_on - Enable Claude chat mode
   ai_off - Disable Claude chat mode
   ai_reset - Reset Claude chat history
   claude_status - Show Claude monitor status
   analyze_now - Run full AI analysis now
   review - Strategy review (AI summary + actions)
   strategy_review - Strategy review (alias)
   analyze_signals - AI: analyze signal quality
   analyze_system - AI: analyze system health
   analyze_market - AI: analyze market conditions
   suggest_config - AI: suggest config tuning
   suggestions - AI: list active suggestions
   apply_suggestion - AI: apply a suggestion by id
   rollback_suggestion - AI: rollback a previous change
   claude_reports - Show AI report schedule
   ai_patch - Generate code patch via Claude (requires setup)
   help - Show available commands
   ```
5. BotFather will confirm the commands are set.

### 1.3 Start the Telegram Command Handler

The command handler is a **separate service** that listens for `/status`, `/signals`, etc.

#### Option 1: Standalone (recommended for testing)

```bash
cd /path/to/pearlalgo-dev-ai-agents
python3 -m pearlalgo.nq_agent.telegram_command_handler
```

You should see something like:

```text
Starting Telegram command handler...
Listening for commands from chat ID: YOUR_CHAT_ID
Press Ctrl+C to stop
```

#### Option 2: Use the helper script

```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/telegram/start_command_handler.sh
```

This script:
- Changes to the project root
- Activates `.venv` if present
- Verifies `pearlalgo` is importable
- Starts `pearlalgo.nq_agent.telegram_command_handler`

### 1.4 Verify Commands Work

1. Start the command handler (see above).
2. In Telegram, send `/status`.
3. You should receive an **Agent Status** card with inline buttons.

If you do **not** get a response:
- Check the handler is running: `./scripts/telegram/check_command_handler.sh`
- Check logs: `tail -f logs/telegram_handler.log` (if you start it with `nohup`)
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct.

---

## 2. Optional: Set Commands via API

Instead of BotFather, you can set commands using the Telegram API.

A helper script is provided:

```bash
cd /path/to/pearlalgo-dev-ai-agents
python3 scripts/telegram/set_bot_commands.py
```

Internally it uses `python-telegram-bot` and calls `Bot.set_my_commands()` with the same command list.

---

## 3. Available Commands and Behavior

Once the command handler is running and commands are configured, the bot supports these commands.

### 3.1 `/start` and `/help`

- Shows basic bot information and available commands.
- Intended primarily for you (authorized chat ID).

### 3.2 Service Control Commands

#### `/start_gateway`
- Starts IBKR Gateway (may take 60+ seconds for authentication)
- Returns success/failure status
- **Note:** Gateway startup requires 2FA approval via IBKR mobile app

#### `/stop_gateway`
- Stops IBKR Gateway gracefully
- Verifies Gateway process is stopped

#### `/gateway_status`
- Shows Gateway process status (running/stopped)
- Shows API port status (listening/not listening)
- Quick health check for Gateway

#### `/start_agent`
- Starts NQ Agent Service in background mode
- Checks if Gateway is running (warns if not)
- Verifies agent process started successfully

#### `/stop_agent`
- Stops NQ Agent Service gracefully
- Verifies agent process is stopped

#### `/restart_agent`
- Stops then starts NQ Agent Service
- Useful for applying configuration changes
- Shows status of both stop and start operations

### 3.3 `/status`

Returns the current agent status, including:

- Running / stopped state
- Pause reason (if paused)
- Activity pulse (time since last scan)
- Gates (standardized terminology):
  - **Futures** (CME ETH + maintenance break; affects data freshness)
  - **Session** (config-driven strategy window; when signals are allowed)
  - When session is closed, shows configured window and next session opening time
- Scans and signals (clarified):
  - **Scans**: session/total (total persists across restarts)
  - **Signals**: generated vs delivered vs failed
- Buffer size (rolling): current/target bars
- Compact 7-day performance summary with trend indicator
- Inline buttons for quick access to all features

### 3.4 `/activity`

Answers the question "Is the bot doing anything?" with:

- Agent status and activity pulse (time since last scan, using `last_successful_cycle`)
- Scan count (session and total)
- Buffer status with fill percentage
- Latest price
- Active Trades count
- Next expected action (e.g., "Next scan in ~60s", "Waiting for session")
- Stale scan warning if scans appear stalled

**Use this when:**
- You're unsure if the bot is actively monitoring
- You want a quick check without full status details
- You want to know what the bot will do next

### 3.5 `/signals`

- Shows the last **10 recent trading signals**.
- For each signal, includes:
  - Type (e.g., breakout)
  - Direction (LONG)
  - Entry price
  - Current status (`generated`, `entered`, `exited`, `expired`).
- Data is read from `data/nq_agent_state/signals.jsonl` via the `state_manager` and `performance_tracker`.

### 3.5 `/performance`

- Shows **7‑day performance metrics** by default:
  - Total signals and exited signals
  - Win / loss counts
  - Win rate percentage
  - Total P&L and average P&L
  - Breakdown by signal type
- Uses the same performance metrics as the periodic Telegram summaries.

**Lookback Options:**
- `/performance` – Default 7-day lookback
- `/performance 24h` – Last 24 hours
- `/performance 7d` – Last 7 days (explicit)
- `/performance 30d` – Last 30 days

**Export Buttons:**
When you run `/performance`, you'll see export buttons:
- **📄 Signals JSONL** – All signals with full metadata (regime, MTF, VWAP, etc.)
- **📄 Exited CSV** – Completed trades with columns: timestamp, signal_id, type, direction, confidence, entry_price, stop_loss, take_profit, exit_price, exit_reason, pnl, is_win, hold_minutes
- **📊 Metrics JSON** – Aggregated performance data

> **Tip:** Export the CSV and share it to get detailed analysis of your signal outcomes.

### 3.5.1 `/signal <id_prefix>`

Shows detailed information for a specific signal:
- Entry price, stop loss, take profit
- Confidence score and signal type
- Regime, session, and market context
- Exit details and P&L (if exited)

**Usage:**
```
/signal sr_bounce_1767     # Shows signal matching this prefix
/signal mean_rev           # Partial match works
```

You can also get a JSON file attachment with the full signal data for sharing.

### 3.5.2 `/grade` - Manual Feedback for Learning

Record your own trade outcomes to help the learning system:

```
/grade <signal_id_prefix> win|loss [pnl] [note]
```

**Examples:**
```
/grade sr_bounce_1767 win 150 Great entry, held to target
/grade mean_rev_456 loss -75 Stopped out on news spike
/grade momentum_short win    # P&L optional
```

**Notes:**
- Feedback is recorded to `data/nq_agent_state/feedback.jsonl`
- If the signal already has a virtual exit, feedback is logged but not double-counted
- Use `/grade ... force` to override and apply to learning anyway

### 3.6 `/config` and `/health`

- `/config`: Shows key configuration values (read-only)
  - Symbol, timeframe, scan interval
  - Risk parameters and position sizing
  
- `/health`: Shows basic agent health status
  - Agent process status
  - State file presence and last update time

### 3.7 `/glossary` (or `/explain`)

Explains key terms used in the UI:

- **Scans** – Strategy loop iterations (each scan looks for trading setups)
- **Signals** – Detected trading opportunities (generated → sent → entered → exited)
- **Pressure** – Order flow imbalance from Level 2 data
- **MTF** – Multi-timeframe trend alignment
- **Gates** – Market hours (Futures) and strategy session windows (Session)
- **Active Trades** – Currently open positions
- **Buffer** – Rolling price data held in memory

**Usage:**
- `/glossary` – Show all terms with drill-down buttons
- `/glossary scans` – Show detailed explanation for "Scans"

### 3.8 `/settings`

Customize your Telegram UI preferences. Changes take effect immediately.

**Available Settings:**

| Setting | Default | Description |
|---------|---------|-------------|
| **Dashboard Buttons** | Off | Add quick-action navigation buttons to dashboards and signal/trade alerts |
| **Expanded Signal Details** | Off | Show full context (regime, MTF, VWAP) by default in signal details |
| **Auto-Chart on Signal** | Off | Automatically generate and send chart with each signal alert |
| **Snooze Non-Critical Alerts** | Off | Temporarily suppress non-critical data quality alerts (1 hour) |

**Usage:**
- `/settings` – Open settings menu with toggle buttons
- Tap a button to toggle a setting on/off
- "Reset Defaults" returns all settings to calm-minimal defaults

**Notes:**
- All settings default to **off** (calm-minimal by default)
- Snooze auto-expires after 1 hour
- Critical alerts (circuit breaker, recovery) are never snoozed
- Settings are stored in `data/nq_agent_state/telegram_prefs.json`

### 3.9 `/chart`

Generates an on-demand price chart.

**Usage:**
- `/chart` – Generate 12-hour chart (default)
- `/chart 16` – Generate 16-hour chart
- `/chart 24` – Generate 24-hour chart (maximum)

**Features:**
- Candlestick price action
- Volume bars
- Pressure panel (if enabled)
- Timeframe toggle buttons: 12h, 16h, 24h (with checkmark on active)

### 3.10 `/pause` and `/resume` (Legacy)

- Currently **informational only** (use `/stop_agent` and `/start_agent` instead)
- These commands acknowledge receipt but don't perform actions
- For full control, use the service control commands above

### 3.11 ATS Execution Commands (When Enabled)

These commands control the Automated Trading System. **ATS is disabled by default** (`execution.enabled: false`).

See [ATS_ROLLOUT_GUIDE.md](ATS_ROLLOUT_GUIDE.md) for safe rollout procedures before enabling.

| Command | Description |
|---------|-------------|
| `/arm` | Arm execution adapter for order placement |
| `/disarm` | Disarm execution (stops new orders, existing positions continue) |
| `/kill` | **Emergency**: Cancel all orders AND disarm |
| `/positions` | Show current positions and execution status |
| `/policy` | Show bandit policy status and per-signal-type statistics |

**Safety notes:**
- ATS starts **disarmed** even when enabled; must `/arm` to place orders
- `/kill` is the emergency stop; cancels all pending orders immediately
- Daily loss limit triggers automatic disarm (see `execution.max_daily_loss`)
- Learning runs in **shadow mode** by default (observe only, no execution impact)

### 3.12 Claude AI (Mobile Cursor)

Claude AI is integrated as a **mobile Cursor-like experience**. Chat with Claude, get code patches, and fix issues — all from your phone.

> **Full documentation:** See [AI_PATCH_GUIDE.md](AI_PATCH_GUIDE.md) for complete setup, usage, and troubleshooting.

**Setup Required:**

1. Install the LLM extra: `pip install -e .[llm]`
2. Add your Anthropic API key to `.env`:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```
3. Restart the Telegram command handler

**Commands:**

| Command | Description |
|---------|-------------|
| `/ai` | Open AI Hub (or tap `🤖 AI Hub` on Home) |
| `/ai_on` | Enable chat mode (messages go to Claude) |
| `/ai_off` | Disable chat mode |
| `/ai_reset` | Clear chat history |
| `/ai_patch <files> <task>` | Direct patch generation (power user) |

**Claude Hub Features:**

- **💬 Chat Mode** - Toggle to chat with Claude about your code
- **🧩 Patch Wizard** - Task-first flow (describe change → pick files → get diff)
- **🧼 Reset** - Clear conversation history

**Strategy Review UI (clean + minimal):**

- The Review screen is intentionally compact (lookback + refresh + **More**).
- Tap **More** to access advanced actions like **Export**, **Discuss**, **Patch Wizard**, **Suggest Config**, **Suggestions**, **Backtest**, and **Reports**.

**Patch Wizard (No Path Typing):**

1. Tap `🧩 Patch Wizard`
2. Describe what you want to change in plain English
3. Claude suggests relevant files — tap to select
4. Tap `✅ Generate Patch`
5. Apply with `git apply patch.diff`

**Direct Command (Power Users):**

```
/ai_patch <file(s)> <task description>
```

Examples:
- `/ai_patch src/pearlalgo/utils/retry.py add exponential backoff with jitter`
- `/ai_patch src/foo.py,src/bar.py refactor the logging`

**Security:**

- Only your authorized chat ID can use these commands
- Blocked paths: `data/`, `logs/`, `.env`, `ibkr/`, `.venv/`, `.git/`
- File size limit: 100KB per file
- Path traversal protection

### 3.13 AI Terminal Mode (Operator Terminal)

The AI Terminal provides a **deterministic command interface** for quick agent control without menus. Commands start with `!` and work even when chat mode is off.

**Terminal Commands:**

| Command | Description |
|---------|-------------|
| `!help` | Show all terminal commands |
| `!status` | Agent status snapshot |
| `!config <path>` | Show config value |
| `!config <path> <value>` | Update config value (policy-gated) |
| `!apply <suggestion_id>` | Apply a suggestion |
| `!rollback <request_id>` | Rollback a previous change |
| `!suggestions` | List active suggestions |
| `!audit [n]` | Show recent audit entries (default 10) |
| `!policy` | Show auto-tune policy status |

**Examples:**

```
!status
```
Response:
```
📊 Agent Status

Mode: paper ⚪ Disarmed
Running: ✅
Uptime: 2h 15m
Connection: 🟢
Errors: 0

Last Signal: 10:15:00
Open Positions: 1
```

```
!config signals.min_confidence
```
Response:
```
📝 Config Value

Path: signals.min_confidence
Value: 0.60
```

```
!config signals.min_confidence 0.65
```
Response:
```
✅ Config Updated

Path: signals.min_confidence
Old: 0.60
New: 0.65

Request ID: act_20260102103000_0001
Rollback: !rollback act_20260102103000_0001
```

**Policy Enforcement:**

Terminal config updates go through the same Auto-Tune Policy as Claude Monitor:
- Only allowlisted config paths can be modified
- Values are bounded (max delta per change)
- Rate limits enforced
- Blocked paths return a rejection message

**Quick Reference:**

| Want to... | Terminal Command |
|------------|-----------------|
| Check agent health | `!status` |
| See today's suggestions | `!suggestions` or `!sug` |
| Apply suggestion #3 | `!apply sug_003` |
| Undo a change | `!rollback act_xxx` |
| Tweak confidence | `!config signals.min_confidence 0.65` |
| Check audit log | `!audit 20` |

---

## 4. What Needs the Command Handler vs. What Does Not

### 4.1 Works without the command handler

These notifications come directly from the NQ Agent Service via `NQAgentTelegramNotifier`:

- Startup and shutdown notifications
- Signal notifications
- **Dashboard** (every 15 minutes) – replaces the old Status/Heartbeat messages
- Error and circuit‑breaker alerts

> **Note:** The dashboard combines price sparkline, MTF trends, session stats, and performance into one clean message every 15m.

### 4.2 Requires the command handler

These features require the command handler service to be running:

- All service control commands (`/start_gateway`, `/stop_gateway`, `/start_agent`, etc.)
- All monitoring commands (`/status`, `/signals`, `/performance`, `/config`, `/health`)
- Inline button callbacks (Start/Stop Agent, Gateway Status, Performance, Signals, etc.)

If commands are unresponsive but you still get status/heartbeat messages, it almost always means the command handler is not running.

---

## 5. Security and Authorization

- The command handler checks that the incoming chat ID matches `TELEGRAM_CHAT_ID`.
- Unauthorized chats receive a simple "Unauthorized access" message.
- Secrets (bot token, chat ID) must remain in `.env` and **never** be committed.

---

## 6. Troubleshooting Cheat Sheet

- **No command responses:**
  - Run `./scripts/telegram/check_command_handler.sh`.
  - If not running, start it with `./scripts/telegram/start_command_handler.sh`.
- **`python-telegram-bot` import errors:**
  - Install inside your venv: `pip install python-telegram-bot`.
- **Handler crashes on start:**
  - Check logs (`logs/telegram_handler.log` if using `nohup`).
  - Verify `.env` is loaded and `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are set.
- **Commands missing in Telegram UI:**
  - Re‑run `/setcommands` in BotFather or `scripts/telegram/set_bot_commands.py`.

---

## 7. Remote Control: Complete System Control via Telegram

The Telegram bot provides complete remote control of your MNQ Agent system, including starting/stopping the Gateway and Agent services directly from Telegram.

### 7.1 Service Control Commands

#### Gateway Control

**`/start_gateway`**
- Starts IBKR Gateway remotely
- Executes `./scripts/gateway/gateway.sh start`
- Waits up to 120 seconds for Gateway to start
- Verifies Gateway process is running and API port 4002 is listening
- **Note:** Gateway startup requires 2FA approval via IBKR mobile app
- May take 60+ seconds if authentication is needed

**`/stop_gateway`**
- Stops IBKR Gateway gracefully
- Executes `./scripts/gateway/gateway.sh stop`
- Verifies Gateway process is stopped

**`/gateway_status`**
- Quick health check for IBKR Gateway
- Shows process status (running/stopped)
- Shows API port status (listening/not listening)
- Overall Gateway health summary

#### Agent Service Control

**`/start_agent`**
- Starts NQ Agent Service in background mode
- Executes `./scripts/lifecycle/start_nq_agent_service.sh --background`
- Checks if Gateway is running (warns if not)
- Verifies agent process started successfully

**`/stop_agent`**
- Stops NQ Agent Service gracefully
- Executes `./scripts/lifecycle/stop_nq_agent_service.sh`
- Verifies agent process is stopped

**`/restart_agent`**
- Restarts NQ Agent Service (stop then start)
- Useful for applying configuration changes
- Shows status of both stop and start operations
- **When to use:**
  - After changing `config/config.yaml`
  - After updating code
  - If agent seems stuck or unresponsive

### 7.2 Complete Workflow Examples

#### Morning Startup (All from Telegram)

```
1. /gateway_status        # Check if Gateway is running
2. /start_gateway         # Start Gateway if needed (wait for 2FA approval)
3. /gateway_status        # Verify Gateway is ready
4. /start_agent           # Start the agent
5. /status                # Verify agent is running
```

#### End of Day Shutdown

```
1. /stop_agent            # Stop the agent
2. /stop_gateway          # Stop Gateway (optional)
3. /status                # Verify everything is stopped
```

#### Apply Configuration Changes

```
1. Edit config/config.yaml on server
2. /restart_agent         # Restart to apply changes
3. /status                # Verify new config is active
4. /config                # View current configuration
```

#### Troubleshooting Workflow

```
1. /status                # Check agent status
2. /gateway_status        # Check Gateway status
3. /health                # Quick health check
4. /restart_agent         # If agent seems stuck
```

### 7.3 Inline Buttons and UI Navigation

The `/status` command includes inline buttons for quick actions:

- **▶️ Start Agent** / **⏹️ Stop Agent** – Quick service control
- **🔄 Restart** – Restart agent
- **🔌 Gateway Status** – Check Gateway health (tri-state indicator):
  - `✅` – Gateway running **and** API ready (data flowing)
  - `🟡` – Gateway running but API not ready (authenticating or awaiting 2FA)
  - `❌` – Gateway stopped
- **📊 Performance** – Detailed metrics
- **🔔 Signals** – Recent signals
- **⚙️ Config** – Configuration values
- **💚 Health** – Health check
- **🏠 Main Menu** – Return to main menu from any view

**Navigation Features:**
- **100% Button-Based**: No need to type commands
- **Contextual Buttons**: Adapt based on current state
- **Status Indicators**: Visual feedback (✅/🟡/❌) on buttons
- **Quick Actions**: Refresh, shortcuts, and navigation

### 7.4 Security & Safety

**Authorization:**
- Only your authorized chat ID (from `TELEGRAM_CHAT_ID`) can execute service control commands
- Unauthorized users receive "❌ Unauthorized access" message
- All command attempts are logged with chat ID

**Safety Features:**
- **Timeouts:** All scripts have execution timeouts (prevents hanging)
- **Verification:** Commands verify processes actually started/stopped
- **Error Handling:** Failures are reported with clear error messages
- **Logging:** All remote control actions are logged

**Best Practices:**
1. **Always check status before starting:**
   ```
   /gateway_status
   /status
   ```
   Prevents duplicate processes

2. **Verify after operations:**
   ```
   /start_agent
   /status  # Verify it actually started
   ```

3. **Use restart for config changes:**
   ```
   /restart_agent  # Safer than stop + start separately
   ```

### 7.5 Command Reference Table

| Command | Purpose | Timeout | Notes |
|---------|---------|---------|-------|
| `/start_gateway` | Start IBKR Gateway | 120s | Requires 2FA approval |
| `/stop_gateway` | Stop IBKR Gateway | 30s | Graceful shutdown |
| `/gateway_status` | Check Gateway status | Instant | Read-only |
| `/start_agent` | Start NQ Agent | 30s | Background mode |
| `/stop_agent` | Stop NQ Agent | 30s | Graceful shutdown |
| `/restart_agent` | Restart NQ Agent | 60s | Stop + Start |
| `/status` | Agent status | Instant | Includes controls |
| `/signals` | Recent signals | Instant | Last 10 signals |
| `/performance` | Performance metrics | Instant | 7-day summary |
| `/config` | Configuration | Instant | Read-only |
| `/health` | Health check | Instant | Read-only |
| `/settings` | UI preferences | Instant | Toggle buttons |

### 7.6 Advanced Usage

#### Scheduled Operations

You can combine commands for automated workflows:

```
# Morning routine (run these in sequence)
/gateway_status
/start_gateway
# Wait for Gateway ready notification
/start_agent
/status
```

#### Monitoring Workflow

```
# Quick health check
/health
/gateway_status

# Detailed status
/status
/performance
```

#### Emergency Stop

```
# Stop everything immediately
/stop_agent
/stop_gateway
```

### 7.7 Integration with Existing Scripts

The Telegram commands execute the same shell scripts you'd run manually:

- `/start_gateway` → `./scripts/gateway/gateway.sh start`
- `/stop_gateway` → `./scripts/gateway/gateway.sh stop`
- `/start_agent` → `./scripts/lifecycle/start_nq_agent_service.sh --background`
- `/stop_agent` → `./scripts/lifecycle/stop_nq_agent_service.sh`

This means:
- ✅ Same behavior as manual execution
- ✅ Same error handling and logging
- ✅ Same safety checks
- ✅ You can still use scripts if Telegram is unavailable

### 7.8 Troubleshooting Remote Control

**Commands Not Working:**
1. Check command handler is running: `./scripts/telegram/check_command_handler.sh`
2. Start command handler if needed: `./scripts/telegram/start_command_handler.sh`
3. Verify bot commands are set: `python3 scripts/telegram/set_bot_commands.py`

**Gateway Won't Start:**
- Check IBKR account is active
- Verify 2FA approval on mobile app
- Check Gateway logs: `tail -f ibkr/ibc/logs/gateway_*.log`

**Agent Won't Start:**
- Check Gateway is running: `/gateway_status`
- Verify Python environment: `python3 -c "import pearlalgo"`
- Check for port conflicts: `ss -tuln | grep 4002`

**Commands Timeout:**
- Gateway startup can take 60+ seconds (normal)
- Agent startup should be < 30 seconds
- If consistently timing out, check server resources

---

## 8. Chart Visualization and UI Features

The Telegram bot provides professional chart visualization and a fully UI-driven interface.

### 8.1 Chart Types

**Entry Charts:**
- Candlestick price action
- Entry line (green/orange)
- Stop loss line (red dashed)
- Take profit line (green dashed)
- Volume bars

**Exit Charts:**
- Full trade lifecycle
- Entry and exit points
- P&L annotation
- Reference stop/TP levels
- Color-coded by win/loss

**Backtest Charts:**
- Historical price action
- Signal markers (triangles)
- Long signals (green ▲)
- Short signals (orange ▼)
- Entry lines for each signal

### 8.2 Test Signal Generation

**Purpose:** Test chart visualization when no real signals exist

**Usage:**
1. Send `/test_signal` or tap "🧪 Test Signal" button
2. System generates a test signal with realistic data
3. Chart is automatically sent
4. Use "🔄 Generate Another" to create more

**Features:**
- Realistic price action simulation
- Entry/Stop/TP levels displayed
- Professional chart formatting
- Instant feedback

### 8.3 Backtest Visualization

**Purpose:** Visualize strategy performance on historical data

**Usage:**
1. Send `/backtest` or tap "📉 Backtest" button
2. System runs demo backtest (if data available)
3. Results and chart are sent
4. Shows signal markers on price chart

**Features:**
- Signal markers (long/short)
- Price action visualization
- Performance metrics
- Chart with all signals
- Detailed PDF report: `/reports` → select report → **📄 PDF Report** (downloads `report.pdf`)

### 8.4 Menu System and Button Navigation

The bot features a **fully UI-driven interface** with inline keyboard buttons. No need to type commands - everything is accessible through intuitive button navigation!

**Main Menu (Status View):**
- Appears when you send `/start`, tap "🏠 Main Menu", or send `/status`
- Button layout:
  - **Stop Agent** / **Restart** (if agent running)
  - **Start Agent** (if agent stopped)
  - **Gateway 🔌 ✅/🟡/❌** (tri-state: ready / authenticating / stopped)
  - **Last Signal** / **Trades**
  - **Activity** / **Data Quality**
  - **Signals** / **Performance**
  - **Backtest** / **Reports**
  - **Settings** (includes Help, Config, Claude hub)

**Signals View:**
- Access via `/signals` or "🔔 Signals" button
- Chart buttons for each signal
- Refresh and Last Signal shortcuts
- Navigation to Performance and Main Menu

**Gateway View:**
- Access via "🔌 Gateway Status" button
- Start/Stop Gateway buttons
- Quick status refresh
- Navigation buttons

**Button Features:**
- **Status Indicators:** Gateway button shows ✅ (ready), 🟡 (authenticating), or ❌ (stopped)
- **Contextual Actions:** Buttons adapt based on current state
- **Quick Actions:** Refresh, shortcuts, and navigation
- **Always Available:** Main Menu button returns to status from anywhere

**Navigation Patterns:**
1. **Check Status:** Tap "📊 Status" → See current state → Tap "🔄 Refresh" to update
2. **View Signals:** Tap "🔔 Signals" → See signal list → Tap "📊 Chart" to view specific signal
3. **Control Services:** Tap "▶️ Start Agent" / "⏹️ Stop Agent" / "🔄 Restart"
4. **Monitor Gateway:** Tap "🔌 Gateway Status" → Check gateway → Tap "▶️ Start Gateway" if stopped

### 8.5 Chart Integration

Charts are fully integrated with the menu system:

1. **Automatic Charts:** Sent with signals automatically by the service
2. **Chart Buttons:** Available in signals view for each signal
3. **Chart Viewing:** Tap "📊 Chart" to view any signal's chart
4. **Test Signals:** Use `/test_signal` to verify chart generation

For detailed chart setup and customization, see [MPLFINANCE_QUICK_START.md](MPLFINANCE_QUICK_START.md).

### 8.6 Troubleshooting Charts and Buttons

**Charts Not Generating:**
- Check matplotlib is installed: `pip install matplotlib`
- Verify chart generator: `/test_signal` should work
- Check logs: `tail -f logs/telegram_handler.log`

**Chart Error Messages (User-Friendly):**
When chart generation fails, the bot shows calm, actionable messages instead of raw errors:
- "📊 *Chart Unavailable*" – Something prevented chart generation; try `/data_quality` to diagnose
- "⏱️ *Chart Timed Out*" – Generation took too long; try a shorter timeframe
- "📊 *Chart Delivery Failed*" – Chart was generated but couldn't be sent; try again

All error messages include a "What to try" section pointing to `/data_quality` or next actions.

**Buttons Not Appearing:**
- Restart handler: `./scripts/telegram/start_command_handler.sh --background`
- Check handler status: `./scripts/telegram/check_command_handler.sh`
- Verify authorization (chat ID)

**Buttons Not Working:**
- Check handler logs: `tail -f logs/telegram_handler.log`
- Verify authorization (check chat ID matches)
- Restart handler to reload callbacks

**Old Messages Without Buttons:**
- Send a new command (like `/status`) to get buttons

---

## 9. UX Philosophy: Calm-Minimal

The Telegram UI follows a **calm-minimal** design philosophy:

> *Healthy state stays CALM. Degraded state gets EXPLANATIONS.*

**Core principles:**

1. **Decision-first layout**: Trade plan and action cue appear before context
2. **Progressive disclosure**: Details live in drill-down views, not push alerts
3. **Silence is a feature**: Only show warnings when something needs attention
4. **Consistent labeling**: Same emoji/label semantics across all views

### 9.1 Activity Pulse

The `/status` Home Card shows an "activity pulse" indicator computed from `last_successful_cycle`:

- 🟢 **Active** (< 2 min): Agent is actively scanning
- 🟡 **Slow** (2-5 min): Agent may be waiting or slow
- 🔴 **Stale** (> 5 min): Agent may need attention

This answers "is the bot doing anything?" at a glance.

### 9.2 Standardized Terminology

The UI uses consistent labels across all views:

| Term | Meaning |
|------|---------|
| **Agent** | NQ Agent service (the trading bot process) |
| **Gateway** | IBKR Gateway (the broker connection) |
| **Scans** | Per-cycle processing iterations |
| **Signals** | Trading opportunities generated |
| **Futures** | CME futures market open/closed |
| **Session** | Strategy session window (config-driven; see /config) |
| **Active Trades** | Currently open positions |
| **Buffer** | Rolling bar data held in memory |

### 9.3 Active Trades Count

When positions are open, the Home Card shows:

```
🎯 *1 active trade*
```

This only appears when count > 0 (calm-minimal: no noise when nothing is active).

### 9.4 Signal Push Alerts (Calm-Minimal)

Signal alerts use a decision-first, compact layout:

```
🎯 *MNQ 🟢 LONG* | Momentum Breakout

*Entry:* $21,234.50  •  R:R 2.1:1
*Stop:* $21,200.00 (34.5 pts)
*TP:* $21,300.00 (65.5 pts)
*Size:* 15 MNQ • Risk: $250

⏳ Monitor for BUY entry at target price

🟢 75% confidence (High)
🧭 Trending Bullish • ✅ MTF

`momentum_brea`
```

**Layout order:**
1. Header (symbol, direction, type)
2. Trade Plan (entry, R:R, stop, TP)
3. Action cue (what to do next)
4. Confidence (single line)
5. Context (condensed regime + MTF)
6. Signal ID footer (for Details drill-down)

Full reasoning and timestamps live in the Details view.

### 9.4 Entry Notification (Calm-Minimal)

```
🎯 *MNQ 🟢 LONG ENTRY*

*Entry:* $21,234.50  •  R:R 2.1:1
*Stop:* $21,200.00 (34.5 pts)
*TP:* $21,300.00 (65.5 pts)

✅ *Position ACTIVE* - Monitor stop/TP

`momentum_brea`
```

### 9.5 Exit Notification (Calm-Minimal)

P&L appears first (most important information):

```
✅ *MNQ 🟢 LONG EXIT*

🟢 *+$125.00*  •  45m
$21,234.50 → $21,300.00 (+65.5 / +0.3%)
🎯 Take Profit

`momentum_brea`
```

### 9.6 Improved Error Messages

Data quality and circuit breaker alerts include:

- **Impact explanation**: What is affected (e.g., "Signal generation paused")
- **What's safe**: What is still working (e.g., "Positions still monitored")
- **Action guidance**: Step-by-step what to do
- **Expected resolution**: When the issue might resolve

### 9.7 Navigation

The main menu features:

- **Quick Actions row**: Last Signal, Active Trades, Activity
- **Streamlined service control**: Start/Stop/Restart + Gateway in one row
- **Grouped monitoring buttons**: Signals, Performance, Data Quality, Health

### 9.8 Lifecycle Notifications

Startup and shutdown messages include:

- **What to expect**: When first signal might appear
- **Next steps**: Clear guidance on what to do next
- **Quick access tips**: Commands to monitor status

### 9.9 Labeled Metrics (v2)

Activity metrics in the Home Card use self-explanatory labels:

```
📊 145 scans (session) / 1,595 total • 2 gen / 0 sent • 25/100 bars • 0 errors
```

**Label semantics:**
- **Scans**: `{session} (session) / {total} total` - Cycle counts
- **Signals**: `{generated} gen / {sent} sent` - Signal delivery
- **Failures**: `/ {failed} fail` - Only shown when non-zero
- **Bars**: `{current}/{target} bars` - Rolling buffer fill
- **Errors**: `{count} errors` - Error count

This removes ambiguity from unlabeled `A/B` ratios.

### 9.10 Dashboard Chart Controls

Dashboard charts can be configured via `config/config.yaml`:

```yaml
service:
  dashboard_chart_enabled: true        # Set false to disable automatic chart pushes
  dashboard_chart_interval: 3600       # Seconds between chart pushes (default: 1 hour)
  dashboard_chart_lookback_hours: 12   # Chart window (12, 16, or 24 hours)
```

**Options:**
- **`dashboard_chart_enabled`**: Set to `false` to disable automatic hourly charts (default: `true`)
- **`dashboard_chart_interval`**: Adjust the interval in seconds (default: 3600 = 1 hour)
- **`dashboard_chart_lookback_hours`**: Chart window in hours (default: 12)

**Timeframe Toggles:**
Push dashboard charts include inline toggle buttons:
- **12h** – Compact view for recent action
- **16h** – Medium view for more context
- **24h** – Extended view for full session context

The active timeframe shows a checkmark (✓). Tapping a button generates a new chart at that timeframe.

**On-demand access:**
Use `/chart` to generate a chart on demand with the same toggle options.

### 9.11 Staleness Callout (v2)

When market data is stale, the Home Card shows an actionable callout:

```
⏰ Data stale (11m) • signals paused • /data_quality
```

**Callout semantics:**
- **Age**: How old the data is (e.g., `11m` or `1.5h`)
- **Impact**: What is affected (e.g., "signals paused")
- **Action**: Command to investigate (e.g., `/data_quality`)

**Stale-safe derived context:**
When data is stale, the following are suppressed to avoid misleading confidence:
- Buy/Sell pressure indicators
- Signal diagnostics
- MTF trends (in push dashboards)

This ensures operators don't see "green" indicators based on outdated data.

### 9.12 Push Dashboard Buttons

Push dashboards no longer include inline "menu" buttons by default (calm-minimal).

**Enable Dashboard Buttons:**
Use `/settings` → toggle **Dashboard Buttons** to add a compact button row (Menu/Activity/Data Quality) to push dashboards.

**Without buttons (default):**
- `/status` for the full interactive Home Card (with buttons)
- `/activity` for liveness ("is it doing anything?")
- `/data_quality` for triage when something looks off

**With buttons enabled:**
Push dashboards include a single row:
```
🏠 Menu   📈 Activity   🛡 Data Quality
```

---

This file is the authoritative reference for Telegram integration. Other Telegram docs should defer to this guide.

