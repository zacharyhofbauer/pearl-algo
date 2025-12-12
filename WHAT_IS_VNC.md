# What is VNC? (Simple Explanation)

## VNC = Virtual Network Computing

**VNC** lets you see and control your server's screen from your local computer, like remote desktop.

Think of it like:
- **Your server** = A computer in another room
- **VNC** = A window that shows you what's on that computer's screen
- **You can click and type** in that window as if you're sitting at the server

## Why We Need It

IBKR Gateway needs to show a login window, but your server has no screen. VNC creates a "virtual screen" so Gateway can show its login window, and you can see it from your computer.

## The Good News

**You only need VNC ONCE** - just to do the first login. After that, Gateway remembers your login and never needs a screen again!

## How to Use VNC

### Step 1: Start VNC on Server

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./scripts/setup_vnc_for_login.sh
```

This creates a virtual screen on your server.

### Step 2: Connect from Your Computer

You need a VNC viewer on your local computer:

**Windows/Mac:**
- Download: https://www.realvnc.com/en/connect/download/viewer/
- Or use built-in: Windows has "Remote Desktop", Mac has "Screen Sharing"

**Linux:**
```bash
# Install VNC viewer
sudo apt install tigervnc-viewer  # or remmina
```

**Connect:**
- Open VNC viewer
- Enter: `192.168.86.32:5901` (or your server IP)
- Enter VNC password (if you set one)

### Step 3: In VNC Window

Once connected, you'll see the server's desktop. Then:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents/ibkr/ibc
export DISPLAY=:1
./gatewaystart.sh
```

Gateway will open in the VNC window, you complete login, then close it.

### Step 4: Done Forever!

After that one login, you can:
- Stop VNC (no longer needed)
- Start Gateway headless (works without VNC)

## Alternative: If You Can't Use VNC

If VNC is too complicated, you might be able to:
1. **SSH with X11 forwarding** (if you have X11 on your local machine)
2. **Use a different server** that has a screen/monitor
3. **Contact IBKR support** to see if they can help with headless setup

But VNC is usually the easiest solution!
