#!/bin/bash
# Test API connection to trigger any pending dialogs

echo "=== Testing API Connection ==="
echo ""

# Check if Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ Gateway is not running"
    exit 1
fi

echo "✅ Gateway is running"
echo ""
echo "Attempting API connection to trigger any pending dialogs..."
echo ""

# Try to connect using Python
cd ~/pearlalgo-dev-ai-agents

python3 << 'EOF'
from ib_insync import IB
import time

ib = IB()
try:
    print("Connecting to Gateway at 127.0.0.1:4002...")
    ib.connect('127.0.0.1', 4002, clientId=99, timeout=5)
    if ib.isConnected():
        print("✅✅✅ SUCCESS! API connection established!")
        print("   Gateway is ready for connections")
        ib.disconnect()
        exit(0)
    else:
        print("❌ Connection failed")
        exit(1)
except Exception as e:
    error_str = str(e).lower()
    if "connection refused" in error_str or "111" in str(e):
        print("⏳ API port not yet listening")
        print("   Gateway may still be starting up")
        print("   Or there may be a dialog waiting for approval")
    elif "write access" in error_str or "permission" in error_str:
        print("⚠️  Write access dialog may be blocking connection")
        print("   Check Gateway logs for 'API client needs write access' dialog")
    else:
        print(f"❌ Connection error: {e}")
    exit(1)
EOF

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ API is working! You can now start the service:"
    echo "   ./scripts/lifecycle/start_nq_agent_service.sh"
else
    echo ""
    echo "📋 Next steps:"
    echo "   1. Check Gateway logs: tail -f ibkr/ibc/logs/ibc-*.txt"
    echo "   2. Look for 'API client needs write access' dialog"
    echo "   3. If dialog appears, approve it (may need VNC)"
    echo "   4. Wait 30-60 seconds and try again"
fi





