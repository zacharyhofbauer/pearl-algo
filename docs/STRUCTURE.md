# Project Structure - LangGraph Multi-Agent Trading System

## Overview

The project now features a dual architecture:
1. **LangGraph Multi-Agent System** (NEW) - Fully agentic trading with 4 specialized agents
2. **Legacy System** (Maintained) - Original futures trading system for backward compatibility

## LangGraph Multi-Agent Architecture

### Core Agents (`src/pearlalgo/agents/`)

```
langgraph_state.py          # Shared state schema using Pydantic
langgraph_workflow.py        # Main LangGraph workflow connecting all agents
market_data_agent.py          # WebSocket streaming + REST fallback
quant_research_agent.py       # Signal generation + LLM reasoning
risk_manager_agent.py         # Enhanced risk management (2% max, 15% DD kill-switch)
portfolio_execution_agent.py  # Final decision + order execution
```

**Workflow:**
```
START → Market Data Agent → Quant Research Agent → Risk Manager Agent → Portfolio/Execution Agent → END
```

### Broker Integration (`src/pearlalgo/brokers/`)

```
factory.py           # Unified broker factory (IBKR/Bybit/Alpaca)
bybit_broker.py      # Bybit crypto perpetuals (ccxt.pro)
alpaca_broker.py     # Alpaca US futures (REST API)
ibkr_broker.py       # IBKR futures (primary, existing)
base.py              # Abstract broker interface
contracts.py         # Contract builders and metadata
```

### Data Providers (`src/pearlalgo/data_providers/`)

```
websocket_provider.py    # WebSocket streaming (Bybit/Binance)
polygon_provider.py      # Polygon.io fallback for US futures
ibkr_data_provider.py    # IBKR data provider (existing)
local_csv_provider.py    # CSV data provider (existing)
base.py                  # Abstract data provider interface
```

### Backtesting & Live Trading

```
backtesting/
  vectorbt_engine.py     # Vectorized backtesting with vectorbt

live/
  langgraph_trader.py    # Main LangGraph trading loop (paper/live modes)
```

### Utilities (`src/pearlalgo/utils/`)

```
telegram_alerts.py       # Telegram notifications
discord_alerts.py        # Discord webhook notifications
logging.py               # Enhanced logging with loguru
```

## Legacy Structure (Maintained)

### Futures Core (`src/pearlalgo/futures/`)

```
config.py         # Prop profile defaults + overrides (yaml/json)
contracts.py      # ES/NQ/GC contract builders and metadata
signals.py        # MA-cross and S/R strategy
sr.py             # Support/Resistance calculations
risk.py           # Prop-style risk state management
performance.py    # Structured trade logging
```

### Scripts (`scripts/`)

```
streamlit_dashboard.py   # NEW: Streamlit dashboard
setup_langgraph.py      # NEW: LangGraph setup helper
run_daily_signals.py    # Legacy: Daily signal generation
daily_workflow.py       # Legacy: Workflow wrapper
live_paper_loop.py      # Legacy: Paper trading loop
automated_trading.py    # Legacy: Automated trading agent
workflow.py             # Legacy: Interactive menu
# ... other legacy scripts
```

## Configuration

```
config/
  config.yaml                # NEW: Main LangGraph configuration
  micro_strategy_config.yaml # Legacy: Micro strategy config
```

## Testing

```
tests/
  test_langgraph_agents.py  # NEW: LangGraph agent tests
  test_futures_core.py       # Legacy: Futures tests
  test_risk.py              # Legacy: Risk tests
  # ... other tests
```

## Deployment

```
Dockerfile           # NEW: Docker container setup
docker-compose.yml   # NEW: Docker orchestration
```

## Key Design Decisions

1. **Backward Compatibility**: Legacy system continues to work alongside LangGraph
2. **IBKR Primary**: Focus on IBKR for futures, Bybit/Alpaca as options
3. **Gradual Migration**: LangGraph system runs alongside existing system
4. **Risk First**: All safety rules hardcoded in `risk_manager_agent.py`
5. **Modular Architecture**: Each agent is independent and testable

## Notes

- IBKR systemd/service helpers stay under `scripts/` (ibgateway.service, etc.)
- Legacy components are maintained for backward compatibility
- LangGraph system is the recommended approach for new development
- All risk rules are hardcoded for safety (2% max risk, 15% drawdown limit)
