# IBKR Gateway Guide

## Prerequisites

- **Java 17+** installed and available on `$PATH` (required by IB Gateway/IBC).
- IB Gateway and IBC installed under **IBKR home** (default: repo-local `ibkr/`, recommended: external path).
  - Set `PEARLALGO_IBKR_HOME` to point at your installation (example: `/opt/ibkr`).
  - Verify with: `./scripts/gateway/gateway.sh install-info`
  - Override per-command: `./scripts/gateway/gateway.sh --ibkr-home /opt/ibkr status`

## 🚀 Start Gateway (Headless)

```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/gateway/gateway.sh start
```

**What happens:**
- Starts Gateway headlessly (no GUI needed)
- Authenticates automatically
- API available on port 4002
- Takes 30-60 seconds to fully start

## 🛑 Stop Gateway

```bash
./scripts/gateway/gateway.sh stop
```

If the Gateway is wedged and won’t stop cleanly:

```bash
pkill -9 -f "java.*IBC.jar"
```

## ✅ Check Gateway Status

```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/gateway/gateway.sh status
```

**Shows:**
- ✅/❌ Gateway process running
- ✅/❌ API port 4002 listening
- Latest log file location

## 📊 VNC Server Operations

### Start VNC Server
```bash
vncserver :1
```

### Stop VNC Server
```bash
vncserver -kill :1
```

### Check if VNC is Running
```bash
ss -tuln | grep 5901
```

### Connect to VNC
- **VNC Client:** RealVNC Viewer or TightVNC Viewer
- **Address:** `your-server-ip:5901` or via SSH tunnel: `ssh -L 5901:localhost:5901 your-server`

### If the terminal won’t open inside VNC (helper)

If clicking terminal icons doesn't work, try these methods:

#### Method 1: Keyboard shortcut

- Press `Ctrl+Alt+T` (common Linux shortcut)
- Or `Alt+F2` then type `xterm` or `gnome-terminal`

#### Method 2: Right‑click desktop

- Right‑click on desktop → "Open Terminal Here"
- If this doesn't work, use the SSH-based workflows below.

#### Method 3: Run commands via SSH (recommended)

Instead of using a VNC terminal, run commands from your main terminal:

```bash
# Check Gateway status
ssh <user>@<server> "./scripts/gateway/gateway.sh tws-conflict"

# Check if 2FA is needed
ssh <user>@<server> "tail -20 $PEARLALGO_IBKR_HOME/ibc/logs/ibc-*.txt | grep -i '2fa\\|authentication'"

# Check if API port is ready
ssh <user>@<server> "ss -tuln | grep 4002"
```

#### Method 4: Direct command execution (via SSH; targets VNC display)

If you can see the VNC desktop but terminal won't open, you can run commands directly:

```bash
# Set DISPLAY to VNC session
export DISPLAY=:1

# Run Gateway start command
cd /path/to/pearlalgo-dev-ai-agents
./scripts/gateway/gateway.sh start
```

Then verify Gateway readiness from your main terminal:

```bash
ss -tuln | grep 4002
```

## 🔧 Manual Gateway Login (VNC - Only if Headless Fails)

```bash
# 1. Stop Gateway
./scripts/gateway/gateway.sh stop

# 2. Start VNC
vncserver :1

# 3. Connect via VNC client, then in VNC terminal:
cd $PEARLALGO_IBKR_HOME/ibc
export DISPLAY=:1
./gatewaystart.sh -inline

# 4. Log in manually, keep open 15-20 min, then File → Exit
# 5. Close VNC: vncserver -kill :1
```

## 📝 View Logs

```bash
# Latest IBC log
tail -f $PEARLALGO_IBKR_HOME/ibc/logs/ibc-*.txt

# Latest Gateway log
tail -f $PEARLALGO_IBKR_HOME/ibc/logs/gateway_*.log
```

## 🔍 Quick Status Checks

```bash
# Gateway running?
pgrep -f "java.*IBC.jar" && echo "✅ Running" || echo "❌ Not running"

# API port listening?
ss -tuln | grep 4002 && echo "✅ Port 4002 listening" || echo "❌ Not listening"

# VNC running?
ss -tuln | grep 5901 && echo "✅ VNC running" || echo "❌ Not running"
```

## ⚠️ Troubleshooting

### Gateway won't start
```bash
# Kill all processes
pkill -9 -f "java.*IBC.jar"
pkill -9 -f "ibcstart.sh"
sleep 3
./scripts/gateway/gateway.sh start
```

### Gateway running but API not ready
- Wait 30-60 seconds (authentication takes time)
- Check logs: `tail -f $PEARLALGO_IBKR_HOME/ibc/logs/ibc-*.txt`

### Error 354 (market data subscription)

If the API is up but live market data requests return **Error 354** (“not subscribed”), use:

- `docs/MARKET_DATA_SUBSCRIPTION.md` (canonical fix guide)

### Multiple autorestart files (causes login issues)
```bash
# Remove all, then do manual VNC login to recreate
find $PEARLALGO_IBKR_HOME/Jts -name "autorestart" -type f -delete
```

## 🎯 Common Workflows

### Start Gateway
```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/gateway/gateway.sh start
./scripts/gateway/gateway.sh status
```

### Stop Gateway
```bash
pkill -f "java.*IBC.jar"
./scripts/gateway/gateway.sh status
```

### Restart Gateway
```bash
./scripts/gateway/gateway.sh stop
sleep 5
cd /path/to/pearlalgo-dev-ai-agents
./scripts/gateway/gateway.sh start
```

---

**Last Updated:** 2025-12-12  
**Gateway Version:** 1041 | **IBC Version:** 3.23.0

---

## 📚 Additional references

- `docs/MARKET_DATA_SUBSCRIPTION.md` — Error 354 subscription + API acknowledgement guide
