#!/bin/bash
# Check NQ Agent Service Status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/scripts/logs/nq_agent.pid"
STATE_FILE="$PROJECT_DIR/data/nq_agent_state/state.json"

cd "$PROJECT_DIR"

echo "=== NQ Agent Service Status ==="
echo ""

# Check if process is running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ Service Process: RUNNING"
        echo "   PID: $PID"
        
        # Get process info
        ps -p "$PID" -o pid,etime,cmd --no-headers | awk '{print "   Started: " $2 " ago"}'
    else
        echo "❌ Service Process: NOT RUNNING (stale PID file)"
        rm -f "$PID_FILE"
    fi
else
    # Check by process name
    PIDS=$(pgrep -f "pearlalgo.nq_agent.main")
    if [ -z "$PIDS" ]; then
        echo "❌ Service Process: NOT RUNNING"
    else
        echo "✅ Service Process: RUNNING"
        for PID in $PIDS; do
            echo "   PID: $PID"
        done
    fi
fi

echo ""

# Check state file if it exists
if [ -f "$STATE_FILE" ]; then
    echo "📊 Service State:"
    if command -v jq &> /dev/null; then
        jq -r '
            "   Cycles: \(.cycle_count // 0)",
            "   Signals: \(.signal_count // 0)",
            "   Buffer: \(.buffer_size // 0) bars",
            "   Config: \(.config.symbol // "NQ") @ \(.config.timeframe // "1m")"
        ' "$STATE_FILE"
    else
        echo "   (Install 'jq' for formatted output)"
        echo "   State file: $STATE_FILE"
    fi
else
    echo "📊 Service State: No state file found (service may not have run yet)"
fi

echo ""

# Check IBKR Gateway
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "✅ IBKR Gateway: RUNNING"
else
    echo "❌ IBKR Gateway: NOT RUNNING"
    echo "   Start with: ./scripts/start_ibgateway_ibc.sh"
fi

echo ""

