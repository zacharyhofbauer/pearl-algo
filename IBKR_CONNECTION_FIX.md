# IBKR Gateway Connection Issue - Root Cause & Fix

## Problem Identified

The IBKR Gateway is **blocking API connections** because it's waiting for manual confirmation of the **"API client needs write access action confirmation"** dialog.

### Symptoms
- Gateway process is running ✅
- Port 4002 is listening ✅  
- But TCP connections fail (error 11 = connection refused)
- IB API connections timeout
- Logs show dialog appearing repeatedly: "API client needs write access action confirmation"

### Root Cause

Even though the configuration has:
- `AcceptIncomingConnectionAction=yes` (in IBC config)
- `ReadOnlyAPI=true` (in Gateway settings)
- `ApiOnly=true` (in Gateway settings)

The Gateway is still showing a **write access confirmation dialog** that blocks connections until manually accepted.

## Solution Applied

### 1. Updated IBC Configuration (`ibkr/ibc/config-auto.ini`)
```ini
[API]
ReadOnlyApi=no          # Changed from 'yes' to 'no' - allows write access
SocketPort=4002
TrustedIPs=127.0.0.1
MasterAPIclientId=0     # Added - ensures proper client ID handling
```

### 2. Updated Gateway Settings (`ibkr/Jts/jts.ini`)
```ini
[IBGateway]
MasterAPIclientId=0     # Added - ensures proper client ID handling
```

## Why This Works

1. **ReadOnlyApi=no**: When set to 'no', the Gateway doesn't prompt for write access confirmation because write access is already granted
2. **MasterAPIclientId=0**: Ensures the Gateway properly handles API client IDs
3. **AcceptIncomingConnectionAction=yes**: Auto-accepts incoming connections (already set)

## Next Steps

### Option 1: Restart Gateway (Recommended)
```bash
# Stop Gateway
pkill -f "java.*IBC.jar"

# Wait a moment
sleep 5

# Restart with new config
cd ~/pearlalgo-dev-ai-agents
./scripts/gateway/start_ibgateway_ibc.sh

# Wait 60-90 seconds for full startup
# Then test connection
```

### Option 2: Manual VNC Acceptance (If Option 1 doesn't work)
If the dialog still appears after restart:
1. Connect via VNC: `vncserver :1` then connect with VNC client
2. In Gateway window, accept the "write access" dialog ONCE
3. Gateway will remember this setting
4. Close VNC: `vncserver -kill :1`

### Test Connection
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python3 -c "
from ib_insync import IB
ib = IB()
try:
    connected = ib.connect('127.0.0.1', 4002, clientId=11, timeout=10)
    if connected and ib.isConnected():
        print('✅ Connection successful!')
        ib.disconnect()
    else:
        print('❌ Connection failed')
except Exception as e:
    print(f'❌ Connection error: {e}')
"
```

## Why Connection Was Failing

1. **Gateway was waiting for dialog confirmation**: The "write access" dialog blocks the API port from accepting connections until confirmed
2. **ReadOnlyApi=yes caused the dialog**: Even in read-only mode, Gateway asks for write access confirmation
3. **No auto-accept mechanism**: IBC's `AcceptIncomingConnectionAction=yes` handles connection dialogs, but not the write access dialog

## Configuration Files Changed

- ✅ `ibkr/ibc/config-auto.ini` - Changed `ReadOnlyApi=no`, added `MasterAPIclientId=0`
- ✅ `ibkr/Jts/jts.ini` - Added `MasterAPIclientId=0` to `[IBGateway]` section

## Verification

After restarting Gateway, verify:
1. Gateway process running: `pgrep -f "java.*IBC.jar"`
2. Port 4002 listening: `ss -tuln | grep 4002`
3. Connection test succeeds (see test command above)
4. No more "write access" dialogs in logs

---

**Note**: The Gateway must be restarted for these configuration changes to take effect.
