# How to Use the 24/7 Multi-Asset Trading System

## Quick Start Guide

### 1. Verify Your Setup

First, make sure everything is configured:

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Check environment variables
python scripts/debug_env.py

# Verify Telegram connection
python scripts/test_telegram.py
```

**Required Environment Variables:**
- `POLYGON_API_KEY` - For market data (required)
- `TELEGRAM_BOT_TOKEN` - For alerts (required)
- `TELEGRAM_CHAT_ID` - For alerts (required)
- `GROQ_API_KEY` - Optional, for LLM reasoning

### 2. Configure the System

Edit `config/config.yaml` to set up your scanning:

```yaml
monitoring:
  workers:
    futures:
      enabled: true
      symbols: ["NQ", "ES"]  # Change to your preferred futures
      interval: 60  # Scan every 60 seconds (1 minute)
      strategy: "intraday_swing"
    
    options:
      enabled: true
      universe: ["SPY", "QQQ", "AAPL", "MSFT"]  # Start small, expand later
      interval: 900  # Scan every 900 seconds (15 minutes)
      strategy: "swing_momentum"
```

### 3. Start the 24/7 Service

#### Option A: Manual Start (Testing)

```bash
# Start the service manually
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Or with custom log file
python -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/my_service.log \
    --health-port 8080
```

**What happens:**
1. Service initializes worker pool
2. Backfills historical data buffers (30 days)
3. Starts futures worker (scans NQ/ES every 60 seconds)
4. Starts options worker (scans equities every 15 minutes)
5. Starts health check server on port 8080
6. Begins continuous scanning

#### Option B: Systemd Service (Production)

```bash
# Install and start the service
sudo ./scripts/deploy_24_7.sh
sudo systemctl start pearlalgo-continuous-service.service

# Enable auto-start on boot
sudo systemctl enable pearlalgo-continuous-service.service

# Check status
sudo systemctl status pearlalgo-continuous-service.service
```

### 4. Monitor the System

#### Check Health

```bash
# Full health check
curl http://localhost:8080/healthz | jq

# Quick health check
curl http://localhost:8080/ready

# Component status
curl http://localhost:8080/healthz | jq '.components'
```

**Expected Response:**
```json
{
  "overall_status": "healthy",
  "components": {
    "data_provider": {
      "status": "healthy",
      "connected": true,
      "success_rate": 0.95
    },
    "workers": {
      "status": "healthy",
      "total_workers": 2,
      "healthy_workers": 2
    },
    "telegram": {
      "status": "healthy",
      "enabled": true
    }
  }
}
```

#### View Logs

```bash
# Service logs (if using systemd)
sudo journalctl -u pearlalgo-continuous-service.service -f

# Application logs
tail -f logs/continuous_service.log

# Worker-specific logs
tail -f logs/worker_*.log

# Filter for signals only
tail -f logs/continuous_service.log | grep -i "signal\|exit\|entry"
```

#### Monitor Telegram

You'll receive real-time notifications:

**Entry Signals:**
```
🟢 *NEW SIGNAL*

Symbol: ES
Direction: LONG
Price: $4,500.00
Strategy: intraday_swing
Confidence: 75% ████████░░
Entry: $4,500.00
Stop Loss: $4,477.50 (0.50%)
Take Profit: $4,545.00 (1.00%)
```

**Exit Signals:**
```
💰 *Position Exited*

Symbol: ES
Direction: LONG 📈
Entry: $4,500.00
Exit: $4,520.00
Size: 1 contracts
Hold Duration: 2:15:00

Realized P&L: $20.00

Exit Reason: Take profit hit
```

### 5. Check Signal Results

#### View Signal CSV

```bash
# View recent signals
tail -20 data/performance/futures_decisions.csv

# Or use Python
python3 -c "
import pandas as pd
df = pd.read_csv('data/performance/futures_decisions.csv')
print('Last 5 signals:')
print(df[['timestamp', 'symbol', 'side', 'entry_price', 'unrealized_pnl', 'filled_size']].tail(5))
"
```

#### View Active Positions

The system tracks active signals in memory. Check logs for:
- Signal entries
- P&L updates
- Exit triggers

### 6. Adjust Configuration

#### Change Scan Frequency

Edit `config/config.yaml`:

```yaml
monitoring:
  workers:
    futures:
      interval: 120  # Change to 2 minutes
    options:
      interval: 1800  # Change to 30 minutes
```

**Restart service:**
```bash
sudo systemctl restart pearlalgo-continuous-service.service
```

#### Add More Symbols

**Futures:**
```yaml
monitoring:
  workers:
    futures:
      symbols: ["NQ", "ES", "MES", "MNQ"]  # Add more
```

**Options:**
```yaml
monitoring:
  workers:
    options:
      universe: ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "NVDA"]  # Expand
```

#### Change Strategies

```yaml
monitoring:
  workers:
    futures:
      strategy: "sr"  # Change to support/resistance
    options:
      strategy: "swing_momentum"  # Keep or change
```

### 7. Test Individual Components

#### Test Futures Scanner Only

```python
from pearlalgo.futures.intraday_scanner import FuturesIntradayScanner

scanner = FuturesIntradayScanner(
    symbols=["ES", "NQ"],
    strategy="intraday_swing",
)

# Run single scan
results = await scanner.scan()
print(results)
```

#### Test Options Scanner Only

```python
from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.swing_scanner import OptionsSwingScanner

universe = EquityUniverse(symbols=["SPY", "QQQ"])
scanner = OptionsSwingScanner(
    universe=universe,
    strategy="swing_momentum",
)

# Run single scan
results = await scanner.scan()
print(results)
```

#### Test Exit Signals

```python
from pearlalgo.futures.signal_tracker import SignalTracker
from pearlalgo.futures.exit_signals import ExitSignalGenerator

tracker = SignalTracker()
tracker.add_signal(
    symbol="ES",
    direction="long",
    entry_price=4500.0,
    size=1,
    stop_loss=4490.0,
    take_profit=4520.0,
)

generator = ExitSignalGenerator(tracker)

# Check if stop loss hit (with price below stop)
exit_signals = generator.generate_exit_signals(state)
```

### 8. Troubleshooting

#### Service Won't Start

```bash
# Check configuration
python -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"

# Check environment
python scripts/debug_env.py

# Check logs
tail -50 logs/continuous_service.log
```

#### No Signals Generated

1. **Check market hours:**
   ```python
   from pearlalgo.utils.market_hours import is_market_open
   print(is_market_open())
   ```

2. **Check data availability:**
   ```bash
   curl http://localhost:8080/healthz | jq '.components.data_provider'
   ```

3. **Check strategy parameters:**
   - Review strategy config in `config/config.yaml`
   - Verify symbols are correct

#### Workers Failing

```bash
# Check worker health
curl http://localhost:8080/healthz | jq '.components.workers'

# Check individual worker logs
grep "worker" logs/continuous_service.log | tail -20

# Restart service
sudo systemctl restart pearlalgo-continuous-service.service
```

#### Telegram Not Working

```bash
# Test Telegram connection
python scripts/test_telegram.py

# Check Telegram config
grep -A 5 "telegram:" config/config.yaml

# Verify environment variables
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
```

### 9. Daily Operations

#### Morning Checklist

```bash
# 1. Check service status
sudo systemctl status pearlalgo-continuous-service.service

# 2. Check health
curl http://localhost:8080/healthz

# 3. Review overnight signals
tail -50 logs/continuous_service.log | grep -i "signal"

# 4. Check Telegram for alerts
# (Review your Telegram chat)
```

#### During Trading Hours

- Monitor Telegram for real-time alerts
- Check health endpoint periodically
- Review signal quality in CSV files

#### End of Day

```bash
# 1. Review daily signals
python3 -c "
import pandas as pd
from datetime import datetime, timedelta
df = pd.read_csv('data/performance/futures_decisions.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])
today = datetime.now().date()
today_signals = df[df['timestamp'].dt.date == today]
print(f'Today: {len(today_signals)} signals')
print(today_signals[['symbol', 'side', 'entry_price', 'unrealized_pnl']])
"

# 2. Check service uptime
sudo systemctl status pearlalgo-continuous-service.service | grep "Active:"

# 3. Review errors
grep -i "error\|exception" logs/continuous_service.log | tail -20
```

### 10. Advanced Usage

#### Custom Strategies

Add your own strategy:

```python
# In src/pearlalgo/strategies/my_strategy.py
from pearlalgo.strategies.base import register_strategy

@register_strategy(
    name="my_custom",
    description="My custom strategy",
    default_params={"param1": 10, "param2": 20},
)
def my_custom_strategy(symbol: str, df: pd.DataFrame, **params):
    # Your strategy logic
    return {
        "side": "long",
        "confidence": 0.8,
        "strategy_name": "my_custom",
    }
```

Then use it:
```yaml
monitoring:
  workers:
    futures:
      strategy: "my_custom"
```

#### Adjust Buffer Size

```yaml
monitoring:
  buffer_size: 2000  # Increase for more history
```

#### Custom Health Checks

The health system is extensible. Add custom checks in `src/pearlalgo/monitoring/health.py`.

### 11. Performance Monitoring

#### Track Signal Quality

```python
import pandas as pd

df = pd.read_csv('data/performance/futures_decisions.csv')

# Calculate win rate
winning_signals = df[df['unrealized_pnl'] > 0]
win_rate = len(winning_signals) / len(df) if len(df) > 0 else 0
print(f"Win Rate: {win_rate:.2%}")

# Average P&L
avg_pnl = df['unrealized_pnl'].mean()
print(f"Average P&L: ${avg_pnl:.2f}")

# Best/Worst signals
print(f"Best: ${df['unrealized_pnl'].max():.2f}")
print(f"Worst: ${df['unrealized_pnl'].min():.2f}")
```

#### Monitor System Resources

```bash
# Check memory/CPU via health endpoint
curl http://localhost:8080/healthz | jq '.components.system_resources'
```

### 12. Stopping the Service

```bash
# If running manually: Ctrl+C

# If using systemd
sudo systemctl stop pearlalgo-continuous-service.service

# Disable auto-start
sudo systemctl disable pearlalgo-continuous-service.service
```

## Common Workflows

### Workflow 1: Start Fresh

```bash
# 1. Configure
nano config/config.yaml

# 2. Test Telegram
python scripts/test_telegram.py

# 3. Start service
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# 4. Monitor
tail -f logs/continuous_service.log
```

### Workflow 2: Add New Symbols

```bash
# 1. Edit config
nano config/config.yaml
# Add symbols to futures or options universe

# 2. Restart service
sudo systemctl restart pearlalgo-continuous-service.service

# 3. Verify
curl http://localhost:8080/healthz | jq '.components.workers'
```

### Workflow 3: Change Strategy

```bash
# 1. Edit config
nano config/config.yaml
# Change strategy name

# 2. Restart service
sudo systemctl restart pearlalgo-continuous-service.service

# 3. Monitor first few signals
tail -f logs/continuous_service.log | grep "signal"
```

## Quick Reference

### Key Commands

```bash
# Start service
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Check health
curl http://localhost:8080/healthz

# View logs
tail -f logs/continuous_service.log

# Test Telegram
python scripts/test_telegram.py

# View signals
tail -20 data/performance/futures_decisions.csv
```

### Key Files

- **Config**: `config/config.yaml`
- **Logs**: `logs/continuous_service.log`
- **Signals**: `data/performance/futures_decisions.csv`
- **Buffers**: `data/buffers/` (persisted historical data)

### Key Endpoints

- **Health**: `http://localhost:8080/healthz`
- **Readiness**: `http://localhost:8080/ready`
- **Liveness**: `http://localhost:8080/live`

## Next Steps

1. **Start Small**: Begin with 2-3 symbols, monitor for a day
2. **Expand Gradually**: Add more symbols as you verify stability
3. **Optimize**: Adjust intervals and strategies based on results
4. **Monitor**: Check health and logs regularly
5. **Iterate**: Refine based on signal quality

For detailed information, see:
- `docs/24_7_OPERATIONS_GUIDE.md` - Operations and troubleshooting
- `docs/OPTIONS_SCANNING_GUIDE.md` - Options-specific configuration
- `UPGRADE_IMPLEMENTATION_SUMMARY.md` - Implementation details
