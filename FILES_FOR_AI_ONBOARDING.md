# Files for AI Onboarding - Quick Reference

## ⭐ START HERE: Essential Reading Order

### 1. AI_ONBOARDING_GUIDE.md
**Purpose:** Complete onboarding guide specifically for AI assistants  
**Read Time:** 10 minutes  
**Contains:**
- System overview
- File organization
- Key system characteristics
- Common tasks and file locations
- Quick start for new AI

### 2. README.md
**Purpose:** Main entry point, user-facing documentation  
**Read Time:** 15 minutes  
**Contains:**
- System overview and features
- Setup instructions
- Quick start commands
- Risk warnings
- Project structure

### 3. ARCHITECTURE.md
**Purpose:** System architecture and design  
**Read Time:** 20 minutes  
**Contains:**
- Agent architecture
- Data flow diagrams
- Component relationships
- State management
- Workflow design

### 4. PLAN_IMPLEMENTATION_COMPLETE.md
**Purpose:** Implementation status and completion report  
**Read Time:** 10 minutes  
**Contains:**
- What's been implemented
- Test results
- Current capabilities
- Known limitations

### 5. config/config.yaml
**Purpose:** Main configuration file  
**Read Time:** 5 minutes  
**Contains:**
- Broker settings
- Symbol configuration
- Risk rules (reference)
- LLM provider settings
- Strategy parameters

## Core Implementation Files (Read When Needed)

### State & Workflow
- `src/pearlalgo/agents/langgraph_state.py` - State schema (Pydantic models)
- `src/pearlalgo/agents/langgraph_workflow.py` - Workflow orchestration

### Agents
- `src/pearlalgo/agents/market_data_agent.py` - Market data fetching
- `src/pearlalgo/agents/quant_research_agent.py` - Signal generation + LLM
- `src/pearlalgo/agents/risk_manager_agent.py` - Risk management
- `src/pearlalgo/agents/portfolio_execution_agent.py` - Trade execution

### Brokers
- `src/pearlalgo/brokers/factory.py` - Broker factory
- `src/pearlalgo/brokers/ibkr_broker.py` - IBKR implementation
- `src/pearlalgo/brokers/bybit_broker.py` - Bybit implementation
- `src/pearlalgo/brokers/alpaca_broker.py` - Alpaca implementation

### Main Entry Point
- `src/pearlalgo/live/langgraph_trader.py` - Main trading loop

## Testing & Validation Files

- `tests/test_langgraph_agents.py` - Agent unit tests
- `tests/test_workflow_integration.py` - Workflow integration tests
- `tests/test_llm_providers.py` - LLM provider tests
- `tests/test_broker_integration.py` - Broker tests
- `scripts/test_paper_trading.py` - Paper trading test
- `PROFESSIONAL_TEST_PLAN.md` - Comprehensive test plan

## Usage & Operations Files

- `scripts/start_langgraph_paper.sh` - Start paper trading
- `scripts/monitor_paper_trading.py` - Monitor execution
- `scripts/verify_setup.py` - Verify system setup
- `scripts/test_all_llm_providers.py` - Test LLM providers
- `LANGGRAPH_QUICKSTART.md` - User quick start guide

## Additional Reference Files

- `MIGRATION_GUIDE.md` - Legacy system migration guide
- `ENV_SETUP.md` - Environment variable setup
- `LLM_SETUP.md` - LLM provider configuration
- `SYSTEM_STATUS.md` - Current system status
- `docs/STRUCTURE.md` - Project structure details
- `docs/ROADMAP.md` - Development roadmap

## Quick Onboarding Checklist

For a new AI assistant, read in this order:

1. [ ] `AI_ONBOARDING_GUIDE.md` (10 min)
2. [ ] `README.md` (15 min)
3. [ ] `ARCHITECTURE.md` (20 min)
4. [ ] `PLAN_IMPLEMENTATION_COMPLETE.md` (10 min)
5. [ ] `config/config.yaml` (5 min)
6. [ ] `src/pearlalgo/agents/langgraph_state.py` (10 min)
7. [ ] `src/pearlalgo/agents/langgraph_workflow.py` (15 min)

**Total Time:** ~85 minutes for complete understanding

## Key Facts to Remember

1. **System Type:** LangGraph multi-agent trading system
2. **Primary Broker:** IBKR (futures)
3. **Risk Rules:** Hardcoded (2% max risk, 15% DD limit, no martingale)
4. **LLM Providers:** Groq (working), OpenAI, Anthropic (configured)
5. **Status:** Paper trading validated, ready for extended runs
6. **Legacy Code:** Archived in `legacy_backup/` and `legacy/`
7. **Test Status:** 30+ tests passing

## Common Questions

**Q: Where are risk rules defined?**  
A: `src/pearlalgo/agents/risk_manager_agent.py` - hardcoded constants at class level

**Q: How do I add a new agent?**  
A: Create in `src/pearlalgo/agents/`, add node to `langgraph_workflow.py`, update state schema

**Q: How do I change LLM provider?**  
A: Update `config/config.yaml` → `llm.provider`, set API key in `.env`

**Q: How do I test the system?**  
A: Run `python scripts/test_paper_trading.py` for single cycle, or `pytest tests/ -v` for full suite

**Q: Where is the main trading loop?**  
A: `src/pearlalgo/live/langgraph_trader.py`

**Q: How do I start paper trading?**  
A: `./scripts/start_langgraph_paper.sh ES sr` or use `langgraph_trader.py` directly

