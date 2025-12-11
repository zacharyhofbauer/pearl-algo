# IBKR Setup Guide - Choose Your Path

## Summary: Two Options for IBKR Data Access

### Option 1: IB Gateway + IBC + VNC (One-Time Setup) ⭐ RECOMMENDED

**Why this is best:**
- ✅ One-time GUI login, then fully headless forever
- ✅ Simple and reliable
- ✅ Already configured (IBC is set up)
- ✅ Works with your existing code

**Steps:**
1. Set VNC password: `vncpasswd` (run this once, set a password)
2. Start VNC: `vncserver :1 -geometry 1920x1080`
3. Connect from your local machine via SSH tunnel
4. Complete IB Gateway login once in VNC
5. Done! Gateway works headless after that

**Time:** ~10 minutes one-time setup

---

### Option 2: Client Portal Web API (More Complex)

**Why consider this:**
- ✅ Modern REST API
- ✅ No GUI needed after initial setup

**Why it's harder:**
- ❌ Still needs browser authentication initially
- ❌ Requires OAuth setup (more complex)
- ❌ Need to implement new provider code
- ❌ May need IBKR Pro account

**Time:** ~1-2 hours setup + code changes

---

## My Recommendation

**Go with Option 1 (VNC one-time login)** because:
1. Everything is already configured (IBC, jts.ini, etc.)
2. You only need GUI access ONCE
3. After that, it's fully automated
4. Simpler and faster to get running

## Quick Start (Option 1)

```bash
# 1. Set VNC password (one-time, interactive)
vncpasswd

# 2. Start VNC
vncserver :1 -geometry 1920x1080

# 3. From your LOCAL machine, create SSH tunnel:
ssh -L 5901:localhost:5901 pearlalgo@your-server-ip

# 4. Connect VNC client to: localhost:5901

# 5. In VNC desktop, open terminal and run:
export DISPLAY=:1
cd ~/ibc
./gatewaystart.sh

# 6. Complete login (one time only)

# 7. After login, close VNC. Gateway now works headless:
cd ~/ibc
./gatewaystart.sh -inline
```

## After One-Time Login

Once you've logged in once, you never need VNC again:

```bash
# Start IB Gateway headless
cd ~/ibc
./gatewaystart.sh -inline

# Test connection
cd ~/pearlalgo-dev-ai-agents
python3 test_ibkr_connection.py

# Start your service
python -m pearlalgo.monitoring.continuous_service
```

---

**Bottom line:** VNC for 10 minutes = headless operation forever. Worth it!
