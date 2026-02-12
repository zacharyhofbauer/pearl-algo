#!/bin/bash
# ============================================================================
# Category: Ops
# Purpose: Manual CLI health check — shows process, gateway, state, and log status
# Replaces: scripts/ops/quick_status.sh + scripts/lifecycle/check_agent_status.sh
#
# Usage:
#   ./scripts/ops/status.sh
#   ./scripts/ops/status.sh --market NQ
#   ./scripts/ops/status.sh --market ES
#
# Requires: jq (optional but recommended for pretty state output)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

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

echo "=== PearlAlgo Status (market=${MARKET}) ==="
echo ""

# ── 1. Agent process ─────────────────────────────────────────────────────────
echo "📦 Services:"
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if ps -p "$PID" > /dev/null 2>&1; then
    UPTIME=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ')
    echo "  ✅ Agent (${MARKET}): RUNNING (pid=${PID}, uptime=${UPTIME})"
  else
    echo "  ❌ Agent (${MARKET}): NOT RUNNING (stale PID file)"
    rm -f "$PID_FILE"
  fi
else
  echo "  ❌ Agent (${MARKET}): NOT RUNNING (no PID file)"
fi

if pgrep -f "telegram_command_handler" > /dev/null 2>&1; then
  echo "  ✅ Telegram Handler: RUNNING"
else
  echo "  ❌ Telegram Handler: NOT RUNNING"
fi

# ── 2. IBKR Gateway ──────────────────────────────────────────────────────────
echo ""
echo "🔌 Gateway:"
if pgrep -f "java.*IBC\\.jar|ibgateway|IB Gateway|java.*jts" > /dev/null 2>&1; then
  echo "  ✅ IBKR Gateway: RUNNING"
else
  echo "  ❌ IBKR Gateway: NOT RUNNING"
fi

# ── 3. Agent state ───────────────────────────────────────────────────────────
echo ""
echo "📊 Agent State:"
if [ -f "$STATE_FILE" ]; then
  if command -v jq &> /dev/null; then
    STATE=$(cat "$STATE_FILE")

    # Core fields
    MARKET_OPEN=$(echo "$STATE" | jq -r '.futures_market_open // false')
    SESSION_OPEN=$(echo "$STATE" | jq -r '.strategy_session_open // false')
    DATA_FRESH=$(echo "$STATE" | jq -r '.data_fresh // false')
    EXEC_MODE=$(echo "$STATE" | jq -r '.execution.mode // "unknown"')
    EXEC_ENABLED=$(echo "$STATE" | jq -r '.execution.enabled // false')
    CYCLES=$(echo "$STATE" | jq -r '.cycle_count // 0')
    SIGNALS=$(echo "$STATE" | jq -r '.signal_count // 0')
    BUFFER_SIZE=$(echo "$STATE" | jq -r '.buffer_size // 0')
    BUFFER_TARGET=$(echo "$STATE" | jq -r '.buffer_size_target // 100')
    SYMBOL=$(echo "$STATE" | jq -r '.config.symbol // "N/A"')
    TIMEFRAME=$(echo "$STATE" | jq -r '.config.timeframe // "N/A"')
    LAST_DIAG=$(echo "$STATE" | jq -r '.signal_diagnostics // "N/A"')
    LAST_BAR_AGE=$(echo "$STATE" | jq -r '.latest_bar_age_minutes // "?"')
    LAST_SUCCESS=$(echo "$STATE" | jq -r '.last_successful_cycle // "(no data yet)"')

    echo "  Market Open:  $MARKET_OPEN"
    echo "  Session Open: $SESSION_OPEN"
    echo "  Data Fresh:   $DATA_FRESH (age: ${LAST_BAR_AGE} min)"
    echo "  Execution:    $EXEC_MODE (enabled=$EXEC_ENABLED)"
    echo "  Config:       $SYMBOL @ $TIMEFRAME"
    echo "  Buffer:       $BUFFER_SIZE / $BUFFER_TARGET bars"
    echo "  Cycles:       $CYCLES | Signals: $SIGNALS"
    echo "  Last Success: $LAST_SUCCESS"
    echo "  Diagnostics:  $LAST_DIAG"

    # Trading bot section
    echo ""
    echo "🧠 Trading Bot:"
    HAS_BOT=$(echo "$STATE" | jq -r 'has("trading_bot")')
    if [ "$HAS_BOT" = "true" ]; then
      echo "$STATE" | jq -r '
        "  Enabled:  \(.trading_bot.enabled // false)",
        "  Selected: \(.trading_bot.selected // "N/A")"
      '
    else
      echo "  (not available in state)"
    fi
  else
    echo "  (install jq for pretty output)"
    echo "  Raw: $(head -c 200 "$STATE_FILE")..."
  fi
else
  echo "  ❌ State file not found: $STATE_FILE"
fi

# ── 4. Recent signals ────────────────────────────────────────────────────────
echo ""
echo "📈 Recent Activity:"
TODAY=$(date -u +%Y-%m-%d)
if [ -f "$SIGNALS_FILE" ]; then
  TODAY_SIGNALS=$(grep -c "$TODAY" "$SIGNALS_FILE" 2>/dev/null || echo "0")
  echo "  Signals today: $TODAY_SIGNALS"

  LAST_SIGNAL=$(tail -n 1 "$SIGNALS_FILE" 2>/dev/null | jq -r '.signal_id // "none"' 2>/dev/null || echo "unknown")
  echo "  Last signal:   $LAST_SIGNAL"
else
  echo "  (no signals file: $SIGNALS_FILE)"
fi

# ── 5. Log health ────────────────────────────────────────────────────────────
echo ""
echo "📝 Recent Logs (last ~200 lines):"
if [ -f "$LOG_FILE" ]; then
  RECENT_ERRORS=$(tail -n 200 "$LOG_FILE" | grep -c "ERROR" || true)
  RECENT_WARNS=$(tail -n 200 "$LOG_FILE" | grep -c "WARNING" || true)
  echo "  Errors:   ${RECENT_ERRORS:-0}"
  echo "  Warnings: ${RECENT_WARNS:-0}"
else
  echo "  (no log file: $LOG_FILE)"
fi

# ── 6. Quick sanity ──────────────────────────────────────────────────────────
echo ""
echo "🎯 Quick Sanity:"
if [ "${MARKET_OPEN:-false}" = "true" ] && [ "${SESSION_OPEN:-false}" = "true" ] && [ "${DATA_FRESH:-false}" = "true" ]; then
  echo "  ✅ Ready to generate signals"
else
  echo "  ⚠️  Not ready: market=${MARKET_OPEN:-unknown}, session=${SESSION_OPEN:-unknown}, data=${DATA_FRESH:-unknown}"
fi

echo ""
echo "=== Status Check Complete ==="
