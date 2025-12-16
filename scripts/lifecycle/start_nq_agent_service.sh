#!/bin/bash
# Start NQ Agent Service in Background

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_DIR/scripts/logs"
PID_FILE="$LOG_DIR/nq_agent.pid"
LOG_FILE="$LOG_DIR/nq_agent.log"

cd "$PROJECT_DIR"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ NQ Agent Service already running (PID: $PID)"
        echo "   Use './scripts/stop_nq_agent_service.sh' to stop it first"
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

echo "=== Starting NQ Agent Service ==="
echo ""

# Start service in background with proper environment
# Use the same python that can import pearlalgo
PYTHON_CMD=$(which python3)
if [ -f .venv/bin/python3 ]; then
    PYTHON_CMD=".venv/bin/python3"
fi

nohup "$PYTHON_CMD" -m pearlalgo.nq_agent.main > "$LOG_FILE" 2>&1 &
SERVICE_PID=$!

# Save PID
echo $SERVICE_PID > "$PID_FILE"

echo "✅ NQ Agent Service started"
echo "   PID: $SERVICE_PID"
echo "   Log: $LOG_FILE"
echo "   PID File: $PID_FILE"
echo ""
echo "To view logs: tail -f $LOG_FILE"
echo "To stop: ./scripts/stop_nq_agent_service.sh"

