#!/bin/bash
# Test live trading with a single symbol to verify it works

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "🧪 Testing Live Trading..."
echo ""
echo "This will test with a single symbol (MES) to verify trading works."
echo "Watch for trade execution in the monitor."
echo ""

# Test with just one symbol, shorter interval for faster testing
pearlalgo --verbosity VERBOSE trade auto \
  --symbols MES \
  --strategy sr \
  --interval 30 \
  --tiny-size 1 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 11 \
  --log-file logs/test_trading.log \
  --log-level INFO

