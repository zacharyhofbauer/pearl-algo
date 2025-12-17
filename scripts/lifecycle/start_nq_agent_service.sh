#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Start NQ Agent Service (production-ready with PID management)
# Usage: ./scripts/lifecycle/start_nq_agent_service.sh [--background]
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/nq_agent.pid"

cd "$PROJECT_DIR"

# Create logs directory if it doesn't exist (for PID file only)
mkdir -p "$PROJECT_DIR/logs"

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

# Check if user wants background mode
if [ "$1" == "--background" ] || [ "$1" == "-b" ]; then
    echo "=== Starting NQ Agent Service (Background Mode) ==="
    echo ""
    
    # Use the same python that can import pearlalgo
    PYTHON_CMD=$(which python3)
    if [ -f .venv/bin/python3 ]; then
        PYTHON_CMD=".venv/bin/python3"
    fi
    
    # Run in background - output goes to /dev/null (no log files)
    nohup "$PYTHON_CMD" -m pearlalgo.nq_agent.main > /dev/null 2>&1 &
    SERVICE_PID=$!
    
    # Save PID
    echo $SERVICE_PID > "$PID_FILE"
    
    echo "✅ NQ Agent Service started in background"
    echo "   PID: $SERVICE_PID"
    echo "   PID File: $PID_FILE"
    echo ""
    echo "⚠️  Note: Logs are not saved to file. Run in foreground to see output."
    echo "To run in foreground: ./scripts/lifecycle/start_nq_agent_service.sh"
    echo "To stop: ./scripts/lifecycle/stop_nq_agent_service.sh"
    exit 0
fi

echo "=== Starting NQ Agent Service (Foreground Mode) ==="
echo "   Press Ctrl+C to stop"
echo "   All logs will appear in this terminal"
echo ""

# Use the same python that can import pearlalgo
PYTHON_CMD=$(which python3)
if [ -f .venv/bin/python3 ]; then
    PYTHON_CMD=".venv/bin/python3"
fi

# Cleanup function
cleanup() {
    # If process is still running, try to kill it
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            # Try graceful kill first
            kill "$PID" 2>/dev/null
            sleep 1
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                kill -9 "$PID" 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi
}

# Handle Ctrl+C - send signal to Python process and cleanup
handle_interrupt() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        # Send SIGINT to Python process (same as Ctrl+C)
        kill -INT "$PID" 2>/dev/null
        # Wait a moment for graceful shutdown
        sleep 2
        # Force kill if still running
        if ps -p "$PID" > /dev/null 2>&1; then
            echo ""
            echo "⚠️  Process didn't exit gracefully, force killing..."
            kill -9 "$PID" 2>/dev/null
        fi
    fi
    cleanup
    exit 0
}

# Set up signal handlers
trap handle_interrupt INT TERM
trap cleanup EXIT

# Run in background to get PID, then wait for it
"$PYTHON_CMD" -m pearlalgo.nq_agent.main &
SERVICE_PID=$!
echo $SERVICE_PID > "$PID_FILE"

# Wait for the process - Ctrl+C will trigger handle_interrupt
wait $SERVICE_PID

