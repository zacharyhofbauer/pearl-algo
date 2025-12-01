#!/bin/bash
# Show live trading activity from console output

cd "$(dirname "$0")/.."

echo "📊 Live Trading Activity"
echo "========================"
echo ""
echo "This shows what the trading agent is doing in real-time"
echo "Press Ctrl+C to stop"
echo ""

# Check if process is running
if ! pgrep -f "pearlalgo trade auto" > /dev/null; then
    echo "❌ No trading process running!"
    echo "Start it with: pearlalgo trade auto --symbols MES --strategy sr --interval 30"
    exit 1
fi

echo "✅ Trading process is running"
echo ""

# Show recent activity from console log
if [ -f "logs/micro_console.log" ]; then
    echo "📝 Recent Console Output:"
    echo "---"
    tail -20 logs/micro_console.log
    echo ""
    echo "👀 Watching for new activity (Ctrl+C to stop)..."
    echo ""
    tail -f logs/micro_console.log 2>/dev/null | grep -E "(Analyzing|signal|FLAT|LONG|SHORT|EXECUTING|Cycle|P&L)" --line-buffered --color=always
elif [ -f "logs/test_trading.log" ]; then
    echo "📝 Recent Activity:"
    echo "---"
    tail -20 logs/test_trading.log | grep -E "(INFO|signal|trade|executing)" --color=always
    echo ""
    echo "👀 Watching for new activity (Ctrl+C to stop)..."
    echo ""
    tail -f logs/test_trading.log 2>/dev/null | grep -E "(INFO|signal|trade|executing|FLAT|LONG|SHORT)" --line-buffered --color=always
else
    echo "⚠️  No log files found. The trading process may not be outputting to logs."
    echo "Try running in foreground to see output:"
    echo "  pearlalgo --verbosity VERBOSE trade auto --symbols MES --strategy sr --interval 30"
fi

