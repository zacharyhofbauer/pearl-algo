#!/bin/bash
# ============================================================================
# Category: Lifecycle
# Purpose: Check market agent status and display information
# Usage:
#   ./scripts/lifecycle/check_agent_status.sh --market NQ
#   ./scripts/lifecycle/check_agent_status.sh --market ES
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

MARKET="${PEARLALGO_MARKET:-NQ}"
if [ "${1:-}" = "--market" ] && [ -n "${2:-}" ]; then
  MARKET="$2"
fi
MARKET="$(echo "$MARKET" | tr '[:lower:]' '[:upper:]')"

PID_FILE="$PROJECT_DIR/logs/agent_${MARKET}.pid"
STATE_FILE="$PROJECT_DIR/data/agent_state/${MARKET}/state.json"

cd "$PROJECT_DIR"

echo "=== Agent Status (market=${MARKET}) ==="
echo ""

# Check if process is running via PID file
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "✅ Service Process: RUNNING"
    echo "   PID: $PID"
    ps -p "$PID" -o pid,etime,cmd --no-headers | awk '{print "   Uptime: " $2}'
  else
    echo "❌ Service Process: NOT RUNNING (stale PID file)"
    rm -f "$PID_FILE"
  fi
else
  echo "❌ Service Process: NOT RUNNING (no PID file: $PID_FILE)"
fi

echo ""

# Check state file if it exists
if [ -f "$STATE_FILE" ]; then
  echo "📊 Service State:"
  if command -v jq &> /dev/null; then
    jq -r '
      "   Market: \(.market // "N/A")",
      "   Cycles: \(.cycle_count // 0)",
      "   Signals: \(.signal_count // 0)",
      "   Buffer: \(.buffer_size // 0) / \(.buffer_size_target // 100) bars",
      "   Config: \(.config.symbol // "N/A") @ \(.config.timeframe // "N/A")"
    ' "$STATE_FILE"

    echo ""
    echo "🧠 Trading Bot:"
    jq -r '
      if .trading_bot != null then
        "   Enabled: \(.trading_bot.enabled // false)",
        "   Selected: \(.trading_bot.selected // "N/A")"
      else
        "   (not available in state)"
      end
    ' "$STATE_FILE"

    echo ""
    echo "📡 Data Health:"
    jq -r '
      if .data_fresh == true then
        "   ✅ Data Fresh: yes"
      elif .data_fresh == false then
        "   ⚠️  Data Fresh: NO (age: \(.latest_bar_age_minutes // "?") min)"
      else
        "   ❓ Data Fresh: unknown"
      end,
      if .last_successful_cycle != null then
        "   Last Success: \(.last_successful_cycle)"
      else
        "   Last Success: (no data yet)"
      end
    ' "$STATE_FILE"
  else
    echo "   (install jq for pretty output)"
  fi
else
  echo "📊 Service State: (no state file: $STATE_FILE)"
fi

