# Testing Guide - LangGraph Multi-Agent Trading System

## Quick Test

### 1. Test Imports
```bash
source .venv/bin/activate
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.langgraph_state import TradingState
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
print('✓ All imports OK')
"
```

### 2. Test State Creation
```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.langgraph_state import create_initial_state
from pearlalgo.core.portfolio import Portfolio

portfolio = Portfolio(cash=100000.0)
state = create_initial_state(portfolio, {})
print(f'✓ State created: trading_enabled={state.trading_enabled}')
"
```

### 3. Test Risk Rules
```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.core.portfolio import Portfolio

agent = RiskManagerAgent(portfolio=Portfolio(cash=100000.0))
print(f'✓ Max risk: {agent.MAX_RISK_PER_TRADE*100}%')
print(f'✓ Max drawdown: {agent.MAX_DRAWDOWN*100}%')
"
```

### 4. Run Full Test Suite
```bash
pytest tests/test_langgraph_agents.py -v
```

## Component Testing

### Market Data Agent
```python
from pearlalgo.agents.market_data_agent import MarketDataAgent

agent = MarketDataAgent(
    symbols=["ES", "NQ"],
    broker="ibkr",
    config={}
)
```

### Quant Research Agent
```python
from pearlalgo.agents.quant_research_agent import QuantResearchAgent

agent = QuantResearchAgent(
    symbols=["ES", "NQ"],
    strategy="sr",
    config={}
)
```

### Risk Manager Agent
```python
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.core.portfolio import Portfolio

agent = RiskManagerAgent(
    portfolio=Portfolio(cash=100000.0),
    config={}
)
```

### Portfolio/Execution Agent
```python
from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
from pearlalgo.core.portfolio import Portfolio

agent = PortfolioExecutionAgent(
    portfolio=Portfolio(cash=100000.0),
    broker_name="ibkr",
    config={}
)
```

## Integration Testing

### Test Broker Factory
```python
from pearlalgo.brokers.factory import get_broker
from pearlalgo.core.portfolio import Portfolio

portfolio = Portfolio(cash=100000.0)
config = {'broker': {'primary': 'ibkr'}}

broker = get_broker('ibkr', portfolio, config)
```

### Test Workflow (without LangGraph runtime)
```python
from pearlalgo.agents.langgraph_state import create_initial_state
from pearlalgo.core.portfolio import Portfolio

portfolio = Portfolio(cash=100000.0)
state = create_initial_state(portfolio, {})
```

## Known Issues

1. **LangGraph Runtime**: Requires `langgraph` package installed
2. **Optional Dependencies**: Some features require:
   - `ccxt` for Bybit/Binance
   - `vectorbt` for backtesting
   - `streamlit` for dashboard
   - `groq` or `litellm` for LLM reasoning

## Troubleshooting

### Import Errors
```bash
# Install all dependencies
pip install -e .

# Or install specific missing packages
pip install langgraph ccxt vectorbt streamlit groq loguru
```

### Config Errors
- Ensure `config/config.yaml` exists
- Check YAML syntax is valid
- Verify all required sections are present

### Broker Connection Errors
- IBKR: Ensure IB Gateway is running
- Bybit/Alpaca: Check API keys in `.env` file

