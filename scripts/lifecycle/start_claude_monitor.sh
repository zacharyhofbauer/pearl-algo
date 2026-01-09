#!/bin/bash
# Start Claude Monitor Service
# 
# This script starts the Claude Monitor as a standalone service.
# The monitor runs alongside the NQ Agent and provides AI-powered
# monitoring, analysis, and suggestions.
#
# Usage:
#   ./scripts/lifecycle/start_claude_monitor.sh              # Foreground
#   ./scripts/lifecycle/start_claude_monitor.sh --background # Background

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_ROOT/logs/claude_monitor.pid"

cd "$PROJECT_ROOT"

# Activate virtual environment if present
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

# Load .env (robust against indented comments and values containing spaces)
if [[ -f ".env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# Check for required environment variables
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
    echo "WARNING: ANTHROPIC_API_KEY not set. Claude analysis will be limited."
fi

if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_CHAT_ID" ]]; then
    echo "WARNING: Telegram not configured. Alerts will only be logged."
fi

# Pick a python executable (prefer `python` if available, otherwise `python3`)
PYTHON_BIN=""
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "ERROR: Neither 'python' nor 'python3' found in PATH. Please install Python 3 or activate your virtualenv." >&2
    exit 1
fi

# Parse arguments
BACKGROUND=false
for arg in "$@"; do
    case $arg in
        --background|-b)
            BACKGROUND=true
            shift
            ;;
    esac
done

echo "Starting Claude Monitor Service..."
echo "Project root: $PROJECT_ROOT"
echo "Claude API: ${ANTHROPIC_API_KEY:+configured}"
echo "Telegram: ${TELEGRAM_BOT_TOKEN:+configured}"

# Idempotency: if already running, do nothing
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$PID" ]] && ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ Claude Monitor already running (PID: $PID)"
        exit 0
    fi
    echo "⚠️  Removing stale PID file: $PID_FILE"
    rm -f "$PID_FILE"
fi

if [[ "$BACKGROUND" == "true" ]]; then
    # Background mode
    LOG_FILE="$PROJECT_ROOT/logs/claude_monitor.log"
    
    mkdir -p "$PROJECT_ROOT/logs"
    touch "$LOG_FILE"
    
    echo "Running in background..."
    echo "Logs: $LOG_FILE"
    echo "PID file: $PID_FILE"
    
    nohup "$PYTHON_BIN" -m pearlalgo.claude_monitor.monitor_service \
        >> "$LOG_FILE" 2>&1 &
    
    echo $! > "$PID_FILE"
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    sleep 1
    if [[ -n "$PID" ]] && ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ Claude Monitor started with PID $PID"
        exit 0
    fi

    echo "❌ Claude Monitor failed to start (process exited immediately)" >&2
    if [[ -f "$LOG_FILE" ]]; then
        echo "--- Last 80 log lines ---" >&2
        tail -n 80 "$LOG_FILE" >&2 || true
    fi
    rm -f "$PID_FILE"
    exit 1
else
    # Foreground mode
    echo "Running in foreground (Ctrl+C to stop)..."
    "$PYTHON_BIN" -m pearlalgo.claude_monitor.monitor_service
fi




