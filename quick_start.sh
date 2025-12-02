#!/bin/bash
# PearlAlgo Quick Start Script
# This script helps you get up and running quickly

set -e

echo "🚀 PearlAlgo Quick Start"
echo "========================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

# Activate virtual environment
echo -e "${YELLOW}Activating virtual environment...${NC}"
source .venv/bin/activate

# Install/upgrade dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -U pip > /dev/null 2>&1
pip install -e . > /dev/null 2>&1
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Creating .env file from template...${NC}"
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✓ .env file created${NC}"
        echo -e "${YELLOW}⚠️  Please edit .env with your API keys and settings${NC}"
    else
        echo -e "${RED}✗ .env.example not found${NC}"
    fi
else
    echo -e "${GREEN}✓ .env file exists${NC}"
fi

# Run verification
echo ""
echo -e "${YELLOW}Running setup verification...${NC}"
python scripts/verify_setup.py

# Ask what to do next
echo ""
echo -e "${GREEN}Setup complete! What would you like to do next?${NC}"
echo ""
echo "1. Run tests"
echo "2. Start paper trading"
echo "3. Run backtest"
echo "4. View dashboard"
echo "5. Exit"
echo ""
read -p "Enter choice (1-5): " choice

case $choice in
    1)
        echo ""
        echo -e "${YELLOW}Running tests...${NC}"
        pytest tests/ -v --cov=src/pearlalgo --cov-report=term-missing
        ;;
    2)
        echo ""
        echo -e "${YELLOW}Starting paper trading...${NC}"
        echo "Press Ctrl+C to stop"
        python -m pearlalgo.live.langgraph_trader \
            --symbols ES \
            --strategy sr \
            --mode paper \
            --interval 60
        ;;
    3)
        echo ""
        echo -e "${YELLOW}Running backtest...${NC}"
        if [ -f "data/futures/ES_15m_sample.csv" ]; then
            python -m pearlalgo.backtesting.vectorbt_engine \
                --data data/futures/ES_15m_sample.csv \
                --symbol ES \
                --strategy sr
        else
            echo -e "${RED}✗ Sample data file not found${NC}"
            echo "Please provide a data file:"
            read -p "Data file path: " datafile
            python -m pearlalgo.backtesting.vectorbt_engine \
                --data "$datafile" \
                --symbol ES \
                --strategy sr
        fi
        ;;
    4)
        echo ""
        echo -e "${YELLOW}Starting dashboard...${NC}"
        echo "Dashboard will open in your browser"
        streamlit run scripts/streamlit_dashboard.py
        ;;
    5)
        echo ""
        echo -e "${GREEN}Goodbye!${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

