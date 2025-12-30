#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Check NQ Agent Service status and display information
# Usage: ./scripts/lifecycle/check_nq_agent_status.sh
# ============================================================================
# Check NQ Agent Service Status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/nq_agent.pid"
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
        # Basic counters
        jq -r '
            "   Cycles: \(.cycle_count // 0)",
            "   Signals: \(.signal_count // 0)",
            "   Buffer: \(.buffer_size // 0) / \(.buffer_size_target // 100) bars",
            "   Config: \(.config.symbol // "MNQ") @ \(.config.timeframe // "5m")"
        ' "$STATE_FILE"
        
        echo ""
        echo "📡 Data Health:"
        jq -r '
            # Data freshness
            if .data_fresh == true then
                "   ✅ Data Fresh: yes"
            elif .data_fresh == false then
                "   ⚠️  Data Fresh: NO (age: \(.latest_bar_age_minutes // "?") min)"
            else
                "   ❓ Data Fresh: unknown"
            end,
            
            # Last successful cycle
            if .last_successful_cycle != null then
                "   Last Success: \(.last_successful_cycle)"
            else
                "   Last Success: (no data yet)"
            end
        ' "$STATE_FILE"
        
        echo ""
        echo "📤 Telegram Delivery:"
        jq -r '
            "   Signals Sent: \(.signals_sent // 0)",
            "   Send Failures: \(.signals_send_failures // 0)",
            if .last_signal_send_error != null and .last_signal_send_error != "" then
                "   ⚠️  Last Error: \(.last_signal_send_error)"
            else
                empty
            end,
            if .last_signal_sent_at != null then
                "   Last Sent: \(.last_signal_sent_at)"
            else
                empty
            end
        ' "$STATE_FILE"
        
        echo ""
        echo "🕐 Market Status:"
        jq -r '
            # Futures market status
            if .futures_market_open == true then
                "   ✅ Futures Market: OPEN"
            elif .futures_market_open == false then
                "   ⏸️  Futures Market: CLOSED"
            else
                "   ❓ Futures Market: unknown"
            end,
            
            # Strategy session status  
            if .strategy_session_open == true then
                "   ✅ Strategy Session: OPEN (generating signals)"
            elif .strategy_session_open == false then
                "   ⏸️  Strategy Session: CLOSED (no signals)"
            else
                "   ❓ Strategy Session: unknown"
            end
        ' "$STATE_FILE"
        
        # Show cadence mode if available
        CADENCE_MODE=$(jq -r '.cadence_mode // empty' "$STATE_FILE" 2>/dev/null)
        if [ -n "$CADENCE_MODE" ]; then
            echo ""
            echo "⏱️  Cadence: $CADENCE_MODE"
        fi
        
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
    echo "   Start with: ./scripts/gateway/gateway.sh start"
fi

echo ""
