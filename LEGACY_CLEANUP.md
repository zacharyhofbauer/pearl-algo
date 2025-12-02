# Legacy System Cleanup Guide

## What Can Be Removed

### 1. Legacy Directory (Already Archived)
- `legacy/` - Can be deleted if you're sure you won't need it
- Contains old moon-era code that's been replaced

### 2. Legacy Agents (Still Referenced by Some Scripts)
These agents are replaced by LangGraph agents but some scripts still use them:
- `src/pearlalgo/agents/automated_trading_agent.py` - Replaced by LangGraph workflow
- `src/pearlalgo/agents/execution_agent.py` - Replaced by `portfolio_execution_agent.py`
- `src/pearlalgo/agents/risk_agent.py` - Replaced by `risk_manager_agent.py`

**Scripts still using legacy agents:**
- `scripts/automated_trading.py`
- `scripts/live_paper_loop.py`
- `scripts/test_agent_live.py`

### 3. Legacy Scripts (Can Be Removed If Not Using)
- `scripts/workflow.py` - Old interactive menu (replaced by LangGraph)
- `scripts/automated_trading.py` - Old trading loop (replaced by `langgraph_trader.py`)
- `scripts/live_paper_loop.py` - Old paper loop (replaced by LangGraph)

### 4. Keep These (Still Needed)
- `src/pearlalgo/brokers/ibkr_broker.py` - **KEEP** - Used by LangGraph
- `src/pearlalgo/futures/` - **KEEP** - Core futures functionality
- `src/pearlalgo/core/` - **KEEP** - Core portfolio/events
- `src/pearlalgo/data_providers/ibkr_data_provider.py` - **KEEP** - Used by LangGraph

## Safe Cleanup Steps

1. **Test LangGraph system first** - Make sure everything works
2. **Remove legacy directory** - `rm -rf legacy/`
3. **Update scripts** - Replace old script calls with LangGraph equivalents
4. **Remove old agents** - Only after confirming no scripts use them

## Migration Path

**Old Way:**
```bash
python scripts/automated_trading.py --symbols ES NQ
```

**New Way (LangGraph):**
```bash
python -m pearlalgo.live.langgraph_trader --symbols ES NQ --mode paper
```

## IBKR Status

**IBKR is STILL PRIMARY** - Required for futures trading. The LangGraph system uses:
- `src/pearlalgo/brokers/ibkr_broker.py` - For order execution
- `src/pearlalgo/data_providers/ibkr_data_provider.py` - For market data

Both are actively used and should NOT be removed.
