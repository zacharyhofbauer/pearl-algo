#!/bin/bash
# Quick check if Gateway API is ready

echo "Checking Gateway API status..."
echo ""

# Check if Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ Gateway is not running"
    exit 1
fi

GATEWAY_PID=$(pgrep -f "java.*IBC.jar" | head -1)
echo "✅ Gateway is running (PID: $GATEWAY_PID)"
echo ""

# Check if API port is listening
if ss -tuln 2>/dev/null | grep -q ":4002"; then
    echo "✅✅✅ API port 4002 is LISTENING!"
    echo ""
    echo "Gateway is ready for connections!"
    echo ""
    echo "You can now start the NQ Agent service:"
    echo "   ./scripts/lifecycle/start_nq_agent_service.sh"
    exit 0
else
    echo "⏳ API port 4002 is not yet listening"
    echo ""
    echo "Gateway is still authenticating or starting up..."
    echo ""
    echo "If you approved the login in your mobile app, wait 30-60 seconds"
    echo "and run this script again:"
    echo "   ./scripts/gateway/check_api_ready.sh"
    echo ""
    echo "Or monitor continuously:"
    echo "   watch -n 2 './scripts/gateway/check_api_ready.sh'"
    exit 1
fi






