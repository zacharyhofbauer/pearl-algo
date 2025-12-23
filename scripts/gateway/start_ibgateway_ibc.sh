#!/bin/bash
# ============================================================================
# Category: Gateway
# Purpose: Start IBKR Gateway with IBC (Interactive Brokers Controller) - Preferred method
# Usage: ./scripts/gateway/start_ibgateway_ibc.sh
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
IBC_DIR="$PROJECT_DIR/ibkr/ibc"

cd "$PROJECT_DIR"

echo "=== Starting IB Gateway with IBC (Read-Only Mode) ==="
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

# Ensure Xvfb is running for headless operation
echo "Ensuring Xvfb virtual display is running..."
if ! pgrep -f "Xvfb :99" > /dev/null; then
    Xvfb :99 -screen 0 1024x768x24 &
    sleep 2
    export DISPLAY=:99
else
    export DISPLAY=:99
    echo "Xvfb already running on DISPLAY=:99"
fi

# Start IBC
echo "Starting IB Gateway..."
cd "$IBC_DIR"

# Use headless version that ensures DISPLAY is set
export DISPLAY=:99
# Start in background with logging
LOG_FILE="logs/gateway_$(date +%Y%m%d_%H%M%S).log"
nohup ./gatewaystart.sh -inline > "$LOG_FILE" 2>&1 &
IBC_PID=$!

echo "IB Gateway starting (PID: $IBC_PID)"
echo "Log file: $IBC_DIR/$LOG_FILE"
echo ""

# Wait for Gateway to start and authenticate
echo "Waiting for Gateway to start and authenticate..."
sleep 10

# Check if process is still running
if ! ps -p $IBC_PID > /dev/null 2>&1; then
    echo "⚠️  Process exited - checking logs..."
    tail -30 "$LOG_FILE" 2>/dev/null | tail -15
    echo ""
    echo "Check full log: tail -f $IBC_DIR/$LOG_FILE"
    exit 1
fi

echo "✅ IB Gateway process is running"

# Wait longer for authentication and API to become available
echo "Waiting for authentication and API to become available..."
for i in {1..12}; do
    sleep 5
    if ss -tuln | grep -q ":4002"; then
        echo "✅ API port 4002 is listening!"
        echo ""
        echo "=== IB Gateway is ready for data access ==="
        echo ""
        echo "Gateway is running and authenticated."
        echo "It will stay running until you stop it."
        echo ""
        echo "To stop Gateway: ./scripts/gateway/stop_ibgateway_ibc.sh"
        echo "To view logs: tail -f $IBC_DIR/$LOG_FILE"
        echo ""
        echo "Test connection:"
        echo "  cd $PROJECT_DIR"
        echo "  python3 scripts/testing/smoke_test_ibkr.py"
        exit 0
    fi
    echo "  Still waiting... ($i/12)"
done

# If we get here, port still not listening
echo "⚠️  Port 4002 not listening after 60 seconds"
echo ""
echo "📱 If you're using IBKR mobile app for 2FA:"
echo "   1. Check your mobile app for a login approval notification"
echo "   2. Tap 'Approve' or 'Allow' to approve the login"
echo "   3. Gateway will automatically continue after approval"
echo ""
echo "   To monitor authentication progress:"
echo "   ./scripts/gateway/wait_for_2fa_approval.sh"
echo ""
echo "Check status:"
echo "  ps aux | grep -E '(java.*IBC|IBC.jar)' | grep -v grep"
echo "  ss -tuln | grep 4002"
echo ""
echo "View logs:"
echo "  tail -f $IBC_DIR/$LOG_FILE"
echo "  tail -f $IBC_DIR/logs/ibc-*.txt"

echo ""
echo "To stop IB Gateway: ./scripts/gateway/stop_ibgateway_ibc.sh"
echo "To view logs: tail -f $IBC_DIR/logs/gateway_*.log"
