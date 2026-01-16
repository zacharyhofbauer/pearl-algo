#!/bin/bash
# ============================================================================
# Restart Pearl Algo Monitor (robust)
#
# Usage:
#   ./scripts/monitor/restart_monitor.sh                 # background (default)
#   ./scripts/monitor/restart_monitor.sh --foreground
#   ./scripts/monitor/restart_monitor.sh --background
#
# Pass-through flags:
#   --display=:0
#   --xauthority=/path
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/pearl_algo_monitor.pid"

cd "$PROJECT_DIR"

MODE="--background"
PASS_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --foreground|-f) MODE="--foreground" ;;
    --background|-b) MODE="--background" ;;
    *) PASS_ARGS+=("$arg") ;;
  esac
done

PATTERN="pearlalgo.monitor"

if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  pkill -TERM -f "$PATTERN" || true
  for _ in $(seq 1 20); do
    if ! pgrep -f "$PATTERN" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if pgrep -f "$PATTERN" >/dev/null 2>&1; then
    pkill -KILL -f "$PATTERN" || true
    sleep 1
  fi
fi

rm -f "$PID_FILE" || true

if [ "$MODE" = "--foreground" ]; then
  exec "$PROJECT_DIR/scripts/monitor/start_monitor.sh" "${PASS_ARGS[@]}"
fi

exec "$PROJECT_DIR/scripts/monitor/start_monitor.sh" --background "${PASS_ARGS[@]}"

