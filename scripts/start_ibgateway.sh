#!/bin/bash
# Script to start IB Gateway with proper settings

GATEWAY_DIR="$HOME/Jts/ibgateway/1041"
LOG_FILE="/tmp/ibgateway.log"

echo "Starting IB Gateway..."

# Check if already running
if pgrep -f "ibgateway" > /dev/null; then
    echo "IB Gateway is already running!"
    ps aux | grep ibgateway | grep -v grep
    exit 0
fi

# Check if gateway directory exists
if [ ! -d "$GATEWAY_DIR" ]; then
    echo "Error: IB Gateway not found at $GATEWAY_DIR"
    exit 1
fi

# Start with xvfb (virtual display) for headless operation
cd "$GATEWAY_DIR"
nohup xvfb-run -a ./ibgateway1 > "$LOG_FILE" 2>&1 &

echo "IB Gateway starting in background..."
echo "Log file: $LOG_FILE"
echo ""
echo "Waiting for gateway to start..."
sleep 5

# Check if it's running
if pgrep -f "ibgateway" > /dev/null; then
    echo "✅ IB Gateway process started"
    echo ""
    echo "⚠️  IMPORTANT: You need to configure API access:"
    echo "   1. Connect via VNC/X11 or use IB Gateway's web interface"
    echo "   2. Go to: Configure → Settings → API → Settings"
    echo "   3. Enable 'Enable ActiveX and Socket Clients'"
    echo "   4. Set Socket port to: 4002 (paper) or 7497 (live)"
    echo "   5. Save and restart"
    echo ""
    echo "To check if API is enabled, run:"
    echo "   ss -tuln | grep 4002"
else
    echo "❌ Failed to start IB Gateway"
    echo "Check log: $LOG_FILE"
    tail -20 "$LOG_FILE"
fi
