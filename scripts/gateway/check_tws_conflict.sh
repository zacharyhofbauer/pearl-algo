#!/bin/bash
# Check for TWS/Gateway conflicts

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

echo "=== IBKR Connection Conflict Check ==="
echo ""

# Check if Gateway is running
GATEWAY_PID=$(pgrep -f "java.*IBC.jar")
if [ -n "$GATEWAY_PID" ]; then
    echo "✅ IBKR Gateway: RUNNING (PID: $GATEWAY_PID)"
else
    echo "❌ IBKR Gateway: NOT RUNNING"
fi

echo ""

# Check for TWS processes (exclude Gateway's own processes and IBC scripts)
# TWS typically runs as standalone "tws" or "Trader Workstation" application
# Exclude: IBC scripts (ibcstart.sh, gatewaystart.sh), Gateway Java process, and our own check script
TWS_PIDS=$(pgrep -f "tws|Trader Workstation" 2>/dev/null | while read pid; do
    # Get the command line for this PID
    cmd=$(ps -p "$pid" -o cmd --no-headers 2>/dev/null)
    # Skip if it's Gateway Java process
    if [ "$pid" = "$GATEWAY_PID" ]; then
        continue
    fi
    # Skip if it's an IBC/Gateway startup script
    if echo "$cmd" | grep -qE "(ibcstart|gatewaystart|IBC\.jar|IbcGateway)"; then
        continue
    fi
    # Skip if it's our own check script
    if echo "$cmd" | grep -q "check_tws_conflict.sh"; then
        continue
    fi
    # This looks like actual TWS
    echo "$pid"
done)

if [ -n "$TWS_PIDS" ]; then
    echo "⚠️  WARNING: TWS (Trader Workstation) processes detected:"
    for PID in $TWS_PIDS; do
        ps -p "$PID" -o pid,cmd --no-headers 2>/dev/null | awk '{print "   PID " $1 ": " substr($0, index($0,$2))}'
    done
    echo ""
    echo "💡 If TWS is connected from a different IP, you'll get Error 162."
    echo "   Solution: Close TWS or disconnect it, then restart Gateway."
else
    echo "✅ No TWS processes detected (Gateway-only mode)"
fi

echo ""

# Check for Error 162 in recent logs
if [ -f "logs/nq_agent.log" ]; then
    ERROR_162_COUNT=$(grep -c "Error 162\|TWS session\|different IP" logs/nq_agent.log 2>/dev/null || echo "0")
    # Remove any newlines and ensure it's a number
    ERROR_162_COUNT=$(echo "$ERROR_162_COUNT" | tr -d '\n' | head -1)
    if [ -n "$ERROR_162_COUNT" ] && [ "$ERROR_162_COUNT" -gt 0 ] 2>/dev/null; then
        echo "⚠️  Error 162 detected in logs ($ERROR_162_COUNT occurrences)"
        echo "   Recent occurrences:"
        grep "Error 162\|TWS session\|different IP" logs/nq_agent.log | tail -3 | sed 's/^/   /'
        echo ""
        echo "💡 This indicates a TWS/Gateway IP conflict."
    else
        echo "✅ No Error 162 in recent logs"
    fi
fi

echo ""





