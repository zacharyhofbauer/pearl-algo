#!/bin/bash
# ============================================================================
# Category: Gateway
# Purpose: Check IBKR Gateway status and connection health
# Usage: ./scripts/gateway/check_gateway_status.sh
# ============================================================================

echo "=== IBKR Gateway Status ==="
echo ""

# Check if process is running
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "✅ Gateway Process: RUNNING"
    ps aux | grep "IBC.jar" | grep -v grep | awk '{print "   PID: " $2 ", Started: " $9}'
else
    echo "❌ Gateway Process: NOT RUNNING"
fi

echo ""

# Check if API port is listening
if ss -tuln | grep -q ":4002"; then
    echo "✅ API Port 4002: LISTENING"
    ss -tuln | grep ":4002" | awk '{print "   " $0}'
else
    echo "❌ API Port 4002: NOT LISTENING"
fi

echo ""

# Show latest log file
LATEST_LOG=$(ls -t ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    echo "📄 Latest Log: $LATEST_LOG"
    echo "   Last modified: $(stat -c %y "$LATEST_LOG" 2>/dev/null | cut -d. -f1)"
else
    echo "📄 Latest Log: Not found"
fi

echo ""

# Quick summary
if pgrep -f "java.*IBC.jar" > /dev/null && ss -tuln | grep -q ":4002"; then
    echo "🎉 Gateway is RUNNING and READY for data access!"
elif pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "⚠️  Gateway is running but API not ready yet (may still be authenticating)"
else
    echo "❌ Gateway is not running. Start it with: ./scripts/start_ibgateway_ibc.sh"
fi
