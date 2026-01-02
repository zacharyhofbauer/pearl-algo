#!/usr/bin/env bash
# Start the Mini App server for PearlAlgo Terminal
#
# Usage:
#   ./scripts/miniapp/start_miniapp.sh [--background]
#
# Options:
#   --background    Run in background with nohup (logs to logs/miniapp.log)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

# Load environment
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

# Check if miniapp extra is installed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "❌ FastAPI not installed. Run: pip install -e '.[miniapp]'"
    exit 1
fi

# Check if already running
PID_FILE="$PROJECT_ROOT/logs/miniapp.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Mini App server already running (PID: $OLD_PID)"
        echo "   Stop it first: ./scripts/miniapp/stop_miniapp.sh"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# Ensure logs directory exists
mkdir -p "$PROJECT_ROOT/logs"

# Parse arguments
BACKGROUND=false
for arg in "$@"; do
    case $arg in
        --background)
            BACKGROUND=true
            shift
            ;;
    esac
done

echo "🚀 Starting Mini App server..."

if [[ "$BACKGROUND" == "true" ]]; then
    # Background mode with nohup
    nohup python3 -m pearlalgo.miniapp.server \
        > "$PROJECT_ROOT/logs/miniapp.log" 2>&1 &
    
    echo $! > "$PID_FILE"
    sleep 2
    
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "✅ Mini App server started (PID: $(cat "$PID_FILE"))"
        echo "   Logs: $PROJECT_ROOT/logs/miniapp.log"
        echo ""
        echo "💡 To check status: ./scripts/miniapp/check_miniapp.sh"
        echo "💡 To stop: ./scripts/miniapp/stop_miniapp.sh"
    else
        echo "❌ Mini App server failed to start. Check logs:"
        tail -20 "$PROJECT_ROOT/logs/miniapp.log"
        exit 1
    fi
else
    # Foreground mode
    echo "   Press Ctrl+C to stop"
    echo ""
    python3 -m pearlalgo.miniapp.server
fi




