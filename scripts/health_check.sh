#!/bin/bash
# Quick 2-minute health check for PearlAlgo trading system
# Usage: ./scripts/health_check.sh

set -e
cd "$(dirname "$0")/.."

echo "=== PearlAlgo Health Check ==="
echo ""

# 1. Service status
echo "📦 Services:"
if pgrep -f "pearlalgo.nq_agent.main" > /dev/null; then
    echo "  ✅ NQ Agent: RUNNING"
else
    echo "  ❌ NQ Agent: NOT RUNNING"
fi

if pgrep -f "telegram_command_handler" > /dev/null; then
    echo "  ✅ Telegram Handler: RUNNING"
else
    echo "  ❌ Telegram Handler: NOT RUNNING"
fi

# 2. IBKR Gateway
echo ""
echo "🔌 Gateway:"
if pgrep -f "ibgateway\|IB Gateway\|java.*jts" > /dev/null; then
    echo "  ✅ IBKR Gateway: RUNNING"
else
    echo "  ❌ IBKR Gateway: NOT RUNNING"
fi

# 3. State file health
echo ""
echo "📊 Agent State:"
if [ -f "data/nq_agent_state/state.json" ]; then
    STATE=$(cat data/nq_agent_state/state.json)
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
    echo "  ❌ State file not found"
fi

# 4. Recent signals
echo ""
echo "📈 Recent Activity:"
TODAY=$(date -u +%Y-%m-%d)
if [ -f "data/nq_agent_state/signals.jsonl" ]; then
    TODAY_SIGNALS=$(grep -c "$TODAY" data/nq_agent_state/signals.jsonl 2>/dev/null || echo "0")
    echo "  Signals today: $TODAY_SIGNALS"
    
    LAST_SIGNAL=$(tail -n 1 data/nq_agent_state/signals.jsonl 2>/dev/null | jq -r '.signal_id // "none"')
    echo "  Last signal: $LAST_SIGNAL"
else
    echo "  ❌ Signals file not found"
fi

# 5. Log health (last 5 min)
echo ""
echo "📝 Recent Logs (errors/warnings):"
if [ -f "logs/nq_agent.log" ]; then
    RECENT_ERRORS=$(tail -n 200 logs/nq_agent.log | grep -c "ERROR" || true)
    RECENT_WARNS=$(tail -n 200 logs/nq_agent.log | grep -c "WARNING" || true)
    echo "  NQ Agent: ${RECENT_ERRORS:-0} errors, ${RECENT_WARNS:-0} warnings (last ~200 lines)"
fi

# 6. Quick sanity
echo ""
echo "🎯 Quick Sanity:"
if [ "$MARKET_OPEN" = "true" ] && [ "$SESSION_OPEN" = "true" ] && [ "$DATA_FRESH" = "true" ]; then
    echo "  ✅ Ready to generate signals"
else
    echo "  ⚠️  Not ready: market=$MARKET_OPEN, session=$SESSION_OPEN, data=$DATA_FRESH"
fi

echo ""
echo "=== Health Check Complete ==="
