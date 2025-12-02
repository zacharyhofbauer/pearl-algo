# LangGraph Multi-Agent Trading System - Quick Start Guide

## Overview

This system implements a fully agentic trading architecture using LangGraph, with 4 specialized agents collaborating in real-time to trade futures contracts (ES, NQ, CL, GC) and crypto perpetuals.

**Note**: This is the primary system. Legacy components have been archived. See `MIGRATION_GUIDE.md` if migrating from the old system.

## Architecture

```
Market Data Agent → Quant Research Agent → Risk Manager Agent → Portfolio/Execution Agent
```

Each agent has a specific role:
1. **Market Data Agent**: Fetches live market data via WebSocket/REST
2. **Quant Research Agent**: Generates trading signals with LLM reasoning
3. **Risk Manager Agent**: Enforces risk rules (2% max risk, 15% drawdown limit)
4. **Portfolio/Execution Agent**: Makes final decisions and executes orders

## Quick Start

### 1. Installation

```bash
# Install dependencies
pip install -e .

# Run setup script
python scripts/setup_langgraph.py
```

### 2. Configuration

Edit `config/config.yaml`:
- Set broker (ibkr/bybit/alpaca)
- Configure symbols (ES, NQ, CL, GC)
- Set API keys in `.env` file

### 3. Paper Trading

```bash
# Start paper trading
python -m pearlalgo.live.langgraph_trader \
    --symbols ES NQ \
    --strategy sr \
    --mode paper \
    --interval 60
```

### 4. Backtesting

```bash
# Run backtest
python -m pearlalgo.backtesting.vectorbt_engine \
    --data data/futures/ES_15m_sample.csv \
    --symbol ES \
    --strategy sr
```

### 5. Dashboard

```bash
# Start Streamlit dashboard
streamlit run scripts/streamlit_dashboard.py
```

## Risk Rules (Hardcoded)

- **Max 2% risk per trade** - Automatically enforced
- **15% account drawdown kill-switch** - Stops all trading if exceeded
- **No martingale** - Never increase position size after losses
- **No averaging down** - Never add to losing positions
- **Volatility targeting** - 0.5-1% daily volatility target

## Broker Support

- **IBKR** (Primary) - Futures via Interactive Brokers Gateway
- **Bybit** - Crypto perpetuals via ccxt.pro
- **Alpaca** - US futures via REST API

## Important Notes

⚠️ **ALWAYS START WITH PAPER TRADING**
- Test extensively before using real money
- Monitor the system actively
- Start with minimum position sizes
- The authors are not responsible for financial losses

## Troubleshooting

1. **IBKR Connection Issues**: Ensure IB Gateway is running and API is enabled
2. **Import Errors**: Run `pip install -e .` to install all dependencies
3. **Config Errors**: Check `config/config.yaml` syntax and required fields
4. **API Key Issues**: Verify all API keys are set in `.env` file

## Next Steps

1. Run setup script: `python scripts/setup_langgraph.py`
2. Configure `config/config.yaml` with your settings
3. Set API keys in `.env` file
4. Start with paper trading
5. Monitor dashboard and logs
6. Test thoroughly before live trading

## Support

See `README.md` for full documentation and `docs/` for detailed guides.

