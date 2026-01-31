#!/bin/bash
# Live Chart Development Helper
# Usage: ./dev.sh [command] [options]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default port (can override with API_PORT env var)
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

case "$1" in
    start|api)
        # Start API server with auto-reload
        echo -e "${GREEN}Starting API server on port $API_PORT with auto-reload...${NC}"
        cd "$PROJECT_ROOT"
        pkill -f "api_server.py" 2>/dev/null
        sleep 1
        python scripts/live-chart/api_server.py --port "$API_PORT" --reload
        ;;

    start-prod|api-prod)
        # Start API server without reload (production mode)
        echo -e "${GREEN}Starting API server on port $API_PORT (production mode)...${NC}"
        cd "$PROJECT_ROOT"
        pkill -f "api_server.py" 2>/dev/null
        sleep 1
        python scripts/live-chart/api_server.py --port "$API_PORT"
        ;;

    frontend|fe)
        # Start frontend dev server
        echo -e "${GREEN}Starting frontend on port $FRONTEND_PORT...${NC}"
        cd "$PROJECT_ROOT/live-chart"
        npm run dev:fresh
        ;;

    both|all)
        # Start both API and frontend
        echo -e "${GREEN}Starting both API and frontend...${NC}"
        cd "$PROJECT_ROOT"
        pkill -f "api_server.py" 2>/dev/null
        pkill -f "next dev" 2>/dev/null
        sleep 1

        # Start API in background
        python scripts/live-chart/api_server.py --port "$API_PORT" --reload &
        API_PID=$!
        echo -e "${GREEN}API started (PID: $API_PID)${NC}"

        sleep 2

        # Start frontend
        cd "$PROJECT_ROOT/live-chart"
        npm run dev
        ;;

    stop)
        # Stop all servers
        echo -e "${YELLOW}Stopping servers...${NC}"
        pkill -f "api_server.py" 2>/dev/null && echo "API stopped" || echo "API not running"
        pkill -f "next dev" 2>/dev/null && echo "Frontend stopped" || echo "Frontend not running"
        echo -e "${GREEN}Done${NC}"
        ;;

    restart)
        # Restart API server
        echo -e "${YELLOW}Restarting API server...${NC}"
        pkill -f "api_server.py" 2>/dev/null
        sleep 2
        cd "$PROJECT_ROOT"
        python scripts/live-chart/api_server.py --port "$API_PORT" --reload
        ;;

    status)
        # Check status of servers
        echo -e "${YELLOW}Server Status:${NC}"
        if pgrep -f "api_server.py" > /dev/null; then
            echo -e "  API:      ${GREEN}RUNNING${NC} (port $API_PORT)"
        else
            echo -e "  API:      ${RED}STOPPED${NC}"
        fi
        if pgrep -f "next dev" > /dev/null; then
            echo -e "  Frontend: ${GREEN}RUNNING${NC} (port $FRONTEND_PORT)"
        else
            echo -e "  Frontend: ${RED}STOPPED${NC}"
        fi
        ;;

    port)
        # Change API port
        if [ -z "$2" ]; then
            echo "Current API_PORT: $API_PORT"
            echo "Usage: ./dev.sh port <port_number>"
        else
            export API_PORT="$2"
            echo -e "${GREEN}API_PORT set to $2${NC}"
            echo "Run './dev.sh restart' to apply"
        fi
        ;;

    logs)
        # Show recent logs
        echo -e "${YELLOW}Tailing logs...${NC}"
        tail -f "$PROJECT_ROOT/logs/"*.log 2>/dev/null || echo "No log files found"
        ;;

    *)
        echo "Live Chart Development Helper"
        echo ""
        echo "Usage: ./dev.sh <command>"
        echo ""
        echo "Commands:"
        echo "  start, api      Start API with auto-reload (development)"
        echo "  api-prod        Start API without reload (production)"
        echo "  frontend, fe    Start frontend dev server"
        echo "  both, all       Start both API and frontend"
        echo "  stop            Stop all servers"
        echo "  restart         Restart API server"
        echo "  status          Check server status"
        echo "  port <num>      Set API port (default: 8000)"
        echo "  logs            Tail log files"
        echo ""
        echo "Environment Variables:"
        echo "  API_PORT        API server port (default: 8000)"
        echo "  FRONTEND_PORT   Frontend port (default: 3001)"
        echo ""
        echo "Examples:"
        echo "  ./dev.sh start              # Start API with reload"
        echo "  API_PORT=8001 ./dev.sh start  # Start on port 8001"
        echo "  ./dev.sh both               # Start everything"
        ;;
esac
