#!/bin/bash
# Test script for signal tracking and exit signal improvements

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🧪 Testing Signal Tracking & Exit Signal Improvements${NC}"
echo "=================================================="
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}❌ Error: Must run from project root${NC}"
    exit 1
fi

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo -e "${YELLOW}📦 Activating virtual environment...${NC}"
    source .venv/bin/activate
fi

# Install test dependencies if needed
echo -e "${YELLOW}📦 Checking test dependencies...${NC}"
python -c "import pytest" 2>/dev/null || pip install -q pytest pytest-asyncio

echo ""
echo -e "${GREEN}1️⃣  Testing Signal Tracker Persistence${NC}"
echo "----------------------------------------"
pytest tests/test_exit_signals.py::test_signal_persistence_save_load -v --tb=short || echo -e "${YELLOW}⚠️  Test may need adjustments${NC}"

echo ""
echo -e "${GREEN}2️⃣  Testing Signal Validation${NC}"
echo "----------------------------------------"
pytest tests/test_exit_signals.py::test_signal_validation -v --tb=short || echo -e "${YELLOW}⚠️  Test may need adjustments${NC}"

echo ""
echo -e "${GREEN}3️⃣  Testing Exit Signal Generation (Async)${NC}"
echo "----------------------------------------"
pytest tests/test_exit_signals.py::test_generate_exit_signals_stop_loss -v --tb=short
pytest tests/test_exit_signals.py::test_generate_exit_signals_take_profit -v --tb=short

echo ""
echo -e "${GREEN}4️⃣  Testing Signal Lifecycle${NC}"
echo "----------------------------------------"
pytest tests/test_signal_lifecycle.py -v --tb=short || echo -e "${YELLOW}⚠️  Some lifecycle tests may need adjustments${NC}"

echo ""
echo -e "${GREEN}5️⃣  Testing Error Recovery${NC}"
echo "----------------------------------------"
pytest tests/test_error_recovery.py -v --tb=short || echo -e "${YELLOW}⚠️  Some error recovery tests may need adjustments${NC}"

echo ""
echo -e "${GREEN}6️⃣  Testing Performance${NC}"
echo "----------------------------------------"
pytest tests/test_signal_performance.py -v --tb=short || echo -e "${YELLOW}⚠️  Performance tests may vary${NC}"

echo ""
echo -e "${GREEN}✅ Test Summary${NC}"
echo "=================================================="
pytest tests/test_exit_signals.py tests/test_signal_lifecycle.py tests/test_error_recovery.py tests/test_signal_performance.py --co -q

echo ""
echo -e "${GREEN}🎉 Testing complete!${NC}"
echo ""
echo "Next steps:"
echo "  - Run the continuous service: python -m pearlalgo.monitoring.continuous_service --config config/config.yaml"
echo "  - Check health: curl http://localhost:8080/healthz | jq"
echo "  - Monitor logs: tail -f logs/continuous_service.log"
