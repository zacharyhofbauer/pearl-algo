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

# Load .env
if [[ -f ".env" ]]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check for required environment variables
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
    echo "WARNING: ANTHROPIC_API_KEY not set. Claude analysis will be limited."
fi

if [[ -z "$TELEGRAM_BOT_TOKEN" ]] || [[ -z "$TELEGRAM_CHAT_ID" ]]; then
    echo "WARNING: Telegram not configured. Alerts will only be logged."
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
    
    echo "Running in background..."
    echo "Logs: $LOG_FILE"
    echo "PID file: $PID_FILE"
    
    nohup python -m pearlalgo.claude_monitor.monitor_service \
        >> "$LOG_FILE" 2>&1 &
    
    echo $! > "$PID_FILE"
    echo "Claude Monitor started with PID $(cat $PID_FILE)"
else
    # Foreground mode
    echo "Running in foreground (Ctrl+C to stop)..."
    python -m pearlalgo.claude_monitor.monitor_service
fi




