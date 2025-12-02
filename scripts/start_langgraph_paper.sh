#!/bin/bash
# Quick start script for LangGraph paper trading

set -e

echo "=========================================="
echo "LangGraph Multi-Agent Trading System"
echo "Paper Trading Mode"
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
    echo "   Please create .env file (see .env.template.all-llm)"
    exit 1
fi

# Check if config.yaml exists
if [ ! -f config/config.yaml ]; then
    echo "❌ config/config.yaml not found!"
    exit 1
fi

# Verify paper mode
if grep -q "PEARLALGO_PROFILE=live" .env; then
    echo "⚠️  WARNING: PEARLALGO_PROFILE is set to 'live'"
    echo "   This script is for paper trading only!"
    read -p "   Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get symbols from command line or use default
SYMBOLS=${1:-"ES NQ"}
STRATEGY=${2:-"sr"}

echo "Starting LangGraph trader..."
echo "  Symbols: $SYMBOLS"
echo "  Strategy: $STRATEGY"
echo "  Mode: paper"
echo

# Run the trader
python -m pearlalgo.live.langgraph_trader \
    --symbols $SYMBOLS \
    --strategy $STRATEGY \
    --mode paper

