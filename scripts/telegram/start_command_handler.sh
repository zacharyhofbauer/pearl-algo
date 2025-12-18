#!/bin/bash
# ============================================================================
# Start Telegram Command Handler Service
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

# Activate virtual environment if it exists (mirror lifecycle/testing behavior)
if [ -f .venv/bin/activate ]; then
    echo "Activating virtual environment..."
    # shellcheck source=/dev/null
    source .venv/bin/activate
    echo "✅ Virtual environment activated"
    echo ""
else
    echo "⚠️  No virtual environment found at .venv/bin/activate"
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
    echo "❌ ERROR: pearlalgo package not found in this Python environment."
    echo "   Activate the correct virtual environment or run: pip install -e ."
    exit 1
fi

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

"$PYTHON_CMD" -m pearlalgo.nq_agent.telegram_command_handler


