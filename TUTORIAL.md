# PearlAlgo: Complete Setup and Testing Tutorial

This tutorial will walk you through setting up, testing, and running the PearlAlgo trading system step by step.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Environment Configuration](#environment-configuration)
4. [Running Tests](#running-tests)
5. [Starting the System](#starting-the-system)
6. [Monitoring and Verification](#monitoring-and-verification)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

1. **Python 3.12+**
   ```bash
   python --version  # Should show 3.12 or higher
   ```

2. **Git** (if cloning from repository)
   ```bash
   git --version
   ```

3. **IBKR Gateway** (for futures trading)
   - Download from [Interactive Brokers](https://www.interactivebrokers.com/en/index.php?f=16457)
   - Install and configure for paper trading

### Optional Software

- **Docker & Docker Compose** (for containerized deployment)
- **Redis** (for distributed state persistence)

---

## Initial Setup

### Step 1: Clone/Enter the Repository

```bash
# If cloning from remote:
# git clone <repository-url>
# cd pearlalgo-dev-ai-agents

# If already in the directory:
cd /home/pearlalgo/pearlalgo-dev-ai-agents
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # On Linux/Mac
# OR
.venv\Scripts\activate    # On Windows
```

### Step 3: Install Dependencies

```bash
# Upgrade pip
pip install -U pip

# Install the package in editable mode
pip install -e .

# Verify installation
python -c "import pearlalgo; print('✓ Installation successful')"
```

### Step 4: Create Environment File

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your settings
nano .env  # or use your preferred editor
```

---

## Environment Configuration

### Minimal Configuration (Paper Trading)

Edit `.env` with at least these settings:

```bash
# IBKR Configuration (for futures)
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=1
IBKR_DATA_CLIENT_ID=2

# Trading Mode (START WITH PAPER!)
PEARLALGO_PROFILE=paper
PEARLALGO_ALLOW_LIVE_TRADING=false

# Starting Balance
LIVE_STARTING_BALANCE=50000.0

# Logging
PEARLALGO_LOG_LEVEL=INFO
```

### Optional: LLM Configuration

If you want LLM reasoning for signals:

```bash
# Choose one or more:
GROQ_API_KEY=your_groq_key          # Free tier at https://console.groq.com
OPENAI_API_KEY=your_openai_key     # Get at https://platform.openai.com/api-keys
ANTHROPIC_API_KEY=your_anthropic_key # Get at https://console.anthropic.com/
```

### Optional: Alerts

```bash
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
DISCORD_WEBHOOK_URL=your_webhook_url
```

### Verify Configuration

```bash
# Run the setup verification script
python scripts/verify_setup.py
```

This will check:
- ✅ Python version
- ✅ Dependencies installed
- ✅ Environment variables set
- ✅ IBKR Gateway connection (if configured)
- ✅ Configuration file validity

---

## Running Tests

### Step 1: Quick Test Run

```bash
# Run all tests with coverage
pytest tests/ -v --cov=src/pearlalgo --cov-report=term-missing

# Expected output: All tests passing, >80% coverage
```

### Step 2: Run Specific Test Suites

```bash
# Test agents only
pytest tests/test_agents/ -v

# Test brokers only
pytest tests/test_providers_and_broker.py -v

# Test risk management
pytest tests/test_risk/ -v

# Test state management
pytest tests/test_state/ -v
```

### Step 3: Run Integration Tests

```bash
# Full workflow integration test
pytest tests/test_workflow_integration.py -v

# This tests the complete LangGraph workflow
```

### Step 4: Linting Check

```bash
# Check code style
ruff check .

# Auto-fix issues
ruff check . --fix

# Format code
ruff format .
```

### Step 5: Type Checking (Optional)

```bash
# If mypy is installed
mypy src/pearlalgo --ignore-missing-imports
```

---

## Starting the System

### Option 1: Paper Trading (Recommended First)

#### Start IBKR Gateway (if using IBKR)

```bash
# Start IBKR Gateway (adjust path as needed)
# On Linux with systemd:
sudo systemctl start ibgateway.service

# Or manually:
# Navigate to IB Gateway installation and start it
# Ensure it's listening on port 4002 (or your configured port)
```

#### Verify IBKR Connection

```bash
# Test connection
python scripts/setup_assistant.py --test-connection
```

#### Start Paper Trading

```bash
# Quick start with single symbol
python -m pearlalgo.live.langgraph_trader \
    --symbols ES \
    --strategy sr \
    --mode paper \
    --interval 60

# Multiple symbols
python -m pearlalgo.live.langgraph_trader \
    --symbols ES NQ GC \
    --strategy sr \
    --mode paper \
    --interval 60

# Using config file
python -m pearlalgo.live.langgraph_trader \
    --config config/config.yaml
```

#### What to Expect

- System will start and connect to IBKR Gateway
- Market data agent will fetch prices
- Quant research agent will generate signals
- Risk manager will evaluate positions
- Portfolio agent will log decisions (paper mode doesn't place real orders)

### Option 2: Docker Deployment

#### Build and Start

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f trading-bot

# Check health
curl http://localhost:8080/healthz
```

#### Stop Services

```bash
# Stop all services
docker-compose down

# Stop but keep volumes (preserves state)
docker-compose stop
```

### Option 3: Backtesting

```bash
# Quick backtest
pearlalgo backtest \
    --data data/futures/ES_15m_sample.csv \
    --symbol ES \
    --strategy sr \
    --start 2024-01-01

# Or using Python module
python -m pearlalgo.backtesting.vectorbt_engine \
    --data data/futures/ES_15m_sample.csv \
    --symbol ES \
    --strategy sr
```

---

## Monitoring and Verification

### Step 1: Check System Status

```bash
# Use setup assistant
python scripts/setup_assistant.py --status

# This shows:
# - IBKR Gateway status
# - Active trading processes
# - Configuration status
```

### Step 2: View Logs

```bash
# Real-time log monitoring
tail -f logs/langgraph_trading.log

# Filter for specific agents
tail -f logs/langgraph_trading.log | grep -E "(MarketData|QuantResearch|RiskManager|PortfolioExecution)"

# Filter for errors
tail -f logs/langgraph_trading.log | grep ERROR
```

### Step 3: View Dashboard

```bash
# Start Streamlit dashboard
streamlit run scripts/streamlit_dashboard.py

# Or use the terminal dashboard
python scripts/dashboard.py --live

# View once
python scripts/dashboard.py --once
```

The dashboard shows:
- Real-time equity curve
- Current positions
- Agent reasoning logs
- Risk metrics
- Trade statistics

### Step 4: Check Performance Logs

```bash
# View performance CSV
cat data/performance/futures_decisions.csv | tail -20

# Or use pandas to analyze
python -c "
import pandas as pd
df = pd.read_csv('data/performance/futures_decisions.csv')
print(df.tail(10))
print(f'\nTotal trades: {len(df)}')
print(f'Win rate: {len(df[df[\"realized_pnl\"] > 0]) / len(df) * 100:.1f}%')
"
```

### Step 5: Check State Persistence

```bash
# View saved state (if using file-based persistence)
cat data/state_cache/state.json | jq .  # Requires jq, or use python

# Or with Python
python -c "
import json
with open('data/state_cache/state.json') as f:
    state = json.load(f)
    print(f'State version: {state.get(\"version\", \"unknown\")}')
    print(f'Symbols tracked: {list(state.get(\"market_data\", {}).keys())}')
"
```

### Step 6: Monitor Health Endpoint

```bash
# If running with health checks
curl http://localhost:8080/healthz

# Expected response:
# {"status": "healthy", "timestamp": "...", "agents": {...}}
```

---

## Troubleshooting

### Issue: Tests Failing

**Problem**: Some tests fail with import errors

**Solution**:
```bash
# Ensure you're in the project root
cd /home/pearlalgo/pearlalgo-dev-ai-agents

# Reinstall in editable mode
pip install -e . --force-reinstall

# Run tests again
pytest tests/ -v
```

### Issue: IBKR Connection Failed

**Problem**: Cannot connect to IBKR Gateway

**Solution**:
```bash
# Check if Gateway is running
pgrep -f IbcGateway

# Check if port is listening
ss -tlnp | grep 4002

# Restart Gateway
python scripts/setup_assistant.py --restart-gateway

# Test connection
python scripts/setup_assistant.py --test-connection
```

### Issue: Module Not Found

**Problem**: `ModuleNotFoundError: No module named 'pearlalgo'`

**Solution**:
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Reinstall package
pip install -e .

# Verify installation
python -c "import pearlalgo; print(pearlalgo.__file__)"
```

### Issue: State Persistence Errors

**Problem**: State file corrupted or missing

**Solution**:
```bash
# Remove corrupted state (will start fresh)
rm -f data/state_cache/state.json

# Restart system (will create new state)
python -m pearlalgo.live.langgraph_trader --mode paper
```

### Issue: Docker Container Won't Start

**Problem**: Container exits immediately

**Solution**:
```bash
# Check logs
docker-compose logs trading-bot

# Check health
docker-compose ps

# Rebuild containers
docker-compose build --no-cache
docker-compose up -d
```

### Issue: WebSocket Connection Fails

**Problem**: Market data agent can't connect via WebSocket

**Solution**:
- System automatically falls back to REST API
- Check logs for fallback messages
- Verify broker API keys if using Bybit/Binance
- For IBKR, WebSocket is not yet fully supported (uses REST)

### Issue: LLM Reasoning Not Working

**Problem**: LLM calls fail or timeout

**Solution**:
```bash
# Check API keys are set
echo $GROQ_API_KEY  # or OPENAI_API_KEY, etc.

# Test LLM provider
python scripts/test_all_llm_providers.py

# System will continue without LLM reasoning if it fails
# Check logs for circuit breaker status
```

---

## Next Steps

### 1. Run a Full Trading Cycle

```bash
# Start paper trading
python -m pearlalgo.live.langgraph_trader \
    --symbols ES \
    --strategy sr \
    --mode paper \
    --interval 60 \
    --max-cycles 10

# Monitor in another terminal
python scripts/dashboard.py --live
```

### 2. Analyze Results

```bash
# Generate performance report
python scripts/daily_report.py

# View trade statistics
python -c "
from pearlalgo.futures.performance import load_performance, summarize_daily_performance
df = load_performance()
stats = summarize_daily_performance()
print(stats)
"
```

### 3. Customize Strategy

Edit `config/config.yaml`:
```yaml
strategy:
  default: "sr"  # Change to "ma_cross", "breakout", or "mean_reversion"
  
  sr:
    fast: 20
    slow: 50
    tolerance: 0.002
```

### 4. Enable Live Trading (⚠️ CAUTION)

**Only after extensive paper trading testing!**

```bash
# Edit .env
PEARLALGO_PROFILE=live
PEARLALGO_ALLOW_LIVE_TRADING=true

# Start with minimal position sizes
python -m pearlalgo.live.langgraph_trader \
    --symbols ES \
    --strategy sr \
    --mode live \
    --interval 300  # Slower intervals for live
```

---

## Quick Reference Commands

```bash
# Setup
python scripts/verify_setup.py
python scripts/setup_assistant.py --status

# Testing
pytest tests/ -v
ruff check .

# Running
python -m pearlalgo.live.langgraph_trader --mode paper --symbols ES
python scripts/dashboard.py --live

# Monitoring
tail -f logs/langgraph_trading.log
python scripts/setup_assistant.py --status

# Docker
docker-compose up -d
docker-compose logs -f trading-bot
curl http://localhost:8080/healthz
```

---

## Support

- Check `README.md` for feature overview
- Check `ARCHITECTURE.md` for system design
- Check logs in `logs/` directory
- Run `python scripts/setup_assistant.py --help` for setup help

**Remember**: Always start with paper trading and test extensively before live trading!

