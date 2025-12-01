#!/bin/bash
# Quick start script for micro strategy with live monitoring

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "🚀 Starting Micro Strategy..."
echo ""
echo "This will start trading in the background."
echo "Use 'pearlalgo dashboard' in another terminal to monitor."
echo ""

# Start in background
nohup pearlalgo --verbosity VERBOSE trade auto \
  --symbols MGC MYM MCL MNQ MES \
  --strategy sr \
  --interval 60 \
  --tiny-size 3 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 10 \
  --log-file logs/micro_trading.log > logs/micro_console.log 2>&1 &

PID=$!
echo "✅ Micro strategy started (PID: $PID)"
echo ""
echo "To monitor:"
echo "  pearlalgo dashboard          # Live dashboard"
echo "  tail -f logs/micro_trading.log  # Trading log"
echo "  tail -f logs/micro_console.log  # Console output"
echo ""
echo "To stop:"
echo "  kill $PID"
echo "  # or"
echo "  pkill -f 'pearlalgo trade auto'"
echo ""

