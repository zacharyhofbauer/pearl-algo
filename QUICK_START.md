# Quick Start Guide - After Restart

## 1. Activate Environment
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
```

## 2. Check System Status
```bash
pearlalgo status
```

## 3. Start IB Gateway (if not running)
```bash
pearlalgo gateway start --wait
```

Or manually:
```bash
cd ~/ibc
./gatewaystart.sh
```

## 4. Verify Connection
```bash
python scripts/test_broker_connection.py
```

## 5. Start Trading

### Option A: Micro Strategy (Recommended)
```bash
bash scripts/start_micro.sh
```

### Option B: Manual CLI
```bash
# Space-separated symbols (easier)
pearlalgo trade auto ES NQ GC --strategy sr --interval 300

# Or with --symbols flag (repeat for each)
pearlalgo trade auto --symbols ES --symbols NQ --symbols GC --strategy sr --interval 300

# Micro strategy
pearlalgo trade auto MGC MYM MCL MNQ MES --strategy sr --interval 60 --tiny-size 3
```

### Option C: Standard Strategy
```bash
pearlalgo trade auto ES NQ GC --strategy sr --interval 300
```

## 6. Monitor Trading

### Recommended: Two Terminal Setup

**Terminal 1: System Dashboard** (overall status)
```bash
pearlalgo dashboard
```
Shows: Gateway status, risk state, performance summary

**Terminal 2: Live Trading Monitor** (trading activity)
```bash
pearlalgo monitor
```
Shows: Latest trades, signals, real-time P&L, activity feed

### Alternative: Single Terminal
```bash
# System dashboard
pearlalgo dashboard

# Or trading activity monitor
pearlalgo monitor
```

### View Logs
```bash
# Trading log
tail -f logs/micro_trading.log

# Console output
tail -f logs/micro_console.log
```

### Check Status
```bash
pearlalgo status
```

## 7. Stop Trading
```bash
# Kill all trading processes
bash scripts/kill_my_processes.sh

# Or manually
pkill -f "pearlalgo trade auto"
```

## Common Commands

```bash
# System status
pearlalgo status

# Gateway management
pearlalgo gateway status
pearlalgo gateway start
pearlalgo gateway stop

# Generate signals
pearlalgo signals --strategy sr --symbols ES NQ GC

# View dashboard
pearlalgo dashboard

# Health check
python scripts/system_health_check.py
```

## Troubleshooting

### Gateway not starting?
```bash
# Check if already running
pearlalgo gateway status

# Check logs
tail -50 /tmp/ibgateway.log

# Restart gateway
pearlalgo gateway restart
```

### Can't connect?
```bash
# Test connection
python scripts/test_broker_connection.py

# Check health
python scripts/system_health_check.py
```

### Trading not working?
```bash
# Check if processes are running
ps aux | grep "pearlalgo trade"

# Check logs
tail -50 logs/micro_trading.log
```

