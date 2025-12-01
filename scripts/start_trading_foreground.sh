#!/bin/bash
# Start trading in foreground so you can see all output

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "🚀 Starting Trading (Foreground Mode - You'll see all output)"
echo ""
echo "This will show you:"
echo "  - Real-time analysis for each symbol"
echo "  - Signal generation (LONG/SHORT/FLAT)"
echo "  - Trade execution when opportunities are found"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Start in foreground with verbose output
pearlalgo --verbosity VERBOSE trade auto \
  --symbols MES \
  --strategy sr \
  --interval 30 \
  --tiny-size 1 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 11 \
  --log-file logs/test_trading.log

