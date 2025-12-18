#!/bin/bash
# ============================================================================
# Check if Telegram Command Handler is Running
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

echo "=== Checking Telegram Command Handler Status ==="
echo ""

# Check if process is running
PIDS=$(pgrep -f "telegram_command_handler")
if [ -z "$PIDS" ]; then
    echo "❌ Command Handler is NOT running"
    echo ""
    echo "To start it, run:"
    echo "  cd ~/pearlalgo-dev-ai-agents"
    echo "  python3 -m pearlalgo.nq_agent.telegram_command_handler"
    echo ""
    echo "Or use the helper script:"
    echo "  ./scripts/telegram/start_command_handler.sh"
    exit 1
else
    echo "✅ Command Handler is running (PID: $PIDS)"
    echo ""
    echo "Process details:"
    ps aux | grep telegram_command_handler | grep -v grep
    echo ""
    echo "To stop it:"
    echo "  pkill -f telegram_command_handler"
    exit 0
fi

