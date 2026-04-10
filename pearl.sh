#!/bin/bash
# ============================================================================
# PEARL Master Control Script
# Purpose: Unified start/stop/restart/status for all PEARL services
# Usage:
#   ./pearl.sh start       Start all services (Gateway → Tradovate Paper → Chart)
#   ./pearl.sh stop        Stop all services gracefully
#   ./pearl.sh restart     Restart all services
#   ./pearl.sh status      Show status of all services
#   ./pearl.sh quick       Quick status (one-liner per service)
#
# Individual service control:
#   ./pearl.sh gateway start|stop|status
#   ./pearl.sh agent start|stop|status
#
# Options:
#   --market MNQ         Market to trade (default: MNQ)
#   --foreground         Run agent in foreground (for debugging)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Defaults
MARKET="${PEARL_MARKET:-MNQ}"
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
                MARKET="${2:-MNQ}"
                shift 2
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

# Sync web app env vars into .env.local (merge, don't overwrite)
# Keep NEXT_PUBLIC_API_KEY as a compatibility fallback until the frontend no
# longer reads the legacy variable name anywhere.
sync_env_local() {
    local env_local="$SCRIPT_DIR/apps/pearl-algo-app/.env.local"
    local changed=false
    local temp_file="${env_local}.tmp"

    # Vars to sync: target_key=source_value
    declare -A sync_vars
    [ -n "${PEARL_API_KEY:-}" ] && sync_vars[NEXT_PUBLIC_READONLY_API_KEY]="$PEARL_API_KEY"
    [ -n "${PEARL_API_KEY:-}" ] && sync_vars[NEXT_PUBLIC_API_KEY]="$PEARL_API_KEY"
    [ -n "${PEARL_WEBAPP_AUTH_ENABLED:-}" ] && sync_vars[PEARL_WEBAPP_AUTH_ENABLED]="$PEARL_WEBAPP_AUTH_ENABLED"
    [ -n "${PEARL_WEBAPP_PASSCODE:-}" ] && sync_vars[PEARL_WEBAPP_PASSCODE]="$PEARL_WEBAPP_PASSCODE"

    # If no vars to sync, skip
    [ ${#sync_vars[@]} -eq 0 ] && return

    # Read existing file into associative array (preserve non-synced vars)
    declare -A existing
    if [ -f "$env_local" ]; then
        while IFS='=' read -r key val; do
            # Skip comments and empty lines
            [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
            # Remove quotes if present
            val="${val#\"}"
            val="${val%\"}"
            existing["$key"]="$val"
        done < <(grep -v '^#' "$env_local" | grep -v '^$' || true)
    fi

    # Merge synced vars (update if changed)
    for key in "${!sync_vars[@]}"; do
        if [ "${existing[$key]:-}" != "${sync_vars[$key]}" ]; then
            existing["$key"]="${sync_vars[$key]}"
            changed=true
        fi
    done

    # Write back if changed or file doesn't exist
    if [ "$changed" = true ] || [ ! -f "$env_local" ]; then
        echo "# API + Auth Configuration (auto-synced by pearl.sh)" > "$temp_file"
        # Write vars in sorted order for consistency
        for key in $(printf '%s\n' "${!existing[@]}" | sort); do
            echo "$key=${existing[$key]}" >> "$temp_file"
        done
        mv "$temp_file" "$env_local"
    fi
}

# Load env files (non-sensitive + secrets)
load_env_files() {
    set -a
    [ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
    local secrets_file="$HOME/.config/pearlalgo/secrets.env"
    [ -f "$secrets_file" ] && source "$secrets_file"
    set +a

    if [ -n "${PEARL_API_KEY:-}" ] && [ -z "${NEXT_PUBLIC_READONLY_API_KEY:-}" ]; then
        export NEXT_PUBLIC_READONLY_API_KEY="$PEARL_API_KEY"
    fi

    if [ -n "${PEARL_API_KEY:-}" ] && [ -z "${NEXT_PUBLIC_API_KEY:-}" ]; then
        export NEXT_PUBLIC_API_KEY="$PEARL_API_KEY"
    fi

    # Sync web app env vars into .env.local (merge, don't overwrite)
    sync_env_local
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

check_chart_status() {
    # Check if API server and Next.js are running (standalone or dev)
    local api_running=$(pgrep -f "api_server.py" &>/dev/null && echo "yes" || echo "no")
    local chart_running="no"
    if pgrep -f "next dev" &>/dev/null; then
        chart_running="dev"
    elif pgrep -f "next-server" &>/dev/null; then
        chart_running="prod"
    fi

    if [ "$api_running" = "yes" ] && [ "$chart_running" != "no" ]; then
        local mode_label=""
        [ "$chart_running" = "prod" ] && mode_label=" (production)" || mode_label=" (dev)"
        echo -e "${GREEN}●${NC} Web App - API + Web running${mode_label}"
    elif [ "$api_running" = "yes" ]; then
        echo -e "${YELLOW}●${NC} Web App - API only"
        return 1
    elif [ "$chart_running" != "no" ]; then
        echo -e "${YELLOW}●${NC} Web App - Web only (no API)"
        return 1
    else
        echo -e "${RED}●${NC} Web App"
        return 1
    fi
}

check_tv_paper_status() {
    if systemctl is-active --quiet pearlalgo-agent 2>/dev/null; then
        local agent_pid=$(systemctl show -p MainPID --value pearlalgo-agent 2>/dev/null || echo "")
        local api_active="down"
        systemctl is-active --quiet pearlalgo-api 2>/dev/null && api_active=":8001"
        echo -e "${GREEN}●${NC} Tradovate Paper Eval - systemd PID ${agent_pid:-?} | API ${api_active}"
        return 0
    fi

    local pidfile="$SCRIPT_DIR/logs/agent_${MARKET}.pid"
    if [ ! -f "$pidfile" ]; then
        pidfile="$SCRIPT_DIR/logs/agent_TV_PAPER.pid"
    fi
    local api_ok=$(curl -s http://localhost:8001/health 2>/dev/null | grep -c "ok" || echo 0)
    
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        local pid=$(cat "$pidfile")
        local uptime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
        local api_label=""
        [ "$api_ok" -gt 0 ] && api_label=" | API :8001" || api_label=" | API down"
        echo -e "${GREEN}●${NC} Tradovate Paper Eval - PID $pid, uptime: $uptime$api_label"
    elif [ "$api_ok" -gt 0 ]; then
        echo -e "${YELLOW}●${NC} Tradovate Paper Eval - API only (agent stopped)"
    else
        echo -e "${RED}●${NC} Tradovate Paper Eval"
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
    if curl -s "${header[@]}" "http://localhost:8001/api/state" &>/dev/null; then
        local data=$(curl -s "${header[@]}" "http://localhost:8001/api/state")
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
    check_tv_paper_status || true
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
    local tv_paper_status="❌"
    if systemctl is-active --quiet pearlalgo-agent 2>/dev/null; then
        tv_paper_status="✅"
    else
        local tv_paper_pid_file="$SCRIPT_DIR/logs/agent_${MARKET}.pid"
        if [ ! -f "$tv_paper_pid_file" ]; then
            tv_paper_pid_file="$SCRIPT_DIR/logs/agent_TV_PAPER.pid"
        fi
        tv_paper_status=$([ -f "$tv_paper_pid_file" ] && kill -0 "$(cat "$tv_paper_pid_file")" 2>/dev/null && echo "✅" || echo "❌")
    fi
    local chart_status=$(pgrep -f "api_server.py" &>/dev/null && (pgrep -f "next-server" &>/dev/null || pgrep -f "next dev" &>/dev/null) && echo "✅" || echo "❌")
    local tunnel_status=$( (systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null || pgrep -f "cloudflared.*tunnel run" &>/dev/null) && echo "✅" || echo "❌")

    echo -e "PEARL: GW $gw_status | TV-Paper $tv_paper_status | Chart $chart_status | Tunnel $tunnel_status"
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
    if systemctl is-enabled pearlalgo-agent &>/dev/null 2>&1; then
        if [ "$FOREGROUND" = true ]; then
            ./scripts/lifecycle/tv_paper_eval.sh restart
        else
            ./scripts/lifecycle/tv_paper_eval.sh start --background
        fi
        echo ""
        return
    fi
    if [ "$FOREGROUND" = true ]; then
        ./scripts/lifecycle/agent.sh start --market "$MARKET"
    else
        ./scripts/lifecycle/agent.sh start --market "$MARKET" --background
    fi
    echo ""
}

start_chart() {
    if [ "$NO_CHART" = true ]; then
        echo -e "${YELLOW}⏭ Skipping Web App (--no-chart)${NC}"
        return
    fi

    echo -e "${CYAN}▶ Starting Web App (pearlalgo.io)...${NC}"

    load_env_files

    local LOG_DIR="$SCRIPT_DIR/logs"
    local CHART_DIR="$SCRIPT_DIR/apps/pearl-algo-app"
    local CHART_PORT="${PEARL_CHART_PORT:-3001}"

    # Start the API against the same per-market state root the agent uses.
    if ! pgrep -f "api_server.py.*--port 8001" &>/dev/null; then
        local TV_STATE_DIR="${PEARLALGO_STATE_DIR:-$SCRIPT_DIR/data/agent_state/${MARKET}}"
        if [ -d "$TV_STATE_DIR" ]; then
            .venv/bin/python scripts/pearlalgo_web_app/api_server.py \
                --market "$MARKET" \
                --data-dir "$TV_STATE_DIR" \
                --port 8001 >> "$LOG_DIR/api_TV_PAPER.log" 2>&1 &
            echo "   API server started (port 8001)"
        fi
    else
        echo "   API server already running (port 8001)"
    fi

    # Start web interface (only if not already running)
    if ! pgrep -f "next-server" &>/dev/null && ! pgrep -f "server\.js.*$CHART_PORT" &>/dev/null; then
        export NEXT_PUBLIC_READONLY_API_KEY="${PEARL_API_KEY:-}"
        export NEXT_PUBLIC_API_KEY="${PEARL_API_KEY:-}"
        cd "$CHART_DIR"

        # Auto-build if no production build exists
        if [ ! -f ".next/BUILD_ID" ]; then
            echo "   No build found — building..."
            npm run build >> "$LOG_DIR/web_app_build.log" 2>&1
            if [ $? -ne 0 ]; then
                echo -e "   ${RED}Build failed!${NC} Check logs/web_app_build.log"
                cd "$SCRIPT_DIR"
                return 1
            fi
            echo "   Build complete."
        fi

        # Copy static assets into standalone dir (required for standalone output)
        if [ -d ".next/standalone" ]; then
            cp -r .next/static .next/standalone/.next/static 2>/dev/null || true
            cp -r public .next/standalone/public 2>/dev/null || true
        fi

        # Load .env.local vars (standalone server doesn't auto-read them)
        if [ -f ".env.local" ]; then
            set -a
            source .env.local 2>/dev/null || true
            set +a
        fi

        # Use standalone server (production) if available, else fall back to next dev
        if [ -f ".next/standalone/server.js" ]; then
            PORT="$CHART_PORT" HOSTNAME="0.0.0.0" nohup node .next/standalone/server.js > "$LOG_DIR/web_app.log" 2>&1 &
            echo "   Chart web started (port $CHART_PORT, production)"
        else
            nohup npx next dev -p "$CHART_PORT" > "$LOG_DIR/web_app.log" 2>&1 &
            echo "   Chart web started (port $CHART_PORT, dev mode)"
        fi
        cd "$SCRIPT_DIR"
    else
        echo "   Chart web already running"
    fi
    
    echo "   URL: http://localhost:$CHART_PORT"
    echo "   Public: https://pearlalgo.io"
    echo ""
}

build_chart() {
    echo -e "${CYAN}▶ Building Web App...${NC}"
    local CHART_DIR="$SCRIPT_DIR/apps/pearl-algo-app"
    local LOG_DIR="$SCRIPT_DIR/logs"
    cd "$CHART_DIR"
    export NEXT_PUBLIC_READONLY_API_KEY="${PEARL_API_KEY:-}"
    export NEXT_PUBLIC_API_KEY="${PEARL_API_KEY:-}"

    # Stop webapp before build to avoid serving stale/missing files during overwrite
    if systemctl is-active --quiet pearlalgo-webapp 2>/dev/null; then
        echo "   Stopping webapp for build..."
        sudo systemctl stop pearlalgo-webapp 2>/dev/null || true
    fi

    npm run build > "$LOG_DIR/web_app_build.log" 2>&1
    local rc=$?
    if [ $rc -eq 0 ]; then
        # Copy static assets into standalone dir
        if [ -d ".next/standalone" ]; then
            cp -r .next/static .next/standalone/.next/static 2>/dev/null || true
            cp -r public .next/standalone/public 2>/dev/null || true
        fi
        echo -e "   ${GREEN}Build successful${NC}"
        # Restart webapp after successful build
        if systemctl is-enabled --quiet pearlalgo-webapp 2>/dev/null; then
            echo "   Restarting webapp..."
            sudo systemctl start pearlalgo-webapp 2>/dev/null || true
        fi
    else
        echo -e "   ${RED}Build failed!${NC} Check logs/web_app_build.log"
        # Restart webapp even on failure so old version keeps serving
        if systemctl is-enabled --quiet pearlalgo-webapp 2>/dev/null; then
            sudo systemctl start pearlalgo-webapp 2>/dev/null || true
        fi
    fi
    cd "$SCRIPT_DIR"
    return $rc
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
    # Start the live market agent first so the API/web layer attaches to the same state dir.
    if [ -f "$SCRIPT_DIR/config/live/tradovate_paper.yaml" ]; then
        echo -e "${CYAN}▶ Starting Tradovate Paper Eval (MNQ)...${NC}"
        start_agent || echo -e "${YELLOW}   Tradovate Paper start failed (non-critical)${NC}"
        echo ""
    fi
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
    if systemctl is-enabled pearlalgo-agent &>/dev/null 2>&1; then
        ./scripts/lifecycle/tv_paper_eval.sh stop 2>/dev/null || true
        echo ""
        return
    fi
    ./scripts/lifecycle/agent.sh stop --market "$MARKET" 2>/dev/null || true
    echo ""
}

stop_chart() {
    echo -e "${CYAN}■ Stopping Web App...${NC}"
    # Kill all API servers and web app
    pkill -f "api_server.py" 2>/dev/null && echo "   Stopped API server(s)" || true
    pkill -f "next-server" 2>/dev/null || true
    pkill -f "next dev" 2>/dev/null || true
    pkill -f "server\.js.*standalone" 2>/dev/null || true
    # Wait a moment and verify
    sleep 1
    if pgrep -f "next-server|next dev|standalone/server" &>/dev/null; then
        echo "   Force killing lingering processes..."
        pkill -9 -f "next-server" 2>/dev/null || true
        pkill -9 -f "next dev" 2>/dev/null || true
        pkill -9 -f "server\.js.*standalone" 2>/dev/null || true
    fi
    echo "   Stopped web app"
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
    ./scripts/gateway/gateway.sh stop || true
    echo ""
}

# Issue 24: Safety prompt during market hours for stop/restart
_confirm_if_market_open() {
    # Skip prompt if --force flag was passed
    if [[ "${FORCE:-}" == "true" ]]; then
        return 0
    fi
    # Quick check: is it a weekday and within US futures hours (18:00-17:00 ET)?
    local et_hour
    et_hour=$(TZ="America/New_York" date +%H 2>/dev/null || echo "99")
    local day_of_week
    day_of_week=$(date +%u 2>/dev/null || echo "6")  # 1=Mon, 7=Sun
    # Futures trade Sun 18:00 - Fri 17:00 ET
    if [[ "$day_of_week" -le 5 ]] && [[ "$et_hour" != "99" ]]; then
        echo -e "${YELLOW}${BOLD}WARNING: Market may be open (ET hour: ${et_hour}, day: ${day_of_week}).${NC}"
        echo -e "${YELLOW}Stopping the agent will halt all position monitoring and exits.${NC}"
        read -r -p "Continue? [y/N] " confirm
        if [[ "${confirm,,}" != "y" ]]; then
            echo -e "${RED}Aborted.${NC}"
            return 1
        fi
    fi
    return 0
}

stop_all() {
    _confirm_if_market_open || return 1

    echo ""
    echo -e "${BOLD}🐚 Stopping PEARL System...${NC}"
    echo -e "${BOLD}═══════════════════════════${NC}"
    echo ""

    activate_venv

    # Stop in reverse dependency order
    stop_tunnel
    stop_chart
    stop_agent
    stop_gateway

    echo -e "${GREEN}${BOLD}✅ PEARL System Stopped${NC}"
    echo ""
}

# ============================================================================
# Restart Function
# ============================================================================

restart_all() {
    _confirm_if_market_open || return 1

    echo ""
    echo -e "${BOLD}🐚 Restarting PEARL System...${NC}"
    echo -e "${BOLD}════════════════════════════${NC}"
    echo ""
    
    stop_all
    sleep 3
    start_all
}

# ============================================================================
# Agent-Only Restart (no gateway restart, no 2FA needed)
# ============================================================================

restart_services_only() {
    load_env_files

    # Restart ALL services except IBKR gateway -- no 2FA needed
    # Restarts: agent, api, webapp
    # Use this for: code changes, config updates, agent issues, bar staleness
    # Use ./pearl.sh restart ONLY when gateway itself is down (triggers 2FA)

    # ADDED 2026-03-25: guard against restarting with open positions
    local header=()
    if [ -n "${PEARL_API_KEY:-}" ]; then
        header=(-H "X-API-Key: $PEARL_API_KEY")
    fi
    open_pos=$(curl -s "${header[@]}" "http://localhost:8001/api/state" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); pos=d.get('tradovate_account',{}).get('positions',[]); print(len(pos))" 2>/dev/null || echo "0")
    if [ "$open_pos" -gt "0" ]; then
        if [[ "${FORCE:-}" == "true" ]]; then
            echo -e "${YELLOW}WARNING: $open_pos open position(s) detected — restarting anyway (FORCE=true).${NC}"
            echo -e "${YELLOW}Broker bracket orders (SL/TP) will continue to manage the position.${NC}"
            echo -e "${YELLOW}Agent-side state (partial_runner, trailing stop overrides) will be lost.${NC}"
        else
            echo -e "${RED}SOFT-RESTART BLOCKED: $open_pos open position(s) detected. Close positions before restarting.${NC}"
            echo -e "${YELLOW}Override with: FORCE=true ./pearl.sh soft-restart${NC}"
            exit 1
        fi
    fi

    echo ""
    echo -e "${BOLD}Restarting Services (no gateway, no 2FA)...${NC}"
    echo ""

    # Stop cleanly - kill stale processes
    echo -e "${CYAN}Stopping all non-gateway services...${NC}"
    sudo systemctl stop pearlalgo-agent pearlalgo-api pearlalgo-webapp pearlalgo-webapp-dev 2>/dev/null || true
    pkill -f "pearlalgo.market_agent.main" 2>/dev/null || true
    pkill -f "pearlalgo_web_app/api_server" 2>/dev/null || true
    sleep 3

    # Start in order
    echo -e "${CYAN}Starting agent...${NC}"
    sudo systemctl start pearlalgo-agent
    sleep 4

    echo -e "${CYAN}Starting API...${NC}"
    sudo systemctl start pearlalgo-api
    sleep 3

    echo -e "${CYAN}Starting webapp...${NC}"
    sudo systemctl start pearlalgo-webapp
    sleep 2

    # Status
    echo ""
    all_ok=true
    for svc in pearlalgo-agent pearlalgo-api pearlalgo-webapp; do
        if sudo systemctl is-active $svc &>/dev/null; then
            echo -e "   ${GREEN}OK: $svc${NC}"
        else
            echo -e "   ${RED}FAILED: $svc${NC}"
            all_ok=false
        fi
    done
    echo ""
    $all_ok && echo -e "${GREEN}Services restarted -- gateway untouched, no 2FA${NC}" || echo -e "${RED}Some services failed${NC}"
    echo ""
    show_quick_status
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
            ./scripts/ops/status.sh --market "$MARKET"
            ;;
        *)
            echo "Unknown agent command: $subcmd"
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
        build)
            load_env_files
            build_chart
            ;;
        deploy)
            # Build + restart in one command (the safe workflow)
            load_env_files
            build_chart && { stop_chart; sleep 2; start_chart; }
            ;;
        *)
            echo "Unknown chart command: $subcmd"
            echo "  Usage: ./pearl.sh chart <start|stop|restart|status|build|deploy>"
            echo "  deploy = build + restart (recommended after code changes)"
            ;;
    esac
}

handle_tv_paper() {
    local subcmd="${1:-status}"
    activate_venv
    load_env_files
    case "$subcmd" in
        start)
            echo -e "${CYAN}▶ Starting Tradovate Paper Eval...${NC}"
            ./scripts/lifecycle/tv_paper_eval.sh start --background
            ;;
        stop)
            echo -e "${CYAN}■ Stopping Tradovate Paper Eval...${NC}"
            ./scripts/lifecycle/tv_paper_eval.sh stop
            ;;
        status)
            check_tv_paper_status || echo "   Not running"
            ;;
        restart)
            echo -e "${CYAN}🔄 Restarting Tradovate Paper Eval...${NC}"
            ./scripts/lifecycle/tv_paper_eval.sh stop 2>/dev/null || true
            sleep 3
            ./scripts/lifecycle/tv_paper_eval.sh start --background
            ;;
        api)
            echo -e "${CYAN}▶ Starting Tradovate Paper API only...${NC}"
            ./scripts/lifecycle/tv_paper_eval.sh api --background
            ;;
        logs)
            tail -f "$SCRIPT_DIR/logs/agent_TV_PAPER.log"
            ;;
        *)
            echo "Usage: ./pearl.sh tv-paper <start|stop|status|restart|api|logs>"
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
            if systemctl is-active --quiet cloudflared-pearlalgo 2>/dev/null; then
                echo -e "${CYAN}■ Restarting Cloudflare Tunnel (systemd)...${NC}"
                if systemctl restart cloudflared-pearlalgo 2>/dev/null; then
                    echo "   Tunnel restarted (systemd)"
                else
                    echo -e "   ${YELLOW}Run: sudo systemctl restart cloudflared-pearlalgo${NC}"
                fi
            else
                handle_tunnel stop
                sleep 2
                start_tunnel
            fi
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
    echo "  start       Start all services (Gateway → Tradovate Paper → Chart)"
    echo "  stop        Stop all services gracefully"
    echo "  restart     Restart all services"
    echo "  status      Show detailed status of all services"
    echo "  quick       Quick status (one-liner)"
    echo ""
    echo -e "${CYAN}Individual Services:${NC}"
    echo "  gateway <start|stop|status>    Control IB Gateway"
    echo "  agent <start|stop|status>      Control market agent (optional)"
    echo "  tv-paper <start|stop|status|restart|api|logs>  Control Tradovate Paper Eval"
    echo "  chart <start|stop|status|build|deploy>  Control Web App (pearlalgo.io)"
    echo "  tunnel <start|stop|status|logs|setup>  Control Cloudflare Tunnel"
    echo ""
    echo -e "${CYAN}Options:${NC}"
    echo "  --market MNQ         Market to trade (default: MNQ)"
    echo "  --no-chart           Skip Web App"
    echo "  --foreground         Run agent in foreground"
    echo ""
    echo -e "${CYAN}Examples:${NC}"
    echo "  ./pearl.sh start                    # Start everything"
    echo "  ./pearl.sh start --market ES        # Start for ES market"
    echo "  ./pearl.sh start --no-chart         # Start without Web App"
    echo "  ./pearl.sh restart                  # Restart everything"
    echo "  ./pearl.sh chart deploy             # Build + restart (after code changes)"
    echo "  ./pearl.sh chart restart            # Restart just Web App (uses existing build)"
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
MARKET="$(echo "$MARKET" | tr '[:lower:]' '[:upper:]')"

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
    hard-restart)
        restart_all
        ;;
    soft-restart)
        restart_services_only
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
    chart)
        handle_chart "${1:-status}"
        ;;
    tv-paper)
        handle_tv_paper "${1:-status}"
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

build_dev_webapp() {
    # Build dev webapp, copy static assets, restart dev service
    # Run after any CSS/JS/TSX changes to apps/pearl-algo-app/
    local DEV_DIR="/home/pearlalgo/projects/pearl-algo/apps/pearl-algo-app"
    echo ""
    echo -e "${BOLD}Building dev webapp...${NC}"
    echo ""

    cd "$DEV_DIR" || { echo -e "${RED}Dev webapp dir not found${NC}"; exit 1; }

    echo -e "${CYAN}Running npm build...${NC}"
    npm run build 2>&1 | tail -8

    if [ $? -ne 0 ]; then
        echo -e "${RED}Build failed — check CSS/TS errors above${NC}"
        exit 1
    fi

    echo -e "${CYAN}Copying static assets...${NC}"
    cp -r .next/static .next/standalone/.next/static
    cp -r public .next/standalone/public 2>/dev/null || true

    echo -e "${CYAN}Restarting dev service...${NC}"
    sudo systemctl restart pearlalgo-webapp-dev
    sleep 3

    if sudo systemctl is-active pearlalgo-webapp-dev &>/dev/null; then
        echo -e "${GREEN}Dev webapp live on port 3002${NC}"
    else
        echo -e "${RED}Dev service failed to start${NC}"
        exit 1
    fi
    echo ""
}
