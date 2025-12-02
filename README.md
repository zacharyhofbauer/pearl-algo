# pearlalgo-dev-ai-agents

**Professional-grade, agentic AI trading bot for futures contracts** using LangGraph multi-agent architecture. Supports ES, NQ, CL, GC futures and crypto perpetuals via IBKR, Bybit, and Alpaca brokers.

## ⚠️ RISK WARNINGS

**CRITICAL: This is a trading system that can lose money. Use at your own risk.**

- **Always start with paper trading** - Never use real money until thoroughly tested
- **Maximum 2% risk per trade** - Hardcoded and enforced
- **15% account drawdown kill-switch** - Automatically stops trading if drawdown exceeds 15%
- **No martingale, no averaging down** - Hardcoded safety rules
- **Test extensively** - Backtest and paper trade before live trading
- **Start small** - Use minimum position sizes when going live
- **Monitor actively** - Check the system regularly, especially in live mode

**The authors are not responsible for any financial losses. Trade at your own risk.**

## Features

### 🚀 LangGraph Multi-Agent System (NEW)
- **4 Specialized Agents** collaborating in real-time:
  1. **Market Data Agent** - WebSocket streaming for OHLCV, order book, funding rates (crypto), OI
  2. **Quant Research Agent** - Signal generation with momentum, mean-reversion, regime detection, and LLM reasoning
  3. **Risk Manager Agent** - Position sizing (2% max risk), 15% drawdown kill-switch, volatility targeting
  4. **Portfolio/Execution Agent** - Final decision making and order placement

### 📊 Core Features
- **Multi-Broker Support**: IBKR (primary), Bybit (crypto perps), Alpaca (US futures)
- **WebSocket Streaming**: Real-time market data via WebSockets with REST fallback
- **Vectorized Backtesting**: Fast backtesting with vectorbt
- **Live Dashboard**: Streamlit dashboard with equity curve, positions, and agent reasoning
- **Alerts**: Telegram and Discord notifications for trades and major events
- **Docker Deployment**: 24/7 cloud deployment with health checks
- **Risk Management**: Hardcoded safety rules (2% risk, 15% drawdown limit, no martingale)

### 📈 Trading Capabilities
- **Futures Contracts**: ES, NQ, CL, GC (and more)
- **Crypto Perpetuals**: BTC/USD, ETH/USD equivalents via Bybit
- **Strategies**: Support/Resistance, MA Cross, Breakout, Mean Reversion
- **Paper Trading**: Default mode with one-click switch to live
- **LLM Reasoning**: Optional Groq/LiteLLM integration for signal explanation

## Setup

### Prerequisites
- Python 3.12+
- IBKR Gateway (for futures trading) or Bybit/Alpaca API keys
- Groq API key (optional, for LLM reasoning)
- Telegram bot token (optional, for alerts)
- Discord webhook URL (optional, for alerts)

### Installation
```bash
# Clone repository
git clone <repository-url>
cd pearlalgo-dev-ai-agents

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -U pip
pip install -e .

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
nano .env  # or use your preferred editor
```

### Configuration

1. **Edit `config/config.yaml`**:
   - Set broker (ibkr/bybit/alpaca)
   - Configure symbols (ES, NQ, CL, GC, etc.)
   - Set risk rules (already hardcoded to safe defaults)
   - Configure LLM provider (Groq/LiteLLM) if using

2. **Set Environment Variables** (in `.env`):
   ```bash
   # IBKR (if using)
   IBKR_HOST=127.0.0.1
   IBKR_PORT=7497
   IBKR_CLIENT_ID=1

   # Bybit (if using)
   BYBIT_API_KEY=your_key
   BYBIT_API_SECRET=your_secret

   # Alpaca (if using)
   ALPACA_API_KEY=your_key
   ALPACA_API_SECRET=your_secret

   # LLM (optional)
   GROQ_API_KEY=your_key

   # Alerts (optional)
   TELEGRAM_BOT_TOKEN=your_token
   TELEGRAM_CHAT_ID=your_chat_id
   DISCORD_WEBHOOK_URL=your_webhook_url
   ```

## 🚀 Quickstart

### LangGraph Multi-Agent Trading (PRIMARY SYSTEM)

**Verify Setup First:**
```bash
# Check system is ready
python scripts/verify_setup.py
```

**Start Paper Trading:**
```bash
# Quick start (single symbol)
./scripts/start_langgraph_paper.sh ES sr

# Multiple symbols
./scripts/start_langgraph_paper.sh ES NQ sr

# Manual start with options
python -m pearlalgo.live.langgraph_trader \
    --symbols ES NQ \
    --strategy sr \
    --mode paper \
    --interval 60 \
    --max-cycles 10

# Or use config file
python -m pearlalgo.live.langgraph_trader --config config/config.yaml
```

**Monitor Trading:**
```bash
# In another terminal
python scripts/monitor_paper_trading.py

# Or watch logs
tail -f logs/*.log | grep -E '(Agent|Signal|Risk|Position|ERROR)'

# Or use the live monitor script
./scripts/watch_trading_live.sh
```

**Run Backtest:**
```bash
# One-line backtest command
pearlalgo backtest --symbol ES --strategy sr --start 2024-01-01

# Or use Python
python -m pearlalgo.backtesting.vectorbt_engine \
    --data data/futures/ES_15m_sample.csv \
    --symbol ES \
    --strategy sr
```

**Start Dashboard:**
```bash
streamlit run scripts/streamlit_dashboard.py
```

**Docker Deployment:**
```bash
# Build and run with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f trading-bot

# Stop
docker-compose down
```

### Testing & Validation

**Run Tests:**
```bash
# Quick validation
./QUICK_TEST_RUN.sh

# Full test suite
pytest tests/ -v

# Test single cycle
python scripts/test_paper_trading.py

# Test LLM providers
python scripts/test_all_llm_providers.py
```

**Note**: Legacy scripts (`workflow.py`, `automated_trading.py`) have been archived. The LangGraph system is the primary trading system. See `MIGRATION_GUIDE.md` for details.

**Setup & Management Assistant:**
```bash
# Interactive setup and management
python scripts/setup_assistant.py

# Quick commands
python scripts/setup_assistant.py --status          # Show system status
python scripts/setup_assistant.py --quick-start    # Ensure Gateway is running
python scripts/setup_assistant.py --start-gateway   # Start IB Gateway
python scripts/setup_assistant.py --restart-gateway # Restart Gateway
python scripts/setup_assistant.py --test-connection # Test API connection
```

**Quick Commands:**
```bash
# Generate signals (default: sr strategy)
python scripts/workflow.py --signals

# View dashboard
python scripts/workflow.py --dashboard

# View live-updating dashboard
python scripts/status_dashboard.py --live
```

**🤖 Automated Trading:**
```bash
# Run automated trading agent
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300

# Micro contracts (fast pace, 1min intervals)
bash scripts/run_micro_strategy.sh

# Diagnostics
python scripts/debug_trading.py      # Check configuration
python scripts/health_check.py     # System health
python scripts/status_dashboard.py  # Real-time dashboard

# See CLI_QUICK_START.md for full guide
```

Backtest a registered strategy (defaults to backtest profile):
```bash
python -m pearlalgo.cli backtest --data data/futures/ES_15m_sample.csv --strategy es_breakout --symbol ES --cash 100000 --commission 0.0
```

Pick a profile/config file (still paper/backtest-safe unless profile=live):
```bash
python -m pearlalgo.cli backtest --data path/to.csv --strategy equity_momentum --profile paper --config-file settings.json
```

Use the lightweight naive engine (runs through DummyBacktestBroker/Portfolio):
```bash
python -m pearlalgo.cli backtest --data data/futures/ES_15m_sample.csv --strategy es_breakout --engine naive
```

Scan multiple symbols (expects CSVs named by symbol under data_dir):
```bash
python -m pearlalgo.cli scan --symbols ES NQ --strategy es_breakout
```

## Futures core entrypoints
- `python scripts/run_daily_signals.py` — fetch ES/NQ/GC (IBKR or CSV), run MA-cross, and log decisions to `data/performance/futures_decisions.csv`.
- `python scripts/live_paper_loop.py --mode ibkr-paper` — paper loop: fetch data, generate signals, size via prop profile, route tiny orders via IBKR paper or dummy broker.
- `python scripts/risk_monitor.py --max-daily-loss 2500` — monitor performance/journal PnL and write `RISK_HALT` when breached.
- `python scripts/daily_workflow.py` — wrapper: run signals then build the markdown daily report.
- `python scripts/daily_report.py` — generate markdown report from signals + performance log.

Legacy (moon-era) CLI/backtesting: archived under `legacy/src/pearlalgo/` with the original CLI (`legacy/src/pearlalgo/cli.py`), agents, backtesting, and live scaffolding preserved for reference.


## Project Structure

### LangGraph Multi-Agent System (NEW)
```
src/pearlalgo/
  agents/
    langgraph_state.py          # Shared state schema (Pydantic)
    langgraph_workflow.py        # Main workflow graph connecting all agents
    market_data_agent.py          # WebSocket data streaming agent
    quant_research_agent.py       # Signal generation + LLM reasoning agent
    risk_manager_agent.py         # Enhanced risk management agent
    portfolio_execution_agent.py  # Order execution agent
    automated_trading_agent.py    # Legacy agent (backward compatible)
    execution_agent.py            # Legacy execution agent
    risk_agent.py                 # Legacy risk agent
    
  brokers/
    factory.py                    # Unified broker factory (IBKR/Bybit/Alpaca)
    bybit_broker.py               # Bybit crypto perpetuals broker
    alpaca_broker.py              # Alpaca US futures broker
    ibkr_broker.py                # IBKR futures broker (primary)
    base.py                       # Abstract broker interface
    contracts.py                  # Contract builders and metadata
    dummy_backtest.py             # Backtest broker
    
  data_providers/
    websocket_provider.py         # WebSocket streaming provider
    polygon_provider.py           # Polygon.io data provider
    ibkr_data_provider.py         # IBKR data provider
    local_csv_provider.py         # CSV data provider
    base.py                       # Abstract data provider
    
  backtesting/
    vectorbt_engine.py            # Vectorized backtesting engine
    
  live/
    langgraph_trader.py           # Main LangGraph trading loop
    
  utils/
    telegram_alerts.py            # Telegram notifications
    discord_alerts.py             # Discord notifications
    logging.py                    # Enhanced logging
    
  futures/                        # Futures-focused modules (existing)
    config.py                     # Prop profile config
    contracts.py                  # Contract metadata
    signals.py                    # Signal generation
    risk.py                       # Risk state management
    performance.py                # Performance logging
    
  core/                           # Core portfolio and events
  config/                         # Configuration and settings
  strategies/                     # Trading strategies
  risk/                           # Risk management modules
  models/                         # Data models
  cli/                            # CLI commands

config/
  config.yaml                     # Main configuration file (NEW)
  micro_strategy_config.yaml      # Micro strategy config

scripts/
  streamlit_dashboard.py          # Streamlit dashboard (NEW)
  setup_langgraph.py             # LangGraph setup helper (NEW)
  automated_trading.py            # Legacy automated trading
  workflow.py                     # Legacy workflow
  # ... other legacy scripts

tests/
  test_langgraph_agents.py        # LangGraph agent tests (NEW)
  test_futures_core.py            # Futures tests
  test_risk.py                    # Risk tests
  # ... other tests

Dockerfile                        # Docker container setup (NEW)
docker-compose.yml                # Docker orchestration (NEW)
```

### Legacy Components (Still Supported)
- `legacy/`: Archived moon-era agents/backtesting/live CLI (kept for reference)
- Existing scripts and workflows continue to work alongside new LangGraph system

## Roadmap (live trading)
1. Add Interactive Brokers adapter via `ib_insync` (connection mgmt, contract builders for ES/NQ/GC/ZN/CL, order routing).
2. Implement account/portfolio sync and risk checks (per-symbol risk budget, max DD guard).
3. Add execution venue abstraction for multiple brokers (IB, Tradovate, CQG).
4. Add data adapters for continuous futures/roll logic.
5. Integrate feature store and ML pipelines (optional).

## Documentation

### Essential Reading
- **README.md** - This file (overview and quickstart)
- **AI_ONBOARDING_GUIDE.md** - **START HERE for new AI assistants** - Complete onboarding guide
- **ARCHITECTURE.md** - Detailed system architecture
- **LANGGRAPH_QUICKSTART.md** - Quick start guide for LangGraph system
- **MIGRATION_GUIDE.md** - Guide for migrating from legacy system

### Reference Documentation
- **TESTING_GUIDE.md** - Testing instructions
- **SYSTEM_STATUS.md** - Current implementation status
- **PLAN_IMPLEMENTATION_COMPLETE.md** - Implementation completion status
- **PROFESSIONAL_TEST_PLAN.md** - Comprehensive test plan
- **STEP_BY_STEP_TESTS.md** - Step-by-step testing guide
- **docs/STRUCTURE.md** - Project structure details
- **docs/ROADMAP.md** - Development roadmap
- **docs/OPS.md** - Operations guide (IBKR Gateway setup)
- **ENV_SETUP.md** - Environment variable setup
- **LLM_SETUP.md** - LLM provider configuration

## Notes
- Strategies are educational examples—customize with your own logic
- Sample data: `data/futures/ES_15m_sample.csv` (synthetic OHLCV for testing)
- IBKR integration: see `docs/OPS.md` for headless Gateway + ib_insync usage
- **All risk rules are hardcoded for safety** - 2% max risk, 15% drawdown limit, no martingale, no averaging down
- Required env for live trading (example keys only; do not commit secrets):
  - `PEARLALGO_BROKER_API_KEY`, `PEARLALGO_BROKER_API_SECRET`, `PEARLALGO_BROKER_BASE_URL`
  - `PEARLALGO_DATA_API_KEY` if your data provider needs it
  - `PEARLALGO_PROFILE` (backtest | paper | live)

## Testing
```bash
pip install -e .[dev]
pytest
```

See `docs/TESTING.md` for CI and lint details. Ops runbook in `docs/OPS.md`.
