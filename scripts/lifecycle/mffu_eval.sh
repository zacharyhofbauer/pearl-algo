#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Start/Stop/Status for MFFU 50K Rapid Evaluation instance
#
# This script launches a separate Pearl agent + API server pair that:
#   - Writes state to data/agent_state/MFFU_EVAL/ (isolated from inception)
#   - Runs the API server on port 8001 (separate from inception on 8000)
#   - Uses Tradovate as the execution adapter (paper/demo)
#
# Usage:
#   ./scripts/lifecycle/mffu_eval.sh start [--background]
#   ./scripts/lifecycle/mffu_eval.sh stop
#   ./scripts/lifecycle/mffu_eval.sh status
#   ./scripts/lifecycle/mffu_eval.sh api [--background]   # API server only
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
# Fixed configuration for the MFFU Evaluation instance
# ---------------------------------------------------------------------------
INSTANCE_NAME="MFFU_EVAL"
MARKET="MNQ"
API_PORT=8001
STATE_DIR="$PROJECT_DIR/data/agent_state/${INSTANCE_NAME}"

PID_FILE="$PROJECT_DIR/logs/agent_${INSTANCE_NAME}.pid"
API_PID_FILE="$PROJECT_DIR/logs/api_${INSTANCE_NAME}.pid"
LOG_FILE="$PROJECT_DIR/logs/agent_${INSTANCE_NAME}.log"
API_LOG_FILE="$PROJECT_DIR/logs/api_${INSTANCE_NAME}.log"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$STATE_DIR"

# Load secrets (Tradovate credentials, API keys, etc.)
SECRETS_FILE="$HOME/.config/pearlalgo/secrets.env"
if [ -f "$SECRETS_FILE" ]; then
    set -a
    source "$SECRETS_FILE"
    set +a
fi

# Also load project .env if present
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Environment for the MFFU instance
export PEARLALGO_MARKET="$MARKET"
export PEARLALGO_STATE_DIR="$STATE_DIR"
export API_PORT="$API_PORT"

# Use unique IBKR client IDs to avoid clashing with inception agent (10/11)
export IBKR_CLIENT_ID=50
export IBKR_DATA_CLIENT_ID=51

# Use MFFU-specific config overlay if it exists, otherwise base config
if [ -f "$PROJECT_DIR/config/markets/mffu_eval.yaml" ]; then
    export PEARLALGO_CONFIG_PATH="$PROJECT_DIR/config/markets/mffu_eval.yaml"
else
    export PEARLALGO_CONFIG_PATH="$PROJECT_DIR/config/config.yaml"
fi

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
        echo "MFFU Eval instance not running"
        exit 1
    fi
fi

if [ "$COMMAND" = "stop" ]; then
    STOPPED=false

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

    if [ "$STOPPED" = true ]; then
        echo "MFFU Eval instance stopped"
        exit 0
    fi

    echo "MFFU Eval instance not running"
    exit 1
fi

if [ "$COMMAND" = "api" ]; then
    # Start only the API server (for viewing data without running the agent)
    activate_venv
    PYTHON_CMD=$(get_python)

    if [ -f "$API_PID_FILE" ]; then
        OLD_PID=$(cat "$API_PID_FILE")
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            echo "API server already running (PID: $OLD_PID)"
            exit 1
        fi
        rm -f "$API_PID_FILE"
    fi

    echo "Starting MFFU Eval API Server"
    echo "  State dir: $STATE_DIR"
    echo "  Port:      $API_PORT"
    echo "  Market:    $MARKET"

    if [ "$BACKGROUND_MODE" = true ]; then
        nohup "$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
            --market "$MARKET" --port "$API_PORT" >> "$API_LOG_FILE" 2>&1 &
        API_PID=$!
        echo $API_PID > "$API_PID_FILE"
        echo "API server started in background (PID: $API_PID)"
        echo "  Log: $API_LOG_FILE"
        echo "  Web: http://localhost:3000?api_port=$API_PORT"
        exit 0
    fi

    "$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
        --market "$MARKET" --port "$API_PORT"
    exit 0
fi

if [ "$COMMAND" != "start" ]; then
    echo "Unknown command: $COMMAND"
    echo "Usage: $0 {start|stop|status|api} [--background]"
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

# Check for stale PID
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "MFFU Eval agent already running (PID: $PID)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

echo "Starting MFFU Eval Instance"
echo "  State dir:  $STATE_DIR"
echo "  API port:   $API_PORT"
echo "  Market:     $MARKET"
echo "  Config:     $PEARLALGO_CONFIG_PATH"
echo "  Web app:    http://localhost:3000?api_port=$API_PORT"

if [ "$BACKGROUND_MODE" = true ]; then
    # Start API server in background
    nohup "$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
        --market "$MARKET" --port "$API_PORT" >> "$API_LOG_FILE" 2>&1 &
    API_PID=$!
    echo $API_PID > "$API_PID_FILE"
    echo "  API server PID: $API_PID"

    # Start agent in background
    if [ -f "$LOG_FILE" ] && [ -s "$LOG_FILE" ]; then
        mv "$LOG_FILE" "${LOG_FILE}.1"
    fi
    nohup "$PYTHON_CMD" -m pearlalgo.market_agent.main >> "$LOG_FILE" 2>&1 &
    AGENT_PID=$!
    echo $AGENT_PID > "$PID_FILE"
    echo "  Agent PID:      $AGENT_PID"
    echo "MFFU Eval instance started in background"
    exit 0
fi

# Foreground: start API server in background, agent in foreground
"$PYTHON_CMD" scripts/pearlalgo_web_app/api_server.py \
    --market "$MARKET" --port "$API_PORT" >> "$API_LOG_FILE" 2>&1 &
API_PID=$!
echo $API_PID > "$API_PID_FILE"
echo "  API server started (PID: $API_PID)"

echo "=== Starting MFFU Eval Agent (Foreground) ==="
echo "  Press Ctrl+C to stop"

"$PYTHON_CMD" -m pearlalgo.market_agent.main &
AGENT_PID=$!
echo $AGENT_PID > "$PID_FILE"

# Clean up API server when agent exits
trap "kill $API_PID 2>/dev/null; rm -f $API_PID_FILE $PID_FILE" EXIT

wait $AGENT_PID
