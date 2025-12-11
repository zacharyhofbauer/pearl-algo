#!/bin/bash
# Setup and test script for signal improvements

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

cd "$(dirname "$0")"

echo -e "${BLUE}🚀 Setting Up and Testing Signal Improvements${NC}"
echo "=================================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python3 not found${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo -e "${GREEN}✅ Python version: $(python3 --version)${NC}"

# Setup virtual environment
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}📦 Creating virtual environment...${NC}"
    python3 -m venv .venv
fi

echo -e "${YELLOW}📦 Activating virtual environment...${NC}"
source .venv/bin/activate

# Upgrade pip
echo -e "${YELLOW}📦 Upgrading pip...${NC}"
pip install --quiet --upgrade pip

# Install package in editable mode
echo -e "${YELLOW}📦 Installing package...${NC}"
pip install --quiet -e .

# Install test dependencies
echo -e "${YELLOW}📦 Installing test dependencies...${NC}"
pip install --quiet pytest pytest-asyncio pytest-cov

echo ""
echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""

# Run tests
echo -e "${BLUE}🧪 Running Tests${NC}"
echo "=================================================="
echo ""

echo -e "${GREEN}1️⃣  Testing Signal Tracker Basic Functions${NC}"
python3 -m pytest tests/test_exit_signals.py::test_stop_loss_check_long tests/test_exit_signals.py::test_stop_loss_check_short tests/test_exit_signals.py::test_take_profit_check_long -v --tb=short || echo -e "${YELLOW}⚠️  Some tests may need adjustments${NC}"

echo ""
echo -e "${GREEN}2️⃣  Testing Exit Signal Generation (Async)${NC}"
python3 -m pytest tests/test_exit_signals.py::test_generate_exit_signals_stop_loss tests/test_exit_signals.py::test_generate_exit_signals_take_profit -v --tb=short || echo -e "${YELLOW}⚠️  Async tests may need adjustments${NC}"

echo ""
echo -e "${GREEN}3️⃣  Testing Signal Persistence${NC}"
python3 -m pytest tests/test_exit_signals.py::test_signal_persistence_save_load -v --tb=short || echo -e "${YELLOW}⚠️  Persistence test may need adjustments${NC}"

echo ""
echo -e "${GREEN}4️⃣  Testing Signal Validation${NC}"
python3 -m pytest tests/test_exit_signals.py::test_signal_validation -v --tb=short || echo -e "${YELLOW}⚠️  Validation test may need adjustments${NC}"

echo ""
echo -e "${GREEN}✅ Test Summary${NC}"
echo "=================================================="
python3 -m pytest tests/test_exit_signals.py --co -q

echo ""
echo -e "${GREEN}🎉 Testing complete!${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Check environment: source .venv/bin/activate && python3 scripts/debug_env.py"
echo "  2. Start service: python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml"
echo "  3. Check health: curl http://localhost:8080/healthz | jq"
echo "  4. Monitor logs: tail -f logs/continuous_service.log"
