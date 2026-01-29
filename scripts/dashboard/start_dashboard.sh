#!/bin/bash
# ============================================================================
# PEARL Dashboard Startup Script
# 
# Launches both the API server and the Next.js dashboard.
# 
# Usage:
#   ./scripts/dashboard/start_dashboard.sh [--market NQ] [--install]
#
# Options:
#   --market MARKET   Market symbol (default: NQ)
#   --install         Install/update npm dependencies before starting
#   --api-only        Start only the API server
#   --dashboard-only  Start only the Next.js dashboard
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"
LOG_DIR="$PROJECT_ROOT/logs"

# Defaults
MARKET="${PEARLALGO_MARKET:-NQ}"
API_PORT="${PEARL_API_PORT:-8000}"
DASHBOARD_PORT="${PEARL_DASHBOARD_PORT:-3000}"
INSTALL_DEPS=false
API_ONLY=false
DASHBOARD_ONLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --market)
            MARKET="$2"
            shift 2
            ;;
        --install)
            INSTALL_DEPS=true
            shift
            ;;
        --api-only)
            API_ONLY=true
            shift
            ;;
        --dashboard-only)
            DASHBOARD_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  PEARL Dashboard Startup${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "  Market:    ${GREEN}$MARKET${NC}"
echo -e "  API Port:  ${GREEN}$API_PORT${NC}"
echo -e "  Dashboard: ${GREEN}http://localhost:$DASHBOARD_PORT${NC}"
echo ""

# Check if Node.js is installed (for dashboard)
if [[ "$DASHBOARD_ONLY" == "true" || "$API_ONLY" == "false" ]]; then
    if ! command -v node &> /dev/null; then
        echo -e "${RED}ERROR: Node.js not found. Please install Node.js 18+ first.${NC}"
        exit 1
    fi
    
    if ! command -v npm &> /dev/null; then
        echo -e "${RED}ERROR: npm not found. Please install npm first.${NC}"
        exit 1
    fi
fi

# Install dashboard dependencies if needed
if [[ "$INSTALL_DEPS" == "true" ]] && [[ -d "$DASHBOARD_DIR" ]]; then
    echo -e "${YELLOW}Installing dashboard dependencies...${NC}"
    cd "$DASHBOARD_DIR"
    npm install
    cd "$PROJECT_ROOT"
    echo -e "${GREEN}Dependencies installed.${NC}"
    echo ""
fi

# Check if dependencies are installed
if [[ "$API_ONLY" == "false" ]] && [[ ! -d "$DASHBOARD_DIR/node_modules" ]]; then
    echo -e "${YELLOW}Dashboard dependencies not installed. Running npm install...${NC}"
    cd "$DASHBOARD_DIR"
    npm install
    cd "$PROJECT_ROOT"
fi

# Function to cleanup background processes on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    if [[ -n "$API_PID" ]]; then
        kill $API_PID 2>/dev/null || true
    fi
    if [[ -n "$DASHBOARD_PID" ]]; then
        kill $DASHBOARD_PID 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start API server
if [[ "$DASHBOARD_ONLY" == "false" ]]; then
    echo -e "${GREEN}Starting API server on port $API_PORT...${NC}"
    cd "$PROJECT_ROOT"
    python scripts/dashboard/api_server.py --market "$MARKET" --port "$API_PORT" > "$LOG_DIR/dashboard_api.log" 2>&1 &
    API_PID=$!
    echo -e "  API PID: $API_PID"
    echo -e "  Log: $LOG_DIR/dashboard_api.log"
    
    # Wait for API to be ready
    sleep 2
    if ! kill -0 $API_PID 2>/dev/null; then
        echo -e "${RED}ERROR: API server failed to start. Check $LOG_DIR/dashboard_api.log${NC}"
        exit 1
    fi
fi

# Start Next.js dashboard
if [[ "$API_ONLY" == "false" ]]; then
    echo ""
    echo -e "${GREEN}Starting Next.js dashboard on port $DASHBOARD_PORT...${NC}"
    cd "$DASHBOARD_DIR"
    PORT=$DASHBOARD_PORT npm run dev > "$LOG_DIR/dashboard_nextjs.log" 2>&1 &
    DASHBOARD_PID=$!
    echo -e "  Dashboard PID: $DASHBOARD_PID"
    echo -e "  Log: $LOG_DIR/dashboard_nextjs.log"
    cd "$PROJECT_ROOT"
    
    # Wait for dashboard to be ready
    sleep 5
    if ! kill -0 $DASHBOARD_PID 2>/dev/null; then
        echo -e "${RED}ERROR: Dashboard failed to start. Check $LOG_DIR/dashboard_nextjs.log${NC}"
        cleanup
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Dashboard is running!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  Dashboard URL:  ${CYAN}http://localhost:$DASHBOARD_PORT${NC}"
echo -e "  API URL:        ${CYAN}http://localhost:$API_PORT${NC}"
echo ""
echo -e "  To enable Telegram screenshot capture:"
echo -e "    ${YELLOW}export PEARL_USE_DASHBOARD=1${NC}"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop."
echo ""

# Wait for processes
wait
