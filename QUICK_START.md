# Quick Start Guide - NQ Futures 24/7 Monitoring

## Overview
This system continuously monitors NQ (and ES) futures, generates trading signals, and sends entry/exit alerts to Telegram.

## Prerequisites

1. **Environment Variables** (in `.env` file):
   ```bash
   POLYGON_API_KEY=your_polygon_api_key
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   ```

2. **Python Environment**:
   ```bash
   source .venv/bin/activate
   ```

## Start the Service

### Option 1: Manual Start (Testing/Development)

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml
```

**What happens:**
- Service initializes
- Backfills historical data buffers (30 days)
- Starts futures worker (scans NQ/ES every 60 seconds)
- Starts health check server on port 8080
- Begins continuous monitoring

### Option 2: Systemd Service (Production)

```bash
# Install and start the service
sudo ./scripts/deploy_24_7.sh
sudo systemctl start pearlalgo-continuous-service.service

# Enable auto-start on boot
sudo systemctl enable pearlalgo-continuous-service.service

# Check status
sudo systemctl status pearlalgo-continuous-service.service
```

## Monitor the System

### Check Health

```bash
# Full health check
curl http://localhost:8080/healthz

# Pretty print (if you have jq)
curl -s http://localhost:8080/healthz | jq .
```

### View Logs

**Note:** When running manually, logs go to the console (stdout). To save to a file:

```bash
# Run with log file
python -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml \
    --log-file logs/continuous_service.log

# Then view logs
tail -f logs/continuous_service.log

# Or redirect console output to file
python -m pearlalgo.monitoring.continuous_service \
    --config config/config.yaml 2>&1 | tee logs/continuous_service.log
```

**If using systemd:**
```bash
# Service logs
sudo journalctl -u pearlalgo-continuous-service.service -f

# Watch for signals only
sudo journalctl -u pearlalgo-continuous-service.service -f | grep -i "signal\|entry\|exit"
```

### Check Telegram

You'll receive real-time notifications:

**Startup Notification (on service start):**
```
🚀 Service Started

Status: Monitoring Active
Symbols: NQ, ES
Strategy: intraday_swing
Scan Interval: 60s
Health Check: http://localhost:8080/healthz

System is now monitoring markets 24/7.
```

**Periodic Status Updates (every 10 minutes):**
```
📊 Status Update

Uptime: 2h 15m
Cycles Run: 135
Worker Status: Running

Buffer Status:
  • NQ: 150 bars
  • ES: 148 bars

System is running normally. Monitoring for signals...
```

**Entry Signals:**
```
📊 Signal Generated

Symbol: NQ
Direction: LONG
Strategy: intraday_swing
Confidence: 75%
```

**Exit Signals:**
```
💰 Position Exited

Symbol: NQ
Direction: LONG 📈
Entry: $18,000.00
Exit: $18,050.00
Size: 1 contracts

Realized P&L: $50.00

Exit Reason: Take profit hit
```

**Shutdown Notification (on service stop):**
```
🛑 Service Stopped

Uptime: 5h 30m
Total Cycles: 330

Service has been shut down gracefully.
```

## Configuration

Edit `config/config.yaml` to customize:

```yaml
monitoring:
  workers:
    futures:
      enabled: true
      symbols: ["NQ", "ES"]  # Change symbols here
      interval: 60  # Scan every 60 seconds (1 minute)
      strategy: "intraday_swing"  # Strategy name
  
  # Status update notifications (Telegram)
  status_update_interval: 600  # seconds (10 minutes) - Send periodic status updates
```

**After changing config, restart the service:**
```bash
# If manual
Ctrl+C, then restart

# If systemd
sudo systemctl restart pearlalgo-continuous-service.service
```

## Stop the Service

```bash
# If running manually
Ctrl+C

# If using systemd
sudo systemctl stop pearlalgo-continuous-service.service
```

## Troubleshooting

### Service Won't Start

```bash
# Check configuration
python -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"

# Check environment variables
echo $POLYGON_API_KEY
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID

# Check logs
tail -50 logs/continuous_service.log
```

### No Signals Generated

1. **Check market hours:**
   ```python
   from pearlalgo.utils.market_hours import is_market_open
   print(is_market_open())
   ```

2. **Check data availability:**
   ```bash
   curl http://localhost:8080/healthz | jq '.components.data_provider'
   ```

3. **Check buffer has data:**
   ```bash
   ls -lh data/buffers/
   ```

### Telegram Not Working

**Common Issues:**

1. **"Not Found" Error:**
   - Make sure you've started the bot by sending `/start` to your bot in Telegram
   - Verify your chat_id is correct
   - Check that the bot has permission to send messages

2. **Test Connection:**
   ```bash
   # Test Telegram connection
   python scripts/test_telegram.py
   ```

3. **Check Credentials:**
   ```bash
   # Verify environment variables are loaded
   source .venv/bin/activate
   python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Chat ID:', os.getenv('TELEGRAM_CHAT_ID'))"
   ```

4. **Check Telegram Config:**
   ```bash
   grep -A 5 "telegram:" config/config.yaml
   ```

## Quick Commands Reference

```bash
# Start service
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml

# Check health
curl http://localhost:8080/healthz

# View logs
tail -f logs/continuous_service.log

# Test Telegram
python scripts/test_telegram.py

# View recent signals
tail -20 data/performance/futures_decisions.csv
```

## Expected Behavior

When running correctly, you should see:

1. **Service starts** - Logs show initialization
2. **Buffers backfill** - Historical data loaded (or warnings if API key invalid)
3. **Workers start** - Futures scanner begins monitoring
4. **Signals generate** - When market conditions match strategy
5. **Telegram alerts** - Entry and exit notifications sent
6. **Health checks** - System reports healthy status

## Next Steps

1. **Monitor for a day** - Watch signals and verify Telegram alerts
2. **Review signal quality** - Check if signals match your expectations
3. **Adjust strategy** - Modify `intraday_swing` parameters if needed
4. **Scale up** - Add more symbols or adjust scan frequency

For detailed information, see:
- `docs/24_7_OPERATIONS_GUIDE.md` - Operations and troubleshooting
- `HOW_TO_USE_24_7_SYSTEM.md` - Detailed usage guide


