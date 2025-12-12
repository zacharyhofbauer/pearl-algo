# Headless IBKR Connection - Solution

## The Problem

Exit code **1107** means Gateway can't authenticate in headless mode because:
- It needs to show a login dialog (can't in headless)
- "autorestart file not found: full authentication will be required"

## The Solution: Create Autorestart File

IBC uses an **autorestart file** to skip authentication on subsequent logins. If this file exists, Gateway can start headless without showing login dialogs.

### Step 1: Do ONE Manual Login (With GUI)

You need to do **one manual login** to create the autorestart file. After that, all future logins can be headless.

**Option A: If you have X11/VNC access:**
```bash
# Start Gateway with GUI
cd /home/pearlalgo/pearlalgo-dev-ai-agents/ibkr/ibc
export DISPLAY=:0  # or your display
./gatewaystart.sh

# Complete login manually (including 2FA if needed)
# This creates the autorestart file
# Then close Gateway
```

**Option B: Use Remote Desktop/VNC:**
1. Connect via VNC or remote desktop
2. Start Gateway manually
3. Complete login
4. Close Gateway
5. Future starts will be headless

### Step 2: Updated Config

I've updated your `config-auto.ini` with:
- `StoreSettingsOnServer=yes` - Saves session settings
- `ReloginAfterSecondFactorAuthenticationTimeout=yes` - Retries 2FA
- Increased timeouts for 2FA

### Step 3: After Manual Login

Once you've done one manual login, the autorestart file will be created at:
```
ibkr/Jts/autorestart_<session_id>
```

Future headless starts will use this file and skip authentication.

## Alternative: Use IBKR Mobile App for 2FA

If you have 2FA enabled:

1. **Start Gateway** (even if it fails initially)
2. **Check your IBKR Mobile app** - you should see a 2FA approval request
3. **Approve the login** from the mobile app
4. **Gateway should then connect** and create the autorestart file

## Quick Test After Manual Login

After doing one manual login:

```bash
# Start Gateway headless
./scripts/start_ibgateway_ibc.sh

# Wait 60 seconds
sleep 60

# Check if port is listening
ss -tuln | grep 4002

# If listening, test connection
pip install -e .
python scripts/smoke_test_ibkr.py
```

## The Key Insight

**You only need to do ONE manual login** to create the autorestart file. After that, all future logins can be completely headless!

The autorestart file tells IBC: "This session is already authenticated, skip the login dialog."

## Next Steps

1. **Do one manual login** (with GUI/VNC/remote desktop)
2. **Complete authentication** (including 2FA if needed)
3. **Close Gateway** (this saves the session)
4. **Start Gateway headless** - it should work now!

Let me know if you can do a manual login, or if you need help setting up VNC/remote desktop access!
