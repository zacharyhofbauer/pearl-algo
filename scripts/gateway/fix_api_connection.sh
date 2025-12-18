#!/bin/bash
# Fix IBKR Gateway API Connection Issues
# 
# This script addresses the "API client needs write access" dialog that blocks connections

echo "=== IBKR Gateway API Connection Fix ==="
echo ""

# Check if Gateway is running
if pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "⚠️  Gateway is running. Stopping it first..."
    pkill -f "java.*IBC.jar"
    sleep 3
fi

echo "Gateway stopped. Configuration has been updated:"
echo "  - ReadOnlyApi=no (allows write access to avoid dialog)"
echo "  - MasterAPIclientId=0 (proper client ID handling)"
echo ""
echo "Restarting Gateway with new configuration..."
echo ""

cd ~/pearlalgo-dev-ai-agents
./scripts/gateway/start_ibgateway_ibc.sh

echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Wait 60-90 seconds for Gateway to fully start and authenticate"
echo "2. If the 'write access' dialog still appears, you may need to:"
echo "   a. Connect via VNC and manually accept it ONCE"
echo "   b. Gateway will remember the setting after that"
echo ""
echo "3. Test connection:"
echo "   python3 -c \"from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1', 4002, clientId=11); print('Connected!' if ib.isConnected() else 'Failed'); ib.disconnect()\""
echo ""






