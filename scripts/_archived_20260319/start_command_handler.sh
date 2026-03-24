#!/bin/bash
# ============================================================================
# Start Telegram Command Handler Service
# Usage:
#   ./scripts/telegram/start_command_handler.sh            # foreground
#   ./scripts/telegram/start_command_handler.sh --background
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/telegram_handler.pid"
LOG_FILE="$PROJECT_DIR/logs/telegram_handler.log"

cd "$PROJECT_DIR"

# Create logs directory if it doesn't exist (for PID/log file only)
mkdir -p "$PROJECT_DIR/logs"

# Activate virtual environment if it exists (mirror lifecycle/testing behavior)
if [ -f .venv/bin/activate ]; then
    echo "Activating virtual environment..."
    # shellcheck source=/dev/null
    source .venv/bin/activate
    echo "Virtual environment activated"
    echo ""
else
    echo "No virtual environment found at .venv/bin/activate"
    echo "   Ensure dependencies are installed in the Python environment."
    echo ""
fi

# Use the same python that can import pearlalgo
PYTHON_CMD=$(which python3)
if [ -f .venv/bin/python3 ]; then
    PYTHON_CMD=".venv/bin/python3"
fi

# Verify pearlalgo is importable
if ! "$PYTHON_CMD" -c "import pearlalgo" 2>/dev/null; then
    echo "ERROR: pearlalgo package not found in this Python environment."
    echo "   Activate the correct virtual environment or run: pip install -e ."
    exit 1
fi

# Check if already running
PIDS=$(pgrep -f "pearlalgo.telegram.main")
if [ -n "$PIDS" ]; then
    echo "Command Handler is already running (PID: $PIDS)"
    echo "   Stop it first with: pkill -f 'pearlalgo.telegram.main'"
    echo "   Or restart safely with: ./scripts/telegram/restart_command_handler.sh --background"
    exit 1
fi

# Background mode?
BACKGROUND=false
for arg in "$@"; do
    if [ "$arg" == "--background" ] || [ "$arg" == "-b" ]; then
        BACKGROUND=true
    fi
done

if [ "$BACKGROUND" = true ]; then
    echo "Starting Telegram Command Handler in background..."
    echo "  Logs: $LOG_FILE"
    echo "  PID file: $PID_FILE"
    echo ""

    nohup "$PYTHON_CMD" -m pearlalgo.telegram.main \
        > "$LOG_FILE" 2>&1 &
    SERVICE_PID=$!
    echo "$SERVICE_PID" > "$PID_FILE"

    echo "Command Handler started (background)"
    echo "   PID: $SERVICE_PID"
    echo "   To check status: ./scripts/telegram/check_command_handler.sh"
    echo "   To stop: pkill -f 'pearlalgo.telegram.main'"
    exit 0
fi

echo "Starting Telegram Command Handler (foreground)..."
echo ""
echo "Use /start in Telegram to open the dashboard"
echo "Press Ctrl+C to stop"
echo ""

"$PYTHON_CMD" -m pearlalgo.telegram.main
