# 24/7 Signal Generation Deployment Guide

## Overview

This guide covers deploying the 24/7 signal generation service that continuously monitors markets, generates signals, and sends Telegram notifications.

## Prerequisites

1. **Polygon API Key** - Required for market data
2. **Telegram Bot Token** - Required for notifications
3. **Telegram Chat ID** - Your Telegram channel/chat ID
4. **Python 3.12+** with virtual environment
5. **Systemd** (for service management on Linux)

## Quick Start

### 1. Environment Setup

Create `.env` file in project root:

```bash
POLYGON_API_KEY=your_polygon_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
GROQ_API_KEY=your_groq_api_key  # Optional, for LLM reasoning
```

### 2. Test Signal Generation

Before deploying 24/7, test the system:

```bash
source .venv/bin/activate
./scripts/run_signal_generation.sh ES NQ sr
```

Monitor Telegram for signal notifications.

### 3. Deploy as Systemd Service

Run the deployment script:

```bash
sudo ./scripts/deploy_24_7.sh
```

This will:
- Create log directories
- Install systemd service
- Enable auto-start on boot
- Configure service with proper settings

### 4. Start the Service

```bash
sudo systemctl start pearlalgo-signal_service.service
```

### 5. Monitor the Service

**Check status:**
```bash
sudo systemctl status pearlalgo-signal_service.service
```

**View logs:**
```bash
# Systemd logs
sudo journalctl -u pearlalgo-signal_service.service -f

# Application logs
tail -f logs/signal_generation.log
```

**Health check:**
```bash
source .venv/bin/activate
python scripts/signal_health_monitor.py
```

## Configuration

### Service Configuration

Edit `/etc/systemd/system/pearlalgo-signal_service.service` to customize:

- **Symbols**: Change `--symbols ES NQ MES MNQ` to your preferred symbols
- **Strategy**: Change `--strategy sr` to your preferred strategy
- **Interval**: Change `--interval 300` (5 minutes) to your preferred interval
  - Note: Must respect Polygon API rate limits (free tier: 5 calls/min)

### Production Config

Edit `config/config.production.yaml` to customize:

- Signal deduplication window
- Market hours awareness
- Telegram notification settings
- Logging configuration

## Features

### 1. Automatic Restart

The service automatically restarts on failure with exponential backoff.

### 2. Signal Deduplication

Prevents duplicate signals within a configurable time window (default: 15 minutes).

### 3. Market Hours Awareness

Skips signal generation when markets are closed (Friday 5 PM ET - Sunday 6 PM ET).

### 4. Health Monitoring

Run `signal_health_monitor.py` to check:
- Service status
- Recent activity
- Polygon API connectivity
- Telegram configuration

### 5. Error Recovery

- Automatic retry on transient errors
- Circuit breaker for repeated failures
- Graceful shutdown handling

## Troubleshooting

### Service Won't Start

1. Check service status:
   ```bash
   sudo systemctl status pearlalgo-signal_service.service
   ```

2. Check logs:
   ```bash
   sudo journalctl -u pearlalgo-signal_service.service -n 50
   ```

3. Verify environment variables:
   ```bash
   sudo systemctl show pearlalgo-signal_service.service | grep Environment
   ```

### No Signals Generated

1. Check if market is open:
   ```bash
   python -c "from pearlalgo.utils.market_hours import is_market_open; print(is_market_open())"
   ```

2. Check Polygon API key:
   ```bash
   echo $POLYGON_API_KEY
   ```

3. Check recent logs:
   ```bash
   tail -100 logs/signal_generation.log
   ```

### Telegram Notifications Not Working

1. Test Telegram bot:
   ```bash
   source .venv/bin/activate
   python scripts/send_test_message.py
   ```

2. Verify credentials:
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

### High Memory Usage

The service has a 2GB memory limit. If exceeded:
- Reduce number of symbols
- Increase interval between cycles
- Check for memory leaks in logs

## Manual Operation

If you prefer to run manually instead of as a service:

```bash
source .venv/bin/activate
python scripts/signal_generation_service.py \
    --symbols ES NQ MES MNQ \
    --strategy sr \
    --interval 300 \
    --log-file logs/signal_generation.log
```

## Stopping the Service

```bash
sudo systemctl stop pearlalgo-signal_service.service
```

To disable auto-start:
```bash
sudo systemctl disable pearlalgo-signal_service.service
```

## Updating the Service

1. Stop the service:
   ```bash
   sudo systemctl stop pearlalgo-signal_service.service
   ```

2. Update code/config

3. Restart the service:
   ```bash
   sudo systemctl start pearlalgo-signal_service.service
   ```

Or reload if only config changed:
```bash
sudo systemctl daemon-reload
sudo systemctl restart pearlalgo-signal_service.service
```

## Monitoring

### Health Check Script

Run periodically (e.g., via cron):

```bash
# Add to crontab (crontab -e)
*/15 * * * * cd /home/pearlalgo/pearlalgo-dev-ai-agents && source .venv/bin/activate && python scripts/signal_health_monitor.py
```

### Log Rotation

Logs are automatically rotated:
- Daily rotation at midnight
- 30-day retention
- Automatic compression

### Metrics to Monitor

- Service uptime
- Cycle count
- Error rate
- Signal generation rate
- Telegram notification success rate

## Next Steps

Once 24/7 operation is stable:

1. **Optimize Signal Quality**
   - Analyze signal performance
   - Tune strategy parameters
   - Add filters

2. **Enhance Strategies**
   - Multi-timeframe analysis
   - Volume confirmation
   - ML-based confidence scoring

3. **Performance Improvements**
   - Backtest strategies
   - Optimize parameters
   - A/B test different approaches

## Support

For issues or questions:
1. Check logs: `logs/signal_generation.log`
2. Run health check: `scripts/signal_health_monitor.py`
3. Review systemd logs: `sudo journalctl -u pearlalgo-signal_service.service`

