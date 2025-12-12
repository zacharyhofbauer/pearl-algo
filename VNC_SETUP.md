# VNC Setup - Step by Step

## What is VNC?

**VNC = Virtual Network Computing**

It's like "remote desktop" - lets you see your server's screen from your computer.

**Simple explanation:**
- Your server = computer with no monitor
- VNC = creates a "virtual monitor" 
- You connect from your computer to see that virtual monitor
- You can click and type as if you're at the server

## Why We Need It

IBKR Gateway needs to show a login window. Since your server has no screen, VNC creates a virtual screen so Gateway can show its login window and you can see it.

**Good news:** You only need VNC ONCE - just for the first login. After that, Gateway remembers and runs headless forever!

## Setup VNC Password

VNC needs a password. Set it with:

```bash
vncpasswd
```

This will prompt you to:
1. Enter a password (choose something simple, you'll only use it once)
2. Verify the password
3. Optionally set a view-only password (say "n" for no)

## After Setting Password

```bash
# Start VNC
vncserver :1 -geometry 1024x768 -depth 24

# Get your server IP
hostname -I | awk '{print $1}'
# Should show: 192.168.86.32
```

## Connect from Your Computer

**You need a VNC viewer on your local computer:**

**Windows:**
- Download: https://www.realvnc.com/en/connect/download/viewer/
- Install and open
- Connect to: `192.168.86.32:5901`
- Enter the VNC password you set

**Mac:**
- Built-in: Applications → Utilities → Screen Sharing
- Or download RealVNC Viewer
- Connect to: `192.168.86.32:5901`

**Linux:**
```bash
sudo apt install tigervnc-viewer
vncviewer 192.168.86.32:5901
```

## In the VNC Window

Once connected, you'll see the server's desktop. Then:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents/ibkr/ibc
export DISPLAY=:1
./gatewaystart.sh
```

Gateway will open, you complete the login, then close it.

## After Login

```bash
# Stop VNC (no longer needed)
vncserver -kill :1

# Future starts are headless!
./scripts/start_ibgateway_ibc.sh
```

## Alternative: If VNC is Too Complicated

If you can't use VNC, you could:
1. **Use a different machine** that has a monitor to do the first login
2. **SSH with X11 forwarding** (if you have X11 on your local machine)
3. **Contact IBKR support** to see if there's another way

But VNC is usually the easiest solution!
