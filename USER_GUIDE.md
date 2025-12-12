# Options Trading System - User Guide

## Quick Start Walkthrough

This guide walks you through using the refactored options trading system focused on QQQ and SPY options.

---

## Step 1: Initial Setup

### 1.1 Verify Environment

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Check your environment variables
python scripts/debug_env.py
```

**Required Environment Variables:**
- `MASSIVE_API_KEY` - **CRITICAL** - Must be set and valid
- `TELEGRAM_BOT_TOKEN` - For receiving alerts
- `TELEGRAM_CHAT_ID` - Your Telegram chat ID

### 1.2 Test 

```bash
python3 -c "
from pearlalgo.data_providers.
import os
api_key = os.getenv('MASSIVE_API_KEY')
if not api_key:
    print('❌ MASSIVE_API_KEY not set!')
    exit(1)
try:
    provider = 
    print('✅ 
except Exception as e:
    print(f'❌ 
    exit(1)
"
```

### 1.3 Test Telegram Connection

```bash
python scripts/test_telegram.py
```

You should receive a test message in your Telegram chat.

---

## Step 2: Configure the System

### 2.1 Edit Configuration File

```bash
nano config/config.yaml
```

### 2.2 Configure Options Workers

The system has two options workers:

**Options Swing Scanner** (15-minute intervals):
```yaml
monitoring:
  workers:
    options:
      enabled: true
      universe: ["QQQ", "SPY"]  # Underlying symbols
      interval: 900  # 15 minutes (900 seconds)
      strategy: "swing_momentum"
```

**Options Intraday Scanner** (1-minute intervals):
```yaml
    options_intraday:
      enabled: true
      symbols: ["QQQ", "SPY"]
      interval: 60  # 1 minute
      strategy: "momentum"  # Options: "momentum", "volatility", "unusual_flow"
```

### 2.3 Configure Strategy Parameters

Add strategy-specific parameters:

```yaml
# Strategy parameters (add to config.yaml)
strategies:
  momentum:
    momentum_threshold: 0.01  # 1% price change
    volume_threshold: 1.5     # 50% volume increase
  volatility:
    compression_threshold: 0.20  # 20% IV compression
  unusual_flow:
    unusual_volume_threshold: 1000
    unusual_oi_threshold: 5000

# Position sizing
position_sizing:
  max_position_size: 10  # Max contracts per trade
  base_position_size: 1
  risk_per_trade: 0.01   # 1% of account per trade

# Exit parameters
exits:
  stop_loss_pct: 0.20     # 20% stop loss
  take_profit_pct: 0.50   # 50% take profit
  time_exit_hours: 4      # Exit after 4 hours
```

---

## Step 3: Start the Service

### 3.1 Manual Start (Testing)

```bash
# Start the service
python -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/options_service.log \
    --health-port 8080
```

**What you'll see:**
1. Service validates MASSIVE_API_KEY
2. Initializes 
3. Starts options swing worker (scans QQQ/SPY every 15 minutes)
4. Starts options intraday worker (scans QQQ/SPY every 60 seconds)
5. Starts health check server on port 8080
6. Begins continuous scanning

### 3.2 Production Start (Systemd)

```bash
# Install service
sudo ./scripts/deploy_24_7.sh

# Start service
sudo systemctl start pearlalgo-continuous-service.service

# Enable auto-start on boot
sudo systemctl enable pearlalgo-continuous-service.service

# Check status
sudo systemctl status pearlalgo-continuous-service.service
```

---

## Step 4: Monitor the System

### 4.1 Check Health Status

```bash
# Full health check
curl http://localhost:8080/healthz | jq

# Quick readiness check
curl http://localhost:8080/ready
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
    }
  }
}
```

### 4.2 View Logs

```bash
# Service logs (if using systemd)
sudo journalctl -u pearlalgo-continuous-service.service -f

# Application logs
tail -f logs/options_service.log

# Filter for signals only
tail -f logs/options_service.log | grep -i "signal\|entry\|exit"
```

### 4.3 Monitor Telegram Alerts

You'll receive real-time notifications in Telegram:

**Entry Signal Example:**
```
🟢 NEW OPTIONS SIGNAL

Underlier: QQQ
Contract: QQQ240119C00100
Type: 📞 CALL
Strike: $100.00
Expiration: 2024-01-19
DTE: 5 days
Underlying Price: $100.50

Strategy: momentum
Confidence: 75% ████████░░

Entry Premium: $2.00
Delta: 0.500

Stop (Underlying): $98.00 (2.00%)
Target (Underlying): $103.00 (3.00%)

Position Size: 1 contracts
Risk Amount: $20.00

Reasoning: Momentum signal: 1.2% price change, 60% volume surge
```

**Exit Signal Example:**
```
💰 Position Exited

Symbol: QQQ240119C00100
Direction: LONG 📈
Entry: $2.00
Exit: $2.50
Size: 1 contracts
Hold Duration: 2:15:00

Realized P&L: $0.50

Exit Reason: Take profit hit
```

---

## Step 5: Understanding Signals

### 5.1 Signal Types

**Intraday Signals (0-7 DTE):**
- High-frequency scanning (every 60 seconds)
- Short-term momentum plays
- Volatility compression breakouts
- Unusual option flow detection

**Swing Signals (7-45 DTE):**
- Multi-day pattern detection
- Volatility compression + breakout
- Support/resistance levels
- Lower frequency (every 15 minutes)

### 5.2 Signal Fields Explained

- **Underlier**: The underlying stock (QQQ, SPY)
- **Contract**: Full option symbol (e.g., QQQ240119C00100)
- **Strike**: Strike price of the option
- **Expiration**: Expiration date
- **DTE**: Days to expiration
- **Delta**: Option delta (price sensitivity)
- **Entry Premium**: Option price at entry
- **Position Size**: Number of contracts
- **Stop Loss**: Stop loss level (in underlying price)
- **Take Profit**: Target level (in underlying price)

---

## Step 6: Backtesting

### 6.1 Basic Backtest

```python
from pearlalgo.backtesting.options_backtest_engine import OptionsBacktestEngine
from pearlalgo.backtesting.historical_data_loader import HistoricalFuturesDataLoader
from pearlalgo.data_providers.
from datetime import datetime
import os

# Initialize components
api_key = os.getenv('MASSIVE_API_KEY')
data_provider = 
loader = HistoricalFuturesDataLoader(data_provider)
engine = OptionsBacktestEngine(initial_cash=100000.0)

# Load historical ES/NQ data for correlation
start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 12, 1)

es_data = loader.load_es_data(start_date, end_date, timeframe="15m")
nq_data = loader.load_nq_data(start_date, end_date, timeframe="15m")

# Run backtest (you'll need to provide your strategy)
results = engine.run_backtest(
    strategy=your_strategy_instance,
    start_date=start_date,
    end_date=end_date,
    underliers=["QQQ", "SPY"],
    historical_data={"ES": es_data, "NQ": nq_data},
)

# View results
print(f"Total Return: {results['total_return']:.2%}")
print(f"Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {results['metrics']['max_drawdown']:.2%}")
print(f"Win Rate: {results['metrics']['win_rate']:.2%}")
```

### 6.2 Parameter Optimization

```python
from pearlalgo.backtesting.parameter_optimizer import ParameterOptimizer

optimizer = ParameterOptimizer()

# Define parameter grid
param_grid = {
    "momentum_threshold": [0.01, 0.02, 0.03],
    "stop_loss_pct": [0.15, 0.20, 0.25],
    "take_profit_pct": [0.40, 0.50, 0.60],
}

# Run optimization
results = optimizer.optimize_parameters(
    strategy=your_strategy,
    data=historical_data,
    param_grid=param_grid,
)

# Compare results
comparison_df = optimizer.compare_results(results)
print(comparison_df.sort_values("total_return", ascending=False))

# Generate report
report = optimizer.generate_report(results)
print(report)
```

See `docs/BACKTESTING_GUIDE.md` for detailed backtesting instructions.

---

## Step 7: Daily Operations

### 7.1 Morning Checklist

```bash
# 1. Check service status
sudo systemctl status pearlalgo-continuous-service.service

# 2. Check health
curl http://localhost:8080/healthz | jq

# 3. Review overnight signals
tail -50 logs/options_service.log | grep -i "signal"

# 4. Check Telegram for alerts
# (Review your Telegram chat)
```

### 7.2 During Trading Hours

- Monitor Telegram for real-time alerts
- Check health endpoint periodically: `curl http://localhost:8080/healthz`
- Review signal quality in logs

### 7.3 End of Day Review

```bash
# Review daily signals
python3 -c "
import pandas as pd
from datetime import datetime
# Assuming signals are logged to CSV
# df = pd.read_csv('data/performance/options_decisions.csv')
# today = datetime.now().date()
# today_signals = df[df['timestamp'].dt.date == today]
# print(f'Today: {len(today_signals)} signals')
"

# Check service uptime
sudo systemctl status pearlalgo-continuous-service.service | grep "Active:"

# Review errors
grep -i "error\|exception" logs/options_service.log | tail -20
```

---

## Step 8: Adjusting Configuration

### 8.1 Change Scan Frequency

Edit `config/config.yaml`:

```yaml
monitoring:
  workers:
    options:
      interval: 1800  # Change to 30 minutes
    options_intraday:
      interval: 120   # Change to 2 minutes
```

**Restart service:**
```bash
sudo systemctl restart pearlalgo-continuous-service.service
```

### 8.2 Add More Symbols

```yaml
monitoring:
  workers:
    options:
      universe: ["QQQ", "SPY", "AAPL", "MSFT", "NVDA"]  # Add more
```

### 8.3 Adjust Strategy Parameters

```yaml
strategies:
  momentum:
    momentum_threshold: 0.015  # Increase threshold (fewer signals)
    volume_threshold: 2.0      # Require higher volume surge
```

### 8.4 Adjust Risk Parameters

```yaml
position_sizing:
  max_position_size: 5   # Reduce max position size
  risk_per_trade: 0.005  # Reduce to 0.5% risk per trade

exits:
  stop_loss_pct: 0.15    # Tighter stop loss (15%)
  take_profit_pct: 0.40  # Lower target (40%)
```

---

## Step 9: Troubleshooting

### 9.1 Service Won't Start

**Check API Key:**
```bash
echo $MASSIVE_API_KEY
python3 -c "
from pearlalgo.data_providers.
import os
api_key = os.getenv('MASSIVE_API_KEY')
if not api_key:
    print('❌ MASSIVE_API_KEY not set')
else:
    try:
        provider = 
        print('✅ API key is valid')
    except Exception as e:
        print(f'❌ API key invalid: {e}')
"
```

**Check Configuration:**
```bash
python -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"
```

**Check Logs:**
```bash
tail -50 logs/options_service.log
grep -i "error\|exception" logs/options_service.log | tail -20
```

### 9.2 No Signals Generated

**Check Data Provider:**
```bash
curl http://localhost:8080/healthz | jq '.components.data_provider'
```

**Check Market Hours:**
```python
from pearlalgo.utils.market_hours import is_market_open
print(is_market_open())
```

**Test Data Fetching:**
```python
import asyncio
from pearlalgo.data_providers.
import os

async def test():
    api_key = os.getenv('MASSIVE_API_KEY')
    provider = 
    data = await provider.get_latest_bar('QQQ')
    if data:
        print(f"✅ Got data for QQQ: ${data['close']:.2f}")
    else:
        print("❌ No data returned")
    await provider.close()

asyncio.run(test())
```

**Check Strategy Filters:**
- Strategy parameters might be too strict
- Review confidence thresholds
- Check volume/OI requirements

### 9.3 Telegram Not Working

```bash
# Test Telegram connection
python scripts/test_telegram.py

# Check Telegram config
grep -A 5 "telegram:" config/config.yaml

# Verify environment variables
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
```

### 9.4 Data Feed Issues

**Check Data Freshness:**
```bash
curl http://localhost:8080/healthz | jq '.components.data_provider.data_freshness'
```

**Check Circuit Breaker:**
```bash
curl http://localhost:8080/healthz | jq '.components.data_provider.circuit_breaker'
```

If circuit breaker is open, wait 5 minutes or restart the service.

---

## Step 10: Advanced Usage

### 10.1 Custom Strategies

Create your own strategy in `src/pearlalgo/options/strategy.py`:

```python
from pearlalgo.options.strategy import OptionsStrategy

class MyCustomStrategy(OptionsStrategy):
    def analyze(self, options_chain, underlying_price):
        # Your custom logic
        return {
            "side": "long",
            "confidence": 0.8,
            "strike": 100.0,
            "expiration": "2024-01-19",
            "option_type": "call",
        }
```

Then use it in config:
```yaml
monitoring:
  workers:
    options:
      strategy: "my_custom"
```

### 10.2 Using Features Module

```python
from pearlalgo.options.features import OptionsFeatureComputer

computer = OptionsFeatureComputer()

# Compute features for price data
df = computer.compute_moving_averages(df)
df = computer.detect_volume_spikes(df, threshold=2.0)
df = computer.compute_momentum_indicators(df)

# Compute IV from options chain
iv_data = computer.compute_implied_volatility(options_chain)
print(f"Average IV: {iv_data['avg_iv']:.2%}")
```

### 10.3 Historical Data for Backtesting

```python
from pearlalgo.backtesting.historical_data_loader import HistoricalFuturesDataLoader

loader = HistoricalFuturesDataLoader(data_provider)

# Load ES data
es_data = loader.load_es_data(
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 1),
    timeframe="15m",
)

# Load multiple symbols and align
data = loader.load_multiple_symbols(
    symbols=["ES", "NQ"],
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 1),
    timeframe="15m",
    align=True,  # Align timestamps
)
```

---

## Common Workflows

### Workflow 1: Start Fresh

```bash
# 1. Verify environment
source .venv/bin/activate
python scripts/debug_env.py

# 2. Test 
python3 -c "from pearlalgo.data_providers..getenv('MASSIVE_API_KEY'))"

# 3. Test Telegram
python scripts/test_telegram.py

# 4. Configure
nano config/config.yaml

# 5. Start service
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# 6. Monitor
tail -f logs/options_service.log
```

### Workflow 2: Add New Underlying

```bash
# 1. Edit config
nano config/config.yaml
# Add symbol to universe: ["QQQ", "SPY", "AAPL"]

# 2. Restart service
sudo systemctl restart pearlalgo-continuous-service.service

# 3. Verify
curl http://localhost:8080/healthz | jq '.components.workers'
```

### Workflow 3: Run Backtest

```bash
# 1. Create backtest script
cat > backtest_example.py << 'EOF'
from pearlalgo.backtesting.options_backtest_engine import OptionsBacktestEngine
# ... (use code from Step 6.1)
EOF

# 2. Run backtest
python backtest_example.py

# 3. Review results
# Check generated metrics and equity curve
```

---

## Key Commands Reference

```bash
# Service Management
sudo systemctl start pearlalgo-continuous-service.service
sudo systemctl stop pearlalgo-continuous-service.service
sudo systemctl restart pearlalgo-continuous-service.service
sudo systemctl status pearlalgo-continuous-service.service

# Health Checks
curl http://localhost:8080/healthz | jq
curl http://localhost:8080/ready

# Logs
tail -f logs/options_service.log
sudo journalctl -u pearlalgo-continuous-service.service -f

# Testing
python scripts/test_telegram.py
python scripts/debug_env.py
```

---

## Next Steps

1. **Start Small**: Begin with QQQ and SPY only
2. **Monitor Closely**: Watch signals for a few days
3. **Adjust Parameters**: Fine-tune based on signal quality
4. **Expand Gradually**: Add more symbols as you verify stability
5. **Backtest First**: Test strategies on historical data before live trading
6. **Review Performance**: Analyze signal quality and adjust accordingly

---

## Getting Help

- **Documentation**: See `docs/BACKTESTING_GUIDE.md` and `docs/FUTURES_RE_ENABLEMENT.md`
- **Logs**: Check `logs/options_service.log` for detailed information
- **Health Endpoint**: `curl http://localhost:8080/healthz | jq` for system status
- **Configuration**: Review `config/config.yaml` for all settings

---

## Important Notes

1. **Market Hours**: The system only scans during market hours (9:30 AM - 4:00 PM ET)
2. **API Limits**: 
3. **Data Freshness**: Check health endpoint to ensure data is fresh (< 5 minutes old)
4. **Signal Quality**: Not all signals are trades - review confidence and reasoning
5. **Risk Management**: Position sizing and stops are automatically calculated based on your config

The system is now ready to scan for options trading opportunities on QQQ and SPY!
