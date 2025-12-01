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

### Recommended: Multi-Terminal Setup

**Terminal 1: Comprehensive Dashboard** (full overview)
```bash
pearlalgo dashboard --full
```
Shows:
- IB Gateway status with uptime
- Trading processes status
- System health (memory, disk)
- Performance metrics (P&L, win rate, W/L)
- Recent trades history
- Risk state with visual buffer indicator
- Current positions
- Latest signals

**Terminal 2: Live Trading Cycle Feed** (real-time trading cycles)
```bash
pearlalgo monitor --live-feed
```
Shows: Real-time trading cycles, "Analyzing", "FLAT", "EXECUTING", cycle-by-cycle activity with color-coded output

### Dashboard Options

```bash
# Standard dashboard (simpler view)
pearlalgo dashboard

# Comprehensive full-screen dashboard (more details)
pearlalgo dashboard --full

# Custom refresh rate (in seconds)
pearlalgo dashboard --refresh 3

# Show once and exit (for screenshots/logging)
pearlalgo dashboard --once
```

### Monitor Options

```bash
# Dashboard view of trades/signals/P&L
pearlalgo monitor

# Live feed with real-time log tailing
pearlalgo monitor --live-feed

# Specify custom log file
pearlalgo monitor --live-feed --log-file logs/standard_console.log

# Custom refresh rate
pearlalgo monitor --refresh 1
```

### Direct Dashboard Scripts

```bash
# Run comprehensive dashboard directly
python scripts/comprehensive_dashboard.py

# Run with custom refresh
python scripts/comprehensive_dashboard.py --refresh 2

# Show once (for scripts/automation)
python scripts/comprehensive_dashboard.py --once
```

### View Logs

```bash
# Trading decisions log
tail -f logs/micro_trading.log

# Console output (detailed strategy reasoning)
tail -f logs/micro_console.log

# Standard strategy logs
tail -f logs/standard_trading.log
tail -f logs/standard_console.log
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

