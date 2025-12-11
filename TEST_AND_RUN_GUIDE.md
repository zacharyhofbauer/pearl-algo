# Test and Run Guide - Signal Improvements

## ✅ Quick Test (All Passed!)

Run this to verify everything works:
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python3 quick_test.py
```

**Expected Output:**
```
✅ ALL TESTS PASSED (4/4)
🎉 System is ready to run!
```

## 🚀 Start the Service

### Option 1: Simple Start
```bash
source .venv/bin/activate
python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml
```

### Option 2: With Custom Log File
```bash
source .venv/bin/activate
python3 -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/my_service.log \
    --health-port 8080
```

### Option 3: Background Process
```bash
source .venv/bin/activate
nohup python3 -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/continuous_service.log \
    --health-port 8080 > logs/service_output.log 2>&1 &

# Check if running
ps aux | grep continuous_service
```

## 📊 Monitor the System

### 1. Check Health
```bash
# Full health check
curl http://localhost:8080/healthz | jq

# Signal tracker health
curl http://localhost:8080/healthz | jq '.components.signal_tracker'

# Exit generator health
curl http://localhost:8080/healthz | jq '.components.exit_signal_generator'
```

### 2. View Logs
```bash
# All logs
tail -f logs/continuous_service.log

# Only signals
tail -f logs/continuous_service.log | grep -i "signal\|exit\|entry"

# Errors
tail -f logs/continuous_service.log | grep -i "error\|warning"
```

### 3. Check Persisted Signals
```bash
# View active signals
cat data/active_signals.json | jq

# Check backup exists
ls -lh data/active_signals.json.bak
```

## 🧪 Run Full Test Suite

### All Signal Tests
```bash
source .venv/bin/activate
pytest tests/test_exit_signals.py tests/test_signal_lifecycle.py tests/test_error_recovery.py tests/test_signal_performance.py -v
```

### Individual Test Files
```bash
# Exit signals
pytest tests/test_exit_signals.py -v

# Signal lifecycle
pytest tests/test_signal_lifecycle.py -v

# Error recovery
pytest tests/test_error_recovery.py -v

# Performance
pytest tests/test_signal_performance.py -v
```

## 🔍 Verify Everything is Working

### Test Signal Persistence Manually
```bash
python3 << 'EOF'
from pathlib import Path
from pearlalgo.futures.signal_tracker import SignalTracker

# Test persistence
path = Path("data/test_manual.json")
tracker1 = SignalTracker(persistence_path=path)
tracker1.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)
tracker1._save_signals(immediate=True)  # Force save

# Load
tracker2 = SignalTracker(persistence_path=path)
print(f"✅ Loaded {len(tracker2.active_signals)} signals")
signal = tracker2.get_signal("ES")
if signal:
    print(f"✅ Signal: {signal.direction} @ ${signal.entry_price:.2f}")
    
# Get metrics
metrics = tracker2.get_metrics()
print(f"✅ Metrics: {metrics['active_signals_count']} signals")
EOF
```

### Test Exit Signal Generation
```bash
python3 << 'EOF'
import asyncio
from pearlalgo.futures.signal_tracker import SignalTracker
from pearlalgo.futures.exit_signals import ExitSignalGenerator
from pearlalgo.agents.langgraph_state import TradingState, MarketData
from datetime import datetime, timezone

async def test():
    tracker = SignalTracker()
    exit_gen = ExitSignalGenerator(signal_tracker=tracker)
    
    tracker.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)
    
    state = TradingState(
        market_data={
            "ES": MarketData("ES", datetime.now(timezone.utc), 4485.0, 4490.0, 4480.0, 4485.0, 1000)
        },
        signals={},
        position_decisions={},
    )
    
    exit_signals = await exit_gen.generate_exit_signals(state)
    if "ES" in exit_signals:
        print(f"✅ Exit signal: {exit_signals['ES'].indicators.get('exit_type')}")
    else:
        print("❌ No exit signal")
    
    metrics = exit_gen.get_exit_metrics()
    print(f"✅ Exit metrics: {metrics['exit_generation']['success_rate']:.2%} success")

asyncio.run(test())
EOF
```

## 🐛 Troubleshooting

### Service Won't Start
```bash
# Check config
python3 -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"

# Check environment
source .venv/bin/activate
python3 scripts/debug_env.py

# Check logs
tail -50 logs/continuous_service.log
```

### No Exit Signals Generated
1. Check if signals exist: `cat data/active_signals.json | jq`
2. Check market data: `curl http://localhost:8080/healthz | jq '.components.data_provider'`
3. Check logs: `tail -f logs/continuous_service.log | grep -i exit`

### Tests Failing
```bash
# Reinstall
source .venv/bin/activate
pip install -e ".[dev]"
pip install pytest pytest-asyncio
```

## 📈 What to Monitor

### Successful Run Indicators:
- ✅ Service starts without errors
- ✅ Health endpoint returns 200
- ✅ Signals being generated (check logs)
- ✅ Exit signals generated when conditions met
- ✅ Signals persisting to `data/active_signals.json`
- ✅ Backup files being created
- ✅ Metrics available via health endpoint

### Key Files to Watch:
- `logs/continuous_service.log` - Main service logs
- `data/active_signals.json` - Persisted signals
- `data/active_signals.json.bak` - Backup file

## 🎯 Quick Commands Reference

```bash
# Quick test
python3 quick_test.py

# Start service
python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Check health
curl http://localhost:8080/healthz | jq

# View signals
cat data/active_signals.json | jq

# Monitor
tail -f logs/continuous_service.log | grep -i signal
```

## 📝 Next Steps After Testing

1. **Let service run** for a few cycles to see signals being generated
2. **Check Telegram** for entry/exit notifications (if configured)
3. **Review metrics** via health endpoint periodically
4. **Test persistence** by restarting service and verifying signals are loaded
5. **Monitor for issues** in logs and health checks
