# IB Gateway Setup Summary - Read-Only Data Access

## ✅ What's Configured

1. **IBC (IB Controller)** - Installed and configured
   - Location: `~/ibc`
   - Config: `~/ibc/config-auto.ini`
   - Read-Only API: **Enabled** ✅
   - Trading Mode: Paper (safe for data)

2. **jts.ini** - Configured for API access
   - Location: `~/Jts/jts.ini`
   - API Only: Enabled
   - Socket Port: 4002
   - Trusted IPs: 127.0.0.1

## ⚠️ Current Issue

IB Gateway is exiting with code 1107 - this typically means:
- Initial authentication is required
- Two-factor authentication may be needed
- Gateway needs to complete first-time login

## 🔧 Solution Options

### Option 1: One-Time Manual Login (Recommended)

If you have ANY way to access a GUI (VNC, X11 forwarding, or can SSH with X11):

```bash
# Start IB Gateway with IBC (will show login window)
cd ~/ibc
./gatewaystart.sh

# Complete the login once
# After successful login, credentials will be saved
# Then you can run it headless forever after
```

### Option 2: Use Existing Session

If IB Gateway was previously logged in, check for saved sessions:

```bash
# Check if there's a saved session
ls -la ~/Jts/ibgateway/1041/data/

# Try starting with existing session
cd ~/ibc
./gatewaystart.sh -inline
```

### Option 3: Configure Auto-Login

If you can provide 2FA token or disable 2FA temporarily:

1. Edit `~/ibc/config-auto.ini`
2. Add 2FA settings if needed
3. Or disable 2FA in IB account settings (temporarily for setup)

## 📝 Quick Commands

**Start IB Gateway:**
```bash
cd ~/ibc
./gatewaystart.sh -inline
```

**Check if running:**
```bash
ps aux | grep IBC.jar
ss -tuln | grep 4002
```

**View logs:**
```bash
tail -f ~/ibc/logs/ibc-*.txt
```

**Stop IB Gateway:**
```bash
~/ibc/stop.sh
```

**Test connection (once Gateway is running):**
```bash
cd ~/pearlalgo-dev-ai-agents
python3 test_ibkr_connection.py
```

## 🎯 Next Steps

1. **Complete initial authentication** (one-time, via GUI if possible)
2. **Verify API port is listening**: `ss -tuln | grep 4002`
3. **Test connection**: `python3 test_ibkr_connection.py`
4. **Start your service**: `python -m pearlalgo.monitoring.continuous_service`

## 📋 Configuration Files

- **IBC Config**: `~/ibc/config-auto.ini` (ReadOnlyApi=yes ✅)
- **Gateway Config**: `~/Jts/jts.ini` (API enabled ✅)
- **Start Script**: `~/pearlalgo-dev-ai-agents/scripts/start_ibgateway_ibc.sh`

Everything is configured correctly - you just need to complete the initial authentication once!
