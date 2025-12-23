#!/bin/bash
# Start IB Gateway with IBC on VNC display for manual configuration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
IBC_DIR="$PROJECT_DIR/ibkr/ibc"

cd "$PROJECT_DIR"

echo "=== Starting IB Gateway with IBC on VNC Display ==="
echo ""

# Check if VNC is running
if ! pgrep -f "Xtigervnc.*:1" > /dev/null && ! pgrep -f "Xvnc.*:1" > /dev/null; then
    echo "⚠️  VNC server may not be running on :1"
    echo "   Starting VNC server..."
    vncserver :1 -geometry 1024x768 -depth 24 2>&1 | head -5
    sleep 2
fi

echo "✅ VNC server is running on :1"
echo ""

# Check if already running
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "⚠️  IB Gateway is already running!"
    ps aux | grep "IBC.jar" | grep -v grep
    echo ""
    echo "To stop it: ./scripts/gateway/stop_ibgateway_ibc.sh"
    exit 1
fi

# Check if IBC is configured
if [ ! -f "$IBC_DIR/config-auto.ini" ]; then
    echo "❌ IBC not configured."
    echo "   Run: ./scripts/gateway/setup_ibgateway.sh"
    exit 1
fi

# Start IBC on VNC display
echo "Starting IB Gateway on VNC display :1..."
cd "$IBC_DIR"

# Use VNC display instead of Xvfb
export DISPLAY=:1

# Start in background with logging
LOG_FILE="logs/gateway_$(date +%Y%m%d_%H%M%S).log"
nohup ./gatewaystart.sh -inline > "$LOG_FILE" 2>&1 &
IBC_PID=$!

echo "IB Gateway starting on VNC display :1 (PID: $IBC_PID)"
echo "Log file: $IBC_DIR/$LOG_FILE"
echo ""
echo "✅ Gateway should now be visible in your VNC viewer!"
echo ""
echo "Connect to VNC:"
SERVER_IP=$(hostname -I | awk '{print $1}')
echo "  vncviewer ${SERVER_IP}:5901"
echo "  (or use SSH tunnel: ssh -L 5901:localhost:5901 <user>@${SERVER_IP})"
echo ""
echo "In VNC, you should see the Gateway window where you can:"
echo "  1. Approve 2FA if needed"
echo "  2. Configure API settings (Configure → Settings → API)"
echo "  3. Enable 'ActiveX and Socket Clients'"
echo "  4. Set port to 4002"
echo "  5. Uncheck 'Read-Only API'"
echo ""
echo "Monitor Gateway:"
echo "  tail -f $IBC_DIR/$LOG_FILE"
echo ""
echo "Check API status:"
echo "  ./scripts/gateway/check_api_ready.sh"






