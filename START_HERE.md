# 🚀 PearlAlgo: Complete Startup Tutorial

**Get your trading system up and running in 5 minutes!**

---

## 📋 Table of Contents

1. [Prerequisites Check](#prerequisites-check)
2. [Initial Setup](#initial-setup)
3. [Environment Configuration](#environment-configuration)
4. [Test the System](#test-the-system)
5. [Start Paper Trading](#start-paper-trading)
6. [Monitor Trading](#monitor-trading)
7. [Troubleshooting](#troubleshooting)

---

## ✅ Prerequisites Check

### Step 1: Verify Python Version

```bash
python3 --version
# Should show: Python 3.12.x or higher
```

If not installed or wrong version:
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install python3.12 python3.12-venv

# Or use pyenv
pyenv install 3.12.0
pyenv global 3.12.0
```

### Step 2: Navigate to Project

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
pwd
# Should show: /home/pearlalgo/pearlalgo-dev-ai-agents
```

**Note:** If your terminal starts in `.venv`, the auto-fix should move you to the project root automatically.

---

## 🔧 Initial Setup

### Step 1: Create Virtual Environment (if not exists)

```bash
# Check if .venv exists
ls -la .venv

# If it doesn't exist, create it
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# You should see (.venv) in your prompt
```

### Step 2: Install Dependencies

```bash
# Make sure you're in the project root
cd /home/pearlalgo/pearlalgo-dev-ai-agents

# Activate venv (if not already)
source .venv/bin/activate

# Upgrade pip
pip install -U pip

# Install the package in editable mode
pip install -e .

# Verify installation
python -c "import pearlalgo; print('✅ Installation successful!')"
```

**Expected output:** `✅ Installation successful!`

### Step 3: Create Required Directories

```bash
# Create directories for logs, data, and state
mkdir -p logs
mkdir -p data/performance
mkdir -p data/state_cache
mkdir -p signals
```

---

## ⚙️ Environment Configuration

### Step 1: Check Your .env File

```bash
# Check if .env exists
ls -la .env

# If it exists, view it
cat .env
```

### Step 2: Verify Key Settings

Your `.env` should have at minimum:

```bash
# IBKR Configuration (for futures)
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11

# Trading Mode (START WITH PAPER!)
PEARLALGO_PROFILE=paper
PEARLALGO_ALLOW_LIVE_TRADING=true

# Starting Balance
LIVE_STARTING_BALANCE=50000.0

# Optional: LLM for Agent Reasoning
GROQ_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

**Important Notes:**
- ✅ **IBKR Gateway is OPTIONAL** - System will use dummy data if IBKR is not available
- ✅ **Polygon API key is OPTIONAL** - System will use dummy data if not available
- ✅ **LLM keys are OPTIONAL** - System works without them (just no LLM reasoning)
- ✅ **Paper mode is SAFE** - No real money is used

### Step 3: Verify Your Configuration

```bash
# Debug your environment configuration
python scripts/debug_env.py
```

This will show you:
- All parsed settings
- IBKR configuration
- Any validation warnings or errors
- Optional API keys status

**Expected output:** All checks should pass (✓) with no errors.

### Step 4: Verify Config File

```bash
# Check config file exists
ls -la config/config.yaml

# View it (optional)
cat config/config.yaml | head -30
```

---

## 🧪 Test the System

### Step 0: Verify Environment Configuration

```bash
# Make sure you're in project root and venv is activated
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Run the debug script to verify your .env is configured correctly
python scripts/debug_env.py
```

This will validate your configuration and show any issues. Fix any errors before proceeding.

### Step 1: Run Quick System Test

```bash
# Make sure you're in project root and venv is activated
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Run the test
python test_system.py
```

**Expected Output:**
```
🚀 PearlAlgo System Test

============================================================
TEST 0: Imports
============================================================
✅ All imports: PASSED

============================================================
TEST 1: Market Data Agent
============================================================
✓ Fetched data for 2 symbols
  MES: $4500.00 (volume: 1000)
  MNQ: $15000.00 (volume: 500)
✅ Market Data Agent: PASSED

============================================================
TEST 2: Full Trading Cycle
============================================================
Running one cycle...
✓ Cycle completed
  Market data: 1 symbols
  Signals: 0 signals
  Decisions: 0 decisions
  Errors: 0 errors
✅ Full Cycle: PASSED

============================================================
TEST SUMMARY
============================================================
Passed: 3/3

✅ ALL TESTS PASSED - System is ready!
```

**If tests pass:** ✅ You're ready to start trading!

**If tests fail:** See [Troubleshooting](#troubleshooting) section below.

---

## 🚀 Start Paper Trading

### Option A: Quick Start Script (Recommended)

```bash
# Make sure you're in project root
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Run the quick start script
./start_micro_paper_trading.sh
```

**What this does:**
- Starts paper trading with micro contracts (MES, MNQ)
- Uses Support/Resistance strategy
- Runs continuously (press Ctrl+C to stop)
- Automatically uses dummy data if IBKR/Polygon unavailable

### Option B: Manual Start

```bash
# Make sure you're in project root
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Start with single symbol
python -m pearlalgo.live.langgraph_trader \
    --symbols MES \
    --strategy sr \
    --mode paper \
    --interval 60

# Or multiple symbols
python -m pearlalgo.live.langgraph_trader \
    --symbols MES MNQ \
    --strategy sr \
    --mode paper \
    --interval 60 \
    --max-cycles 10
```

**Command Options:**
- `--symbols MES MNQ` - Symbols to trade (MES=Micro E-mini S&P, MNQ=Micro Nasdaq)
- `--strategy sr` - Strategy (sr=support/resistance, ma=moving average)
- `--mode paper` - Trading mode (paper or live)
- `--interval 60` - Seconds between cycles
- `--max-cycles 10` - Number of cycles (0 = infinite)

### What You'll See

```
🚀 Starting Paper Trading with Micro Contracts
================================================

Checking IBKR Gateway...
⚠ IBKR Gateway not detected. Starting anyway...

Starting LangGraph Paper Trading System...
Symbols: MES, MNQ
Strategy: Support/Resistance
Mode: Paper Trading
Interval: 60 seconds

WebSocket not supported for broker: ibkr
API connection failed: ConnectionRefusedError...  ← Expected if IBKR not running
Using dummy data for MES (all real sources failed)  ← ✅ This is fine!
Using dummy data for MNQ (all real sources failed)  ← ✅ This is fine!
MarketDataAgent: Updated 2 symbols
Starting cycle #1
QuantResearchAgent: Generated signals
RiskManagerAgent: Evaluated risk
PortfolioExecutionAgent: Executed decisions
Cycle #1 completed in 2.3s
Starting cycle #2
...
```

**Key Points:**
- ✅ "Using dummy data" is **NORMAL** if IBKR Gateway is not running
- ✅ System will continue working with dummy data
- ✅ No real money is used in paper mode
- ✅ You'll see cycles running every 60 seconds

---

## 👀 Monitor Trading

### Option 1: Watch Logs (Terminal 2)

Open a **new terminal** and run:

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
tail -f logs/langgraph_trading.log
```

**Filter for specific events:**
```bash
# Watch for signals
tail -f logs/langgraph_trading.log | grep -i signal

# Watch for trades/decisions
tail -f logs/langgraph_trading.log | grep -i "trade\|decision\|position"

# Watch for errors
tail -f logs/langgraph_trading.log | grep -i error
```

### Option 2: Use Monitor Script

```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./monitor_trades.sh
```

### Option 3: Check Performance CSV

```bash
# View recent trades
tail -20 data/performance/futures_decisions.csv

# Or use Python for better formatting
python -c "
import pandas as pd
df = pd.read_csv('data/performance/futures_decisions.csv')
print(df.tail(10).to_string())
"
```

### Option 4: Check State File

```bash
# View current state
cat data/state_cache/state.json | python -m json.tool | head -50
```

---

## 🛠️ Troubleshooting

### Problem: "ModuleNotFoundError: No module named 'pearlalgo'"

**Solution:**
```bash
# Make sure you're in project root
cd /home/pearlalgo/pearlalgo-dev-ai-agents

# Activate venv
source .venv/bin/activate

# Reinstall
pip install -e . --force-reinstall
```

### Problem: "All data sources failed" and system stops

**Solution:**
- This should NOT happen in paper mode (dummy data should kick in)
- Check your `.env` has `PEARLALGO_PROFILE=paper`
- Check logs: `tail -50 logs/langgraph_trading.log`
- Restart with: `python -m pearlalgo.live.langgraph_trader --mode paper --symbols MES`

### Problem: Tests fail with import errors

**Solution:**
```bash
# Reinstall everything
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e . --force-reinstall
python test_system.py
```

### Problem: Terminal starts in .venv directory

**Solution:**
- The auto-fix should handle this automatically
- If it doesn't work, manually run:
  ```bash
  cd /home/pearlalgo/pearlalgo-dev-ai-agents
  ```

### Problem: IBKR Connection Refused (Expected!)

**This is NORMAL if IBKR Gateway is not running:**
- System will automatically use dummy data
- You'll see: "Using dummy data for MES (all real sources failed)"
- This is **fine** for paper trading
- To use real IBKR data, start IBKR Gateway first

### Problem: System hangs or doesn't start

**Solution:**
```bash
# Check if port 4002 is in use
lsof -i :4002

# Kill any processes using it (if needed)
kill -9 <PID>

# Or change IBKR_PORT in .env to a different port
```

### Problem: "Permission denied" on scripts

**Solution:**
```bash
# Make scripts executable
chmod +x start_micro_paper_trading.sh
chmod +x monitor_trades.sh
chmod +x quick_start.sh
```

---

## 📊 Next Steps

### 1. Let It Run

Once started, let the system run for a few cycles to see:
- Market data updates
- Signal generation
- Risk evaluation
- Trade decisions

### 2. Review Results

After running for a while:
```bash
# Check performance
cat data/performance/futures_decisions.csv

# Check logs
tail -100 logs/langgraph_trading.log
```

### 3. Customize Strategy

Edit `config/config.yaml`:
```yaml
strategy:
  default: "sr"  # Change to "ma_cross", "breakout", etc.
```

### 4. Add Real Data Sources (Optional)

**To use IBKR Gateway:**
1. Download and install IBKR Gateway
2. Start it and configure for paper trading
3. System will automatically use it instead of dummy data

**To use Polygon API:**
1. Get API key from https://polygon.io
2. Add to `.env`: `POLYGON_API_KEY=your_key`
3. System will use it as fallback

### 5. Enable LLM Reasoning (Optional)

If you have LLM API keys in `.env`, the system will automatically:
- Generate signal explanations
- Provide market context
- Add reasoning to trade decisions

---

## 🎯 Quick Reference

### Essential Commands

```bash
# Setup
cd /home/pearlalgo/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Test
python test_system.py

# Start Trading
./start_micro_paper_trading.sh

# Monitor
tail -f logs/langgraph_trading.log

# Stop
# Press Ctrl+C in the terminal running the trader
```

### File Locations

- **Logs:** `logs/langgraph_trading.log`
- **Performance:** `data/performance/futures_decisions.csv`
- **State:** `data/state_cache/state.json`
- **Config:** `config/config.yaml`
- **Environment:** `.env`

---

## ✅ Success Checklist

- [ ] Python 3.12+ installed
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -e .`)
- [ ] `.env` file configured
- [ ] `test_system.py` passes all tests
- [ ] Paper trading starts successfully
- [ ] Logs are being generated
- [ ] System runs cycles without errors

---

## 🆘 Still Need Help?

1. **Check configuration:** `python scripts/debug_env.py`
2. **Check logs:** `tail -100 logs/langgraph_trading.log`
3. **Run test:** `python test_system.py`
4. **Verify setup:** `python scripts/verify_setup.py`
5. **Check status:** `python scripts/setup_assistant.py --status`

---

**You're all set! Happy trading! 🚀**

Remember: Always start with paper trading and test extensively before live trading!

