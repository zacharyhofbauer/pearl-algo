#!/bin/bash
# ============================================================================
# Category: Gateway
# Purpose: Stop IBKR Gateway gracefully (IBC method)
# Usage: ./scripts/gateway/stop_ibgateway_ibc.sh
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

echo "=== Stopping IB Gateway ==="
echo ""

# Check if Gateway is running
GATEWAY_PID=$(pgrep -f "java.*IBC.jar")
if [ -z "$GATEWAY_PID" ]; then
    echo "❌ IB Gateway is not running"
    exit 1
fi

echo "Found Gateway process: $GATEWAY_PID"
echo "Stopping Gateway..."

# Try to use IBC stop script first (but don't fail if telnet is missing)
if [ -f "$PROJECT_DIR/ibkr/ibc/stop.sh" ]; then
    echo "Using IBC stop script..."
    cd "$PROJECT_DIR/ibkr/ibc"
    ./stop.sh 2>/dev/null || true  # Ignore errors (e.g., telnet not found)
    sleep 3
else
    echo "IBC stop script not found, killing process directly..."
    kill "$GATEWAY_PID" 2>/dev/null
    sleep 2
fi

# Check if still running and force kill if needed
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "⚠️  Process didn't stop gracefully, force killing..."
    pkill -9 -f "java.*IBC.jar"
    sleep 1
fi

# Verify it's stopped
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ Failed to stop Gateway"
    exit 1
else
    echo "✅ IB Gateway stopped"
fi

echo ""



