#!/bin/bash
# Monitor Trades in Real-Time
# This script shows live trade activity

set -e

echo "📊 PearlAlgo Trade Monitor"
echo "==========================="
echo ""
echo "Monitoring trades, signals, and performance..."
echo "Press Ctrl+C to stop"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to display latest trades
show_trades() {
    perf_file="data/performance/futures_decisions.csv"
    if [ -f "$perf_file" ]; then
        echo -e "${BLUE}=== Latest Trades ===${NC}"
        tail -5 "$perf_file" | column -t -s, 2>/dev/null || tail -5 "$perf_file"
        echo ""
    else
        echo -e "${YELLOW}No trades yet...${NC}"
    fi
}

# Function to display latest signals
show_signals() {
    signals_dir="signals"
    if [ -d "$signals_dir" ]; then
        latest_signal=$(ls -t "$signals_dir"/*_signals.csv 2>/dev/null | head -1)
        if [ -n "$latest_signal" ]; then
            echo -e "${BLUE}=== Latest Signals ===${NC}"
            tail -3 "$latest_signal" | column -t -s, 2>/dev/null || tail -3 "$latest_signal"
            echo ""
        fi
    fi
}

# Function to show system status
show_status() {
    echo -e "${BLUE}=== System Status ===${NC}"
    
    # Check if trading process is running
    if pgrep -f "langgraph_trader" > /dev/null; then
        echo -e "${GREEN}✓ Trading system is running${NC}"
    else
        echo -e "${RED}✗ Trading system not running${NC}"
    fi
    
    # Check IBKR Gateway
    if pgrep -f IbcGateway > /dev/null; then
        echo -e "${GREEN}✓ IBKR Gateway is running${NC}"
    else
        echo -e "${YELLOW}⚠ IBKR Gateway not running${NC}"
    fi
    
    echo ""
}

# Main monitoring loop
while true; do
    clear
    echo "📊 PearlAlgo Trade Monitor - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    echo ""
    
    show_status
    show_trades
    show_signals
    
    echo -e "${YELLOW}Refreshing in 5 seconds... (Ctrl+C to stop)${NC}"
    sleep 5
done

