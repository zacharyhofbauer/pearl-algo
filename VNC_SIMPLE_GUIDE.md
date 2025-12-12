# Simple VNC Setup for IBKR Login

## What Happened

- ❌ Mobile app 2FA didn't trigger (Gateway exited before it could)
- ✅ VNC is available on your server
- ✅ We can use VNC to do ONE manual login

## What is VNC?

**VNC = Virtual Network Computing**

It's like "remote desktop" - it lets you see your server's screen from your computer.

**Simple analogy:**
- Your server = computer in another room (no monitor)
- VNC = a window on your computer that shows the server's screen
- You can click and type in that window

## Why We Need It

IBKR Gateway needs to show a login window. Your server has no screen, so Gateway can't show the window. VNC creates a "virtual screen" so Gateway can show its window, and you can see it from your computer.

## The Plan

1. **Start VNC** (creates virtual screen on server)
2. **Connect from your computer** (see the virtual screen)
3. **Start Gateway in VNC** (login window appears)
4. **Complete login** (enter credentials, approve 2FA)
5. **Close Gateway** (saves the session)
6. **Stop VNC** (no longer needed)
7. **Future starts are headless!** ✅

## Quick Start

I've created a script to help. Run:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./scripts/setup_vnc_for_login.sh
```

This will:
- Start VNC server
- Show you how to connect
- Give you the server IP: **192.168.86.32**

## Connect from Your Computer

You need a VNC viewer on your local computer:

**Windows:**
- Download: https://www.realvnc.com/en/connect/download/viewer/
- Or use built-in Remote Desktop

**Mac:**
- Built-in: Applications → Utilities → Screen Sharing
- Or download RealVNC Viewer

**Linux:**
```bash
sudo apt install tigervnc-viewer
```

**Then connect to:** `192.168.86.32:5901`

## After Connecting

In the VNC window, you'll see the server's desktop. Then:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents/ibkr/ibc
export DISPLAY=:1
./gatewaystart.sh
```

Gateway will open, you complete login, then close it. Done!

## After One Login

Once you've done the login:
- Stop VNC: `vncserver -kill :1`
- Future Gateway starts: `./scripts/start_ibgateway_ibc.sh` (headless, no VNC needed!)

## Need Help?

If you can't use VNC, alternatives:
1. SSH with X11 forwarding (if you have X11)
2. Use a different machine with a monitor
3. Contact IBKR support

But VNC is usually the easiest! Let me know if you need help setting it up.
