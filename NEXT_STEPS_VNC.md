# Next Steps - Connect to VNC

## Current Status
- ✅ VNC password set
- ✅ VNC port 5901 is listening
- ⚠️ Desktop may be minimal (just a terminal window is fine!)

## Connect Now:

### Step 1: SSH Tunnel (from your LOCAL computer)

```bash
ssh -L 5901:localhost:5901 pearlalgo@192.168.86.32
```

### Step 2: Connect VNC Client

Connect to: `localhost:5901`

**If you see:**
- A desktop → Great! Open terminal and run IB Gateway
- A terminal window → Perfect! Just run the commands there
- Blank/black screen → Try right-clicking or pressing keys to wake it up

### Step 3: Run IB Gateway

In the VNC window (terminal or desktop):

```bash
export DISPLAY=:1
cd ~/ibc
./gatewaystart.sh
```

### Step 4: Complete Login

Enter your IBKR credentials and complete login.

### Step 5: Verify

After login, check if API port is open:

```bash
ss -tuln | grep 4002
```

If you see port 4002, **you're done!** Close VNC and run headless:

```bash
cd ~/ibc
./gatewaystart.sh -inline
```

---

**Alternative**: If VNC connection doesn't work, we can try X11 forwarding over SSH instead (simpler, but requires X11 on your local machine).
