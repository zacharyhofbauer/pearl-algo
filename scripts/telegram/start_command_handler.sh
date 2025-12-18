#!/bin/bash
# ============================================================================
# Start Telegram Command Handler Service
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

# Check if already running
PIDS=$(pgrep -f "telegram_command_handler")
if [ -n "$PIDS" ]; then
    echo "⚠️  Command Handler is already running (PID: $PIDS)"
    echo "   Stop it first with: pkill -f telegram_command_handler"
    exit 1
fi

echo "Starting Telegram Command Handler..."
echo ""
echo "This service listens for Telegram commands (/status, /signals, etc.)"
echo "Press Ctrl+C to stop"
echo ""

python3 -m pearlalgo.nq_agent.telegram_command_handler

