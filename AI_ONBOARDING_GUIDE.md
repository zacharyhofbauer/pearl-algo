# AI Onboarding Guide - LangGraph Multi-Agent Trading System

## Quick Context for AI Assistants

This is a professional-grade, agentic AI trading bot for futures contracts (ES, NQ, CL, GC, and crypto-perp equivalents) built with LangGraph. The system uses a stateful multi-agent workflow with 4 specialized agents.

## Essential Files to Read (In Order)

### 1. Start Here: System Overview
- **`README.md`** - Main entry point, setup instructions, architecture overview
- **`ARCHITECTURE.md`** - System architecture, agent design, data flow
- **`LANGGRAPH_QUICKSTART.md`** - Quick start guide for using the system

### 2. Implementation Status
- **`PLAN_IMPLEMENTATION_COMPLETE.md`** - Complete status of all implementation phases
- **`SYSTEM_STATUS.md`** - Current system status and capabilities
- **`MIGRATION_GUIDE.md`** - Guide for migrating from legacy system

### 3. Configuration
- **`config/config.yaml`** - Main configuration file (brokers, symbols, risk rules, LLM providers)
- **`ENV_SETUP.md`** - Environment variable setup guide
- **`.env`** - Environment variables (API keys, broker settings)

### 4. Core Implementation Files
- **`src/pearlalgo/agents/langgraph_state.py`** - State schema (Pydantic models)
- **`src/pearlalgo/agents/langgraph_workflow.py`** - Main workflow orchestration
- **`src/pearlalgo/agents/market_data_agent.py`** - Market data fetching
- **`src/pearlalgo/agents/quant_research_agent.py`** - Signal generation + LLM reasoning
- **`src/pearlalgo/agents/risk_manager_agent.py`** - Risk management (2% max, 15% DD limit)
- **`src/pearlalgo/agents/portfolio_execution_agent.py`** - Trade execution

### 5. Broker Integration
- **`src/pearlalgo/brokers/factory.py`** - Broker factory (IBKR, Bybit, Alpaca)
- **`src/pearlalgo/brokers/ibkr_broker.py`** - IBKR broker (primary)
- **`src/pearlalgo/brokers/bybit_broker.py`** - Bybit broker (crypto perps)
- **`src/pearlalgo/brokers/alpaca_broker.py`** - Alpaca broker (US futures)

### 6. Testing & Validation
- **`tests/test_langgraph_agents.py`** - Agent unit tests
- **`tests/test_workflow_integration.py`** - Workflow integration tests
- **`tests/test_llm_providers.py`** - LLM provider tests
- **`scripts/test_paper_trading.py`** - Paper trading test script
- **`PROFESSIONAL_TEST_PLAN.md`** - Comprehensive test plan

### 7. Usage & Operations
- **`scripts/start_langgraph_paper.sh`** - Start paper trading
- **`scripts/monitor_paper_trading.py`** - Monitor trading execution
- **`scripts/verify_setup.py`** - Verify system setup
- **`scripts/test_all_llm_providers.py`** - Test LLM providers

## Key System Characteristics

### Architecture
- **Framework**: LangGraph (stateful multi-agent workflow)
- **Language**: Python 3.11+
- **State Management**: Pydantic v2 models
- **LLM Integration**: Groq, OpenAI, Anthropic (via LiteLLM)

### Agents (4 Specialized Agents)
1. **Market Data Agent**: Streams live OHLCV, order book, funding rates, OI via WebSockets
2. **Quant Research Agent**: Generates signals using momentum, mean-reversion, regime detection + LLM reasoning
3. **Risk Manager Agent**: Position sizing, max drawdown guardrails, volatility targeting, stop-loss, take-profit
4. **Portfolio/Execution Agent**: Final decision logic, order placement, position management

### Risk Rules (Hardcoded)
- Max 2% risk per trade
- Volatility-targeted position sizing (target 0.5–1% daily vol)
- Hard 15% account drawdown kill-switch
- No martingale
- No averaging down

### Brokers Supported
- **IBKR** (primary) - Futures via IB Gateway
- **Bybit** (crypto perps) - Via ccxt.pro
- **Alpaca** (US futures) - Via REST API

### Data Sources
- IBKR (primary)
- Polygon.io (fallback for US futures)
- Binance/Bybit public WebSockets (crypto perps)

### Current Status
- ✅ All 4 phases of implementation complete
- ✅ 30+ unit tests passing
- ✅ Paper trading functional and tested
- ✅ All 3 LLM providers working
- ✅ Risk rules enforced
- ✅ Documentation complete

## Common Tasks & File Locations

### Adding a New Agent
- Create agent in `src/pearlalgo/agents/`
- Add node to `langgraph_workflow.py`
- Update state schema in `langgraph_state.py` if needed
- Add tests in `tests/test_langgraph_agents.py`

### Modifying Risk Rules
- **`src/pearlalgo/agents/risk_manager_agent.py`** - Hardcoded constants at top of class
- **`config/config.yaml`** - Configuration values (but agent uses hardcoded values)

### Adding a New Broker
- Create broker in `src/pearlalgo/brokers/`
- Implement `Broker` base class interface
- Add to `broker/factory.py`
- Add tests in `tests/test_broker_integration.py`

### Changing LLM Provider
- Update `config/config.yaml` → `llm.provider`
- Set API key in `.env`
- Agent auto-detects: `src/pearlalgo/agents/quant_research_agent.py`

### Running Tests
- Unit tests: `pytest tests/test_langgraph_agents.py -v`
- Integration: `pytest tests/test_workflow_integration.py -v`
- Paper trading: `python scripts/test_paper_trading.py`
- All tests: `pytest tests/ -v`

## Important Notes

1. **Legacy Code**: Archived in `legacy_backup/` and `legacy/` directories. Don't modify.
2. **Paper Trading**: Always start with `PEARLALGO_PROFILE=paper` in `.env`
3. **IB Gateway**: Must be running for IBKR broker (check with `./scripts/ibgateway_status.sh`)
4. **LLM Reasoning**: Optional but recommended. System works without it.
5. **Risk Rules**: Hardcoded in `RiskManagerAgent` - cannot be overridden via config

## Quick Start for New AI

1. Read `README.md` for overview
2. Read `ARCHITECTURE.md` for system design
3. Review `config/config.yaml` for configuration structure
4. Check `PLAN_IMPLEMENTATION_COMPLETE.md` for what's been done
5. Run `python scripts/verify_setup.py` to check system status
6. Run `python scripts/test_paper_trading.py` to see it in action

## File Organization

```
pearlalgo-dev-ai-agents/
├── src/pearlalgo/
│   ├── agents/          # 4 LangGraph agents
│   ├── brokers/         # Broker implementations
│   ├── data_providers/  # Data source integrations
│   ├── live/            # Main trading loop
│   └── backtesting/     # Backtesting engine
├── config/
│   └── config.yaml      # Main configuration
├── scripts/             # Helper scripts
├── tests/               # Test suite
└── docs/                # Documentation
```

## Current Implementation Status

**All Core Features Complete:**
- ✅ LangGraph multi-agent workflow
- ✅ All 4 agents implemented
- ✅ IBKR, Bybit, Alpaca brokers
- ✅ LLM reasoning (Groq, OpenAI, Anthropic)
- ✅ Risk management (hardcoded rules)
- ✅ Paper trading mode
- ✅ Backtesting engine
- ✅ Monitoring & alerts
- ✅ Comprehensive tests

**Ready For:**
- Extended paper trading (24+ hours)
- Live trading (after validation)
- Multi-symbol trading
- Strategy optimization

