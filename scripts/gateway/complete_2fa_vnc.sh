#!/bin/bash
# Complete 2FA authentication for IBKR Gateway via VNC
# Use this when Gateway is waiting for 2FA input

echo "=== Complete 2FA Authentication for IBKR Gateway ==="
echo ""

# Check if Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ IB Gateway is not running!"
    echo "   Start it first: ./scripts/gateway/start_ibgateway_ibc.sh"
    exit 1
fi

echo "✅ Gateway is running and waiting for 2FA"
echo ""

# Check if VNC is already running
VNC_DISPLAY=":1"
if pgrep -f "Xvnc.*${VNC_DISPLAY}" > /dev/null; then
    echo "✅ VNC server already running on ${VNC_DISPLAY}"
    VNC_PORT="5901"
else
    echo "Starting VNC server on ${VNC_DISPLAY}..."
    vncserver ${VNC_DISPLAY} -geometry 1024x768 -depth 24 2>&1 | tee /tmp/vnc_start.log
    
    if [ $? -eq 0 ]; then
        echo "✅ VNC server started!"
        VNC_PORT="5901"
    else
        # Check if it's already running
        if grep -q "already in use" /tmp/vnc_start.log 2>/dev/null; then
            echo "✅ VNC server already running"
            VNC_PORT="5901"
        else
            echo "❌ Failed to start VNC server"
            echo ""
            echo "You may need to set a VNC password first:"
            echo "   vncpasswd"
            exit 1
        fi
    fi
fi

# Get server IP
SERVER_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "localhost")

echo ""
echo "=== Connect to VNC ==="
echo ""
echo "Option 1: Direct connection (if firewall allows):"
echo "   vncviewer ${SERVER_IP}:${VNC_PORT}"
echo ""
echo "Option 2: SSH tunnel (recommended):"
echo "   ssh -L ${VNC_PORT}:localhost:${VNC_PORT} ${USER}@${SERVER_IP}"
echo "   Then: vncviewer localhost:${VNC_PORT}"
echo ""
echo "=== In VNC Session ==="
echo ""
echo "1. You should see the IBKR Gateway window"
echo "2. Look for the 'Second Factor Authentication' dialog"
echo "3. Enter your 2FA code from your authenticator app"
echo "4. Click 'OK' or 'Submit'"
echo ""
echo "5. Wait for Gateway to fully load (you'll see the main Gateway window)"
echo "6. The API port 4002 should become available within 30-60 seconds"
echo ""
echo "=== After Authentication ==="
echo ""
echo "You can close VNC (Gateway will continue running headlessly):"
echo "   vncserver -kill ${VNC_DISPLAY}"
echo ""
echo "Check if API is ready:"
echo "   ss -tuln | grep 4002"
echo ""
echo "Or check Gateway status:"
echo "   ./scripts/gateway/check_tws_conflict.sh"
echo ""


