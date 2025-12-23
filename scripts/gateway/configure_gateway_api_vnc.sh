#!/bin/bash
# Configure Gateway API settings via VNC (one-time setup)
# After this, Gateway should work headlessly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

echo "=== Configure Gateway API Settings (One-Time VNC Setup) ==="
echo ""

# Check if Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ Gateway is not running!"
    echo "   Start it first: ./scripts/gateway/start_ibgateway_ibc.sh"
    exit 1
fi

echo "✅ Gateway is running"
echo ""

# Start VNC if not running
VNC_DISPLAY=":1"
if ! pgrep -f "Xvnc.*${VNC_DISPLAY}" > /dev/null; then
    echo "Starting VNC server..."
    vncserver ${VNC_DISPLAY} -geometry 1024x768 -depth 24
    if [ $? -ne 0 ]; then
        echo "❌ Failed to start VNC"
        exit 1
    fi
    echo "✅ VNC server started"
else
    echo "✅ VNC server already running"
fi

SERVER_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "localhost")

echo ""
echo "=== Connect to VNC ==="
echo ""
echo "Option 1: Direct: vncviewer ${SERVER_IP}:5901"
echo "Option 2: SSH tunnel: ssh -L 5901:localhost:5901 pearlalgo@${SERVER_IP}"
echo "   Then: vncviewer localhost:5901"
echo ""
echo "=== In VNC Session ==="
echo ""
echo "1. You should see the IBKR Gateway window"
echo ""
echo "2. Enable API Access:"
echo "   - Click: Configure → Settings (or File → Global Configuration → API → Settings)"
echo "   - Check: 'Enable ActiveX and Socket Clients'"
echo "   - Set Socket port: 4002"
echo "   - UNCHECK: 'Read-Only API' (if checked)"
echo "   - Under 'Trusted IPs', ensure 127.0.0.1 is listed"
echo "   - Click 'OK'"
echo ""
echo "3. If you see 'API client needs write access' dialog:"
echo "   - Click 'Yes' or 'Allow' to grant write access"
echo ""
echo "4. Wait 30 seconds for API to start"
echo ""
echo "5. Close Gateway (File → Exit) - this saves settings"
echo ""
echo "6. After closing, Gateway will restart automatically (if AutoRestart enabled)"
echo "   Or restart manually: ./scripts/gateway/start_ibgateway_ibc.sh"
echo ""
echo "=== After Configuration ==="
echo ""
echo "Check if API is ready:"
echo "   ./scripts/gateway/check_api_ready.sh"
echo ""
echo "Close VNC when done:"
echo "   vncserver -kill ${VNC_DISPLAY}"
echo ""






