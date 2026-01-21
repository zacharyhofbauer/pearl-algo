#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Start Pearl Algo Monitor suite (Gateway + Agent + Telegram + Monitor)
#
# Defaults:
# - Starts Agent in background (holds the IBKR connection)
# - Starts Telegram command handler in background (optional)
# - Starts the Monitor UI (optional; requires GUI session)
#
# Flags:
#   --no-gateway   Skip starting IB Gateway
#   --no-telegram  Skip starting Telegram command handler
#   --no-monitor   Skip starting the Monitor UI
#
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

NO_GATEWAY=false
NO_TELEGRAM=false
NO_MONITOR=false
MARKET="${PEARLALGO_MARKET:-NQ}"

for arg in "$@"; do
  case "$arg" in
    --no-gateway) NO_GATEWAY=true ;;
    --no-telegram) NO_TELEGRAM=true ;;
    --no-monitor) NO_MONITOR=true ;;
    --market=*) MARKET="${arg#*=}" ;;
  esac
done

cd "$PROJECT_DIR"

echo "=== Starting Pearl Algo Monitor suite ==="

if [ "$NO_GATEWAY" = false ]; then
  echo ""
  echo "-> Starting IB Gateway (best-effort)..."
  ./scripts/gateway/gateway.sh start || true
fi

echo ""
echo "-> Starting Agent (market=${MARKET}) (background)..."
./scripts/lifecycle/agent.sh start --market "$MARKET" --background || true

if [ "$NO_TELEGRAM" = false ]; then
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo ""
    echo "-> Telegram command handler skipped (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not set)."
  else
  echo ""
  echo "-> Starting Telegram command handler (background)..."
  ./scripts/telegram/start_command_handler.sh --background || true
  fi
fi

if [ "$NO_MONITOR" = false ]; then
  echo ""
  echo "-> Starting Pearl Algo Monitor (GUI)..."
  ./scripts/monitor/start_monitor.sh --background || true
fi

echo ""
echo "Done."

