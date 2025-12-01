#!/bin/bash
# Quick start script for standard futures strategy (ES, NQ, GC)

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "🚀 Starting Standard Futures Strategy..."
echo ""
echo "Symbols: ES, NQ, GC"
echo "Strategy: Support/Resistance"
echo "Interval: 5 minutes"
echo ""
echo "This will start trading in the background."
echo "Use 'pearlalgo dashboard' in another terminal to monitor."
echo ""

# Create logs directory if it doesn't exist
mkdir -p logs

# Start in background
nohup pearlalgo --verbosity VERBOSE trade auto \
  ES NQ GC \
  --strategy sr \
  --interval 300 \
  --tiny-size 1 \
  --ib-client-id 5 \
  --log-file logs/standard_trading.log \
  --log-level INFO > logs/standard_console.log 2>&1 &

PID=$!
echo "✅ Standard strategy started (PID: $PID)"
echo ""
echo "To monitor (recommended: use 2 terminals):"
echo ""
echo "  Terminal 1 - Status Dashboard:"
echo "    pearlalgo dashboard"
echo ""
echo "  Terminal 2 - Live Feed:"
echo "    pearlalgo monitor --live-feed --log-file logs/standard_console.log"
echo ""
echo "  Or view logs directly:"
echo "    tail -f logs/standard_trading.log    # Trading decisions"
echo "    tail -f logs/standard_console.log    # Console output"
echo ""
echo "To stop:"
echo "  kill $PID"
echo "  # or"
echo "  pkill -f 'pearlalgo trade auto'"
echo ""

