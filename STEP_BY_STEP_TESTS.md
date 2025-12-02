# Step-by-Step Test Instructions

## 🎯 Professional Trader Testing Approach

Follow these tests **in order**. Each test validates a specific aspect of the system.

---

## PRE-FLIGHT CHECKLIST

Before starting, ensure:
- [ ] Virtual environment activated: `source .venv/bin/activate`
- [ ] IB Gateway running (if using IBKR): `scripts/ibgateway_status.sh`
- [ ] `.env` file configured with all API keys
- [ ] `config/config.yaml` exists and is valid

---

## TEST SEQUENCE

### ⚡ Quick Test (5 minutes)
**Run this first to verify basic functionality:**

```bash
./QUICK_TEST_RUN.sh
```

**Expected:** All tests pass (green checkmarks)

**If failures:** Check the specific test logs in `/tmp/test_*.log`

---

### 📋 Detailed Test Sequence

#### Step 1: Environment Validation (30 seconds)
```bash
python scripts/verify_setup.py
```

**What to check:**
- ✅ All required env vars detected
- ✅ All required packages installed
- ✅ Core modules importable

**If issues:**
- Install missing packages: `pip install -e .`
- Check `.env` file exists
- Verify `config/config.yaml` syntax

**Feedback needed:** List any missing items

---

#### Step 2: Component Import Test (10 seconds)
```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.langgraph_state import TradingState
from pearlalgo.agents.langgraph_workflow import TradingWorkflow
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.quant_research_agent import QuantResearchAgent
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
from pearlalgo.brokers.factory import get_broker
from pearlalgo.live.langgraph_trader import LangGraphTrader
print('✅ All imports successful')
"
```

**Expected:** ✅ All imports successful

**If errors:** Note which component failed to import

**Feedback needed:** Any import errors?

---

#### Step 3: Unit Test Suite (1 minute)
```bash
pytest tests/ -v --tb=short -q
```

**Expected:** All tests pass (30+ tests)

**What to check:**
- Test count matches expected
- All tests show "PASSED"
- No errors or warnings

**If failures:**
- Note which test file failed
- Copy the error message
- Check if it's a missing dependency or code issue

**Feedback needed:** 
- How many tests passed?
- Any failures? Which ones?

---

#### Step 4: LLM Provider Test (1 minute)
```bash
python scripts/test_all_llm_providers.py
```

**Expected:**
- ✅ Groq: PASS (may show reasoning warning)
- ✅ OpenAI: PASS
- ✅ Anthropic: PASS (may show reasoning warning)

**What to check:**
- All 3 providers initialize
- OpenAI reasoning works
- Groq/Anthropic may need model name fixes

**If issues:**
- Note which provider failed
- Check if API keys are set
- Verify model names in config.yaml

**Feedback needed:**
- Which providers work?
- Any model errors?

---

#### Step 5: Risk Rules Validation (10 seconds)
```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.core.portfolio import Portfolio

portfolio = Portfolio(cash=100000.0)
config = {'risk': {'max_risk_per_trade': 0.02, 'max_drawdown': 0.15}}
agent = RiskManagerAgent(portfolio=portfolio, config=config)

print(f'Max Risk Per Trade: {agent.MAX_RISK_PER_TRADE * 100}%')
print(f'Max Drawdown: {agent.MAX_DRAWDOWN * 100}%')
print(f'Allow Martingale: {agent.ALLOW_MARTINGALE}')
print(f'Allow Averaging Down: {agent.ALLOW_AVERAGING_DOWN}')

assert agent.MAX_RISK_PER_TRADE == 0.02
assert agent.MAX_DRAWDOWN == 0.15
assert agent.ALLOW_MARTINGALE == False
assert agent.ALLOW_AVERAGING_DOWN == False

print('✅ All risk rules correctly enforced')
"
```

**Expected:**
- Max Risk: 2.0%
- Max Drawdown: 15.0%
- Martingale: False
- Averaging Down: False
- ✅ All assertions pass

**Feedback needed:** Do all values match expected?

---

#### Step 6: Broker Connection Test (30 seconds)
```bash
# Test IBKR (if using)
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.core.portfolio import Portfolio

try:
    portfolio = Portfolio(cash=100000.0)
    broker = IBKRBroker(portfolio=portfolio)
    print('✅ IBKR broker initialized')
    print('⚠️  Note: Actual connection requires IB Gateway running')
except Exception as e:
    print(f'⚠️  IBKR init: {e}')
"
```

**Expected:** Broker initializes (connection test requires Gateway)

**Feedback needed:** Does broker initialize? Any errors?

---

#### Step 7: Single Workflow Cycle Test (2 minutes)
```bash
# Run single cycle
python scripts/test_paper_trading.py
```

**Expected:**
- ✅ TradingWorkflow initialized
- ✅ Single cycle completes
- ✅ State transitions work
- ✅ No real orders placed
- ✅ Agent reasoning logged

**What to monitor:**
- Look for agent reasoning messages
- Check for any ERROR or WARNING messages
- Verify "Paper Mode Verified" message

**If issues:**
- Note the error message
- Check if IB Gateway is running
- Verify config.yaml is valid

**Feedback needed:**
- Did the cycle complete?
- Any errors?
- Did you see agent reasoning output?

---

#### Step 8: Paper Trading Short Run (5 minutes)
```bash
# Run for 2-3 cycles only
timeout 300 python -m pearlalgo.live.langgraph_trader \
    --symbols ES \
    --strategy sr \
    --mode paper \
    --interval 60 \
    --max-cycles 3 \
    2>&1 | tee test_run.log
```

**What to monitor:**
- Agent initialization messages
- Market data fetching
- Signal generation
- Risk calculations
- Position decisions
- No crashes or errors

**After run, check log:**
```bash
tail -50 test_run.log | grep -E "(✅|❌|ERROR|WARNING|Agent|Signal|Risk|Position)"
```

**Expected:**
- System runs for 2-3 cycles
- All agents report activity
- Signals generated
- Risk calculations shown
- No critical errors

**Feedback needed:**
- How many cycles completed?
- Any errors in the log?
- Did you see trading signals?
- Did risk calculations appear?

---

#### Step 9: Telegram Alert Test (30 seconds)
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
        print('✅ Telegram alert sent - check your phone!')
    else:
        print('❌ Telegram alert failed')
else:
    print('⚠️  Telegram not configured (optional)')
"
```

**Expected:** Alert sent or "not configured" message

**Feedback needed:** Did you receive the alert?

---

## 📊 Test Results Form

After running all tests, fill this out:

```
=== TEST RESULTS ===
Date: ___________
Tester: ___________

Step 1: Environment Validation
  Status: PASS / FAIL
  Issues: ________________________

Step 2: Component Imports
  Status: PASS / FAIL
  Issues: ________________________

Step 3: Unit Tests
  Status: PASS / FAIL
  Tests Passed: __ / __
  Issues: ________________________

Step 4: LLM Providers
  Groq: WORKING / NOT WORKING
  OpenAI: WORKING / NOT WORKING
  Anthropic: WORKING / NOT WORKING
  Issues: ________________________

Step 5: Risk Rules
  Status: PASS / FAIL
  Issues: ________________________

Step 6: Broker Connection
  Status: PASS / FAIL
  Issues: ________________________

Step 7: Single Cycle
  Status: PASS / FAIL
  Issues: ________________________

Step 8: Paper Trading Run
  Cycles Completed: __
  Status: PASS / FAIL
  Issues: ________________________

Step 9: Telegram Alerts
  Status: PASS / FAIL
  Issues: ________________________

=== OVERALL ASSESSMENT ===
System Ready: YES / NO
Blocking Issues: ________________________
Recommendations: ________________________
```

---

## 🚨 Critical Issues to Report

If you encounter any of these, report immediately:

1. **System crashes** during any test
2. **Import errors** that can't be resolved
3. **Broker connection failures** (if using IBKR)
4. **Risk rules not enforced** (critical!)
5. **Real orders placed** in paper mode (critical!)
6. **Kill-switch not working** (critical!)

---

## ✅ Success Criteria

System is ready for paper trading if:
- ✅ All unit tests pass
- ✅ All components importable
- ✅ LLM providers initialize (at least OpenAI)
- ✅ Risk rules enforced
- ✅ Single cycle completes
- ✅ No critical errors in logs

---

## 📝 Next Steps After Tests

If all tests pass:
1. Run paper trading for 24 hours
2. Monitor actively
3. Validate risk rules in action
4. Check Telegram alerts

If tests fail:
1. Note specific failures
2. Check error logs
3. Report issues for fixes
4. Don't proceed to live trading

---

## 💡 Professional Trader Notes

- **Test systematically** - Don't skip steps
- **Document everything** - Keep logs
- **Validate risk first** - Most critical
- **Start small** - Single symbol, short runs
- **Monitor actively** - Especially first 24 hours
- **Never skip paper trading** - Always validate first

