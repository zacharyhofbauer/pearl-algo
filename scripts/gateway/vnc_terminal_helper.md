# Opening Terminal in VNC Session

If clicking terminal icons doesn't work, try these methods:

## Method 1: Keyboard Shortcut
- Press `Ctrl+Alt+T` (common Linux shortcut)
- Or `Alt+F2` then type `xterm` or `gnome-terminal`

## Method 2: Right-Click Desktop
- Right-click on desktop → "Open Terminal Here"
- If this doesn't work, try the desktop scripts below

## Method 3: Use Desktop Scripts
I've created scripts on your desktop that you can double-click:
- `run_in_terminal.sh` - Opens a terminal window
- `start_ibkr_gateway_live.sh` - Starts Gateway in a terminal
- `complete_2fa.sh` - Helper for 2FA

**To make them executable:**
1. Right-click the file → Properties
2. Check "Allow executing file as program" or set permissions
3. Double-click to run

## Method 4: Run Commands via SSH (Easier!)
Instead of using VNC terminal, run commands from your main terminal:

```bash
# Check Gateway status
ssh pearlalgo@your-server "./scripts/gateway/check_tws_conflict.sh"

# Check if 2FA is needed
ssh pearlalgo@your-server "tail -20 ibkr/ibc/logs/ibc-*.txt | grep -i '2fa\|authentication'"

# Check if API port is ready
ssh pearlalgo@your-server "ss -tuln | grep 4002"
```

## Method 5: Direct Command Execution
If you can see the VNC desktop but terminal won't open, you can run commands directly:

1. In your SSH session (not VNC), run:
```bash
# Set DISPLAY to VNC session
export DISPLAY=:1

# Run Gateway start command
cd ~/pearlalgo-dev-ai-agents
./scripts/gateway/start_ibgateway_ibc.sh
```

## Current Status
Your Gateway is already running (PID 484033) and waiting for 2FA.

**To complete 2FA without terminal:**
1. In VNC, you should see the IBKR Gateway window
2. Look for "Second Factor Authentication" dialog
3. Enter your 2FA code
4. Click OK

**To verify Gateway is ready:**
Run from your main terminal (not VNC):
```bash
ss -tuln | grep 4002
```

If port 4002 is listening, Gateway is ready!


