#!/usr/bin/env bash
# Stop the Mini App server
#
# Usage:
#   ./scripts/miniapp/stop_miniapp.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PID_FILE="$PROJECT_ROOT/logs/miniapp.pid"

if [[ ! -f "$PID_FILE" ]]; then
    echo "⚠️  No PID file found. Mini App may not be running."
    
    # Try to find and kill by process name
    PIDS=$(pgrep -f "pearlalgo.miniapp.server" || true)
    if [[ -n "$PIDS" ]]; then
        echo "   Found running processes: $PIDS"
        echo "   Stopping..."
        kill $PIDS 2>/dev/null || true
        sleep 1
        echo "✅ Stopped"
    fi
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    echo "🛑 Stopping Mini App server (PID: $PID)..."
    kill "$PID"
    
    # Wait for graceful shutdown
    for i in {1..10}; do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 0.5
    done
    
    # Force kill if still running
    if kill -0 "$PID" 2>/dev/null; then
        echo "   Forcing shutdown..."
        kill -9 "$PID" 2>/dev/null || true
    fi
    
    rm -f "$PID_FILE"
    echo "✅ Mini App server stopped"
else
    echo "⚠️  Process $PID not running. Cleaning up PID file."
    rm -f "$PID_FILE"
fi



