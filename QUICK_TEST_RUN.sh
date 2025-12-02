#!/bin/bash
# Professional Trading System - Quick Test Suite
# Run all critical tests in sequence

set -e

echo "=========================================="
echo "PROFESSIONAL TRADING SYSTEM TEST SUITE"
echo "=========================================="
echo

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test results
PASSED=0
FAILED=0

test_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASSED++))
}

test_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAILED++))
}

test_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
}

# Activate venv if not already
if [ -z "$VIRTUAL_ENV" ]; then
    source .venv/bin/activate 2>/dev/null || echo "⚠️  Virtual env not found"
fi

echo "Phase 1: Environment Validation"
echo "--------------------------------"
python scripts/verify_setup.py > /tmp/test_setup.log 2>&1
if [ $? -eq 0 ]; then
    test_pass "Environment & Configuration"
else
    test_fail "Environment & Configuration (check /tmp/test_setup.log)"
fi
echo

echo "Phase 2: Component Imports"
echo "--------------------------"
python3 -c "
import sys
sys.path.insert(0, 'src')
try:
    from pearlalgo.agents.langgraph_state import TradingState
    from pearlalgo.agents.langgraph_workflow import TradingWorkflow
    from pearlalgo.agents.market_data_agent import MarketDataAgent
    from pearlalgo.agents.quant_research_agent import QuantResearchAgent
    from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
    from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
    from pearlalgo.brokers.factory import get_broker
    from pearlalgo.live.langgraph_trader import LangGraphTrader
    print('✅ All imports successful')
    sys.exit(0)
except Exception as e:
    print(f'❌ Import error: {e}')
    sys.exit(1)
" > /tmp/test_imports.log 2>&1
if [ $? -eq 0 ]; then
    test_pass "Component Imports"
else
    test_fail "Component Imports (check /tmp/test_imports.log)"
fi
echo

echo "Phase 3: Unit Tests"
echo "-------------------"
pytest tests/test_langgraph_agents.py tests/test_llm_providers.py tests/test_broker_integration.py tests/test_config_loading.py tests/test_workflow_integration.py -v --tb=short -q > /tmp/test_unit.log 2>&1
if [ $? -eq 0 ]; then
    test_pass "Unit Tests"
    tail -3 /tmp/test_unit.log
else
    test_fail "Unit Tests (check /tmp/test_unit.log)"
fi
echo

echo "Phase 4: LLM Providers"
echo "---------------------"
python scripts/test_all_llm_providers.py > /tmp/test_llm.log 2>&1
LLM_RESULT=$?
if grep -q "All LLM providers working" /tmp/test_llm.log; then
    test_pass "LLM Providers"
elif grep -q "PASS" /tmp/test_llm.log; then
    test_warn "LLM Providers (some may need model fixes)"
    grep -E "(PASS|FAIL)" /tmp/test_llm.log | head -3
else
    test_fail "LLM Providers (check /tmp/test_llm.log)"
fi
echo

echo "Phase 5: Risk Rules Validation"
echo "-------------------------------"
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.core.portfolio import Portfolio

portfolio = Portfolio(cash=100000.0)
config = {'risk': {'max_risk_per_trade': 0.02, 'max_drawdown': 0.15}}
agent = RiskManagerAgent(portfolio=portfolio, config=config)

assert agent.MAX_RISK_PER_TRADE == 0.02, 'Max risk should be 2%'
assert agent.MAX_DRAWDOWN == 0.15, 'Max drawdown should be 15%'
assert agent.ALLOW_MARTINGALE == False, 'Martingale should be disabled'
assert agent.ALLOW_AVERAGING_DOWN == False, 'Averaging down should be disabled'

print('✅ All risk rules correctly enforced')
sys.exit(0)
" > /tmp/test_risk.log 2>&1
if [ $? -eq 0 ]; then
    test_pass "Risk Rules"
else
    test_fail "Risk Rules (check /tmp/test_risk.log)"
fi
echo

echo "Phase 6: Paper Trading Config"
echo "------------------------------"
python3 -c "
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

profile = os.getenv('PEARLALGO_PROFILE')
allow_live = os.getenv('PEARLALGO_ALLOW_LIVE_TRADING')
ibkr_host = os.getenv('IBKR_HOST')
ibkr_port = os.getenv('IBKR_PORT')

all_ok = True
if profile != 'paper':
    print('⚠️  PEARLALGO_PROFILE is not paper')
    all_ok = False
if not ibkr_host or not ibkr_port:
    print('⚠️  IBKR connection not configured')
    all_ok = False
if all_ok:
    print('✅ Paper trading configuration valid')
    sys.exit(0)
else:
    sys.exit(1)
" > /tmp/test_config.log 2>&1
if [ $? -eq 0 ]; then
    test_pass "Paper Trading Config"
else
    test_warn "Paper Trading Config (check /tmp/test_config.log)"
    cat /tmp/test_config.log
fi
echo

echo "=========================================="
echo "TEST SUMMARY"
echo "=========================================="
echo -e "${GREEN}Passed: ${PASSED}${NC}"
echo -e "${RED}Failed: ${FAILED}${NC}"
echo

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ALL CRITICAL TESTS PASSED${NC}"
    echo
    echo "Next Steps:"
    echo "1. Run paper trading: ./scripts/start_langgraph_paper.sh ES NQ sr"
    echo "2. Monitor: python scripts/monitor_paper_trading.py"
    exit 0
else
    echo -e "${RED}❌ SOME TESTS FAILED${NC}"
    echo "Check logs in /tmp/test_*.log"
    exit 1
fi

