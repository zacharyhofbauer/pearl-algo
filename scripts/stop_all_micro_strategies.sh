#!/bin/bash
# Stop all micro strategies

cd "$(dirname "$0")/.."

echo "🛑 Stopping all micro strategies..."
echo ""

# Try to read PIDs from file
if [ -f logs/micro_strategies_pids.txt ]; then
    echo "Stopping processes from PID file..."
    while read pid; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Stopping PID $pid..."
            kill "$pid" 2>/dev/null
        fi
    done < logs/micro_strategies_pids.txt
    rm -f logs/micro_strategies_pids.txt
fi

# Also kill any remaining trading processes
echo "Stopping any remaining trading processes..."
pkill -f "pearlalgo trade auto" 2>/dev/null

# Wait a moment for processes to stop
sleep 2

# Check if any are still running
if pgrep -f "pearlalgo trade auto" > /dev/null; then
    echo "⚠️  Some processes still running, force killing..."
    pkill -9 -f "pearlalgo trade auto" 2>/dev/null
    sleep 1
fi

# Final check
if pgrep -f "pearlalgo trade auto" > /dev/null; then
    echo "❌ Some processes may still be running"
    echo "   Run: pkill -9 -f 'pearlalgo trade auto'"
else
    echo "✅ All micro strategies stopped"
fi

echo ""

