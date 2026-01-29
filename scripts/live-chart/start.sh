#!/bin/bash
# ============================================================================
# PEARL Live Main Chart Startup Script
# 
# Launches the API server and TradingView chart web interface.
# 
# Usage:
#   ./scripts/live-chart/start.sh [--market NQ] [--install]
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHART_DIR="$PROJECT_ROOT/live-chart"
LOG_DIR="$PROJECT_ROOT/logs"

MARKET="${PEARLALGO_MARKET:-NQ}"
API_PORT="${PEARL_API_PORT:-8000}"
CHART_PORT="${PEARL_CHART_PORT:-3000}"
INSTALL_DEPS=false
API_ONLY=false
CHART_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --market) MARKET="$2"; shift 2 ;;
        --install) INSTALL_DEPS=true; shift ;;
        --api-only) API_ONLY=true; shift ;;
        --chart-only) CHART_ONLY=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

echo "========================================"
echo "  PEARL Live Main Chart"
echo "========================================"
echo ""
echo "  Market:     $MARKET"
echo "  API Port:   $API_PORT"
echo "  Chart URL:  http://localhost:$CHART_PORT"
echo ""

# Install deps if needed
if [[ "$INSTALL_DEPS" == "true" ]] && [[ -d "$CHART_DIR" ]]; then
    echo "Installing dependencies..."
    cd "$CHART_DIR" && npm install
    cd "$PROJECT_ROOT"
fi

if [[ "$CHART_ONLY" == "false" ]] && [[ ! -d "$CHART_DIR/node_modules" ]]; then
    echo "Installing chart dependencies..."
    cd "$CHART_DIR" && npm install
    cd "$PROJECT_ROOT"
fi

cleanup() {
    echo ""
    echo "Shutting down..."
    [[ -n "$API_PID" ]] && kill $API_PID 2>/dev/null || true
    [[ -n "$CHART_PID" ]] && kill $CHART_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start API server
if [[ "$CHART_ONLY" == "false" ]]; then
    echo "Starting API server..."
    cd "$PROJECT_ROOT"
    python scripts/live-chart/api_server.py --market "$MARKET" --port "$API_PORT" > "$LOG_DIR/live_chart_api.log" 2>&1 &
    API_PID=$!
    echo "  API PID: $API_PID"
    sleep 2
fi

# Start chart web interface
if [[ "$API_ONLY" == "false" ]]; then
    echo "Starting Live Main Chart..."
    cd "$CHART_DIR"
    PORT=$CHART_PORT npm run dev > "$LOG_DIR/live_chart_web.log" 2>&1 &
    CHART_PID=$!
    echo "  Chart PID: $CHART_PID"
    cd "$PROJECT_ROOT"
    sleep 3
fi

echo ""
echo "========================================"
echo "  Live Main Chart is running!"
echo "========================================"
echo ""
echo "  Open: http://localhost:$CHART_PORT"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

wait
