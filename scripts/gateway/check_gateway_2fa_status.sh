#!/bin/bash
# Check Gateway 2FA status - run from SSH terminal (not VNC)

echo "=== IBKR Gateway 2FA Status Check ==="
echo ""

# Check if Gateway is running
if pgrep -f "java.*IBC.jar" > /dev/null; then
    GATEWAY_PID=$(pgrep -f "java.*IBC.jar" | head -1)
    echo "✅ Gateway is running (PID: $GATEWAY_PID)"
else
    echo "❌ Gateway is NOT running"
    echo "   Start it: ./scripts/gateway/start_ibgateway_ibc.sh"
    exit 1
fi

# Check if API port is listening
if ss -tuln 2>/dev/null | grep -q ":4002"; then
    echo "✅ API port 4002 is LISTENING - Gateway is ready!"
    echo ""
    echo "You can now start the NQ Agent service:"
    echo "   ./scripts/lifecycle/start_nq_agent_service.sh"
    exit 0
else
    echo "⚠️  API port 4002 is NOT listening yet"
    echo ""
fi

# Check latest IBC log for 2FA status
LATEST_LOG=$(ls -t ibkr/ibc/logs/ibc-*.txt 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    echo "📋 Recent Gateway activity:"
    echo ""
    tail -20 "$LATEST_LOG" | grep -E "2FA|Second Factor|Authentication|Authenticated|Logged|main window|API" | tail -5
    echo ""
    
    if grep -q "Second Factor Authentication" "$LATEST_LOG" && ! grep -q "Authenticated\|Logged.*in" "$LATEST_LOG"; then
        echo "🔐 Gateway is WAITING for 2FA authentication"
        echo ""
        echo "To complete 2FA:"
        echo "1. Connect to VNC: vncviewer your-server-ip:5901"
        echo "2. Look for IBKR Gateway window with 'Second Factor Authentication' dialog"
        echo "3. Enter your 2FA code from authenticator app"
        echo "4. Click OK"
        echo ""
        echo "After entering 2FA, wait 30-60 seconds, then run this script again:"
        echo "   ./scripts/gateway/check_gateway_2fa_status.sh"
    elif grep -q "Authenticated\|Logged.*in\|main window" "$LATEST_LOG"; then
        echo "✅ Gateway appears to be authenticated"
        echo "   Waiting for API port to become available..."
        echo "   This usually takes 30-60 seconds after authentication"
    fi
else
    echo "⚠️  Could not find Gateway logs"
fi

echo ""
echo "=== Quick Commands ==="
echo "Check API port: ss -tuln | grep 4002"
echo "View Gateway logs: tail -f ibkr/ibc/logs/ibc-*.txt"
echo "Check Gateway process: ps aux | grep IBC.jar"

