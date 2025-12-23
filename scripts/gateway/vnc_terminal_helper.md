# Opening Terminal in VNC Session

If clicking terminal icons doesn't work, try these methods:

## Method 1: Keyboard Shortcut
- Press `Ctrl+Alt+T` (common Linux shortcut)
- Or `Alt+F2` then type `xterm` or `gnome-terminal`

## Method 2: Right-Click Desktop
- Right-click on desktop → "Open Terminal Here"
- If this doesn't work, use the SSH-based workflows below.

## Method 3: Run Commands via SSH (Recommended)
Instead of using VNC terminal, run commands from your main terminal:

```bash
# Check Gateway status
ssh <user>@<server> "./scripts/gateway/check_tws_conflict.sh"

# Check if 2FA is needed
ssh <user>@<server> "tail -20 ibkr/ibc/logs/ibc-*.txt | grep -i '2fa\\|authentication'"

# Check if API port is ready
ssh <user>@<server> "ss -tuln | grep 4002"
```

## Method 4: Direct Command Execution (via SSH, targets VNC display)
If you can see the VNC desktop but terminal won't open, you can run commands directly:

1. In your SSH session (not VNC), run:
```bash
# Set DISPLAY to VNC session
export DISPLAY=:1

# Run Gateway start command
cd /path/to/pearlalgo-dev-ai-agents
./scripts/gateway/start_ibgateway_ibc.sh
```

## Verify Gateway readiness

Run from your main terminal (not VNC):

```bash
ss -tuln | grep 4002
```

If port 4002 is listening, Gateway is ready!






