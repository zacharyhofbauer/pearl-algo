#!/bin/bash
# Quick health check for the market agent
# Usage:
#   ./scripts/health_check.sh
#   ./scripts/health_check.sh --market NQ

set -euo pipefail
cd "$(dirname "$0")/.."

MARKET="${PEARLALGO_MARKET:-NQ}"
if [ "${1:-}" = "--market" ] && [ -n "${2:-}" ]; then
  MARKET="$2"
fi
MARKET="$(echo "$MARKET" | tr '[:lower:]' '[:upper:]')"

STATE_DIR="${PEARLALGO_STATE_DIR:-data/agent_state/${MARKET}}"
STATE_FILE="${STATE_DIR}/state.json"
SIGNALS_FILE="${STATE_DIR}/signals.jsonl"
PID_FILE="logs/agent_${MARKET}.pid"
LOG_FILE="logs/agent_${MARKET}.log"

echo "=== PearlAlgo Health Check (market=${MARKET}) ==="
echo ""

# 1. Service status
echo "📦 Services:"
if [ -f "$PID_FILE" ] && ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
  echo "  ✅ Agent (${MARKET}): RUNNING (pid=$(cat "$PID_FILE"))"
else
  echo "  ❌ Agent (${MARKET}): NOT RUNNING"
fi

if pgrep -f "telegram_command_handler" > /dev/null; then
  echo "  ✅ Telegram Handler: RUNNING"
else
  echo "  ❌ Telegram Handler: NOT RUNNING"
fi

# 2. IBKR Gateway
echo ""
echo "🔌 Gateway:"
if pgrep -f "java.*IBC\\.jar|ibgateway|IB Gateway|java.*jts" > /dev/null; then
  echo "  ✅ IBKR Gateway: RUNNING"
else
  echo "  ❌ IBKR Gateway: NOT RUNNING"
fi

# 3. State file health
echo ""
echo "📊 Agent State:"
if [ -f "$STATE_FILE" ]; then
  STATE=$(cat "$STATE_FILE")
  MARKET_OPEN=$(echo "$STATE" | jq -r '.futures_market_open // false')
  SESSION_OPEN=$(echo "$STATE" | jq -r '.strategy_session_open // false')
  DATA_FRESH=$(echo "$STATE" | jq -r '.data_fresh // false')
  EXEC_MODE=$(echo "$STATE" | jq -r '.execution.mode // "unknown"')
  EXEC_ENABLED=$(echo "$STATE" | jq -r '.execution.enabled // false')
  CYCLES=$(echo "$STATE" | jq -r '.cycle_count // 0')
  SIGNALS=$(echo "$STATE" | jq -r '.signal_count // 0')
  LAST_DIAG=$(echo "$STATE" | jq -r '.signal_diagnostics // "N/A"')

  echo "  Market Open: $MARKET_OPEN"
  echo "  Session Open: $SESSION_OPEN"
  echo "  Data Fresh: $DATA_FRESH"
  echo "  Execution: $EXEC_MODE (enabled=$EXEC_ENABLED)"
  echo "  Cycles: $CYCLES | Signals: $SIGNALS"
  echo "  Last Diagnostics: $LAST_DIAG"
else
  echo "  ❌ State file not found: $STATE_FILE"
fi

# 4. Recent signals
echo ""
echo "📈 Recent Activity:"
TODAY=$(date -u +%Y-%m-%d)
if [ -f "$SIGNALS_FILE" ]; then
  TODAY_SIGNALS=$(grep -c "$TODAY" "$SIGNALS_FILE" 2>/dev/null || echo "0")
  echo "  Signals today: $TODAY_SIGNALS"

  LAST_SIGNAL=$(tail -n 1 "$SIGNALS_FILE" 2>/dev/null | jq -r '.signal_id // "none"')
  echo "  Last signal: $LAST_SIGNAL"
else
  echo "  ❌ Signals file not found: $SIGNALS_FILE"
fi

# 5. Log health (last ~200 lines)
echo ""
echo "📝 Recent Logs (errors/warnings):"
if [ -f "$LOG_FILE" ]; then
  RECENT_ERRORS=$(tail -n 200 "$LOG_FILE" | grep -c "ERROR" || true)
  RECENT_WARNS=$(tail -n 200 "$LOG_FILE" | grep -c "WARNING" || true)
  echo "  Agent (${MARKET}): ${RECENT_ERRORS:-0} errors, ${RECENT_WARNS:-0} warnings (last ~200 lines)"
fi

# 6. Quick sanity
echo ""
echo "🎯 Quick Sanity:"
if [ "${MARKET_OPEN:-false}" = "true" ] && [ "${SESSION_OPEN:-false}" = "true" ] && [ "${DATA_FRESH:-false}" = "true" ]; then
  echo "  ✅ Ready to generate signals"
else
  echo "  ⚠️  Not ready: market=${MARKET_OPEN:-unknown}, session=${SESSION_OPEN:-unknown}, data=${DATA_FRESH:-unknown}"
fi

echo ""
echo "=== Health Check Complete ==="
