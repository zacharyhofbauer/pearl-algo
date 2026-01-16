#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Stop Pearl Algo Monitor suite (Monitor + Telegram + Agent + Gateway)
#
# Flags:
#   --no-gateway   Skip stopping IB Gateway
#   --no-telegram  Skip stopping Telegram command handler
#   --no-monitor   Skip stopping the Monitor UI
#
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

NO_GATEWAY=false
NO_TELEGRAM=false
NO_MONITOR=false

for arg in "$@"; do
  case "$arg" in
    --no-gateway) NO_GATEWAY=true ;;
    --no-telegram) NO_TELEGRAM=true ;;
    --no-monitor) NO_MONITOR=true ;;
  esac
done

cd "$PROJECT_DIR"

echo "=== Stopping Pearl Algo Monitor suite ==="

if [ "$NO_MONITOR" = false ]; then
  echo ""
  echo "-> Stopping Monitor (best-effort)..."
  pkill -f "pearlalgo.monitor" || true
fi

if [ "$NO_TELEGRAM" = false ]; then
  echo ""
  echo "-> Stopping Telegram command handler (best-effort)..."
  pkill -f "telegram_command_handler" || true
fi

echo ""
echo "-> Stopping NQ Agent..."
./scripts/lifecycle/stop_nq_agent_service.sh || true

if [ "$NO_GATEWAY" = false ]; then
  echo ""
  echo "-> Stopping IB Gateway (best-effort)..."
  ./scripts/gateway/gateway.sh stop || true
fi

echo ""
echo "Done."

