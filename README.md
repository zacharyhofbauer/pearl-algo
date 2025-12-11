# pearlalgo-dev-ai-agents

**Professional-grade, vendor-agnostic quantitative trading platform** using LangGraph multi-agent architecture. Operates independently with Massive.com/Tradier data providers and internal paper trading engines. Supports futures, options, and crypto via multiple brokers.

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

## For Quants

This system implements a professional quant/agentic trading architecture:

### Multi-Agent Architecture
- **Market Data Agent**: Real-time data streaming with WebSocket + REST fallbacks
- **Quant Research Agent**: Signal generation with momentum, mean-reversion, regime detection, and optional ML/LLM reasoning
- **Risk Manager Agent**: Position sizing (2% max risk), 15% drawdown kill-switch, volatility targeting
- **Portfolio Execution Agent**: Order placement with retry logic and execution quality tracking

### Risk Management
- Hardcoded safety rules: 2% max risk per trade, 15% account drawdown limit
- No martingale, no averaging down (enforced)
- Volatility-based position sizing
- Real-time PnL tracking and risk monitoring

### Data & Execution
- **Vendor-Agnostic Data Layer**: Massive.com, Tradier, Local Parquet (IBKR optional/deprecated)
- **Professional Paper Trading**: Realistic futures/options simulation with slippage and margin
- **Multi-Broker Support**: Paper (internal), IBKR (deprecated), Bybit, Alpaca
- **Complete Audit Trail**: SQLite trade ledger for immutable record-keeping
- Professional error handling with clear diagnostics

### Open-Source Philosophy
Built entirely on free/open-source tools (Pandas, TA-Lib, Scikit-Learn, Plotly, ib_insync, etc.) - no paid dependencies required for core functionality.

## Features

### 🚀 LangGraph Multi-Agent System (NEW)
- **4 Specialized Agents** collaborating in real-time:
  1. **Market Data Agent** - WebSocket streaming for OHLCV, order book, funding rates (crypto), OI with reconnection logic
  2. **Quant Research Agent** - Signal generation with momentum, mean-reversion, regime detection, ML support, and LLM reasoning
  3. **Risk Manager Agent** - Position sizing (2% max risk), 15% drawdown kill-switch, volatility targeting, cool-down periods
  4. **Portfolio/Execution Agent** - Final decision making and order placement with retry logic
- **State Persistence**: File-based (default) or Redis-backed state storage for seamless restarts
- **Enhanced Error Handling**: Retry logic with exponential backoff and circuit breakers for API/LLM calls
- **Structured Logging**: Correlation IDs and timing metrics for request tracing

### 🔄 24/7 Continuous Monitoring (NEW)
- **Worker Pool Architecture**: Parallel workers for futures and options scanning
- **Historical Data Buffers**: Rolling buffers (1000+ bars) with automatic backfill
- **Data Feed Manager**: Automatic reconnection, rate-limit queuing, health monitoring
- **Health Check Endpoints**: HTTP endpoints (`/healthz`, `/ready`, `/live`) for monitoring
- **Exit Signal Generation**: Automatic stop loss, take profit, and time-based exits
- **Real-time Telegram Alerts**: Entry and exit notifications with P&L tracking

### 📊 Core Features
- **Multi-Broker Support**: Paper (internal simulation, default), Bybit (crypto perps), Alpaca (US futures), IBKR (optional/deprecated)
- **WebSocket Streaming**: Real-time market data via WebSockets with REST fallback
- **Vectorized Backtesting**: Fast backtesting with vectorbt
- **Live Dashboard**: Streamlit dashboard with equity curve, positions, and agent reasoning
- **Alerts**: Telegram and Discord notifications for trades and major events
- **Docker Deployment**: 24/7 cloud deployment with health checks
- **Risk Management**: Hardcoded safety rules (2% risk, 15% drawdown limit, no martingale)

### 📈 Trading Capabilities
- **Futures Contracts**: ES, NQ, CL, GC (and more)
- **Futures Intraday Scanning**: High-frequency scanning (1-5 min) for NQ/ES
- **Equity Options Scanning**: Swing-trade scanning (15-60 min) for broad-market equities
- **Crypto Perpetuals**: BTC/USD, ETH/USD equivalents via Bybit
- **Strategies**: Support/Resistance, MA Cross, Breakout, Mean Reversion, Intraday Swing, Swing Momentum
- **Paper Trading**: Default mode with one-click switch to live
- **LLM Reasoning**: Optional Groq/LiteLLM integration for signal explanation

## Quick Start

**👉 Start here: [README_V2_START_HERE.md](README_V2_START_HERE.md)** - Complete setup and getting started guide

For a quick 5-minute setup, see [QUICK_START_V2.md](QUICK_START_V2.md)

### Prerequisites
- Python 3.12+
- Massive.com API key (recommended) or Tradier API key for market data
- Bybit/Alpaca API keys (optional, for live trading)
- Groq API key (optional, for LLM reasoning)
- Telegram bot token (optional, for alerts)
- Discord webhook URL (optional, for alerts)

**Note:** IBKR is now optional/deprecated. See [IBKR_DEPRECATION_NOTICE.md](IBKR_DEPRECATION_NOTICE.md) for details.

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

# Verify configuration
python scripts/debug_env.py
```

**For detailed setup instructions, see [START_HERE.md](START_HERE.md)**

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
   IBKR_PORT=4002
   IBKR_CLIENT_ID=10
   IBKR_DATA_CLIENT_ID=11

   # Trading Mode
   PEARLALGO_PROFILE=paper
   PEARLALGO_DUMMY_MODE=false

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

**24/7 Continuous Service:**
```bash
# Start 24/7 service (manual)
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Or use systemd (recommended)
sudo ./scripts/deploy_24_7.sh
sudo systemctl start pearlalgo-continuous-service.service

# Check health
curl http://localhost:8080/healthz

# View logs
sudo journalctl -u pearlalgo-continuous-service.service -f
```

**Docker Deployment (24/7 Operation):**
```bash
# Build and run with docker-compose (includes Redis for state persistence)
docker-compose up -d

# View logs
docker-compose logs -f trading-bot

# Check health
curl http://localhost:8080/healthz

# View dashboard
docker-compose logs -f dashboard

# Stop
docker-compose down

# Restart (preserves state)
docker-compose restart trading-bot
```

**State Persistence:**
- State is automatically saved to `data/state_cache/` (file-based, default)
- Optional Redis backend for distributed state (configured in `docker-compose.yml`)
- State persists across restarts, allowing seamless recovery
- Migration path for schema evolution

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
    langgraph_state.py          # Shared state schema (Pydantic) with validation
    state_store.py              # State persistence (file-based + Redis)
    langgraph_workflow.py        # Main workflow graph connecting all agents
    market_data_agent.py          # WebSocket data streaming agent (with reconnection)
    quant_research_agent.py       # Signal generation + LLM reasoning + ML support
    risk_manager_agent.py         # Enhanced risk management agent
    portfolio_execution_agent.py  # Order execution agent (with retry logic)
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
    massive_provider.py           # Massive.com data provider
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
  
  utils/
    retry.py                    # Retry logic and circuit breakers
    logging.py                  # Structured logging with correlation IDs
    health.py                   # Health check endpoint
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
- **docs/24_7_OPERATIONS_GUIDE.md** - 24/7 operations and monitoring guide
- **docs/OPTIONS_SCANNING_GUIDE.md** - Options scanning configuration and usage

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
