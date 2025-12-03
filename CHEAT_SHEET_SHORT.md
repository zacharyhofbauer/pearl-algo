# 🎯 PearlAlgo - Quick Reference

> **Daily Commands** - Most common commands you'll use every day

---

## 🚀 Daily Workflow

```bash
# 1. Activate & Check Configuration
cd ~/pearlalgo-dev-ai-agents && source .venv/bin/activate
python scripts/debug_env.py          # Verify .env configuration

# 2. Test IBKR Connection (if using IBKR)
python scripts/debug_ibkr.py         # Test IBKR Gateway connection

# 3. Start Trading (Paper Mode - Recommended)
./start_micro_paper_trading.sh       # Quick start with micro contracts
# OR
python -m pearlalgo.live.langgraph_trader \
    --symbols MES MNQ \
    --strategy sr \
    --mode paper \
    --interval 60

# 4. View Dashboard (New Terminal)
python scripts/dashboard.py           # Unified dashboard

# 5. Monitor Logs (New Terminal)
tail -f logs/langgraph_trading.log   # Trading logs
./monitor_trades.sh                  # Monitor script

# 6. Stop Trading
# Press Ctrl+C in the terminal running the trader
```

---

## 📊 Dashboard & Monitoring

```bash
# Unified dashboard
python scripts/dashboard.py

# Monitor trades
./monitor_trades.sh

# Health check
python scripts/health_check.py

# System health
python scripts/system_health_check.py
```

---

## 🔌 IBKR Gateway & Connection

```bash
# Debug IBKR connection
python scripts/debug_ibkr.py

# Check IBKR Gateway status
bash scripts/ibgateway_status.sh

# View IBKR Gateway logs
bash scripts/ibgateway_logs.sh

# Or use CLI (if available)
pearlalgo gateway status    # Check status
pearlalgo gateway start     # Start
pearlalgo gateway stop      # Stop
pearlalgo gateway restart   # Restart
```

---

## 📈 Trading

```bash
# Quick Start (Paper Trading with Micro Contracts)
./start_micro_paper_trading.sh

# LangGraph Trader (Main System)
python -m pearlalgo.live.langgraph_trader \
    --symbols MES MNQ \
    --strategy sr \
    --mode paper \
    --interval 60

# Daily Workflow (Signals + Report)
python scripts/daily_workflow.py --symbols ES NQ GC

# Run Daily Signals
python scripts/run_daily_signals.py --strategy sr --symbols ES NQ
```

---

## 📝 Logs

```bash
# Main trading logs
tail -f logs/langgraph_trading.log

# Daily summary
tail -20 logs/daily_summary.csv

# Performance data
tail -20 data/performance/futures_decisions.csv

# Gateway logs
bash scripts/ibgateway_logs.sh
# or
tail -50 /tmp/ibgateway.log
```

---

## 🛑 Stop Trading

```bash
# Stop the trader (in the terminal running it)
Ctrl+C

# Or kill by process name
pkill -f "langgraph_trader"
pkill -f "pearlalgo.live.langgraph_trader"
```

---

## 🔍 Quick Checks & Debugging

```bash
# Verify environment configuration
python scripts/debug_env.py

# Test IBKR connection
python scripts/debug_ibkr.py

# System health check
python scripts/health_check.py

# Verify setup
python scripts/verify_setup.py

# Check if trading is running
ps aux | grep "langgraph_trader"
ps aux | grep "pearlalgo.live"
```

---

## 📁 Key Files

- **Signals**: `signals/YYYYMMDD_signals.csv`
- **Performance**: `data/performance/futures_decisions.csv`
- **Config**: `config/config.yaml`
- **Environment**: `.env` (see `.env.example` for template)
- **State Cache**: `data/state_cache/` (LangGraph state)
- **Logs**: `logs/langgraph_trading.log`

---

## 💡 Pro Tips

1. **Use multiple terminals**: Dashboard in one, logs in another, trading in third
2. **Start with paper mode**: Always test in paper mode first (`PEARLALGO_PROFILE=paper`)
3. **Verify config first**: Run `python scripts/debug_env.py` before trading
4. **Use dummy mode for testing**: Set `PEARLALGO_DUMMY_MODE=true` to test without IBKR
5. **Monitor risk**: Keep dashboard open to watch risk state
6. **Check IBKR connection**: Run `python scripts/debug_ibkr.py` if having connection issues

---

## 🆘 Quick Troubleshooting

```bash
# Configuration issues?
python scripts/debug_env.py          # Check .env configuration

# IBKR connection problems?
python scripts/debug_ibkr.py         # Test IBKR connection
# See IBKR_CONNECTION_FIXES.md for detailed help

# Gateway not starting?
bash scripts/ibgateway_status.sh     # Check status
pearlalgo gateway restart            # Restart (if CLI available)

# Dashboard shows no data?
ls -la data/performance/futures_decisions.csv
tail -20 data/performance/futures_decisions.csv

# System not working?
python scripts/health_check.py       # Run health check
python test_system.py                # Run system tests
```

---

## ⚙️ Environment Variables

Key variables in `.env`:
```bash
# IBKR Configuration
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11

# Trading Mode
PEARLALGO_PROFILE=paper              # paper, live, backtest, dummy
PEARLALGO_DUMMY_MODE=false           # true = allow dummy data fallback

# See .env.example for complete template
```

**For full documentation**: See `START_HERE.md` or `CHEAT_SHEET.md`

