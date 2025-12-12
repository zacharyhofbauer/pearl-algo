#!/bin/bash
# Complete IB Gateway setup script for read-only data access

echo "=== IB Gateway Setup for Read-Only Data Access ==="
echo ""

# 1. Configure jts.ini
echo "1. Configuring jts.ini..."
mkdir -p ~/Jts

# Check if SocketPort already exists
if ! grep -q "SocketPort" ~/Jts/jts.ini 2>/dev/null; then
    echo "   Adding API port settings..."
    cat >> ~/Jts/jts.ini << 'EOF'

# API Configuration for Read-Only Data Access (added automatically)
SocketPort=4002
ReadOnlyAPI=true
EnableReadOnlyAPI=true
MasterAPIclientId=0
EOF
    echo "   ✅ API settings added"
else
    echo "   ✅ API settings already exist"
fi

# 2. Start IB Gateway
echo ""
echo "2. Starting IB Gateway..."
pkill -f ibgateway 2>/dev/null
sleep 2

cd ~/Jts/ibgateway/1041 || exit 1

# Ensure Xvfb is running
echo "   Ensuring Xvfb virtual display is running..."
source ~/ibc/start_xvfb.sh
if [ $? -ne 0 ]; then
    echo "   ❌ Failed to start Xvfb"
    exit 1
fi

# Start with DISPLAY set
echo "   Starting IB Gateway with DISPLAY=:99..."
export DISPLAY=:99
./ibgateway1 > /tmp/ibgateway.log 2>&1 &
GATEWAY_PID=$!

echo "   Process ID: $GATEWAY_PID"
echo "   Log file: /tmp/ibgateway.log"

# 3. Wait and check
echo ""
echo "3. Waiting for IB Gateway to start..."
sleep 10

if ps -p $GATEWAY_PID > /dev/null 2>&1; then
    echo "   ✅ IB Gateway process is running"
else
    echo "   ⚠️  Process may have exited - check logs"
    tail -20 /tmp/ibgateway.log
fi

# 4. Check API port
echo ""
echo "4. Checking API port..."
sleep 5
if ss -tuln | grep -q ":4002"; then
    echo "   ✅ API port 4002 is listening!"
    echo ""
    echo "=== Setup Complete ==="
    echo "IB Gateway is running with read-only API enabled"
    echo "Port 4002 is open for data connections"
    echo ""
    echo "Test connection:"
    echo "  cd ~/pearlalgo-dev-ai-agents"
    echo "  python3 test_ibkr_connection.py"
else
    echo "   ⚠️  Port 4002 not listening yet"
    echo "   This may be normal - IB Gateway needs to:"
    echo "   1. Start up completely"
    echo "   2. Log in (if credentials are saved, this happens automatically)"
    echo "   3. Then enable API port"
    echo ""
    echo "   Check status: ss -tuln | grep 4002"
    echo "   View logs: tail -f /tmp/ibgateway.log"
fi

echo ""
echo "Note: IB Gateway may need to log in first before API becomes available."
echo "If you see login prompts in logs, you may need to configure auto-login."
