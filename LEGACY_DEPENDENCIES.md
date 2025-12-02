# Legacy Dependencies Documentation

## Scripts Using Legacy Agents

### 1. `scripts/automated_trading.py`
- **Uses**: `automated_trading_agent.py`
- **Purpose**: Old automated trading loop
- **Replacement**: `langgraph_trader.py`
- **Status**: Can be removed after testing LangGraph system

### 2. `scripts/live_paper_loop.py`
- **Uses**: `execution_agent.py`
- **Purpose**: Old paper trading loop
- **Replacement**: `langgraph_trader.py` with `--mode paper`
- **Status**: Can be removed after testing LangGraph system

### 3. `scripts/test_agent_live.py`
- **Uses**: `automated_trading_agent.py`
- **Purpose**: Testing old agent system
- **Replacement**: `tests/test_langgraph_agents.py`
- **Status**: Can be removed after testing LangGraph system

### 4. `scripts/workflow.py`
- **Uses**: Various legacy components
- **Purpose**: Old interactive menu system
- **Replacement**: LangGraph system with config.yaml
- **Status**: Can be removed

## Legacy Agent Files

### Files to Archive:
1. `src/pearlalgo/agents/automated_trading_agent.py` - Replaced by LangGraph workflow
2. `src/pearlalgo/agents/execution_agent.py` - Replaced by `portfolio_execution_agent.py`
3. `src/pearlalgo/agents/risk_agent.py` - Replaced by `risk_manager_agent.py`

## Impact Analysis

### What Will Break:
- `scripts/automated_trading.py` - Will fail (uses legacy agent)
- `scripts/live_paper_loop.py` - Will fail (uses legacy agent)
- `scripts/test_agent_live.py` - Will fail (uses legacy agent)
- `scripts/workflow.py` - May have issues (uses legacy components)

### What Will Continue Working:
- All LangGraph agents and workflow
- All broker integrations (IBKR, Bybit, Alpaca)
- All data providers
- All core functionality (portfolio, events, futures)
- All new tests

## Migration Path

**Old Scripts → New LangGraph System:**
- `scripts/automated_trading.py` → `python -m pearlalgo.live.langgraph_trader --mode paper`
- `scripts/live_paper_loop.py` → `python -m pearlalgo.live.langgraph_trader --mode paper`
- `scripts/workflow.py` → Use `config/config.yaml` and LangGraph trader directly

## Safe Removal Order

1. Test LangGraph system thoroughly
2. Archive legacy agents to `legacy_backup/`
3. Remove legacy scripts
4. Remove legacy agent files
5. Update documentation

