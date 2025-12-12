# Headless IBKR Connection - Complete Solution

## The Core Problem

Exit code **1107** = Gateway needs authentication but can't show login dialog in headless mode.

**The Solution:** Create an **autorestart file** by doing ONE manual login. After that, all future logins are headless!

## How Autorestart File Works

1. **First login (manual):** Gateway authenticates → creates `autorestart` file
2. **Future logins (headless):** IBC finds `autorestart` file → skips authentication → starts headless ✅

## Solution: One-Time VNC Login

Since you have `vncserver` installed, we can do one manual login via VNC:

### Step 1: Start VNC Server

```bash
# Start VNC server on display :1
vncserver :1 -geometry 1024x768 -depth 24

# Set password (first time only)
# vncpasswd
```

### Step 2: Connect via VNC Client

From your local machine:
```bash
# If you have VNC client installed
vncviewer <server_ip>:5901

# Or use SSH tunnel:
ssh -L 5901:localhost:5901 pearlalgo@<server_ip>
# Then connect vncviewer to localhost:5901
```

### Step 3: Start Gateway with GUI

In the VNC session:
```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents/ibkr/ibc
export DISPLAY=:1
./gatewaystart.sh
```

### Step 4: Complete Login

1. Gateway login dialog appears in VNC
2. Enter credentials (already in config)
3. Complete 2FA if needed (use mobile app)
4. Let Gateway fully start
5. Close Gateway (this saves the session/autorestart file)

### Step 5: Future Headless Starts

After the autorestart file is created:
```bash
# Stop VNC (no longer needed)
vncserver -kill :1

# Start Gateway headless (will use autorestart file)
./scripts/start_ibgateway_ibc.sh

# Should work without GUI now!
```

## Alternative: Try Mobile App 2FA First

Before setting up VNC, try this:

1. **Start Gateway** (it will fail, but may trigger 2FA)
2. **Check IBKR Mobile app** for 2FA approval
3. **Approve login** from mobile app
4. **Gateway might connect** and create autorestart file

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./scripts/start_ibgateway_ibc.sh

# While it's starting, check your IBKR mobile app
# If you see a 2FA request, approve it
# Gateway might then connect successfully
```

## Quick VNC Setup Script

Let me create a script to help with VNC setup:

```bash
# Start VNC
vncserver :1 -geometry 1024x768 -depth 24

# Get your server IP
hostname -I | awk '{print $1}'

# Connect from your machine:
# vncviewer <server_ip>:5901
```

## After Autorestart File is Created

The autorestart file will be at:
```
ibkr/Jts/<session_dir>/autorestart
```

Once this exists, Gateway can start completely headless!

## Summary

**You only need ONE manual login** (via VNC) to create the autorestart file. After that:
- ✅ All future logins are headless
- ✅ No GUI needed
- ✅ No VNC needed
- ✅ Fully automated

Would you like me to:
1. Create a VNC setup script?
2. Try the mobile app 2FA method first?
3. Help you connect via VNC?
