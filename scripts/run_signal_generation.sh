#!/bin/bash
# Run Signal Generation Mode
# Generates signals and tracks PnL without executing trades

set -e

echo "=========================================="
echo "PearlAlgo Signal Generation Mode"
echo "=========================================="
echo

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtual environment not activated"
    echo "   Activating .venv..."
    source .venv/bin/activate
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "   Please create .env file"
    exit 1
fi

# Get symbols from command line or use default
SYMBOLS=${1:-"ES NQ"}
STRATEGY=${2:-"sr"}

echo "Starting signal generation..."
echo "  Symbols: $SYMBOLS"
echo "  Strategy: $STRATEGY"
echo "  Mode: signal-only (no trade execution)"
echo

# Run the trader in signal-only mode
python -m pearlalgo.live.langgraph_trader \
    --symbols $SYMBOLS \
    --strategy $STRATEGY \
    --mode paper
