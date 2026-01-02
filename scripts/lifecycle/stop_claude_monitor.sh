#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Stop Claude Monitor Service gracefully
# Usage: ./scripts/lifecycle/stop_claude_monitor.sh
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/claude_monitor.pid"

cd "$PROJECT_DIR"

echo "=== Stopping Claude Monitor Service ==="
echo ""

# Try to stop using PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" || true)
    if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping service (PID: $PID)..."
        kill "$PID" 2>/dev/null || true

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
            kill -9 "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
            echo "✅ Service force stopped"
            exit 0
        fi
    else
        echo "⚠️  PID file exists but process not running (stale PID file)"
        rm -f "$PID_FILE"
    fi
else
    # Try to find and kill by process name
    PIDS=$(pgrep -f "pearlalgo.claude_monitor.monitor_service" || true)
    if [ -z "$PIDS" ]; then
        echo "❌ Claude Monitor Service is not running"
        exit 1
    else
        echo "Found service processes: $PIDS"
        for PID in $PIDS; do
            echo "Stopping PID: $PID..."
            kill "$PID" 2>/dev/null || true
        done

        # Wait for graceful shutdown
        sleep 2

        # Check if any processes are still running and force kill
        REMAINING=$(pgrep -f "pearlalgo.claude_monitor.monitor_service" || true)
        if [ -n "$REMAINING" ]; then
            echo "⚠️  Some processes didn't stop gracefully, force killing..."
            for PID in $REMAINING; do
                kill -9 "$PID" 2>/dev/null && echo "Force killed PID: $PID"
            done
        fi

        # Clean up PID file if it exists
        rm -f "$PID_FILE"
        echo "✅ Service stopped"
    fi
fi


