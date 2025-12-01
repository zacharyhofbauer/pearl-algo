# Automated Trading Agent Setup Guide

This guide explains how to set up fully automated IBKR paper trading that runs continuously.

## Overview

The automated trading agent:
- ✅ Runs continuously with market hours awareness
- ✅ Auto-recovers from connection errors
- ✅ Manages positions and exits automatically
- ✅ Respects risk limits and cooldown periods
- ✅ Logs all decisions and trades
- ✅ Can run as a systemd service for 24/7 operation

## Quick Start

### 1. Manual Run (Testing)

First, test the agent manually to ensure everything works:

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate

# Run with default settings (ES, NQ, GC, sr strategy, 5min interval)
python scripts/automated_trading.py

# Custom configuration
python scripts/automated_trading.py \
  --symbols NQ ES \
  --strategy sr \
  --interval 300 \
  --tiny-size 1 \
  --log-level INFO \
  --log-file logs/automated_trading.log
```

### 2. Systemd Service Setup (Production)

For 24/7 automated trading, set up as a systemd service:

```bash
# Copy service file to systemd directory
sudo cp scripts/automated_trading.service /etc/systemd/system/

# Edit the service file to match your configuration
sudo nano /etc/systemd/system/automated_trading.service

# Key settings to customize:
# - User/Group (currently set to 'pearlalgo')
# - WorkingDirectory
# - ExecStart command with your preferred symbols/strategy
# - Log file path

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable automated_trading.service

# Start the service
sudo systemctl start automated_trading.service

# Check status
sudo systemctl status automated_trading.service

# View logs
sudo journalctl -u automated_trading.service -f

# Or view the log file directly
tail -f logs/automated_trading.log
```

### 3. Health Monitoring

Check system health:

```bash
# Run health check
python scripts/health_check.py

# View status dashboard (real-time)
python scripts/status_dashboard.py --live
```

## Configuration

### .env File (Required)
```bash
PEARLALGO_PROFILE=live
PEARLALGO_ALLOW_LIVE_TRADING=true
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002
PEARLALGO_IB_CLIENT_ID=1
```

### Trading Parameters

Edit the service file or command line arguments:

- `--symbols`: Symbols to trade (default: ES NQ GC)
  - Regular: ES, NQ, GC, YM, RTY, CL
  - Micro: MGC, MYM, MCL, MNQ, MES (use `config/micro_strategy_config.yaml`)
- `--strategy`: Strategy name (ma_cross or sr, default: sr)
- `--interval`: Loop interval in seconds (default: 300 = 5 minutes)
- `--tiny-size`: Base contract size (default: 1, use 3-5 for micro)
- `--profile-config`: Path to prop profile config (optional)

### Risk Profile

Configure risk limits in `config/prop_profile.yaml`:

```yaml
name: automated
starting_balance: 50000.0
daily_loss_limit: 2500.0
target_profit: 5000.0
max_trades: 20  # Optional: limit trades per day
cooldown_minutes: 60
max_contracts_by_symbol:
  ES: 2
  NQ: 2
  GC: 1
```

### IB Gateway Setup

Ensure IB Gateway is running and accessible:

```bash
# Check if IB Gateway service is running
sudo systemctl status ibgateway.service

# Start if needed
sudo systemctl start ibgateway.service

# The automated trading agent will wait for IB Gateway to be ready
```

## Features

### Market Hours Awareness

The agent automatically checks if markets are open. Currently configured for:
- Monday-Friday trading (futures trade nearly 24/5)
- Can be customized in `automated_trading_agent.py`

### Error Recovery

- Automatic reconnection on connection failures
- Configurable retry logic (`--max-retries`, `--retry-delay`)
- Continues trading after temporary errors

### Position Management

- Automatically exits positions on opposite signals
- Risk-based exits (HARD_STOP, COOLDOWN)
- Tracks entry/exit times for performance analysis

### Risk Management

- Respects daily loss limits
- Tapers position sizing as risk buffer shrinks
- Cooldown periods after max trades or hard stops
- Per-symbol contract limits

## Monitoring

### Real-time Dashboard

```bash
python scripts/status_dashboard.py --live
```

Shows:
- IB Gateway status
- Latest signals and reports
- Performance metrics (win rate, PnL, drawdown)
- Risk state (OK, NEAR_LIMIT, HARD_STOP, COOLDOWN)
- Per-symbol statistics

### Log Files

- Service logs: `sudo journalctl -u automated_trading.service -f`
- Application logs: `logs/automated_trading.log` (if configured)
- Performance log: `data/performance/futures_decisions.csv`

### Health Checks

```bash
python scripts/health_check.py
```

Checks:
- IB Gateway connectivity
- Recent trading activity
- Current risk state

## Micro Contracts

### Quick Start
```bash
bash scripts/run_micro_strategy.sh
```

Trades: MGC (Gold), MYM (Dow), MCL (Crude), MNQ (NASDAQ), MES (S&P)
- 1-minute intervals
- 3-5 contracts per trade
- Uses `config/micro_strategy_config.yaml`

### Available Micro Contracts
- ✅ MGC - Micro Gold (COMEX)
- ✅ MYM - Micro Dow (CBOT)
- ✅ MCL - Micro Crude (NYMEX)
- ✅ MNQ - Micro NASDAQ (CME)
- ✅ MES - Micro S&P 500 (CME)
- ❌ MRTY - Micro Russell (not available in IBKR)

## Troubleshooting

### No Trades Executing
1. **Check configuration**: `python scripts/debug_trading.py`
   - Should show: Profile=live, Allow Live Trading=True
2. **Check signals**: Look for "FLAT signal" vs "LONG/SHORT" in output
3. **Check risk state**: Look for "TRADE BLOCKED" messages
4. **Check IB Gateway**: `sudo systemctl status ibgateway.service`

### Agent Not Starting

1. Check IB Gateway is running:
   ```bash
   sudo systemctl status ibgateway.service
   ```

2. Check service logs:
   ```bash
   sudo journalctl -u automated_trading.service -n 50
   ```

3. Verify Python environment:
   ```bash
   source .venv/bin/activate
   python scripts/automated_trading.py --help
   ```

### Connection Errors

- Ensure IB Gateway is running on correct port (default: 4002)
- Check firewall settings
- Verify client IDs don't conflict

### No Trades Executing

- Check risk state: `python scripts/health_check.py`
- Verify market hours
- Check if cooldown is active
- Review signals: `python scripts/status_dashboard.py`

### Performance Issues

- Reduce `--interval` for faster updates (but respect API rate limits)
- Check system resources: `htop`
- Review log files for errors

## Stopping the Agent

```bash
# Stop the service
sudo systemctl stop automated_trading.service

# Disable auto-start on boot
sudo systemctl disable automated_trading.service

# For manual runs, use Ctrl+C
```

## Next Steps

Once paper trading is working well:

1. Review performance: `python scripts/daily_report.py`
2. Adjust risk parameters based on results
3. Fine-tune strategy parameters
4. Consider adding TradingView webhook integration (future)
5. Consider adding Tradovate support (future)

## Safety Notes

⚠️ **This is paper trading** - no real money at risk, but:
- Always monitor the system, especially initially
- Review logs regularly
- Set appropriate risk limits
- Test thoroughly before considering live trading
- The agent respects risk limits, but always verify behavior

