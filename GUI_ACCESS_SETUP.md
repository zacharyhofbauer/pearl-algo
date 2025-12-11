# How to Get GUI Access for IB Gateway Setup

## Quick Setup (Recommended)

Run this script to set up VNC server:

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/quick_vnc_setup.sh
```

This will:
1. Install VNC server and lightweight desktop (xfce4)
2. Set up VNC password (you'll be prompted)
3. Start VNC server on display :1

## Connect to VNC

### Step 1: Create SSH Tunnel (from your local machine)

```bash
# Replace with your server's IP or hostname
ssh -L 5901:localhost:5901 pearlalgo@your-server-ip
```

### Step 2: Connect VNC Client

On your local machine, use a VNC client:
- **Mac**: Built-in Screen Sharing or download "VNC Viewer"
- **Windows**: Download "TightVNC" or "RealVNC Viewer"
- **Linux**: `vncviewer localhost:5901`

Connect to: `localhost:5901`

### Step 3: Complete IB Gateway Login

Once connected to VNC:
1. Open a terminal in the VNC session
2. Run:
   ```bash
   export DISPLAY=:1
   cd ~/ibc
   ./gatewaystart.sh
   ```
3. Complete the IB Gateway login (one time only)
4. After successful login, credentials will be saved
5. You can close VNC - Gateway will work headless after this

## Alternative: X11 Forwarding (If SSH supports it)

If your SSH connection supports X11 forwarding:

```bash
# Connect with X11 forwarding
ssh -X pearlalgo@your-server-ip

# Then run IB Gateway
cd ~/ibc
./gatewaystart.sh
```

## After Initial Login

Once you've completed the login once, IB Gateway will save your session and you can run it headless:

```bash
cd ~/ibc
./gatewaystart.sh -inline
```

## VNC Management Commands

**Start VNC:**
```bash
vncserver :1 -geometry 1920x1080
```

**Stop VNC:**
```bash
vncserver -kill :1
```

**Check if VNC is running:**
```bash
ps aux | grep vncserver
```

**Change VNC password:**
```bash
vncpasswd
```

## Troubleshooting

**VNC connection refused:**
- Check firewall: `sudo ufw allow 5901`
- Verify VNC is running: `ps aux | grep vncserver`

**Can't see desktop in VNC:**
- Restart VNC: `vncserver -kill :1 && vncserver :1`

**IB Gateway window doesn't appear:**
- Make sure DISPLAY is set: `export DISPLAY=:1`
- Check if Gateway is running: `ps aux | grep IBC`
