#!/bin/bash
# Monitor Gateway and wait for 2FA approval via mobile app
# This script watches for when you approve the login in your IBKR mobile app

echo "=== Waiting for IBKR Mobile App 2FA Approval ==="
echo ""

# Check if Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ IB Gateway is not running!"
    echo "   Start it first: ./scripts/gateway/start_ibgateway_ibc.sh"
    exit 1
fi

GATEWAY_PID=$(pgrep -f "java.*IBC.jar" | head -1)
echo "✅ Gateway is running (PID: $GATEWAY_PID)"
echo ""

# Find the latest IBC log file
LATEST_LOG=$(ls -t ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/ibc-*.txt 2>/dev/null | head -1)

if [ -z "$LATEST_LOG" ]; then
    echo "⚠️  Could not find IBC log file"
    LATEST_LOG=""
else
    echo "📋 Monitoring log: $LATEST_LOG"
fi

echo ""
echo "📱 ACTION REQUIRED:"
echo "   1. Check your IBKR mobile app"
echo "   2. You should see a login approval notification"
echo "   3. Tap 'Approve' or 'Allow' to approve the login"
echo ""
echo "⏳ Waiting for authentication to complete..."
echo "   (This script will monitor and notify when Gateway is ready)"
echo ""

# Monitor for authentication completion
MAX_WAIT=600  # 10 minutes
CHECK_INTERVAL=2
ELAPSED=0
AUTHENTICATED=false

while [ $ELAPSED -lt $MAX_WAIT ]; do
    # Check if API port is listening
    if ss -tuln 2>/dev/null | grep -q ":4002"; then
        echo ""
        echo "✅✅✅ SUCCESS! Gateway is authenticated and API is ready!"
        echo ""
        echo "   API port 4002 is listening"
        echo "   Gateway is ready for connections"
        echo ""
        echo "You can now start the NQ Agent service:"
        echo "   ./scripts/lifecycle/start_nq_agent_service.sh"
        echo ""
        AUTHENTICATED=true
        break
    fi
    
    # Check log for authentication success
    if [ -n "$LATEST_LOG" ] && [ -f "$LATEST_LOG" ]; then
        # Look for signs of successful authentication
        if grep -qi "logged in\|authenticated\|main window" "$LATEST_LOG" 2>/dev/null; then
            if ! grep -qi "second factor\|2fa\|authentication.*dialog" "$LATEST_LOG" 2>/dev/null | tail -5; then
                echo "   ℹ️  Log shows authentication may have completed..."
            fi
        fi
    fi
    
    # Check if Gateway process is still running
    if ! ps -p $GATEWAY_PID > /dev/null 2>&1; then
        echo ""
        echo "❌ Gateway process exited!"
        echo "   Check logs: tail -50 $LATEST_LOG"
        exit 1
    fi
    
    # Progress indicator
    if [ $((ELAPSED % 10)) -eq 0 ] && [ $ELAPSED -gt 0 ]; then
        echo "   Still waiting... (${ELAPSED}s elapsed)"
        echo "   📱 Remember to approve the login in your IBKR mobile app!"
    fi
    
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
done

if [ "$AUTHENTICATED" = false ]; then
    echo ""
    echo "⏱️  Timeout after ${MAX_WAIT} seconds"
    echo ""
    echo "📋 Troubleshooting:"
    echo "   1. Did you approve the login in your IBKR mobile app?"
    echo "   2. Check Gateway status: ./scripts/gateway/check_tws_conflict.sh"
    echo "   3. Check logs: tail -50 $LATEST_LOG"
    echo "   4. Check if API port is ready: ss -tuln | grep 4002"
    echo ""
    exit 1
fi


