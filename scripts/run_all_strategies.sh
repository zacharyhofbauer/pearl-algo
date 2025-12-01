#!/bin/bash
# Run both regular and micro strategies simultaneously
# Regular contracts: ES, NQ, GC, YM, RTY, CL
# Micro contracts: MGC, MYM, MRTY, MCL (faster pace, 3-5 contracts)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
source .venv/bin/activate

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  🎯 Multi-Strategy Trading Setup                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check if screen is available
if ! command -v screen &> /dev/null; then
    echo "⚠️  screen not found. Installing..."
    echo "   Please install: sudo apt-get install screen"
    exit 1
fi

echo "Starting strategies in screen sessions..."
echo ""

# Regular contracts - slower pace (5 min intervals)
echo "📊 Starting Regular Contracts (ES, NQ, GC, YM, RTY, CL) - 5min intervals..."
screen -dmS regular-contracts bash -c "
cd $PROJECT_ROOT
source .venv/bin/activate
python scripts/automated_trading.py \
  --symbols ES NQ GC YM RTY CL \
  --sec-types FUT FUT FUT FUT FUT FUT \
  --strategy sr \
  --interval 300 \
  --tiny-size 1 \
  --ib-client-id 1 \
  --log-file logs/regular_trading.log
"

sleep 2

# Micro contracts - faster pace (1 min intervals, 3-5 contracts)
# Using all available micro contracts: MGC, MYM, MCL, MNQ, MES
echo "⚡ Starting Micro Contracts (MGC, MYM, MCL, MNQ, MES) - 1min intervals, 3-5 contracts..."
screen -dmS micro-contracts bash -c "
cd $PROJECT_ROOT
source .venv/bin/activate
python scripts/automated_trading.py \
  --symbols MGC MYM MCL MNQ MES \
  --sec-types FUT FUT FUT FUT FUT \
  --strategy sr \
  --interval 60 \
  --tiny-size 3 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 10 \
  --log-file logs/micro_trading.log
"

sleep 2

echo ""
echo "✅ Both strategies started!"
echo ""
echo "📋 To view sessions:"
echo "   screen -r regular-contracts  # Regular contracts (5min)"
echo "   screen -r micro-contracts    # Micro contracts (1min)"
echo ""
echo "📊 To list all sessions:"
echo "   screen -ls"
echo ""
echo "🛑 To stop a session:"
echo "   screen -r regular-contracts"
echo "   # Press Ctrl+C to stop, then type 'exit'"
echo ""

