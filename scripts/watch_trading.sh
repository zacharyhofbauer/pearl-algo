#!/bin/bash
# Watch trading activity in real-time

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "👀 Watching Trading Activity..."
echo "Press Ctrl+C to stop"
echo ""

# Watch both logs
tail -f logs/test_trading.log logs/micro_trading.log 2>/dev/null | grep -E "(INFO|WARNING|ERROR|signal|trade|executing|EXECUTING|FLAT|LONG|SHORT)" --color=always

