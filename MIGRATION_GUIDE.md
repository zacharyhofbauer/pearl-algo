# Migration Guide - Legacy to LangGraph System

## Overview

The system has been migrated from legacy agents to the LangGraph multi-agent architecture. This guide helps users migrate from the old system.

## What Changed

### Old System (Deprecated)
- `automated_trading_agent.py` - Single monolithic agent
- `execution_agent.py` - Separate execution logic
- `risk_agent.py` - Separate risk management
- `scripts/workflow.py` - Interactive menu
- `scripts/automated_trading.py` - Old trading loop

### New System (LangGraph)
- **4 Specialized Agents** working together:
  - `market_data_agent.py` - Market data streaming
  - `quant_research_agent.py` - Signal generation + LLM reasoning
  - `risk_manager_agent.py` - Enhanced risk management
  - `portfolio_execution_agent.py` - Order execution
- `langgraph_trader.py` - Unified trading system
- `config/config.yaml` - Centralized configuration

## Migration Steps

### 1. Update Your Scripts

**Old Way:**
```bash
python scripts/automated_trading.py --symbols ES NQ --strategy sr
```

**New Way:**
```bash
python -m pearlalgo.live.langgraph_trader --symbols ES NQ --strategy sr --mode paper
```

### 2. Update Configuration

**Old Way:**
- Environment variables only
- Scattered config files

**New Way:**
- `config/config.yaml` - Main configuration
- Environment variables for API keys (in `.env`)
- See `ENV_SETUP.md` for details

### 3. Update Imports

**Old Imports (Don't Use):**
```python
from pearlalgo.agents.automated_trading_agent import AutomatedTradingAgent
from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.agents.risk_agent import RiskAgent
```

**New Imports (Use These):**
```python
from pearlalgo.agents.langgraph_workflow import TradingWorkflow
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.quant_research_agent import QuantResearchAgent
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
```

### 4. Update Trading Logic

**Old Way:**
```python
agent = AutomatedTradingAgent(...)
agent.run()
```

**New Way:**
```python
workflow = TradingWorkflow(
    symbols=["ES", "NQ"],
    broker="ibkr",
    strategy="sr",
    config=config,
)
state = create_initial_state(portfolio, config)
final_state = await workflow.run_cycle(state)
```

## Key Differences

### Architecture
- **Old**: Single agent handling everything
- **New**: 4 specialized agents collaborating via LangGraph

### State Management
- **Old**: Ad-hoc state management
- **New**: Centralized `TradingState` with Pydantic validation

### Risk Management
- **Old**: Configurable risk rules
- **New**: Hardcoded safety rules (2% max risk, 15% DD limit)

### LLM Integration
- **Old**: No LLM reasoning
- **New**: Optional LLM reasoning for signal explanation (Groq, OpenAI, Anthropic)

### Configuration
- **Old**: Environment variables + scattered configs
- **New**: Centralized `config.yaml` + environment variables

## Backward Compatibility

### What Still Works
- IBKR broker integration (unchanged)
- Core portfolio and events (unchanged)
- Futures contracts and signals (unchanged)
- Data providers (unchanged)

### What Doesn't Work
- Legacy agent imports (removed)
- Old scripts (`workflow.py`, `automated_trading.py`) (deprecated)
- Old risk agent (replaced by `risk_manager_agent.py`)

## Testing Your Migration

1. **Run Tests:**
   ```bash
   pytest tests/test_langgraph_agents.py -v
   ```

2. **Test Paper Trading:**
   ```bash
   python scripts/test_paper_trading.py
   ```

3. **Verify Configuration:**
   ```bash
   python scripts/verify_setup.py
   ```

## Getting Help

- See `LANGGRAPH_QUICKSTART.md` for quick start
- See `ARCHITECTURE.md` for system architecture
- See `TESTING_GUIDE.md` for testing instructions
- Check `LEGACY_DEPENDENCIES.md` for what was removed

## Rollback

If you need the old system:
- Legacy agents are backed up in `legacy_backup/agents/`
- Old scripts are in `scripts/*.old` files
- You can restore them, but they are not maintained

## Questions?

Common issues:
- **"Module not found"** - Make sure you're using new imports
- **"Config not found"** - Check `config/config.yaml` exists
- **"Agent not found"** - Use LangGraph agents, not legacy ones

