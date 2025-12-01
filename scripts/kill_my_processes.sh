#!/bin/bash
# Kill only trading-related processes owned by current user (safer)

echo "🔍 Finding trading processes owned by $(whoami)..."

# Get current user
USER=$(whoami)

# Kill trading processes owned by current user only
echo "Killing trading processes..."
pkill -u $USER -f "pearlalgo trade"
pkill -u $USER -f "automated_trading"
pkill -u $USER -f "manual_trade_test"
pkill -u $USER -f "python.*trade"
pkill -u $USER -f "python.*broker"
pkill -u $USER -f "python.*agent"

# Wait a moment
sleep 1

# Check remaining TRADING processes only (exclude cursor, gateway, etc.)
REMAINING=$(ps aux | awk -v user="$USER" '$1 == user {print}' | grep -E "(pearlalgo trade|automated_trading|manual_trade_test|python.*trade|python.*broker|python.*agent)" | grep -v -E "(cursor|gateway|ibgateway|java|node|bash.*ibc)" | grep -v grep | wc -l)

if [ "$REMAINING" -eq 0 ]; then
    echo "✅ All your trading processes killed"
    echo ""
    echo "Note: Cursor/VS Code and IB Gateway processes are left running (as expected)"
else
    echo "⚠️  Some trading processes may still be running:"
    ps aux | awk -v user="$USER" '$1 == user {print}' | grep -E "(pearlalgo trade|automated_trading|manual_trade_test|python.*trade|python.*broker|python.*agent)" | grep -v -E "(cursor|gateway|ibgateway|java|node|bash.*ibc)" | grep -v grep
    echo ""
    echo "To force kill your trading processes:"
    echo "  pkill -9 -u $USER -f 'pearlalgo trade'"
    echo "  pkill -9 -u $USER -f 'automated_trading'"
fi

