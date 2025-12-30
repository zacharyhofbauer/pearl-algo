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

# ----------------------------------------------------------------------------
# Arg parsing
# ----------------------------------------------------------------------------
BACKGROUND_MODE=false
EXECUTION_DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --background|-b)
            BACKGROUND_MODE=true
            ;;
        --execution-dry-run)
            EXECUTION_DRY_RUN=true
            ;;
    esac
done

# Enable execution dry-run via typed env overrides (no orders; still requires /arm to attempt execution)
if [ "$EXECUTION_DRY_RUN" = true ]; then
    export PEARLALGO_EXECUTION_ENABLED=true
    export PEARLALGO_EXECUTION_MODE=dry_run
    export PEARLALGO_EXECUTION_ARMED=false
    echo "🛡️  ATS dry_run enabled via env overrides (execution.enabled=true, armed=false, mode=dry_run)"
fi

# Create logs directory if it doesn't exist (for PID file only)
mkdir -p "$PROJECT_DIR/logs"

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
    echo "   Start it with: ./scripts/gateway/gateway.sh start"
    # In non-interactive contexts (e.g. Telegram command handler), do not block on input.
    # Preserve the prompt's default answer ("N") by failing fast.
    if [ -t 0 ]; then
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "❌ Non-interactive session detected; refusing to continue without Gateway (default: N)"
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
if [ "$BACKGROUND_MODE" = true ]; then
    echo "=== Starting NQ Agent Service (Background Mode) ==="
    echo ""
    
    # Use the same python that can import pearlalgo
    PYTHON_CMD=$(which python3)
    if [ -f .venv/bin/python3 ]; then
        PYTHON_CMD=".venv/bin/python3"
    fi
    
    # Log file for background mode (with basic rotation)
    LOG_FILE="$PROJECT_DIR/logs/nq_agent.log"
    
    # Rotate existing log if it exists and is non-empty
    if [ -f "$LOG_FILE" ] && [ -s "$LOG_FILE" ]; then
        # Keep one backup (overwrite if exists)
        mv "$LOG_FILE" "${LOG_FILE}.1"
        echo "📁 Rotated previous log to ${LOG_FILE}.1"
    fi
    
    # Run in background - output captured to log file
    nohup "$PYTHON_CMD" -m pearlalgo.nq_agent.main >> "$LOG_FILE" 2>&1 &
    SERVICE_PID=$!
    
    # Save PID
    echo $SERVICE_PID > "$PID_FILE"
    
    echo "✅ NQ Agent Service started in background"
    echo "   PID: $SERVICE_PID"
    echo "   PID File: $PID_FILE"
    echo "   Log File: $LOG_FILE"
    echo ""
    echo "📋 To view logs: tail -f $LOG_FILE"
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

