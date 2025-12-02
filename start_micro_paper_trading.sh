#!/bin/bash
# Start Paper Trading with Micro Contracts
# This script starts the LangGraph trading system with micro futures

set -e

echo "🚀 Starting Paper Trading with Micro Contracts"
echo "================================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source .venv/bin/activate
fi

# Check IBKR Gateway
echo -e "${BLUE}Checking IBKR Gateway...${NC}"
if pgrep -f IbcGateway > /dev/null; then
    echo -e "${GREEN}✓ IBKR Gateway is running${NC}"
else
    echo -e "${YELLOW}⚠ IBKR Gateway not detected. Starting anyway (will use dummy broker if needed)...${NC}"
fi

# Create necessary directories
mkdir -p logs
mkdir -p data/performance
mkdir -p data/state_cache
mkdir -p signals

echo ""
echo -e "${BLUE}Starting LangGraph Paper Trading System...${NC}"
echo -e "${YELLOW}Symbols: MES, MNQ (Micro E-mini S&P 500 and Nasdaq)${NC}"
echo -e "${YELLOW}Strategy: Support/Resistance${NC}"
echo -e "${YELLOW}Mode: Paper Trading${NC}"
echo -e "${YELLOW}Interval: 60 seconds${NC}"
echo ""
echo -e "${GREEN}Press Ctrl+C to stop${NC}"
echo ""

# Start the trading system
python -m pearlalgo.live.langgraph_trader \
    --symbols MES MNQ \
    --strategy sr \
    --mode paper \
    --interval 60 \
    --max-cycles 0  # 0 = run indefinitely

