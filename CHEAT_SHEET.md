# 🎯 PearlAlgo Futures Trading - Complete Cheat Sheet

> **Quick Reference Guide** - Everything you need to know to trade futures with PearlAlgo

---

## 📦 Installation & Setup

### First Time Setup
```bash
cd ~/pearlalgo-dev-ai-agents
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .  # Install CLI command system-wide
```

After installation, the `pearlalgo` command is available system-wide.

### Verbosity Levels
Control output detail with `--verbosity`:
```bash
pearlalgo --verbosity QUIET status    # Errors only
pearlalgo --verbosity NORMAL status    # Default
pearlalgo --verbosity VERBOSE trade auto  # Detailed
pearlalgo --verbosity DEBUG trade auto    # Full debugging
```

---

## 🚀 Quick Start (After Restart)

### 1. Activate Environment
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
```

### 2. Check System Status
```bash
pearlalgo status
```

### 3. Start IB Gateway
```bash
pearlalgo gateway start --wait
# Or manually: cd ~/ibc && ./gatewaystart.sh
```

### 4. Verify Connection
```bash
python scripts/test_broker_connection.py
```

### 5. Start Trading

**Option A: Micro Strategy (Recommended for Testing)**
```bash
bash scripts/start_micro.sh
```

**Option B: Manual CLI - Standard Contracts**
```bash
# Space-separated symbols
pearlalgo trade auto ES NQ GC --strategy sr --interval 300

# Or with --symbols flag
pearlalgo trade auto --symbols ES --symbols NQ --symbols GC --strategy sr --interval 300
```

**Option C: Manual CLI - Micro Contracts**
```bash
pearlalgo trade auto MGC MYM MCL MNQ MES --strategy sr --interval 60 --tiny-size 3
```

### 6. Monitor Trading

**Terminal 1: Unified Dashboard** (Recommended)
```bash
# Unified dashboard
python scripts/dashboard.py

# Monitor trades
./monitor_trades.sh

# Health check
python scripts/health_check.py
```

**Terminal 2: Live Trading Feed**
```bash
pearlalgo monitor --live-feed
```

### 7. Stop Trading
```bash
# Stop the trader (in the terminal running it)
Ctrl+C

# Or kill by process name
pkill -f "langgraph_trader"
pkill -f "pearlalgo.live.langgraph_trader"
```

---

## 📊 Dashboard Commands

### Unified Dashboard
```bash
# Main dashboard
python scripts/dashboard.py

# Monitor trades
./monitor_trades.sh

# Health check
python scripts/health_check.py

# System health
python scripts/system_health_check.py
```

---

## 🔌 Gateway Management

```bash
pearlalgo gateway status      # Check gateway status
pearlalgo gateway start      # Start IB Gateway
pearlalgo gateway stop       # Stop IB Gateway
pearlalgo gateway restart    # Restart IB Gateway
```

---

## 📈 Trading Commands

### Standard Contracts (ES, NQ, GC)
```bash
pearlalgo trade auto ES NQ GC --strategy sr --interval 300
```

### Micro Contracts (MGC, MYM, MCL, MNQ, MES)
```bash
pearlalgo trade auto MGC MYM MCL MNQ MES --strategy sr --interval 60 --tiny-size 3
```

### Strategy Options
- `--strategy sr` - Support/Resistance strategy
- `--strategy ma_cross` - Moving Average Crossover
- `--interval 300` - Signal generation interval (seconds)
- `--tiny-size 3` - Position size for micro contracts

---

## 📊 Dashboard Metrics Reference

### Risk States
- **✅ OK** - Drawdown < 50% of daily loss limit
- **⚠️ NEAR_LIMIT** - Drawdown 50-80% of daily loss limit
- **❌ HARD_STOP** - Drawdown > 80% or trading halted

### Key Performance Metrics
- **Sharpe Ratio** - Risk-adjusted returns (higher = better)
- **Sortino Ratio** - Downside risk-adjusted returns (higher = better)
- **Drawdown %** - Percentage of daily loss limit used
- **Realized P&L** - Profit/loss from closed positions
- **Unrealized P&L** - Current profit/loss from open positions

### Per-Symbol Columns
- **Symbol** - Trading symbol (ES, NQ, GC, etc.)
- **Contract** - Contract month
- **Last Signal** - Time of most recent signal
- **Side** - LONG/SHORT/FLAT direction
- **Realized P&L** - Cumulative realized profit/loss
- **Unrealized P&L** - Current unrealized profit/loss
- **Risk** - Risk state indicator
- **Position** - Current position size
- **Trades** - Number of trades today
- **Max** - Maximum contracts allowed

### Trade Statistics
- **Total Trades** - Number of completed trades
- **Win Rate** - Percentage of winning trades
- **Avg Hold Time** - Average time in trade (minutes)
- **Largest Winner** - Best trade P&L
- **Largest Loser** - Worst trade P&L
- **Avg P&L/Trade** - Average profit/loss per trade

---

## 📁 File Locations

| Type | Location | Description |
|------|----------|-------------|
| **Signals** | `signals/YYYYMMDD_signals.csv` | Daily trading signals |
| **Reports** | `reports/YYYYMMDD_report.md` | Daily performance reports |
| **Performance** | `data/performance/futures_decisions.csv` | Trading decisions log |
| **Config** | `config/prop_profile.yaml` | Risk profile configuration |
| **Micro Config** | `config/micro_strategy_config.yaml` | Micro strategy settings |

---

## 📝 Logs

### Trading Logs
```bash
# Micro strategy
tail -f logs/micro_trading.log      # Trading decisions
tail -f logs/micro_console.log       # Console output

# Standard strategy
tail -f logs/standard_trading.log
tail -f logs/standard_console.log
```

### Gateway Logs
```bash
tail -50 /tmp/ibgateway.log
```

---

## 🔍 System Status & Health

```bash
# Overall system status
pearlalgo status

# Detailed health check
python scripts/system_health_check.py

# Debug environment configuration
python scripts/debug_env.py

# Test IBKR connection
python scripts/debug_ibkr.py

# Check trading processes
ps aux | grep "pearlalgo trade"
```

---

## 🎯 Common Commands

```bash
# System status
pearlalgo status

# Gateway management
pearlalgo gateway status
pearlalgo gateway start
pearlalgo gateway stop

# Generate signals (without trading)
pearlalgo signals --strategy sr --symbols ES NQ GC

# View dashboard
python scripts/dashboard.py

# Health check
python scripts/health_check.py
python scripts/system_health_check.py
```

---

## 🐛 Troubleshooting

### Gateway Not Starting?
```bash
# Check if already running
pearlalgo gateway status

# Check logs
tail -50 /tmp/ibgateway.log

# Restart gateway
pearlalgo gateway restart
```

### Can't Connect?
```bash
# Debug configuration
python scripts/debug_env.py

# Test IBKR connection
python scripts/debug_ibkr.py

# Check health
python scripts/health_check.py
python scripts/system_health_check.py

# Verify gateway is running
pearlalgo gateway status
```

### Trading Not Working?
```bash
# Check if processes are running
ps aux | grep "pearlalgo trade"

# Check logs
tail -50 logs/micro_trading.log

# Debug environment
python scripts/debug_env.py

# Verify IBKR gateway connection
python scripts/debug_ibkr.py
```

### Dashboard Shows No Data?
```bash
# Check performance log exists
ls -la data/performance/futures_decisions.csv

# Verify trading has been executed today
# Check file permissions
chmod 644 data/performance/futures_decisions.csv
```

### Risk Calculations Wrong?
```bash
# Verify config settings
cat config/prop_profile.yaml

# Check daily loss limit matches expectations
# Review performance log data quality
head -20 data/performance/futures_decisions.csv
```

---

## 💡 Pro Tips

1. **Multi-Terminal Setup**: Use 2-3 terminals:
   - Terminal 1: Dashboard (`python scripts/dashboard.py`)
   - Terminal 2: Monitor (`./monitor_trades.sh`)
   - Terminal 3: Logs (`tail -f logs/langgraph_trading.log`)

2. **Start with Micro**: Always test with micro contracts first (MGC, MYM, etc.) before trading standard contracts.

3. **Monitor Risk**: Keep the dashboard open to monitor risk state in real-time.

4. **Check Gateway First**: Always verify gateway is running before starting trading.

5. **Use Scripts**: Prefer using `./start_micro_paper_trading.sh` or LangGraph trader for consistency.
6. **Verify Config First**: Always run `python scripts/debug_env.py` before trading.
7. **Test IBKR Connection**: Run `python scripts/debug_ibkr.py` if having connection issues.

---

## 📚 Additional Resources

- **Full Documentation**: See `README_FUTURES.md` for detailed dashboard documentation
- **Project README**: See `README.md` for project overview
- **CLI Help**: Run `pearlalgo --help` for CLI command reference

## 🔄 Migration from Old Scripts

Old scripts still work, but you can migrate to the new CLI:

| Old Command | New Command |
|------------|-------------|
| `python scripts/run_daily_signals.py` | Daily signals generation |
| `python scripts/dashboard.py` | Unified dashboard |
| `python -m pearlalgo.live.langgraph_trader` | Main LangGraph trader |
| `python scripts/daily_workflow.py` | Daily workflow (signals + report) |
| `python scripts/setup_assistant.py` | `pearlalgo setup` |

---

## 🎯 Quick Command Reference

| Action | Command |
|--------|---------|
| **Verify Config** | `python scripts/debug_env.py` |
| **Test IBKR Connection** | `python scripts/debug_ibkr.py` |
| **Start Trading (Paper)** | `./start_micro_paper_trading.sh` |
| **View Dashboard** | `python scripts/dashboard.py` |
| **Monitor Trades** | `./monitor_trades.sh` |
| **Health Check** | `python scripts/health_check.py` |
| **Stop Trading** | `Ctrl+C` in trader terminal |
| **View Logs** | `tail -f logs/langgraph_trading.log` |

---

*Last Updated: 2025-12-02*

## 📖 View This Cheat Sheet

```bash
# View short quick reference (default - daily commands)
pearlalgo help
# or
pearlalgo cheat-sheet

# View full comprehensive cheat sheet
pearlalgo help --full
# or
pearlalgo help --long

# View specific section from full version
pearlalgo help --full --section trading
pearlalgo help --full --section dashboard
pearlalgo help --full --section troubleshooting
```

