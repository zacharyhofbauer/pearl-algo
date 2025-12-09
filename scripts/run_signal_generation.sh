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

# Get symbols and strategy from command line
# Handle multiple symbols: ./script.sh ES NQ sr  or  ./script.sh "ES NQ" sr
if [ $# -eq 0 ]; then
    SYMBOLS="ES NQ"
    STRATEGY="sr"
elif [ $# -eq 1 ]; then
    SYMBOLS="$1"
    STRATEGY="sr"
elif [ $# -eq 2 ]; then
    # If second arg is a known strategy, treat first as single symbol
    if [[ "$2" =~ ^(sr|ma_cross|breakout|mean_reversion)$ ]]; then
        SYMBOLS="$1"
        STRATEGY="$2"
    else
        # Otherwise treat as multiple symbols
        SYMBOLS="$1 $2"
        STRATEGY="sr"
    fi
else
    # 3+ args: last one is strategy, rest are symbols
    STRATEGY="${!#}"
    SYMBOLS="${@:1:$(($#-1))}"
fi

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
