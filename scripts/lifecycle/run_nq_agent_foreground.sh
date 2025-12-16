#!/bin/bash
# Run NQ Agent Service in Foreground (with live terminal output)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/scripts/logs/nq_agent.pid"

cd "$PROJECT_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ NQ Agent Service already running (PID: $PID)"
        echo "   Use './scripts/lifecycle/stop_nq_agent_service.sh' to stop it first"
        exit 1
    else
        # Stale PID file
        rm -f "$PID_FILE"
    fi
fi

# Check if IBKR Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "⚠️  Warning: IBKR Gateway doesn't appear to be running"
    echo "   Start it with: ./scripts/start_ibgateway_ibc.sh"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Activate virtual environment if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "⚠️  Warning: No virtual environment found at .venv/bin/activate"
    echo "   Make sure to install dependencies: pip install -e ."
fi

# Check if package is installed
if ! python3 -c "import pearlalgo" 2>/dev/null; then
    echo "❌ ERROR: pearlalgo package not found!"
    echo "   Install it with: pip install -e ."
    exit 1
fi

echo "=== Starting NQ Agent Service (Foreground Mode) ==="
echo "   Press Ctrl+C to stop"
echo ""

# Use the same python that can import pearlalgo
PYTHON_CMD=$(which python3)
if [ -f .venv/bin/python3 ]; then
    PYTHON_CMD=".venv/bin/python3"
fi

# Run in foreground - output goes directly to terminal
# Save PID for cleanup on Ctrl+C
"$PYTHON_CMD" -m pearlalgo.nq_agent.main &
SERVICE_PID=$!
echo $SERVICE_PID > "$PID_FILE"

# Wait for the process and cleanup on exit
trap "kill $SERVICE_PID 2>/dev/null; rm -f $PID_FILE; exit" INT TERM
wait $SERVICE_PID
