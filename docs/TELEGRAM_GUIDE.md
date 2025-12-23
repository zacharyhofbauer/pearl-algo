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
   status - Get current agent status
   activity - Is the bot doing anything?
   signals - Show recent signals
   last_signal - Show most recent signal with chart
   active_trades - Show currently open positions
   performance - Show performance metrics
   data_quality - Check data freshness and quality
   config - Show key configuration values (read-only)
   health - Show basic agent health (read-only)
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
- Activity pulse (time since last cycle)
- Futures/session gates:
  - **FuturesMarketOpen** (CME ETH + maintenance break; affects data freshness)
  - **StrategySessionOpen** (prop-firm window: 18:00–16:10 ET; when signals are allowed)
  - When session is closed, shows next session opening time
- Cycles and signals (clarified):
  - **Cycles**: session/total (total persists across restarts)
  - **Signals**: generated vs delivered vs failed
- Buffer size (rolling): current/target bars
- Compact 7-day performance summary with trend indicator
- Inline buttons for quick access to all features

### 3.4 `/activity`

Answers the question "Is the bot doing anything?" with:

- Agent status and activity pulse (time since last cycle)
- Cycle count (session and total)
- Buffer status with fill percentage
- Latest price
- Active positions count
- Next expected action (e.g., "Next cycle in ~60s", "Waiting for session")

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

- Shows **7‑day performance metrics**:
  - Total signals and exited signals
  - Win / loss counts
  - Win rate percentage
  - Total P&L and average P&L
- Uses the same performance metrics as the periodic Telegram summaries.

### 3.6 `/config` and `/health`

- `/config`: Shows key configuration values (read-only)
  - Symbol, timeframe, scan interval
  - Risk parameters and position sizing
  
- `/health`: Shows basic agent health status
  - Service process status
  - State file presence and last update time

### 3.7 `/pause` and `/resume` (Legacy)

- Currently **informational only** (use `/stop_agent` and `/start_agent` instead)
- These commands acknowledge receipt but don't perform actions
- For full control, use the service control commands above

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
- Executes `./scripts/gateway/start_ibgateway_ibc.sh`
- Waits up to 120 seconds for Gateway to start
- Verifies Gateway process is running and API port 4002 is listening
- **Note:** Gateway startup requires 2FA approval via IBKR mobile app
- May take 60+ seconds if authentication is needed

**`/stop_gateway`**
- Stops IBKR Gateway gracefully
- Executes `./scripts/gateway/stop_ibgateway_ibc.sh`
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
- **🔌 Gateway Status** – Check Gateway health (shows ✅ when running, ❌ when stopped)
- **📊 Performance** – Detailed metrics
- **🔔 Signals** – Recent signals
- **⚙️ Config** – Configuration values
- **💚 Health** – Health check
- **🏠 Main Menu** – Return to main menu from any view

**Navigation Features:**
- **100% Button-Based**: No need to type commands
- **Contextual Buttons**: Adapt based on current state
- **Status Indicators**: Visual feedback (✅/❌) on buttons
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

- `/start_gateway` → `./scripts/gateway/start_ibgateway_ibc.sh`
- `/stop_gateway` → `./scripts/gateway/stop_ibgateway_ibc.sh`
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

### 8.4 Menu System and Button Navigation

The bot features a **fully UI-driven interface** with inline keyboard buttons. No need to type commands - everything is accessible through intuitive button navigation!

**Main Menu (Status View):**
- Appears when you send `/start`, tap "🏠 Main Menu", or send `/status`
- Button layout:
  - **Stop Agent** / **Restart** (if agent running)
  - **Start Agent** (if agent stopped)
  - **Gateway ✅/❌** / **Refresh**
  - **Status** / **Signals** / **Performance**
  - **Config** / **Health** / **Help**

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
- **Status Indicators:** Gateway button shows ✅ when running, ❌ when stopped
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

## 9. UX Improvements (v2)

### 9.1 Activity Pulse

The status and activity views now show an "activity pulse" indicator:

- 🟢 **Active** (< 2 min): Agent is actively cycling
- 🟡 **Slow** (2-5 min): Agent may be waiting or slow
- 🔴 **Stale** (> 5 min): Agent may need attention

This helps answer "is the bot doing anything?" at a glance.

### 9.2 Enhanced Signal Messages

Signal alerts now include:

- **Action cue**: Clear next steps (e.g., "Monitor for BUY entry at target price")
- **Timing**: When the signal was generated (with relative time)
- **Entry/Exit context**: Position size, risk amount, and clear explanations

### 9.3 Improved Error Messages

Data quality and circuit breaker alerts now include:

- **Impact explanation**: What is affected (e.g., "Signal generation paused")
- **What's safe**: What is still working (e.g., "Positions still monitored")
- **Action guidance**: Step-by-step what to do
- **Expected resolution**: When the issue might resolve

### 9.4 Enhanced Navigation

The main menu now features:

- **Quick Actions row**: Last Signal, Active Trades, Activity
- **Streamlined service control**: Start/Stop/Restart + Gateway in one row
- **Grouped monitoring buttons**: Signals, Performance, Data Quality, Health

### 9.5 Lifecycle Notifications

Startup and shutdown messages now include:

- **What to expect**: When first signal might appear
- **Next steps**: Clear guidance on what to do next
- **Quick access tips**: Commands to monitor status

---

This file is the authoritative reference for Telegram integration. Other Telegram docs should defer to this guide.

