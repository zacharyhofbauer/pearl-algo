#!/bin/bash
# Stop NQ Agent Service

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/scripts/logs/nq_agent.pid"

cd "$PROJECT_DIR"

echo "=== Stopping NQ Agent Service ==="
echo ""

# Try to stop using PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping service (PID: $PID)..."
        kill "$PID"
        
        # Wait for graceful shutdown
        for i in {1..10}; do
            if ! ps -p "$PID" > /dev/null 2>&1; then
                echo "✅ Service stopped gracefully"
                rm -f "$PID_FILE"
                exit 0
            fi
            sleep 1
        done
        
        # Force kill if still running
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "⚠️  Force killing service..."
            kill -9 "$PID"
            rm -f "$PID_FILE"
            echo "✅ Service force stopped"
        fi
    else
        echo "⚠️  PID file exists but process not running (stale PID file)"
        rm -f "$PID_FILE"
    fi
else
    # Try to find and kill by process name
    PIDS=$(pgrep -f "pearlalgo.nq_agent.main")
    if [ -z "$PIDS" ]; then
        echo "❌ NQ Agent Service is not running"
        exit 1
    else
        echo "Found service processes: $PIDS"
        for PID in $PIDS; do
            kill "$PID" 2>/dev/null && echo "Stopped PID: $PID"
        done
        echo "✅ Service stopped"
    fi
fi

