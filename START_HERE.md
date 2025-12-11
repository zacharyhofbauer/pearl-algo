# Quick Start: Test and Run the Improved System

## 🚀 Quick Start (3 Steps)

### Step 1: Setup and Test
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
./setup_and_test.sh
```

### Step 2: Start the Service
```bash
# Make sure virtual environment is activated
source .venv/bin/activate

# Start the continuous service
python3 -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/continuous_service.log \
    --health-port 8080
```

### Step 3: Monitor
```bash
# In another terminal, check health
curl http://localhost:8080/healthz | jq

# Watch logs
tail -f logs/continuous_service.log | grep -i "signal\|exit\|entry"
```

## 📋 Detailed Testing

### Run All Signal Tests
```bash
source .venv/bin/activate
pytest tests/test_exit_signals.py tests/test_signal_lifecycle.py tests/test_error_recovery.py -v
```

### Test Individual Components

**1. Test Signal Persistence:**
```bash
python3 << 'EOF'
from pathlib import Path
from pearlalgo.futures.signal_tracker import SignalTracker

# Test persistence
persistence_path = Path("data/test_signals.json")
tracker1 = SignalTracker(persistence_path=persistence_path)
tracker1.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)

# Load in new tracker
tracker2 = SignalTracker(persistence_path=persistence_path)
print(f"✅ Loaded {len(tracker2.active_signals)} signals")
signal = tracker2.get_signal("ES")
if signal:
    print(f"✅ Signal: {signal.direction} @ ${signal.entry_price:.2f}")
EOF
```

**2. Test Exit Signal Generation:**
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
        print(f"✅ Exit signal generated: {exit_signals['ES'].indicators.get('exit_type')}")
    else:
        print("❌ No exit signal generated")

asyncio.run(test())
EOF
```

**3. Test Metrics:**
```bash
python3 << 'EOF'
from pearlalgo.futures.signal_tracker import SignalTracker

tracker = SignalTracker()
tracker.add_signal("ES", "long", 4500.0, 1)
tracker.add_signal("NQ", "short", 15000.0, 1)

metrics = tracker.get_metrics()
print(f"✅ Active signals: {metrics['active_signals_count']}")
print(f"✅ Persistence success rate: {metrics['persistence_operations']['success_rate']:.2%}")
EOF
```

## 🔍 Verify System is Working

### Check Health Endpoint
```bash
# Full health check
curl http://localhost:8080/healthz | jq

# Signal tracker health
curl http://localhost:8080/healthz | jq '.components.signal_tracker'

# Exit generator health  
curl http://localhost:8080/healthz | jq '.components.exit_signal_generator'
```

### Check Persisted Signals
```bash
# View active signals
cat data/active_signals.json | jq 2>/dev/null || echo "No signals yet"

# Check backup
ls -lh data/active_signals.json.bak 2>/dev/null || echo "No backup yet"
```

### Monitor Logs
```bash
# All logs
tail -f logs/continuous_service.log

# Only signals
tail -f logs/continuous_service.log | grep -i "signal\|exit\|entry"

# Errors only
tail -f logs/continuous_service.log | grep -i "error\|warning"
```

## 🐛 Troubleshooting

### Tests Failing
```bash
# Reinstall dependencies
source .venv/bin/activate
pip install -e ".[dev]"
pip install pytest pytest-asyncio
```

### Service Won't Start
```bash
# Check config
python3 -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"

# Check environment
source .venv/bin/activate
python3 scripts/debug_env.py
```

### No Exit Signals
1. Check if signals are being tracked: `cat data/active_signals.json | jq`
2. Check market data: `curl http://localhost:8080/healthz | jq '.components.data_provider'`
3. Check logs: `tail -f logs/continuous_service.log | grep -i exit`

## 📊 What to Look For

### Successful Test Run Should Show:
- ✅ Signal persistence save/load working
- ✅ Exit signals generated for stop loss/take profit
- ✅ Signal validation working
- ✅ Metrics being collected

### Successful Service Run Should Show:
- ✅ Service starts without errors
- ✅ Health endpoint returns 200
- ✅ Signals being generated and tracked
- ✅ Exit signals being generated when conditions met
- ✅ Signals persisting to `data/active_signals.json`

## 🎯 Next Steps After Testing

1. **Let it run for a few cycles** to see signals being generated
2. **Check Telegram** for entry/exit notifications (if configured)
3. **Review metrics** via health endpoint
4. **Test persistence** by restarting service and verifying signals are loaded

## 📝 Quick Reference

```bash
# Setup
source .venv/bin/activate
./setup_and_test.sh

# Start service
python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Check health
curl http://localhost:8080/healthz | jq

# View signals
cat data/active_signals.json | jq

# Monitor
tail -f logs/continuous_service.log | grep -i signal
```
