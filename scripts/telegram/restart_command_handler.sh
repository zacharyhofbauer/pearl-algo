#!/bin/bash
# ============================================================================
# Restart Telegram Command Handler Service (robust)
# Usage:
#   ./scripts/telegram/restart_command_handler.sh            # background (default)
#   ./scripts/telegram/restart_command_handler.sh --foreground
#   ./scripts/telegram/restart_command_handler.sh --background
#
# Behavior:
# - Sends SIGTERM to existing handler(s)
# - Waits until fully stopped
# - Escalates to SIGKILL if needed
# - Restarts via start_command_handler.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$PROJECT_DIR/logs/telegram_handler.pid"

cd "$PROJECT_DIR"

MODE="--background"
for arg in "$@"; do
  if [ "$arg" == "--foreground" ] || [ "$arg" == "-f" ]; then
    MODE="--foreground"
  fi
  if [ "$arg" == "--background" ] || [ "$arg" == "-b" ]; then
    MODE="--background"
  fi
done

echo "=== Restarting Telegram Command Handler ==="
echo ""

PATTERN="telegram_command_handler"

if pgrep -f "$PATTERN" >/dev/null 2>&1; then
  echo "Stopping existing handler process(es)..."
  pkill -TERM -f "$PATTERN" || true

  # Wait up to 20s for clean shutdown
  for _ in $(seq 1 20); do
    if ! pgrep -f "$PATTERN" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  # Escalate if still running
  if pgrep -f "$PATTERN" >/dev/null 2>&1; then
    echo "⚠️  Still running after SIGTERM — forcing stop (SIGKILL)..."
    pkill -KILL -f "$PATTERN" || true
    sleep 1
  fi
else
  echo "No existing handler process found."
fi

# Clean up pid file (best-effort)
rm -f "$PID_FILE" || true

echo ""
echo "Starting handler ($MODE)..."
if [ "$MODE" == "--foreground" ]; then
  exec ./scripts/telegram/start_command_handler.sh
else
  exec ./scripts/telegram/start_command_handler.sh --background
fi


