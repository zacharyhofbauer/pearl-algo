# IBKR Gateway & VNC - Quick Reference

## 🚀 Start Gateway (Headless)

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/start_ibgateway_ibc.sh
```

**What happens:**
- Starts Gateway headlessly (no GUI needed)
- Authenticates automatically
- API available on port 4002
- Takes 30-60 seconds to fully start

## 🛑 Stop Gateway

```bash
pkill -f "java.*IBC.jar"
```

## ✅ Check Gateway Status

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/check_gateway_status.sh
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

## 🔧 Manual Gateway Login (VNC - Only if Headless Fails)

```bash
# 1. Stop Gateway
pkill -f "java.*IBC.jar"

# 2. Start VNC
vncserver :1

# 3. Connect via VNC client, then in VNC terminal:
cd ~/pearlalgo-dev-ai-agents/ibkr/ibc
export DISPLAY=:1
./gatewaystart.sh -inline

# 4. Log in manually, keep open 15-20 min, then File → Exit
# 5. Close VNC: vncserver -kill :1
```

## 📝 View Logs

```bash
# Latest IBC log
tail -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/ibc-3.23.0_GATEWAY-1041_*.txt

# Latest Gateway log
tail -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log
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
./scripts/start_ibgateway_ibc.sh
```

### Gateway running but API not ready
- Wait 30-60 seconds (authentication takes time)
- Check logs: `tail -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/ibc-3.23.0_GATEWAY-1041_*.txt`

### Multiple autorestart files (causes login issues)
```bash
# Remove all, then do manual VNC login to recreate
find ~/pearlalgo-dev-ai-agents/ibkr/Jts -name "autorestart" -type f -delete
```

## 🎯 Common Workflows

### Start Gateway
```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/start_ibgateway_ibc.sh
./scripts/check_gateway_status.sh
```

### Stop Gateway
```bash
pkill -f "java.*IBC.jar"
./scripts/check_gateway_status.sh
```

### Restart Gateway
```bash
pkill -f "java.*IBC.jar"
sleep 5
cd ~/pearlalgo-dev-ai-agents
./scripts/start_ibgateway_ibc.sh
```

---

**Last Updated:** 2025-12-12  
**Gateway Version:** 1041 | **IBC Version:** 3.23.0
