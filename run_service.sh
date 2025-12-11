#!/bin/bash
# Quick script to start the continuous service

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

cd "$(dirname "$0")"

echo -e "${GREEN}🚀 Starting Continuous Service${NC}"
echo "=================================================="
echo ""

# Activate virtual environment
if [ -d ".venv" ]; then
    echo -e "${YELLOW}📦 Activating virtual environment...${NC}"
    source .venv/bin/activate
else
    echo -e "${RED}❌ Virtual environment not found. Run setup_and_test.sh first${NC}"
    exit 1
fi

# Check config
if [ ! -f "config/config.yaml" ]; then
    echo -e "${RED}❌ Config file not found: config/config.yaml${NC}"
    exit 1
fi

# Create logs directory
mkdir -p logs
mkdir -p data

# Check environment variables
echo -e "${YELLOW}📋 Checking environment...${NC}"
if [ -z "$POLYGON_API_KEY" ]; then
    echo -e "${RED}❌ POLYGON_API_KEY not set - service will fail without it${NC}"
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo -e "${YELLOW}⚠️  Telegram not configured (alerts disabled)${NC}"
fi

echo ""
echo -e "${GREEN}▶️  Starting service...${NC}"
echo "   Config: config/config.yaml"
echo "   Logs: logs/continuous_service.log"
echo "   Health: http://localhost:8080/healthz"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
echo ""

# Start service
python3 -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/continuous_service.log \
    --health-port 8080
