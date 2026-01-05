#!/usr/bin/env bash
# Check Mini App server status
#
# Usage:
#   ./scripts/miniapp/check_miniapp.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load environment for port
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

PORT="${MINIAPP_PORT:-8080}"
HOST="${MINIAPP_HOST:-127.0.0.1}"
PID_FILE="$PROJECT_ROOT/logs/miniapp.pid"

echo "🔍 Mini App Server Status"
echo "========================="
echo ""

# Check PID file
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "✅ Process: RUNNING (PID: $PID)"
    else
        echo "❌ Process: NOT RUNNING (stale PID file)"
    fi
else
    echo "❌ Process: NOT RUNNING (no PID file)"
fi

# Check port
if ss -tuln | grep -q ":$PORT "; then
    echo "✅ Port $PORT: LISTENING"
else
    echo "❌ Port $PORT: NOT LISTENING"
fi

# Try health endpoint
echo ""
echo "🏥 Health Check:"
if curl -sf "http://$HOST:$PORT/api/health" 2>/dev/null; then
    echo ""
    echo "✅ Health endpoint: OK"
else
    echo "❌ Health endpoint: FAILED (server may be starting or not running)"
fi

# Show configuration
echo ""
echo "⚙️  Configuration:"
echo "   Host: $HOST"
echo "   Port: $PORT"
if [[ -n "${MINIAPP_BASE_URL:-}" ]]; then
    echo "   Base URL: $MINIAPP_BASE_URL"
else
    echo "   Base URL: (not set - configure MINIAPP_BASE_URL in .env)"
fi

# Show recent logs if available
LOG_FILE="$PROJECT_ROOT/logs/miniapp.log"
if [[ -f "$LOG_FILE" ]]; then
    echo ""
    echo "📋 Recent logs (last 5 lines):"
    tail -5 "$LOG_FILE" | sed 's/^/   /'
fi

echo ""
echo "💡 Commands:"
echo "   Start:  ./scripts/miniapp/start_miniapp.sh [--background]"
echo "   Stop:   ./scripts/miniapp/stop_miniapp.sh"
echo "   Logs:   tail -f $PROJECT_ROOT/logs/miniapp.log"





