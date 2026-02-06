#!/bin/bash
# ============================================================================
# PEARL Master Control Script
# Purpose: Unified start/stop/restart/status for all PEARL services
# Usage:
#   ./pearl.sh start       Start all services (Gateway → Agent → Telegram)
#   ./pearl.sh stop        Stop all services gracefully
#   ./pearl.sh restart     Restart all services
#   ./pearl.sh status      Show status of all services
#   ./pearl.sh quick       Quick status (one-liner per service)
#
# Individual service control:
#   ./pearl.sh gateway start|stop|status
#   ./pearl.sh agent start|stop|status
#   ./pearl.sh telegram start|stop|status
#
# Options:
#   --market NQ|ES|GC    Market to trade (default: NQ)
#   --no-telegram        Skip Telegram handler
#   --foreground         Run agent in foreground (for debugging)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
MARKET="${PEARL_MARKET:-NQ}"
NO_TELEGRAM=false
NO_CHART=false
FOREGROUND=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Parse global options
parse_options() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --market)
                MARKET="${2:-NQ}"
                shift 2
                ;;
            --no-telegram)
                NO_TELEGRAM=true
                shift
                ;;
            --no-chart)
                NO_CHART=true
                shift
                ;;
            --foreground|-f)
                FOREGROUND=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done
}

# Load env files (non-sensitive + secrets)
load_env_files() {
    set -a
    [ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
    local secrets_file="$HOME/.config/pearlalgo/secrets.env"
    [ -f "$secrets_file" ] && source "$secrets_file"
    set +a

    if [ -n "${PEARL_API_KEY:-}" ] && [ -z "${NEXT_PUBLIC_API_KEY:-}" ]; then
        export NEXT_PUBLIC_API_KEY="$PEARL_API_KEY"
    fi
}

# Activate virtual environment
activate_venv() {
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    else
        echo -e "${RED}❌ Virtual environment not found. Run: python3 -m venv .venv${NC}"
        exit 1
    fi
}

# ============================================================================
# Status Functions
# ============================================================================

check_gateway_status() {
    if ./scripts/gateway/gateway.sh api-ready &>/dev/null; then
        echo -e "${GREEN}●${NC} Gateway"
    else
        echo -e "${RED}●${NC} Gateway"
        return 1
    fi
}

check_agent_status() {
    local pidfile="$SCRIPT_DIR/logs/agent_$MARKET.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        local pid=$(cat "$pidfile")
        local uptime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
        echo -e "${GREEN}●${NC} Agent ($MARKET) - PID $pid, uptime: $uptime"
    else
        echo -e "${RED}●${NC} Agent ($MARKET)"
        return 1
    fi
}

check_telegram_status() {
    local pidfile="$SCRIPT_DIR/logs/telegram_handler.pid"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        local pid=$(cat "$pidfile")
        echo -e "${GREEN}●${NC} Telegram - PID $pid"
    else
        echo -e "${RED}●${NC} Telegram"
        return 1
    fi
}

check_chart_status() {
    # Check if API server and Next.js are running
    local api_running=$(pgrep -f "api_server.py" &>/dev/null && echo "yes" || echo "no")
    local chart_running=$(pgrep -f "next" &>/dev/null && echo "yes" || echo "no")
    
    if [ "$api_running" = "yes" ] && [ "$chart_running" = "yes" ]; then
        echo -e "${GREEN}●${NC} Web App - API + Web running"
    elif [ "$api_running" = "yes" ]; then
        echo -e "${YELLOW}●${NC} Web App - API only"
        return 1
    elif [ "$chart_running" = "yes" ]; then
        echo -e "${YELLOW}●${NC} Web App - Web only (no API)"
        return 1
    else
        echo -e "${RED}●${NC} Web App"
        return 1
    fi
}

check_mffu_status() {
    local pidfile="$SCRIPT_DIR/logs/agent_MFFU_EVAL.pid"
    local api_ok=$(curl -s http://localhost:8001/health 2>/dev/null | grep -c "ok" || echo 0)
    
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        local pid=$(cat "$pidfile")
        local uptime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
        local api_label=""
        [ "$api_ok" -gt 0 ] && api_label=" | API :8001" || api_label=" | API down"
        echo -e "${GREEN}●${NC} MFFU Eval - PID $pid, uptime: $uptime$api_label"
    elif [ "$api_ok" -gt 0 ]; then
        echo -e "${YELLOW}●${NC} MFFU Eval - API only (agent stopped)"
    else
        echo -e "${RED}●${NC} MFFU Eval"
        return 1
    fi
}

check_tunnel_status() {
    # Check if cloudflared tunnel is running (either as service or process)
    if systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null; then
        echo -e "${GREEN}●${NC} Tunnel (systemd) - pearlalgo.io"
    elif pgrep -f "cloudflared.*tunnel run" &>/dev/null; then
        echo -e "${GREEN}●${NC} Tunnel (manual) - pearlalgo.io"
    else
        echo -e "${RED}●${NC} Tunnel - pearlalgo.io unreachable"
        return 1
    fi
}

check_api_status() {
    load_env_files
    local header=()
    if [ -n "${PEARL_API_KEY:-}" ]; then
        header=(-H "X-API-Key: $PEARL_API_KEY")
    fi
    if curl -s "${header[@]}" "http://localhost:8000/api/state" &>/dev/null; then
        local data=$(curl -s "${header[@]}" "http://localhost:8000/api/state")
        local pnl=$(echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('daily_pnl', 0):+.2f}\")" 2>/dev/null || echo "N/A")
        local trades=$(echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('daily_wins',0)}W/{d.get('daily_losses',0)}L\")" 2>/dev/null || echo "N/A")
        echo -e "${GREEN}●${NC} API - P&L: \$$pnl | Trades: $trades"
    else
        echo -e "${RED}●${NC} API"
        return 1
    fi
}

# Full status display
show_status() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║       🐚 PEARL System Status         ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
    echo ""
    
    activate_venv
    
    echo -e "${CYAN}Services:${NC}"
    check_gateway_status || true
    check_agent_status || true
    check_mffu_status || true
    check_telegram_status || true
    check_chart_status || true
    check_tunnel_status || true
    echo ""
    
    echo -e "${CYAN}Data:${NC}"
    check_api_status || true
    echo ""
}

# Quick one-liner status
show_quick_status() {
    activate_venv
    
    local gw_status=$(./scripts/gateway/gateway.sh api-ready &>/dev/null && echo "✅" || echo "❌")
    local agent_pid_file="$SCRIPT_DIR/logs/agent_$MARKET.pid"
    local agent_status=$([ -f "$agent_pid_file" ] && kill -0 "$(cat "$agent_pid_file")" 2>/dev/null && echo "✅" || echo "❌")
    local tg_pid_file="$SCRIPT_DIR/logs/telegram_handler.pid"
    local tg_status=$([ -f "$tg_pid_file" ] && kill -0 "$(cat "$tg_pid_file")" 2>/dev/null && echo "✅" || echo "❌")
    local mffu_pid_file="$SCRIPT_DIR/logs/agent_MFFU_EVAL.pid"
    local mffu_status=$([ -f "$mffu_pid_file" ] && kill -0 "$(cat "$mffu_pid_file")" 2>/dev/null && echo "✅" || echo "❌")
    local chart_status=$(pgrep -f "api_server.py" &>/dev/null && pgrep -f "next" &>/dev/null && echo "✅" || echo "❌")
    local tunnel_status=$( (systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null || pgrep -f "cloudflared.*tunnel run" &>/dev/null) && echo "✅" || echo "❌")
    
    echo -e "PEARL: GW $gw_status | Agent $agent_status | MFFU $mffu_status | TG $tg_status | Chart $chart_status | Tunnel $tunnel_status"
}

# ============================================================================
# Start Functions
# ============================================================================

start_gateway() {
    echo -e "${CYAN}▶ Starting IB Gateway...${NC}"
    if ./scripts/gateway/gateway.sh api-ready &>/dev/null; then
        echo -e "${YELLOW}   Already running${NC}"
    else
        ./scripts/gateway/gateway.sh start
    fi
    echo ""
}

start_agent() {
    echo -e "${CYAN}▶ Starting Market Agent ($MARKET)...${NC}"
    if [ "$FOREGROUND" = true ]; then
        ./scripts/lifecycle/agent.sh start --market "$MARKET"
    else
        ./scripts/lifecycle/agent.sh start --market "$MARKET" --background
    fi
    echo ""
}

start_telegram() {
    if [ "$NO_TELEGRAM" = true ]; then
        echo -e "${YELLOW}⏭ Skipping Telegram (--no-telegram)${NC}"
        return
    fi
    echo -e "${CYAN}▶ Starting Telegram Handler...${NC}"
    ./scripts/telegram/restart_command_handler.sh --background
    echo ""
}

start_chart() {
    if [ "$NO_CHART" = true ]; then
        echo -e "${YELLOW}⏭ Skipping Web App (--no-chart)${NC}"
        return
    fi

    # Check if already running
    if pgrep -f "api_server.py" &>/dev/null && pgrep -f "next" &>/dev/null; then
        echo -e "${YELLOW}⏭ Web App already running${NC}"
        return
    fi

    echo -e "${CYAN}▶ Starting Web App (pearlalgo.io)...${NC}"

    load_env_files

    local LOG_DIR="$SCRIPT_DIR/logs"
    local CHART_DIR="$SCRIPT_DIR/pearlalgo_web_app"
    local API_PORT="${PEARL_API_PORT:-8000}"
    local CHART_PORT="${PEARL_CHART_PORT:-3001}"

    # Start API server
    if ! pgrep -f "api_server.py" &>/dev/null; then
        python3 scripts/pearlalgo_web_app/api_server.py --market "$MARKET" --port "$API_PORT" > "$LOG_DIR/web_app_api.log" 2>&1 &
        echo "   API server started (port $API_PORT)"
    fi

    # Start web interface
    if ! pgrep -f "next" &>/dev/null; then
        cd "$CHART_DIR"
        PORT=$CHART_PORT npm run dev > "$LOG_DIR/web_app.log" 2>&1 &
        cd "$SCRIPT_DIR"
        echo "   Chart web started (port $CHART_PORT)"
    fi
    
    echo "   URL: http://localhost:$CHART_PORT"
    echo "   Public: https://pearlalgo.io"
    echo ""
}

start_tunnel() {
    # Check if already running (systemd or manual)
    if systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null; then
        echo -e "${YELLOW}⏭ Tunnel already running (systemd)${NC}"
        return
    fi
    if pgrep -f "cloudflared.*tunnel run" &>/dev/null; then
        echo -e "${YELLOW}⏭ Tunnel already running (manual)${NC}"
        return
    fi
    
    echo -e "${CYAN}▶ Starting Cloudflare Tunnel...${NC}"
    
    # Try systemd first (preferred)
    if systemctl start cloudflared-pearlalgo 2>/dev/null; then
        echo "   Tunnel started (systemd)"
        return
    fi
    
    # Fall back to manual start
    local LOG_DIR="$SCRIPT_DIR/logs"
    mkdir -p "$LOG_DIR"
    nohup cloudflared --config "$HOME/.cloudflared/config.yml" tunnel run > "$LOG_DIR/cloudflared.log" 2>&1 &
    sleep 2
    if pgrep -f "cloudflared.*tunnel run" &>/dev/null; then
        echo "   Tunnel started (manual)"
        echo -e "   ${YELLOW}Tip: Run 'sudo ./scripts/setup-cloudflared-service.sh' to auto-start on boot${NC}"
    else
        echo -e "${RED}   Failed to start tunnel${NC}"
    fi
    echo ""
}

start_all() {
    echo ""
    echo -e "${BOLD}🐚 Starting PEARL System...${NC}"
    echo -e "${BOLD}═══════════════════════════${NC}"
    echo ""
    
    activate_venv
    
    # Start in dependency order
    start_gateway
    sleep 2
    start_agent
    sleep 2
    start_telegram
    sleep 1
    start_chart
    sleep 1
    start_tunnel
    
    echo -e "${GREEN}${BOLD}✅ PEARL System Started${NC}"
    echo ""
    show_quick_status
}

# ============================================================================
# Stop Functions
# ============================================================================

stop_agent() {
    echo -e "${CYAN}■ Stopping Market Agent ($MARKET)...${NC}"
    ./scripts/lifecycle/agent.sh stop --market "$MARKET" 2>/dev/null || true
    echo ""
}

stop_telegram() {
    echo -e "${CYAN}■ Stopping Telegram Handler...${NC}"
    local pidfile="$SCRIPT_DIR/logs/telegram_handler.pid"
    if [ -f "$pidfile" ]; then
        local pid=$(cat "$pidfile")
        kill "$pid" 2>/dev/null || true
        rm -f "$pidfile"
        echo "   Stopped PID $pid"
    else
        echo "   Not running"
    fi
    echo ""
}

stop_chart() {
    echo -e "${CYAN}■ Stopping Web App...${NC}"
    pkill -f "api_server.py" 2>/dev/null && echo "   Stopped API server" || echo "   API server not running"
    pkill -f "next-server" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null && echo "   Stopped web app" || echo "   Web app not running"
    echo ""
}

stop_tunnel() {
    echo -e "${CYAN}■ Stopping Cloudflare Tunnel...${NC}"
    # Note: If running as systemd service, we DON'T stop it (it should always run)
    if systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null; then
        echo "   Tunnel running as systemd service (not stopping - always on)"
    elif pgrep -f "cloudflared.*tunnel run" &>/dev/null; then
        pkill -f "cloudflared.*tunnel run" 2>/dev/null && echo "   Stopped manual tunnel" || echo "   Failed to stop"
    else
        echo "   Not running"
    fi
    echo ""
}

stop_gateway() {
    echo -e "${CYAN}■ Stopping IB Gateway...${NC}"
    ./scripts/gateway/gateway.sh stop 2>/dev/null || true
    echo ""
}

stop_all() {
    echo ""
    echo -e "${BOLD}🐚 Stopping PEARL System...${NC}"
    echo -e "${BOLD}═══════════════════════════${NC}"
    echo ""
    
    activate_venv
    
    # Stop in reverse dependency order
    stop_tunnel
    stop_chart
    stop_agent
    stop_telegram
    stop_gateway
    
    echo -e "${GREEN}${BOLD}✅ PEARL System Stopped${NC}"
    echo ""
}

# ============================================================================
# Restart Function
# ============================================================================

restart_all() {
    echo ""
    echo -e "${BOLD}🐚 Restarting PEARL System...${NC}"
    echo -e "${BOLD}════════════════════════════${NC}"
    echo ""
    
    stop_all
    sleep 3
    start_all
}

# ============================================================================
# Individual Service Control
# ============================================================================

handle_gateway() {
    local subcmd="${1:-status}"
    activate_venv
    case "$subcmd" in
        start)
            start_gateway
            ;;
        stop)
            stop_gateway
            ;;
        status)
            ./scripts/gateway/gateway.sh status
            ;;
        *)
            ./scripts/gateway/gateway.sh "$subcmd"
            ;;
    esac
}

handle_agent() {
    local subcmd="${1:-status}"
    activate_venv
    case "$subcmd" in
        start)
            start_agent
            ;;
        stop)
            stop_agent
            ;;
        status)
            ./scripts/lifecycle/check_agent_status.sh --market "$MARKET"
            ;;
        *)
            echo "Unknown agent command: $subcmd"
            ;;
    esac
}

handle_telegram() {
    local subcmd="${1:-status}"
    activate_venv
    case "$subcmd" in
        start)
            start_telegram
            ;;
        stop)
            stop_telegram
            ;;
        status)
            check_telegram_status || echo "   Not running"
            ;;
        restart)
            stop_telegram
            start_telegram
            ;;
        *)
            echo "Unknown telegram command: $subcmd"
            ;;
    esac
}

handle_chart() {
    local subcmd="${1:-status}"
    activate_venv
    case "$subcmd" in
        start)
            start_chart
            ;;
        stop)
            stop_chart
            ;;
        status)
            check_chart_status || echo "   Not running"
            ;;
        restart)
            stop_chart
            sleep 2
            start_chart
            ;;
        *)
            echo "Unknown chart command: $subcmd"
            ;;
    esac
}

handle_mffu() {
    local subcmd="${1:-status}"
    activate_venv
    load_env_files
    case "$subcmd" in
        start)
            echo -e "${CYAN}▶ Starting MFFU Eval...${NC}"
            ./scripts/lifecycle/mffu_eval.sh start --background
            ;;
        stop)
            echo -e "${CYAN}■ Stopping MFFU Eval...${NC}"
            ./scripts/lifecycle/mffu_eval.sh stop
            ;;
        status)
            check_mffu_status || echo "   Not running"
            ;;
        restart)
            echo -e "${CYAN}🔄 Restarting MFFU Eval...${NC}"
            ./scripts/lifecycle/mffu_eval.sh stop 2>/dev/null || true
            sleep 3
            ./scripts/lifecycle/mffu_eval.sh start --background
            ;;
        api)
            echo -e "${CYAN}▶ Starting MFFU API only...${NC}"
            ./scripts/lifecycle/mffu_eval.sh api --background
            ;;
        logs)
            tail -f "$SCRIPT_DIR/logs/agent_MFFU_EVAL.log"
            ;;
        *)
            echo "Usage: ./pearl.sh mffu <start|stop|status|restart|api|logs>"
            ;;
    esac
}

handle_tunnel() {
    local subcmd="${1:-status}"
    case "$subcmd" in
        start)
            start_tunnel
            ;;
        stop)
            # Force stop even if systemd (for manual override)
            echo -e "${CYAN}■ Stopping Cloudflare Tunnel...${NC}"
            if systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null; then
                systemctl stop cloudflared-pearlalgo 2>/dev/null && echo "   Stopped systemd service" || echo "   Failed (need sudo?)"
            fi
            pkill -f "cloudflared.*tunnel run" 2>/dev/null && echo "   Stopped process" || true
            ;;
        status)
            check_tunnel_status || echo "   Not running"
            # Also check if publicly accessible
            echo -n "   Public access: "
            curl -s -o /dev/null -w "%{http_code}" --max-time 5 https://pearlalgo.io/ 2>/dev/null | grep -q "200" && echo "✅ https://pearlalgo.io" || echo "❌ unreachable"
            ;;
        restart)
            handle_tunnel stop
            sleep 2
            start_tunnel
            ;;
        setup)
            echo "Run: sudo ./scripts/setup-cloudflared-service.sh"
            ;;
        logs)
            if systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null; then
                journalctl -u cloudflared-pearlalgo -f --no-pager -n 50
            elif [ -f "$SCRIPT_DIR/logs/cloudflared.log" ]; then
                tail -f "$SCRIPT_DIR/logs/cloudflared.log"
            else
                echo "No logs available"
            fi
            ;;
        *)
            echo "Usage: ./pearl.sh tunnel <start|stop|status|restart|setup|logs>"
            ;;
    esac
}

# ============================================================================
# Help
# ============================================================================

show_help() {
    echo ""
    echo -e "${BOLD}🐚 PEARL Master Control${NC}"
    echo ""
    echo "Usage: ./pearl.sh <command> [options]"
    echo ""
    echo -e "${CYAN}Commands:${NC}"
    echo "  start       Start all services (Gateway → Agent → Telegram → Chart)"
    echo "  stop        Stop all services gracefully"
    echo "  restart     Restart all services"
    echo "  status      Show detailed status of all services"
    echo "  quick       Quick status (one-liner)"
    echo ""
    echo -e "${CYAN}Individual Services:${NC}"
    echo "  gateway <start|stop|status>    Control IB Gateway"
    echo "  agent <start|stop|status>      Control Market Agent (Inception)"
    echo "  mffu <start|stop|status|restart|api|logs>  Control MFFU Eval"
    echo "  telegram <start|stop|status>   Control Telegram Handler"
    echo "  chart <start|stop|status>      Control Web App (pearlalgo.io)"
    echo "  tunnel <start|stop|status|logs|setup>  Control Cloudflare Tunnel"
    echo ""
    echo -e "${CYAN}Options:${NC}"
    echo "  --market NQ|ES|GC    Market to trade (default: NQ)"
    echo "  --no-telegram        Skip Telegram handler"
    echo "  --no-chart           Skip Web App"
    echo "  --foreground         Run agent in foreground"
    echo ""
    echo -e "${CYAN}Examples:${NC}"
    echo "  ./pearl.sh start                    # Start everything"
    echo "  ./pearl.sh start --market ES        # Start for ES market"
    echo "  ./pearl.sh start --no-chart         # Start without Web App"
    echo "  ./pearl.sh restart                  # Restart everything"
    echo "  ./pearl.sh chart restart            # Restart just Web App"
    echo "  ./pearl.sh tunnel status            # Check tunnel + public access"
    echo "  ./pearl.sh tunnel logs              # View tunnel logs"
    echo "  ./pearl.sh status                   # Check all services"
    echo ""
}

# ============================================================================
# Main
# ============================================================================

COMMAND="${1:-help}"
shift || true

# Parse remaining args for options
parse_options "$@"

case "$COMMAND" in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        restart_all
        ;;
    status)
        show_status
        ;;
    quick)
        show_quick_status
        ;;
    gateway)
        handle_gateway "${1:-status}"
        ;;
    agent)
        handle_agent "${1:-status}"
        ;;
    telegram)
        handle_telegram "${1:-status}"
        ;;
    chart)
        handle_chart "${1:-status}"
        ;;
    mffu)
        handle_mffu "${1:-status}"
        ;;
    tunnel)
        handle_tunnel "${1:-status}"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        show_help
        exit 1
        ;;
esac
