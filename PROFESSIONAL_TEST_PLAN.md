# Professional Trading System - Comprehensive Test Plan

## 🎯 Test Philosophy
As a professional trader, we test systematically: **Unit → Integration → Paper Trading → Live Validation**

---

## PHASE 1: System Integrity Tests (Run First)

### Test 1.1: Environment & Configuration Validation
```bash
# Run this first
python scripts/verify_setup.py
```

**Expected Results:**
- ✅ All required environment variables detected
- ✅ All required Python packages installed
- ✅ Core modules importable
- ✅ Config files valid

**If Failures:**
- Install missing packages: `pip install -e .`
- Check `.env` file exists and has all keys
- Verify `config/config.yaml` syntax

---

### Test 1.2: Component Import Test
```bash
python3 -c "
import sys
sys.path.insert(0, 'src')

# Test all critical imports
try:
    from pearlalgo.agents.langgraph_state import TradingState, create_initial_state
    from pearlalgo.agents.langgraph_workflow import TradingWorkflow
    from pearlalgo.agents.market_data_agent import MarketDataAgent
    from pearlalgo.agents.quant_research_agent import QuantResearchAgent
    from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
    from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
    from pearlalgo.brokers.factory import get_broker
    from pearlalgo.live.langgraph_trader import LangGraphTrader
    print('✅ All core components importable')
except Exception as e:
    print(f'❌ Import error: {e}')
    sys.exit(1)
"
```

**Expected:** ✅ All imports succeed

---

### Test 1.3: Unit Test Suite
```bash
pytest tests/test_langgraph_agents.py -v
pytest tests/test_llm_providers.py -v
pytest tests/test_broker_integration.py -v
pytest tests/test_config_loading.py -v
pytest tests/test_workflow_integration.py -v
```

**Expected:** All tests pass (30+ tests)

**If Failures:**
- Check error messages
- Verify test data is correct
- Ensure all dependencies installed

---

## PHASE 2: LLM Provider Tests

### Test 2.1: LLM Provider Initialization
```bash
python scripts/test_all_llm_providers.py
```

**Expected Results:**
- ✅ Groq: Initialized (may show reasoning warning if model needs update)
- ✅ OpenAI: Initialized and reasoning works
- ✅ Anthropic: Initialized (may show reasoning warning if model needs update)

**If Failures:**
- Check API keys in `.env`
- Verify model names in `config/config.yaml`
- Update model names if decommissioned

---

## PHASE 3: Broker Connection Tests

### Test 3.1: IBKR Connection (If Using IBKR)
```bash
# Ensure IB Gateway is running first
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.core.portfolio import Portfolio

try:
    portfolio = Portfolio(cash=100000.0)
    broker = IBKRBroker(portfolio=portfolio)
    print('✅ IBKR broker initialized')
    # Note: Actual connection test requires Gateway running
except Exception as e:
    print(f'⚠️  IBKR init: {e}')
"
```

**Expected:** Broker initializes (connection requires Gateway)

---

### Test 3.2: Broker Factory Test
```bash
pytest tests/test_broker_integration.py::test_broker_factory_ibkr -v
pytest tests/test_broker_integration.py::test_broker_factory_bybit -v
pytest tests/test_broker_integration.py::test_broker_factory_alpaca -v
```

**Expected:** All broker factories work

---

## PHASE 4: Workflow Integration Test

### Test 4.1: Single Workflow Cycle (Dry Run)
```bash
python scripts/test_paper_trading.py
```

**Expected Results:**
- ✅ TradingWorkflow initializes
- ✅ Single cycle completes
- ✅ State transitions work
- ✅ No real orders placed (paper mode)
- ✅ Agent reasoning logged

**If Failures:**
- Check IB Gateway connection (if using IBKR)
- Verify config.yaml is valid
- Check error logs for specific issues

---

## PHASE 5: Risk Management Validation

### Test 5.1: Risk Rules Enforcement
```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.core.portfolio import Portfolio

portfolio = Portfolio(cash=100000.0)
config = {'risk': {'max_risk_per_trade': 0.02, 'max_drawdown': 0.15}}
agent = RiskManagerAgent(portfolio=portfolio, config=config)

# Verify hardcoded rules
assert agent.MAX_RISK_PER_TRADE == 0.02, 'Max risk should be 2%'
assert agent.MAX_DRAWDOWN == 0.15, 'Max drawdown should be 15%'
assert agent.ALLOW_MARTINGALE == False, 'Martingale should be disabled'
assert agent.ALLOW_AVERAGING_DOWN == False, 'Averaging down should be disabled'

print('✅ All risk rules correctly enforced')
"
```

**Expected:** All assertions pass

---

## PHASE 6: Paper Trading Validation

### Test 6.1: Paper Trading Configuration Check
```bash
python3 -c "
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

checks = {
    'PEARLALGO_PROFILE': os.getenv('PEARLALGO_PROFILE'),
    'PEARLALGO_ALLOW_LIVE_TRADING': os.getenv('PEARLALGO_ALLOW_LIVE_TRADING'),
    'IBKR_HOST': os.getenv('IBKR_HOST'),
    'IBKR_PORT': os.getenv('IBKR_PORT'),
}

print('Paper Trading Configuration:')
for key, value in checks.items():
    status = '✅' if value else '❌'
    print(f'{status} {key} = {value}')

if checks['PEARLALGO_PROFILE'] != 'paper':
    print('⚠️  WARNING: Not in paper mode!')
"
```

**Expected:**
- ✅ PEARLALGO_PROFILE = paper
- ✅ IBKR_HOST and PORT set
- ⚠️ PEARLALGO_ALLOW_LIVE_TRADING (should be false for extra safety)

---

### Test 6.2: Start Paper Trading (Single Symbol, Short Run)
```bash
# Run for 2-3 cycles only
timeout 120 python -m pearlalgo.live.langgraph_trader \
    --symbols ES \
    --strategy sr \
    --mode paper \
    2>&1 | tee test_run.log
```

**What to Monitor:**
- Agent initialization messages
- Market data fetching
- Signal generation
- Risk calculations
- Position decisions
- No errors or crashes

**Expected:** System runs for 2-3 cycles without errors

---

### Test 6.3: Monitor Paper Trading Output
```bash
# After Test 6.2, check the log
tail -50 test_run.log | grep -E "(✅|❌|ERROR|WARNING|Agent|Signal|Risk|Position)"
```

**Expected:**
- ✅ All agents report activity
- ✅ Signals generated
- ✅ Risk calculations shown
- ✅ Position decisions made
- ❌ No critical errors

---

## PHASE 7: Alert System Test

### Test 7.1: Telegram Alert Test (If Configured)
```bash
python3 -c "
import sys
import asyncio
sys.path.insert(0, 'src')
from pearlalgo.utils.telegram_alerts import TelegramAlerts
import os
from dotenv import load_dotenv

load_dotenv()

bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
chat_id = os.getenv('TELEGRAM_CHAT_ID')

if bot_token and chat_id:
    alerter = TelegramAlerts(bot_token=bot_token, chat_id=chat_id)
    result = asyncio.run(alerter.send_message('🧪 Test Alert - LangGraph System'))
    if result:
        print('✅ Telegram alert sent successfully')
    else:
        print('❌ Telegram alert failed')
else:
    print('⚠️  Telegram not configured (optional)')
"
```

**Expected:** Alert sent or "not configured" message

---

## PHASE 8: End-to-End Validation

### Test 8.1: Full System Health Check
```bash
# Run all validation checks
echo "=== SYSTEM HEALTH CHECK ===" && \
python scripts/verify_setup.py && \
echo "" && \
echo "=== LLM PROVIDERS ===" && \
python scripts/test_all_llm_providers.py 2>&1 | grep -E "(✅|❌|PASS|FAIL)" && \
echo "" && \
echo "=== UNIT TESTS ===" && \
pytest tests/ -v --tb=short -q 2>&1 | tail -5
```

**Expected:** All checks pass

---

## PHASE 9: Production Readiness Checklist

### Pre-Live Trading Validation

Run this checklist before live trading:

```bash
cat << 'EOF'
=== PRODUCTION READINESS CHECKLIST ===

[ ] 1. Paper trading ran successfully for at least 24 hours
[ ] 2. All risk rules verified and enforced
[ ] 3. No unexpected errors in logs
[ ] 4. Telegram/Discord alerts working
[ ] 5. IB Gateway connection stable
[ ] 6. Position sizing calculations correct
[ ] 7. Kill-switch tested (15% drawdown limit)
[ ] 8. State persistence verified (if implemented)
[ ] 9. Backup and recovery plan in place
[ ] 10. Monitoring dashboard accessible

=== RISK VALIDATION ===
[ ] Max 2% risk per trade enforced
[ ] 15% drawdown kill-switch working
[ ] No martingale behavior
[ ] No averaging down
[ ] Position sizing correct

=== CONFIGURATION ===
[ ] PEARLALGO_PROFILE=paper (for testing)
[ ] PEARLALGO_ALLOW_LIVE_TRADING=false (for safety)
[ ] All API keys valid
[ ] Broker credentials correct
[ ] Starting balance appropriate

EOF
```

---

## 📊 Test Results Template

After running tests, fill this out:

```
=== TEST RESULTS ===
Date: ___________
Tester: ___________

Phase 1: System Integrity
  [ ] Test 1.1: Environment Validation - PASS/FAIL
  [ ] Test 1.2: Component Imports - PASS/FAIL
  [ ] Test 1.3: Unit Tests - PASS/FAIL (__/__ tests passed)

Phase 2: LLM Providers
  [ ] Test 2.1: LLM Initialization - PASS/FAIL
  - Groq: WORKING/NOT WORKING
  - OpenAI: WORKING/NOT WORKING
  - Anthropic: WORKING/NOT WORKING

Phase 3: Broker Connections
  [ ] Test 3.1: IBKR Connection - PASS/FAIL
  [ ] Test 3.2: Broker Factory - PASS/FAIL

Phase 4: Workflow Integration
  [ ] Test 4.1: Single Cycle - PASS/FAIL

Phase 5: Risk Management
  [ ] Test 5.1: Risk Rules - PASS/FAIL

Phase 6: Paper Trading
  [ ] Test 6.1: Config Check - PASS/FAIL
  [ ] Test 6.2: Short Run - PASS/FAIL
  [ ] Test 6.3: Output Validation - PASS/FAIL

Phase 7: Alerts
  [ ] Test 7.1: Telegram - PASS/FAIL

Phase 8: End-to-End
  [ ] Test 8.1: Health Check - PASS/FAIL

Issues Found:
1. ________________________________
2. ________________________________
3. ________________________________

Next Steps:
1. ________________________________
2. ________________________________
```

---

## 🚀 Quick Test Sequence (Run This First)

For a quick validation, run these in order:

```bash
# 1. Environment check
python scripts/verify_setup.py

# 2. Unit tests
pytest tests/ -v --tb=short -q

# 3. LLM providers
python scripts/test_all_llm_providers.py

# 4. Single workflow cycle
python scripts/test_paper_trading.py
```

If all pass, proceed to longer paper trading runs.

---

## ⚠️ Critical Warnings

1. **ALWAYS START WITH PAPER TRADING**
2. **Verify risk rules before live trading**
3. **Test kill-switch functionality**
4. **Monitor first 24 hours actively**
5. **Keep logs for analysis**

---

## 📝 Feedback Instructions

After running tests, provide:
1. Which tests passed/failed
2. Any error messages
3. Unexpected behavior
4. Performance observations
5. Suggestions for improvements

