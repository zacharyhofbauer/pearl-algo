# Connect to VNC - Step by Step

## Your Server Info
- **Server IP**: 192.168.86.32
- **VNC Port**: 5901
- **VNC Display**: :1

## Step 1: Create SSH Tunnel (from your LOCAL machine)

Open a terminal on your **local computer** (not the server) and run:

```bash
ssh -L 5901:localhost:5901 pearlalgo@192.168.86.32
```

Keep this terminal open - it's creating the secure tunnel.

## Step 2: Connect VNC Client

While the SSH tunnel is running, use a VNC client:

**Mac:**
- Use built-in "Screen Sharing" app
- Or download "VNC Viewer" from App Store
- Connect to: `localhost:5901`

**Windows:**
- Download "TightVNC Viewer" or "RealVNC Viewer"
- Connect to: `localhost:5901`

**Linux:**
```bash
vncviewer localhost:5901
```

**Password:** Use the password you set with `vncpasswd`

## Step 3: In VNC, Start IB Gateway

Once connected to VNC, you should see a desktop (or at least a terminal window).

Open a terminal in VNC and run:

```bash
export DISPLAY=:1
cd ~/ibc
./gatewaystart.sh
```

## Step 4: Complete IB Gateway Login

- Enter your IBKR username and password
- Complete any 2FA if required
- Let it log in completely

## Step 5: Verify API is Working

After login, in the VNC terminal, test:

```bash
ss -tuln | grep 4002
```

You should see port 4002 listening.

## Step 6: Close VNC - You're Done!

After successful login, you can:
- Close VNC
- Close the SSH tunnel
- IB Gateway will now work headless forever

## After This One-Time Setup

You'll never need VNC again. Just run:

```bash
cd ~/ibc
./gatewaystart.sh -inline
```

Then start your service:
```bash
cd ~/pearlalgo-dev-ai-agents
python -m pearlalgo.monitoring.continuous_service
```
