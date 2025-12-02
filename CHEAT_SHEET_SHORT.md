# 🎯 PearlAlgo - Quick Reference

> **Daily Commands** - Most common commands you'll use every day

---

## 🚀 Daily Workflow

```bash
# 1. Activate & Check Status
cd ~/pearlalgo-dev-ai-agents && source .venv/bin/activate
pearlalgo status

# 2. Start Gateway (if needed)
pearlalgo gateway start --wait

# 3. Start Trading (Micro - Recommended)
bash scripts/start_micro.sh

# 4. View Dashboard (New Terminal)
python scripts/status_dashboard.py --live --refresh 30

# 5. Stop Trading
bash scripts/kill_my_processes.sh
```

---

## 📊 Dashboard

```bash
# Live dashboard (60s refresh)
python scripts/status_dashboard.py --live

# Custom refresh (30s)
python scripts/status_dashboard.py --live --refresh 30

# Show once
python scripts/status_dashboard.py
```

---

## 🔌 Gateway

```bash
pearlalgo gateway status    # Check status
pearlalgo gateway start     # Start
pearlalgo gateway stop      # Stop
pearlalgo gateway restart   # Restart
```

---

## 📈 Trading

```bash
# Micro Strategy (Recommended)
bash scripts/start_micro.sh

# Standard Contracts
pearlalgo trade auto ES NQ GC --strategy sr --interval 300

# Micro Contracts
pearlalgo trade auto MGC MYM MCL MNQ MES --strategy sr --interval 60 --tiny-size 3
```

---

## 📝 Logs

```bash
# Trading logs
tail -f logs/micro_trading.log
tail -f logs/micro_console.log

# Gateway logs
tail -50 /tmp/ibgateway.log
```

---

## 🛑 Stop Trading

```bash
bash scripts/kill_my_processes.sh
# or
pkill -f "pearlalgo trade auto"
```

---

## 🔍 Quick Checks

```bash
pearlalgo status                              # System status
python scripts/test_broker_connection.py     # Test connection
ps aux | grep "pearlalgo trade"              # Check if trading
```

---

## 📁 Key Files

- **Signals**: `signals/YYYYMMDD_signals.csv`
- **Performance**: `data/performance/futures_decisions.csv`
- **Config**: `config/prop_profile.yaml`

---

## 💡 Pro Tips

1. **Use 2 terminals**: Dashboard in one, logs in another
2. **Start with micro**: Test with MGC, MYM before standard contracts
3. **Monitor risk**: Keep dashboard open to watch risk state
4. **Check gateway first**: Always verify gateway is running

---

## 🆘 Quick Troubleshooting

```bash
# Gateway not starting?
pearlalgo gateway restart

# Can't connect?
python scripts/test_broker_connection.py

# Dashboard shows no data?
ls -la data/performance/futures_decisions.csv
```

---

**For full documentation**: `pearlalgo help --full` or see `CHEAT_SHEET.md`

