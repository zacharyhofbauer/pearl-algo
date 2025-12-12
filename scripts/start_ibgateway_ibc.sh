#!/bin/bash
# Start IB Gateway with IBC for read-only data access

echo "=== Starting IB Gateway with IBC (Read-Only Mode) ==="
echo ""

# Check if already running
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "⚠️  IB Gateway is already running!"
    ps aux | grep "IBC.jar" | grep -v grep
    echo ""
    echo "To stop it: ~/pearlalgo-dev-ai-agents/ibkr/ibc/stop.sh"
    exit 1
fi

# Check if IBC is configured
if [ ! -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/config-auto.ini ]; then
    echo "❌ IBC not configured. Run:"
    echo "   ~/pearlalgo-dev-ai-agents/scripts/configure_ibc_readonly.sh"
    exit 1
fi

# Ensure Xvfb is running for headless operation
echo "Ensuring Xvfb virtual display is running..."
source ~/pearlalgo-dev-ai-agents/ibkr/ibc/start_xvfb.sh
if [ $? -ne 0 ]; then
    echo "❌ Failed to start Xvfb. Cannot start IB Gateway."
    exit 1
fi

# Start IBC
echo "Starting IB Gateway..."
cd ~/pearlalgo-dev-ai-agents/ibkr/ibc

# Use headless version that ensures DISPLAY is set
export DISPLAY=:99
# Start in background with logging
nohup ./gatewaystart.sh -inline > logs/gateway_$(date +%Y%m%d_%H%M%S).log 2>&1 &
IBC_PID=$!

echo "IB Gateway starting (PID: $IBC_PID)"
echo "Log file: ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log"
echo ""

# Wait a bit and check
sleep 5

if ps -p $IBC_PID > /dev/null 2>&1; then
    echo "✅ IB Gateway process is running"
else
    echo "⚠️  Process may have exited - check logs"
    tail -20 ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log 2>/dev/null | tail -10
fi

# Check API port
echo ""
echo "Waiting for API to become available..."
sleep 10

if ss -tuln | grep -q ":4002"; then
    echo "✅ API port 4002 is listening!"
    echo ""
    echo "=== IB Gateway is ready for data access ==="
    echo ""
    echo "Test connection:"
    echo "  cd ~/pearlalgo-dev-ai-agents"
    echo "  python3 test_ibkr_connection.py"
else
    echo "⚠️  Port 4002 not listening yet"
    echo "   IB Gateway may still be starting up or logging in"
    echo "   Check status: ss -tuln | grep 4002"
    echo "   View logs: tail -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log"
fi

echo ""
    echo "To stop IB Gateway: ~/pearlalgo-dev-ai-agents/ibkr/ibc/stop.sh"
    echo "To view logs: tail -f ~/pearlalgo-dev-ai-agents/ibkr/ibc/logs/gateway_*.log"
