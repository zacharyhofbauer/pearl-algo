#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Start/Stop/Status for market-specific agent instances
# Usage:
#   ./scripts/lifecycle/agent.sh start --market NQ [--background]
#   ./scripts/lifecycle/agent.sh stop --market NQ
#   ./scripts/lifecycle/agent.sh status --market NQ
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

COMMAND="${1:-}"
shift || true

MARKET=""
BACKGROUND_MODE=false
CONFIG_PATH=""
STATE_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --market)
            MARKET="${2:-}"
            shift 2
            ;;
        --background|-b)
            BACKGROUND_MODE=true
            shift 1
            ;;
        --config)
            CONFIG_PATH="${2:-}"
            shift 2
            ;;
        --state-dir)
            STATE_DIR="${2:-}"
            shift 2
            ;;
        *)
            shift 1
            ;;
    esac
done

if [ -z "$MARKET" ]; then
    echo "❌ Missing --market (e.g., NQ/ES/GC)"
    exit 1
fi

MARKET_UPPER="$(echo "$MARKET" | tr '[:lower:]' '[:upper:]')"
MARKET_LOWER="$(echo "$MARKET" | tr '[:upper:]' '[:lower:]')"

PID_FILE="$PROJECT_DIR/logs/agent_${MARKET_UPPER}.pid"
LOG_FILE="$PROJECT_DIR/logs/agent_${MARKET_UPPER}.log"

cd "$PROJECT_DIR"
mkdir -p "$PROJECT_DIR/logs"

if [ -z "$CONFIG_PATH" ]; then
    DEFAULT_CONFIG="$PROJECT_DIR/config/accounts/tradovate_paper.yaml"
    if [ -f "$DEFAULT_CONFIG" ]; then
        CONFIG_PATH="$DEFAULT_CONFIG"
    else
        CONFIG_PATH="$PROJECT_DIR/config/base.yaml"
    fi
fi

if [ -z "$STATE_DIR" ]; then
    STATE_DIR="$PROJECT_DIR/data/agent_state/${MARKET_UPPER}"
fi

export PEARLALGO_MARKET="$MARKET_UPPER"
export PEARLALGO_CONFIG_PATH="$CONFIG_PATH"
export PEARLALGO_STATE_DIR="$STATE_DIR"

# Assign default IBKR client IDs if not already set
if [ -z "${IBKR_CLIENT_ID:-}" ]; then
    case "$MARKET_UPPER" in
        NQ) IBKR_CLIENT_ID=10 ;;
        ES) IBKR_CLIENT_ID=20 ;;
        GC) IBKR_CLIENT_ID=30 ;;
        *) IBKR_CLIENT_ID=40 ;;
    esac
    export IBKR_CLIENT_ID
fi

if [ -z "${IBKR_DATA_CLIENT_ID:-}" ]; then
    case "$MARKET_UPPER" in
        NQ) IBKR_DATA_CLIENT_ID=11 ;;
        ES) IBKR_DATA_CLIENT_ID=21 ;;
        GC) IBKR_DATA_CLIENT_ID=31 ;;
        *) IBKR_DATA_CLIENT_ID=41 ;;
    esac
    export IBKR_DATA_CLIENT_ID
fi

if [ "$COMMAND" = "status" ]; then
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "🟢 Agent $MARKET_UPPER running (PID: $PID)"
            exit 0
        fi
    fi
    if pgrep -f "pearlalgo.market_agent.main" > /dev/null 2>&1; then
        echo "🟡 Agent process detected but PID file missing for $MARKET_UPPER"
        exit 0
    fi
    echo "🔴 Agent $MARKET_UPPER not running"
    exit 1
fi

if [ "$COMMAND" = "stop" ]; then
    STOPPED=false
    
    # First, try the PID file
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID" 2>/dev/null || true
            sleep 2
            if ps -p "$PID" > /dev/null 2>&1; then
                kill -9 "$PID" 2>/dev/null || true
            fi
            STOPPED=true
        fi
        rm -f "$PID_FILE"
    fi
    
    # Also kill orphan processes for THIS market only (check env/cmdline for state dir)
    # Avoids killing other market agents (e.g., TV_PAPER_EVAL when stopping NQ)
    ORPHAN_PIDS=$(pgrep -f "pearlalgo.market_agent.main" 2>/dev/null || true)
    if [ -n "$ORPHAN_PIDS" ]; then
        for OPID in $ORPHAN_PIDS; do
            # Only kill if this process belongs to our state dir
            PROC_ENV=$(cat /proc/$OPID/environ 2>/dev/null | tr '\0' '\n' | grep "PEARLALGO_STATE_DIR" || true)
            if echo "$PROC_ENV" | grep -q "$STATE_DIR" 2>/dev/null || [ -z "$PROC_ENV" ]; then
                echo "🧹 Killing orphan agent process (PID: $OPID)"
                kill "$OPID" 2>/dev/null || true
                sleep 1
                if ps -p "$OPID" > /dev/null 2>&1; then
                    kill -9 "$OPID" 2>/dev/null || true
                fi
                STOPPED=true
            fi
        done
    fi
    
    if [ "$STOPPED" = true ]; then
        echo "✅ Agent $MARKET_UPPER stopped"
        exit 0
    fi
    
    echo "⚠️  Agent $MARKET_UPPER not running (no PID file or processes found)"
    exit 1
fi

if [ "$COMMAND" != "start" ]; then
    echo "❌ Unknown command: $COMMAND (use start|stop|status)"
    exit 1
fi

if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ IBKR Gateway doesn't appear to be running"
    echo "   Start it with: ./scripts/gateway/gateway.sh start"
    exit 1
fi

# Pre-start cleanup: kill stale agent processes for THIS market only
# (avoids killing other market agents like TV_PAPER_EVAL when restarting NQ)
ORPHAN_PIDS=$(pgrep -f "pearlalgo.market_agent.main" 2>/dev/null || true)
CLEANED=false
if [ -n "$ORPHAN_PIDS" ]; then
    for OPID in $ORPHAN_PIDS; do
        # Only kill if this process belongs to our state dir (or has no identifiable state dir)
        PROC_ENV=$(cat /proc/$OPID/environ 2>/dev/null | tr '\0' '\n' | grep "PEARLALGO_STATE_DIR" || true)
        if echo "$PROC_ENV" | grep -q "$STATE_DIR" 2>/dev/null || [ -z "$PROC_ENV" ]; then
            echo "🧹 Killing stale agent (PID: $OPID)"
            kill "$OPID" 2>/dev/null || true
            sleep 1
            if ps -p "$OPID" > /dev/null 2>&1; then
                kill -9 "$OPID" 2>/dev/null || true
            fi
            CLEANED=true
        fi
    done
    if [ "$CLEANED" = true ]; then
        echo "   Waiting for IBKR connection cleanup..."
        sleep 3
    fi
fi

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ Agent $MARKET_UPPER already running (PID: $PID)"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# Activate virtual environment if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
else
    echo "⚠️  Warning: No virtual environment found at .venv/bin/activate"
    echo "   Make sure to install dependencies: pip install -e ."
fi

PYTHON_CMD=$(which python3)
if [ -f .venv/bin/python3 ]; then
    PYTHON_CMD=".venv/bin/python3"
fi

if ! "$PYTHON_CMD" -c "import pearlalgo" 2>/dev/null; then
    echo "❌ ERROR: pearlalgo package not found!"
    echo "   Install it with: pip install -e ."
    exit 1
fi

if [ "$BACKGROUND_MODE" = true ]; then
    if [ -f "$LOG_FILE" ] && [ -s "$LOG_FILE" ]; then
        mv "$LOG_FILE" "${LOG_FILE}.1"
        echo "📁 Rotated previous log to ${LOG_FILE}.1"
    fi
    nohup "$PYTHON_CMD" -m pearlalgo.market_agent.main --config "$CONFIG_PATH" --data-dir "$STATE_DIR" >> "$LOG_FILE" 2>&1 &
    SERVICE_PID=$!
    echo $SERVICE_PID > "$PID_FILE"
    echo "✅ Agent $MARKET_UPPER started in background (PID: $SERVICE_PID)"
    echo "   Log: $LOG_FILE"
    exit 0
fi

echo "=== Starting Agent $MARKET_UPPER (Foreground Mode) ==="
echo "   Press Ctrl+C to stop"
echo ""

"$PYTHON_CMD" -m pearlalgo.market_agent.main --config "$CONFIG_PATH" --data-dir "$STATE_DIR" &
SERVICE_PID=$!
echo $SERVICE_PID > "$PID_FILE"

wait $SERVICE_PID
