# Telegram Remote Control Guide

**Complete remote control of your MNQ Agent system via Telegram**

This guide explains how to control almost everything in your trading system directly from Telegram, including starting/stopping the Gateway and Agent services.

---

## Quick Start

1. **Start the Telegram Command Handler:**
   ```bash
   ./scripts/telegram/start_command_handler.sh
   ```

2. **Update Bot Commands (one-time setup):**
   ```bash
   python3 scripts/telegram/set_bot_commands.py
   ```
   Or manually via BotFather: `/setcommands` → paste the command list from `TELEGRAM_GUIDE.md`

3. **You're ready!** Send commands from your authorized Telegram chat.

---

## Service Control Commands

### Gateway Control

#### `/start_gateway`
Starts IBKR Gateway remotely.

**What it does:**
- Executes `./scripts/gateway/start_ibgateway_ibc.sh`
- Waits up to 120 seconds for Gateway to start
- Verifies Gateway process is running
- Checks if API port 4002 is listening

**Usage:**
```
/start_gateway
```

**Response:**
- ✅ Success: "IBKR Gateway started successfully"
- ❌ Failure: Error message with details

**Notes:**
- Gateway startup requires 2FA approval via IBKR mobile app
- May take 60+ seconds if authentication is needed
- You'll receive a notification when Gateway is ready

#### `/stop_gateway`
Stops IBKR Gateway gracefully.

**What it does:**
- Executes `./scripts/gateway/stop_ibgateway_ibc.sh`
- Verifies Gateway process is stopped

**Usage:**
```
/stop_gateway
```

#### `/gateway_status`
Quick health check for IBKR Gateway.

**What it shows:**
- Process status (running/stopped)
- API port status (listening/not listening)
- Overall Gateway health

**Usage:**
```
/gateway_status
```

**Response:**
```
🔌 IBKR Gateway Status

Process: 🟢 RUNNING
API Port: 🟢 LISTENING

Status: 🟢 Gateway is RUNNING and API is READY
```

---

### Agent Service Control

#### `/start_agent`
Starts NQ Agent Service in background mode.

**What it does:**
- Executes `./scripts/lifecycle/start_nq_agent_service.sh --background`
- Checks if Gateway is running (warns if not)
- Verifies agent process started successfully

**Usage:**
```
/start_agent
```

**Response:**
- ✅ Success: "NQ Agent Service started successfully"
- ⚠️ Warning if Gateway not running
- ❌ Failure: Error message with details

#### `/stop_agent`
Stops NQ Agent Service gracefully.

**What it does:**
- Executes `./scripts/lifecycle/stop_nq_agent_service.sh`
- Verifies agent process is stopped

**Usage:**
```
/stop_agent
```

#### `/restart_agent`
Restarts NQ Agent Service (stop then start).

**What it does:**
- Stops the agent (if running)
- Waits 2 seconds
- Starts the agent in background mode
- Shows status of both operations

**Usage:**
```
/restart_agent
```

**When to use:**
- After changing `config/config.yaml`
- After updating code
- If agent seems stuck or unresponsive

---

## Complete Workflow Examples

### Morning Startup (All from Telegram)

```
1. /gateway_status        # Check if Gateway is running
2. /start_gateway         # Start Gateway if needed (wait for 2FA approval)
3. /gateway_status        # Verify Gateway is ready
4. /start_agent           # Start the agent
5. /status                # Verify agent is running
```

### End of Day Shutdown

```
1. /stop_agent            # Stop the agent
2. /stop_gateway          # Stop Gateway (optional)
3. /status                # Verify everything is stopped
```

### Apply Configuration Changes

```
1. Edit config/config.yaml on server
2. /restart_agent         # Restart to apply changes
3. /status                # Verify new config is active
4. /config                # View current configuration
```

### Troubleshooting

```
1. /status                # Check agent status
2. /gateway_status        # Check Gateway status
3. /health                # Quick health check
4. /restart_agent         # If agent seems stuck
```

---

## Security & Safety

### Authorization
- **Only your authorized chat ID** can execute service control commands
- Unauthorized users receive "❌ Unauthorized access" message
- All command attempts are logged with chat ID

### Safety Features
- **Timeouts:** All scripts have execution timeouts (prevents hanging)
- **Verification:** Commands verify processes actually started/stopped
- **Error Handling:** Failures are reported with clear error messages
- **Logging:** All remote control actions are logged

### Best Practices
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

---

## Inline Buttons

The `/status` command now includes inline buttons for quick actions:

- **▶️ Start Agent** / **⏹️ Stop Agent** – Quick service control
- **🔌 Gateway Status** – Check Gateway health
- **📊 Performance** – Detailed metrics
- **🔔 Signals** – Recent signals
- **⚙️ Config** – Configuration values
- **💚 Health** – Health check

Just tap the buttons instead of typing commands!

---

## Command Reference

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

---

## Troubleshooting

### Commands Not Working

1. **Check command handler is running:**
   ```bash
   ./scripts/telegram/check_command_handler.sh
   ```

2. **Start command handler if needed:**
   ```bash
   ./scripts/telegram/start_command_handler.sh
   ```

3. **Verify bot commands are set:**
   ```bash
   python3 scripts/telegram/set_bot_commands.py
   ```

### Gateway Won't Start

- Check IBKR account is active
- Verify 2FA approval on mobile app
- Check Gateway logs: `tail -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log`

### Agent Won't Start

- Check Gateway is running: `/gateway_status`
- Verify Python environment: `python3 -c "import pearlalgo"`
- Check for port conflicts: `ss -tuln | grep 4002`

### Commands Timeout

- Gateway startup can take 60+ seconds (normal)
- Agent startup should be < 30 seconds
- If consistently timing out, check server resources

---

## Advanced Usage

### Scheduled Operations

You can combine commands for automated workflows:

```
# Morning routine (run these in sequence)
/gateway_status
/start_gateway
# Wait for Gateway ready notification
/start_agent
/status
```

### Monitoring Workflow

```
# Quick health check
/health
/gateway_status

# Detailed status
/status
/performance
```

### Emergency Stop

```
# Stop everything immediately
/stop_agent
/stop_gateway
```

---

## Integration with Existing Scripts

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

---

## See Also

- `TELEGRAM_GUIDE.md` – Complete Telegram integration reference
- `CHEAT_SHEET.md` – Quick operational reference
- `NQ_AGENT_GUIDE.md` – Full operational guide
