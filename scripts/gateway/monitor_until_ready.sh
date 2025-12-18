#!/bin/bash
# Monitor Gateway until API is ready

echo "=== Monitoring Gateway until API is ready ==="
echo ""

MAX_WAIT=300  # 5 minutes
CHECK_INTERVAL=5
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if ss -tuln 2>/dev/null | grep -q ":4002"; then
        echo ""
        echo "✅✅✅ SUCCESS! API port 4002 is listening!"
        echo ""
        echo "Gateway is ready for connections!"
        echo ""
        echo "You can now start the NQ Agent service:"
        echo "   ./scripts/lifecycle/start_nq_agent_service.sh"
        exit 0
    fi
    
    if [ $((ELAPSED % 15)) -eq 0 ] && [ $ELAPSED -gt 0 ]; then
        echo "   Still waiting... (${ELAPSED}s elapsed)"
        if ! pgrep -f "java.*IBC.jar" > /dev/null; then
            echo "   ⚠️  Gateway process not running!"
            exit 1
        fi
    fi
    
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
done

echo ""
echo "⏱️  Timeout after ${MAX_WAIT} seconds"
echo "   Check Gateway status: ./scripts/gateway/check_tws_conflict.sh"
exit 1






