#!/bin/bash
# ============================================================================
# Category: Gateway
# Purpose: Consolidated entry point for IBKR Gateway lifecycle + diagnostics
# Usage:
#   ./scripts/gateway/gateway.sh <command>
#
# Commands:
#   start           Start Gateway headless via IBC
#   stop            Stop Gateway (IBC)
#   status          Check Gateway status
#   api-ready       Check API port readiness
#   tws-conflict    Detect TWS/Gateway conflicts
#   2fa-status      Check whether 2FA is required
#   wait-2fa        Wait for 2FA approval (mobile)
#   complete-2fa    Complete 2FA via VNC
#   auto-2fa        Auto-enter 2FA code (if applicable)
#   monitor         Monitor until API is ready
#   setup           One-time gateway + IBC setup
#   vnc-setup       One-time VNC setup for manual login
#   vnc-config-api  One-time API config via VNC
#   disable-sleep   Disable auto-sleep (host helper)
#
# Notes:
# - This script delegates to existing per-purpose scripts to preserve compatibility.
# - It is meant to reduce the need to remember 10+ script names.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

print_help() {
  sed -n '1,120p' "$0" | sed -n '/^# ===/,$p' >/dev/null 2>&1 || true
  cat <<'EOF'
Usage:
  ./scripts/gateway/gateway.sh <command>

Commands:
  start           Start Gateway headless via IBC
  stop            Stop Gateway (IBC)
  status          Check Gateway status
  api-ready       Check API port readiness
  tws-conflict    Detect TWS/Gateway conflicts
  2fa-status      Check whether 2FA is required
  wait-2fa        Wait for 2FA approval (mobile)
  complete-2fa    Complete 2FA via VNC
  auto-2fa        Auto-enter 2FA code (if applicable)
  monitor         Monitor until API is ready
  setup           One-time gateway + IBC setup
  vnc-setup       One-time VNC setup for manual login
  vnc-config-api  One-time API config via VNC
  disable-sleep   Disable auto-sleep (host helper)
  help            Show this help
EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  help|-h|--help)
    print_help
    exit 0
    ;;
  start)
    exec "$SCRIPT_DIR/start_ibgateway_ibc.sh" "$@"
    ;;
  stop)
    exec "$SCRIPT_DIR/stop_ibgateway_ibc.sh" "$@"
    ;;
  status)
    exec "$SCRIPT_DIR/check_gateway_status.sh" "$@"
    ;;
  api-ready)
    exec "$SCRIPT_DIR/check_api_ready.sh" "$@"
    ;;
  tws-conflict)
    exec "$SCRIPT_DIR/check_tws_conflict.sh" "$@"
    ;;
  2fa-status)
    exec "$SCRIPT_DIR/check_gateway_2fa_status.sh" "$@"
    ;;
  wait-2fa)
    exec "$SCRIPT_DIR/wait_for_2fa_approval.sh" "$@"
    ;;
  complete-2fa)
    exec "$SCRIPT_DIR/complete_2fa_vnc.sh" "$@"
    ;;
  auto-2fa)
    exec "$SCRIPT_DIR/auto_2fa.sh" "$@"
    ;;
  monitor)
    exec "$SCRIPT_DIR/monitor_until_ready.sh" "$@"
    ;;
  setup)
    exec "$SCRIPT_DIR/setup_ibgateway.sh" "$@"
    ;;
  vnc-setup)
    exec "$SCRIPT_DIR/setup_vnc_for_login.sh" "$@"
    ;;
  vnc-config-api)
    exec "$SCRIPT_DIR/configure_gateway_api_vnc.sh" "$@"
    ;;
  disable-sleep)
    exec "$SCRIPT_DIR/disable_auto_sleep.sh" "$@"
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    echo >&2
    print_help >&2
    exit 2
    ;;
esac


