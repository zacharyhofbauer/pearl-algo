#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Start/Stop/Status for Tradovate Paper Evaluation instance
#
# This script launches a separate Pearl agent + API server pair that:
#   - Writes state to data/agent_state/TV_PAPER_EVAL/ (isolated from IBKR Virtual)
#   - Runs the API server on port 8001 (separate from IBKR Virtual on 8000)
#   - Uses Tradovate as the execution adapter (paper/demo)
#
# Usage:
#   ./scripts/lifecycle/tv_paper_eval.sh start [--background]
#   ./scripts/lifecycle/tv_paper_eval.sh stop
#   ./scripts/lifecycle/tv_paper_eval.sh status
#   ./scripts/lifecycle/tv_paper_eval.sh api [--background]   # API server only
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

COMMAND="${1:-}"
shift || true

BACKGROUND_MODE=false
while [ $# -gt 0 ]; do
    case "$1" in
        --background|-b)
            BACKGROUND_MODE=true
            shift 1
            ;;
        *)
            shift 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Fixed configuration for the Tradovate Paper Evaluation instance
# ---------------------------------------------------------------------------
INSTANCE_NAME="TV_PAPER"
MARKET="MNQ"
API_PORT=8001
CONFIG_FILE="$PROJECT_DIR/config/accounts/tradovate_paper.yaml"
STATE_DIR="$PROJECT_DIR/data/tradovate/paper"

PID_FILE="$PROJECT_DIR/logs/agent_${INSTANCE_NAME}.pid"
API_PID_FILE="$PROJECT_DIR/logs/api_${INSTANCE_NAME}.pid"
LOG_FILE="$PROJECT_DIR/logs/agent_${INSTANCE_NAME}.log"
API_LOG_FILE="$PROJECT_DIR/logs/api_${INSTANCE_NAME}.log"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$STATE_DIR"

# Load project .env first (base defaults)
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Load secrets SECOND so real keys override placeholders in .env
SECRETS_FILE="$HOME/.config/pearlalgo/secrets.env"
if [ -f "$SECRETS_FILE" ]; then
    set -a
    source "$SECRETS_FILE"
    set +a
fi

# Environment for the Tradovate Paper instance
export PEARLALGO_MARKET="$MARKET"
export PEARLALGO_STATE_DIR="$STATE_DIR"
export API_PORT="$API_PORT"

# Use unique IBKR client IDs to avoid clashing with IBKR Virtual agent (10/11)
export IBKR_CLIENT_ID=50
export IBKR_DATA_CLIENT_ID=51
export IB_CLIENT_ID_LIVE_CHART=97

# New parameterized config path
export PEARLALGO_CONFIG_PATH="$CONFIG_FILE"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

activate_venv() {
    if [ -f .venv/bin/activate ]; then
        source .venv/bin/activate
    else
        echo "Warning: No virtual environment found at .venv/bin/activate"
    fi
}

get_python() {
    if [ -f .venv/bin/python3 ]; then
        echo ".venv/bin/python3"
    else
        which python3
    fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

if [ "$COMMAND" = "status" ]; then
    AGENT_UP=false
    API_UP=false

    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            AGENT_UP=true
        fi
    fi

    if [ -f "$API_PID_FILE" ]; then
        PID=$(cat "$API_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            API_UP=true
        fi
    fi

    if $AGENT_UP && $API_UP; then
        echo "Agent: running | API (:${API_PORT}): running | State: $STATE_DIR"
        exit 0
    elif $AGENT_UP; then
        echo "Agent: running | API (:${API_PORT}): stopped | State: $STATE_DIR"
        exit 0
    elif $API_UP; then
        echo "Agent: stopped | API (:${API_PORT}): running | State: $STATE_DIR"
        exit 0
    else
        echo "Tradovate Paper instance not running"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Helper: kill any process holding our API port (prevents stale ghost servers)
# ---------------------------------------------------------------------------
kill_port_holders() {
    local PORT="$1"
    local PIDS
    PIDS=$(ss -tlnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | sort -u || true)
    if [ -z "$PIDS" ]; then
        # Fallback: lsof
        PIDS=$(lsof -ti ":${PORT}" 2>/dev/null | sort -u || true)
    fi
    if [ -n "$PIDS" ]; then
        for P in $PIDS; do
            echo "  Killing stale process on port $PORT (PID: $P)"
            kill "$P" 2>/dev/null || true
        done
        sleep 2
        # Force-kill survivors
        for P in $PIDS; do
            if ps -p "$P" > /dev/null 2>&1; then
                kill -9 "$P" 2>/dev/null || true
            fi
        done
    fi
}

# ---------------------------------------------------------------------------
# Helper: full stop (PID files + port cleanup + orphans)
# ---------------------------------------------------------------------------
do_stop() {
    local STOPPED=false

    # 1. Kill processes from PID files
    for PF in "$PID_FILE" "$API_PID_FILE"; do
        if [ -f "$PF" ]; then
            PID=$(cat "$PF")
            if ps -p "$PID" > /dev/null 2>&1; then
                kill "$PID" 2>/dev/null || true
                sleep 2
                if ps -p "$PID" > /dev/null 2>&1; then
                    kill -9 "$PID" 2>/dev/null || true
                fi
                STOPPED=true
            fi
            rm -f "$PF"
        fi
    done

    # 2. Kill anything still holding our API port (catches manually started servers)
    kill_port_holders "$API_PORT"

    # 3. Kill orphan agent processes for this state dir
    local ORPHAN_PIDS=""
    ORPHAN_PIDS=$(pgrep -f "pearlalgo.market_agent.main" 2>/dev/null || true)
    for OPID in $ORPHAN_PIDS; do
        local PROC_ENV=""
        PROC_ENV=$(cat /proc/$OPID/environ 2>/dev/null | tr '\0' '\n' | grep "PEARLALGO_STATE_DIR" || true)
        if echo "$PROC_ENV" | grep -q "TV_PAPER_EVAL" 2>/dev/null; then
            echo "  Killing orphan Tradovate Paper agent (PID: $OPID)"
            kill "$OPID" 2>/dev/null || true
            sleep 1
            kill -9 "$OPID" 2>/dev/null || true
            STOPPED=true
        fi
    done

    echo "$STOPPED"
}

if [ "$COMMAND" = "stop" ]; then
    RESULT=$(do_stop)
    if [ "$RESULT" = "true" ]; then
        echo "Tradovate Paper instance stopped"
        exit 0
    fi
    echo "Tradovate Paper instance not running"
    exit 0
fi

# ---------------------------------------------------------------------------
# Restart command: stop everything, then start
# ---------------------------------------------------------------------------
if [ "$COMMAND" = "restart" ]; then
    echo "Restarting Tradovate Paper instance..."
    do_stop > /dev/null
    sleep 1
    # Fall through to start
    COMMAND="start"
fi

if [ "$COMMAND" = "api" ]; then
    # Start only the API server (for viewing data without running the agent)
    activate_venv
    PYTHON_CMD=$(get_python)

    # Clear any stale process on our port first
    kill_port_holders "$API_PORT"
    rm -f "$API_PID_FILE"

    echo "Starting Tradovate Paper API Server"
    echo "  State dir: $STATE_DIR"
    echo "  Port:      $API_PORT"
    echo "  Market:    $MARKET"
    echo "  IBKR chart client ID: $IB_CLIENT_ID_LIVE_CHART"

    if [ "$BACKGROUND_MODE" = true ]; then
        nohup "$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
            --data-dir "$STATE_DIR" --port "$API_PORT" >> "$API_LOG_FILE" 2>&1 &
        API_PID=$!
        echo $API_PID > "$API_PID_FILE"
        echo "API server started in background (PID: $API_PID)"
        echo "  Log: $API_LOG_FILE"
        echo "  Web: http://localhost:3000?api_port=$API_PORT"
        exit 0
    fi

    "$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
        --data-dir "$STATE_DIR" --port "$API_PORT"
    exit 0
fi

if [ "$COMMAND" != "start" ]; then
    echo "Unknown command: $COMMAND"
    echo "Usage: $0 {start|stop|restart|status|api} [--background]"
    exit 1
fi

# ---------------------------------------------------------------------------
# Start command: launch agent + API server
# ---------------------------------------------------------------------------
activate_venv
PYTHON_CMD=$(get_python)

if ! "$PYTHON_CMD" -c "import pearlalgo" 2>/dev/null; then
    echo "ERROR: pearlalgo package not found. Run: pip install -e ."
    exit 1
fi

# Kill any stale processes before starting fresh
kill_port_holders "$API_PORT"

# Check for stale PID
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Tradovate Paper agent already running (PID: $PID). Use 'restart' to replace."
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi
rm -f "$API_PID_FILE"

echo "Starting Tradovate Paper Instance"
echo "  State dir:  $STATE_DIR"
echo "  API port:   $API_PORT"
echo "  Market:     $MARKET"
echo "  Config:     $PEARLALGO_CONFIG_PATH"
echo "  Web app:    http://localhost:3000?api_port=$API_PORT"

if [ "$BACKGROUND_MODE" = true ]; then
    # Start API server in background
    nohup "$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
        --data-dir "$STATE_DIR" --port "$API_PORT" >> "$API_LOG_FILE" 2>&1 &
    API_PID=$!
    echo $API_PID > "$API_PID_FILE"
    echo "  API server PID: $API_PID"

    # Start agent in background
    if [ -f "$LOG_FILE" ] && [ -s "$LOG_FILE" ]; then
        mv "$LOG_FILE" "${LOG_FILE}.1"
    fi
    nohup "$PYTHON_CMD" -m pearlalgo.market_agent.main \
        --config "$CONFIG_FILE" --data-dir "$STATE_DIR" >> "$LOG_FILE" 2>&1 &
    AGENT_PID=$!
    echo $AGENT_PID > "$PID_FILE"
    echo "  Agent PID:      $AGENT_PID"
    echo "Tradovate Paper instance started in background"
    exit 0
fi

# Foreground: start API server in background, agent in foreground
"$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
    --data-dir "$STATE_DIR" --port "$API_PORT" >> "$API_LOG_FILE" 2>&1 &
API_PID=$!
echo $API_PID > "$API_PID_FILE"
echo "  API server started (PID: $API_PID)"

echo "=== Starting Tradovate Paper Agent (Foreground) ==="
echo "  Press Ctrl+C to stop"

"$PYTHON_CMD" -m pearlalgo.market_agent.main \
    --config "$CONFIG_FILE" --data-dir "$STATE_DIR" &
AGENT_PID=$!
echo $AGENT_PID > "$PID_FILE"

# Clean up API server when agent exits
trap "kill $API_PID 2>/dev/null; rm -f $API_PID_FILE $PID_FILE" EXIT

wait $AGENT_PID
