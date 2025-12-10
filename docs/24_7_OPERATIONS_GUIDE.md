# 24/7 Operations Guide

## Overview

This guide covers operating the 24/7 continuous monitoring system for futures intraday trading and options swing scanning.

## Architecture

The system consists of:

1. **Continuous Service** (`src/pearlalgo/monitoring/continuous_service.py`)
   - Orchestrates worker pool
   - Manages health checks
   - Handles graceful shutdown

2. **Worker Pool** (`src/pearlalgo/monitoring/worker_pool.py`)
   - Separate workers for futures and options
   - Automatic restart on failure
   - Health monitoring

3. **Data Feed Manager** (`src/pearlalgo/monitoring/data_feed_manager.py`)
   - Polygon API connection management
   - Rate limiting (5 calls/sec free tier)
   - Automatic reconnection

4. **Health Check System** (`src/pearlalgo/monitoring/health.py`)
   - HTTP endpoints: `/healthz`, `/ready`, `/live`
   - Component health monitoring
   - System resource tracking

## Starting the Service

### Manual Start

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python -m pearlalgo.monitoring.continuous_service --config config/config.yaml
```

### Using Systemd (Recommended)

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

## Configuration

### Workers Configuration

Edit `config/config.yaml`:

```yaml
monitoring:
  workers:
    futures:
      enabled: true
      symbols: ["NQ", "ES"]
      interval: 60  # seconds (1 minute)
      strategy: "intraday_swing"
    options:
      enabled: true
      universe: ["SPY", "QQQ", "AAPL", "MSFT"]
      interval: 900  # seconds (15 minutes)
      strategy: "swing_momentum"
```

### Data Feed Configuration

```yaml
monitoring:
  data_feeds:
    polygon:
      rate_limit: 5  # calls per second
      reconnect_delay: 5.0  # seconds
      max_reconnect_attempts: 10
```

### Health Check Configuration

```yaml
monitoring:
  health:
    enabled: true
    port: 8080
    check_interval: 60  # seconds
```

## Monitoring

### Health Endpoints

- **`/healthz`** - Full health check (returns 200 if healthy, 503 if degraded)
- **`/ready`** - Readiness probe (Kubernetes-compatible)
- **`/live`** - Liveness probe (Kubernetes-compatible)

```bash
# Check health
curl http://localhost:8080/healthz

# Check readiness
curl http://localhost:8080/ready

# Check liveness
curl http://localhost:8080/live
```

### Logs

```bash
# View service logs
sudo journalctl -u pearlalgo-continuous-service.service -f

# View application logs
tail -f logs/continuous_service.log

# View worker logs
tail -f logs/worker_*.log
```

### Worker Statistics

The service tracks:
- Total workers
- Workers by type (futures, options, data_feed)
- Workers by status (idle, running, error, stopped)
- Total errors and restarts

## Troubleshooting

### Service Won't Start

1. Check configuration:
   ```bash
   python -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"
   ```

2. Check environment variables:
   ```bash
   python scripts/debug_env.py
   ```

3. Check logs:
   ```bash
   sudo journalctl -u pearlalgo-continuous-service.service -n 50
   ```

### Workers Failing

1. Check worker health:
   ```bash
   curl http://localhost:8080/healthz | jq '.components.workers'
   ```

2. Check individual worker logs:
   ```bash
   grep "worker" logs/continuous_service.log | tail -20
   ```

3. Restart service:
   ```bash
   sudo systemctl restart pearlalgo-continuous-service.service
   ```

### Data Feed Issues

1. Check Polygon API key:
   ```bash
   echo $POLYGON_API_KEY
   ```

2. Check connection:
   ```bash
   curl http://localhost:8080/healthz | jq '.components.data_provider'
   ```

3. Check rate limits:
   - Free tier: 5 calls/second
   - If exceeded, increase interval or reduce symbols

### Memory Issues

1. Check memory usage:
   ```bash
   curl http://localhost:8080/healthz | jq '.components.system_resources'
   ```

2. Reduce buffer size in config:
   ```yaml
   monitoring:
     buffer_size: 500  # Reduce from 1000
   ```

3. Restart service periodically:
   ```bash
   # Add to crontab for daily restart
   0 2 * * * systemctl restart pearlalgo-continuous-service.service
   ```

## Performance Tuning

### Scan Intervals

- **Futures**: 60 seconds (1 minute) for intraday
- **Options**: 900 seconds (15 minutes) for swing

Adjust based on:
- API rate limits
- Signal frequency
- System resources

### Buffer Size

Default: 1000 bars per symbol

- Increase for longer lookback periods
- Decrease to save memory
- Minimum: 50 bars for basic indicators

### Worker Count

Default: 1 futures worker, 1 options worker

- Add more workers for parallel scanning
- Monitor CPU usage
- Each worker uses ~100-200MB memory

## Maintenance

### Daily Tasks

1. Check health status
2. Review logs for errors
3. Monitor Telegram alerts
4. Check signal generation rate

### Weekly Tasks

1. Review performance metrics
2. Clean old log files
3. Verify buffer persistence
4. Update configuration if needed

### Monthly Tasks

1. Review and optimize strategies
2. Update equity universe
3. Review risk parameters
4. System updates

## Backup and Recovery

### State Persistence

Buffers are saved to `data/buffers/`:
- Automatic save on shutdown
- Load on startup
- Format: `{symbol}_buffer.pkl`

### Recovery

If service crashes:
1. Buffers are automatically reloaded on restart
2. Signal tracker state is lost (will rebuild)
3. No trade execution state (signal-only mode)

## Scaling

### Horizontal Scaling

Run multiple instances:
- Different symbol sets per instance
- Shared Telegram channel
- Separate health endpoints

### Vertical Scaling

Increase resources:
- More workers
- Larger buffers
- Faster scan intervals

## Security

- API keys in environment variables only
- No hardcoded secrets
- Logs don't contain sensitive data
- Health endpoints don't expose secrets

## Support

For issues:
1. Check logs first
2. Review health endpoints
3. Check configuration
4. Review this guide
