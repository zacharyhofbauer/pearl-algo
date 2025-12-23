#!/bin/bash
# Quick VNC setup for one-time IBKR Gateway manual login
# After this one login, Gateway can run headless forever

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== VNC Setup for IBKR Gateway Manual Login ==="
echo ""

# Check if VNC is already running
if pgrep -f "Xvnc.*:1" > /dev/null; then
    echo "⚠️  VNC server already running on :1"
    echo "   To kill it: vncserver -kill :1"
    echo ""
    SERVER_IP=$(hostname -I | awk '{print $1}')
    echo "✅ Connect via VNC:"
    echo "   vncviewer $SERVER_IP:5901"
    echo "   Or: ssh -L 5901:localhost:5901 pearlalgo@$SERVER_IP"
    exit 0
fi

# Start VNC server
echo "Starting VNC server on display :1..."
vncserver :1 -geometry 1024x768 -depth 24

if [ $? -eq 0 ]; then
    echo "✅ VNC server started!"
    echo ""
    SERVER_IP=$(hostname -I | awk '{print $1}')
    echo "=== Connection Instructions ==="
    echo ""
    echo "1. From your local machine, connect via VNC:"
    echo "   vncviewer $SERVER_IP:5901"
    echo ""
    echo "   Or use SSH tunnel:"
    echo "   ssh -L 5901:localhost:5901 pearlalgo@$SERVER_IP"
    echo "   Then: vncviewer localhost:5901"
    echo ""
    echo "2. In the VNC session, start Gateway:"
    echo "   cd $PROJECT_DIR/ibkr/ibc"
    echo "   export DISPLAY=:1"
    echo "   ./gatewaystart.sh"
    echo ""
    echo "3. Complete login (credentials are in config)"
    echo "   - Approve 2FA from mobile app if needed"
    echo "   - Let Gateway fully start"
    echo "   - Close Gateway (this saves the session)"
    echo ""
    echo "4. After login, stop VNC (no longer needed):"
    echo "   vncserver -kill :1"
    echo ""
    echo "5. Future starts are headless:"
    echo "   ./scripts/gateway/start_ibgateway_ibc.sh"
    echo ""
else
    echo "❌ Failed to start VNC server"
    echo "   You may need to set a VNC password first:"
    echo "   vncpasswd"
    exit 1
fi


