# Quick Start: Testing & Running the Improved System

## Prerequisites

1. **Activate virtual environment:**
   ```bash
   cd ~/pearlalgo-dev-ai-agents
   source .venv/bin/activate
   ```

2. **Verify environment variables:**
   ```bash
   python scripts/debug_env.py
   ```

   Required:
   - `POLYGON_API_KEY` - For market data
   - `TELEGRAM_BOT_TOKEN` - For alerts (optional but recommended)
   - `TELEGRAM_CHAT_ID` - For alerts (optional but recommended)

## Step 1: Run Tests

### Quick Test Suite
```bash
./test_signal_improvements.sh
```

### Individual Test Suites

**Test exit signals:**
```bash
pytest tests/test_exit_signals.py -v
```

**Test signal lifecycle:**
```bash
pytest tests/test_signal_lifecycle.py -v
```

**Test error recovery:**
```bash
pytest tests/test_error_recovery.py -v
```

**Test performance:**
```bash
pytest tests/test_signal_performance.py -v
```

### Run All Signal Tests
```bash
pytest tests/test_exit_signals.py tests/test_signal_lifecycle.py tests/test_error_recovery.py tests/test_signal_performance.py -v
```

## Step 2: Test Signal Persistence Manually

```bash
python3 << 'EOF'
from pathlib import Path
from pearlalgo.futures.signal_tracker import SignalTracker
from datetime import datetime, timezone

# Create tracker with persistence
persistence_path = Path("data/test_signals.json")
tracker = SignalTracker(persistence_path=persistence_path)

# Add a signal
tracker.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0, take_profit=4520.0)
print("✅ Signal added")

# Create new tracker and load
tracker2 = SignalTracker(persistence_path=persistence_path)
print(f"✅ Loaded {len(tracker2.active_signals)} signals")

# Verify signal
signal = tracker2.get_signal("ES")
if signal:
    print(f"✅ Signal loaded: {signal.direction} @ ${signal.entry_price:.2f}")
    print(f"   Stop: ${signal.stop_loss:.2f}, Target: ${signal.take_profit:.2f}")

# Get metrics
metrics = tracker2.get_metrics()
print(f"✅ Metrics: {metrics['active_signals_count']} signals, PnL: ${metrics['total_pnl']:.2f}")

# Cleanup
tracker2.clear()
print("✅ Test complete")
EOF
```

## Step 3: Test Exit Signal Generation

```bash
python3 << 'EOF'
import asyncio
from pearlalgo.futures.signal_tracker import SignalTracker
from pearlalgo.futures.exit_signals import ExitSignalGenerator
from pearlalgo.agents.langgraph_state import TradingState, MarketData
from datetime import datetime, timezone

async def test_exit_signals():
    tracker = SignalTracker()
    exit_gen = ExitSignalGenerator(signal_tracker=tracker)
    
    # Add signal
    tracker.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0, take_profit=4520.0)
    print("✅ Signal added")
    
    # Test stop loss hit
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
        print(f"   Reason: {exit_signals['ES'].reasoning}")
    
    # Get metrics
    metrics = exit_gen.get_exit_metrics()
    print(f"✅ Exit metrics: {metrics['exit_generation']['success_rate']:.2%} success rate")

asyncio.run(test_exit_signals())
EOF
```

## Step 4: Start the Continuous Service

### Option A: Manual Start (Recommended for Testing)

```bash
# Start the service
python -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/continuous_service.log \
    --health-port 8080
```

### Option B: Background Process

```bash
# Start in background
nohup python -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/continuous_service.log \
    --health-port 8080 > logs/service_output.log 2>&1 &

# Check if running
ps aux | grep continuous_service

# View logs
tail -f logs/continuous_service.log
```

## Step 5: Monitor the System

### Check Health Endpoint

```bash
# Full health check
curl http://localhost:8080/healthz | jq

# Check signal tracker health
curl http://localhost:8080/healthz | jq '.components.signal_tracker'

# Check exit generator health
curl http://localhost:8080/healthz | jq '.components.exit_signal_generator'
```

### Monitor Logs

```bash
# Service logs
tail -f logs/continuous_service.log

# Filter for signals
tail -f logs/continuous_service.log | grep -i "signal\|exit\|entry"

# Filter for errors
tail -f logs/continuous_service.log | grep -i "error\|warning"
```

### Check Signal Persistence

```bash
# View persisted signals
cat data/active_signals.json | jq

# Check backup file
ls -lh data/active_signals.json.bak 2>/dev/null || echo "No backup yet"
```

## Step 6: Verify Signal Tracking

```bash
python3 << 'EOF'
from pathlib import Path
import json

# Check persisted signals
persistence_path = Path("data/active_signals.json")
if persistence_path.exists():
    with open(persistence_path) as f:
        signals = json.load(f)
    print(f"✅ Found {len(signals)} persisted signals")
    for symbol, data in signals.items():
        print(f"   {symbol}: {data['direction']} @ ${data['entry_price']:.2f} (state: {data.get('lifecycle_state', 'active')})")
else:
    print("ℹ️  No persisted signals yet (service may not have generated any)")
EOF
```

## Troubleshooting

### Tests Failing

1. **Import errors:**
   ```bash
   pip install -e ".[dev]"
   ```

2. **Async test issues:**
   ```bash
   pip install pytest-asyncio
   ```

3. **Missing dependencies:**
   ```bash
   pip install -r requirements.txt  # if exists
   pip install pytest pytest-asyncio pytz
   ```

### Service Not Starting

1. **Check configuration:**
   ```bash
   python -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"
   ```

2. **Check environment:**
   ```bash
   python scripts/debug_env.py
   ```

3. **Check logs:**
   ```bash
   tail -50 logs/continuous_service.log
   ```

### No Exit Signals Generated

1. **Check active signals:**
   ```bash
   cat data/active_signals.json | jq
   ```

2. **Check market data:**
   ```bash
   curl http://localhost:8080/healthz | jq '.components.data_provider'
   ```

3. **Check exit generator metrics:**
   ```bash
   # Add this to a test script or check logs
   ```

## Next Steps

1. **Monitor for a few cycles** to see signals being generated
2. **Check Telegram** for entry/exit notifications
3. **Review metrics** via health endpoint
4. **Check persistence** after service restart

## Quick Commands Reference

```bash
# Run all signal tests
pytest tests/test_exit_signals.py tests/test_signal_lifecycle.py -v

# Start service
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Check health
curl http://localhost:8080/healthz | jq

# View signals
cat data/active_signals.json | jq

# Monitor logs
tail -f logs/continuous_service.log | grep -i signal
```
