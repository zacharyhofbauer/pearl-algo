# pearlalgo-dev-ai-agents

**Simple NQ futures trading agent** with IBKR connection and Telegram notifications.

## Overview

This is a focused trading system for NQ (E-mini NASDAQ-100) futures:
- **Data Source**: IBKR (Interactive Brokers)
- **Strategy**: NQ intraday strategy
- **Notifications**: Telegram alerts for signals and trades
- **Deployment**: Simple service that runs 24/7

## ⚠️ RISK WARNINGS

**CRITICAL: This is a trading system that can lose money. Use at your own risk.**

- **Always start with paper trading** - Never use real money until thoroughly tested
- **Maximum 2% risk per trade** - Hardcoded and enforced
- **15% account drawdown kill-switch** - Automatically stops trading if drawdown exceeds 15%
- **Test extensively** - Paper trade before live trading
- **Monitor actively** - Check the system regularly

**The authors are not responsible for any financial losses. Trade at your own risk.**

## Features

- **NQ Intraday Strategy**: Focused strategy for NQ futures trading
- **IBKR Integration**: Direct connection to Interactive Brokers for market data
- **Telegram Notifications**: Real-time alerts for signals, entries, and exits
- **Simple Architecture**: Clean, focused codebase without unnecessary complexity
- **24/7 Operation**: Runs continuously as a service

## Prerequisites

- Python 3.12+
- IBKR account with API access
- IB Gateway or TWS running (for IBKR connection)
- Telegram bot token (for notifications)

## Installation

```bash
# Clone repository
git clone <repository-url>
cd pearlalgo-dev-ai-agents

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -U pip
pip install -e .

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
nano .env  # or use your preferred editor
```

## Configuration

### Environment Variables (.env)

```bash
# IBKR Connection
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Data Provider
PEARLALGO_DATA_PROVIDER=ibkr
```

### Config File (config/config.yaml)

The main configuration file is `config/config.yaml`. Key settings:

- `symbol`: Trading symbol (default: "NQ")
- `timeframe`: Bar timeframe (default: "1m")
- `scan_interval`: How often to check for signals (default: 60 seconds)
- `risk`: Risk management parameters

## Quick Start

### 1. Start IB Gateway

Make sure IB Gateway or TWS is running and configured for API access.

### 2. Test IBKR Connection

```bash
python scripts/smoke_test_ibkr.py
```

### 3. Test Telegram

```bash
python scripts/test_telegram.py
```

### 4. Start NQ Agent

```bash
# Using the startup script
./scripts/start_nq_agent.sh

# Or directly
python -m pearlalgo.nq_agent.main
```

The agent will:
- Connect to IBKR
- Fetch NQ market data
- Generate trading signals
- Send notifications to Telegram

## Project Structure

```
pearlalgo-dev-ai-agents/
├── src/pearlalgo/
│   ├── nq_agent/          # NQ agent service (main entry point)
│   │   ├── main.py        # Entry point
│   │   ├── service.py     # Service loop
│   │   ├── data_fetcher.py
│   │   ├── state_manager.py
│   │   └── telegram_notifier.py
│   ├── strategies/
│   │   └── nq_intraday/   # NQ intraday strategy
│   ├── data_providers/
│   │   └── ibkr/          # IBKR data provider
│   └── utils/
│       └── telegram_alerts.py
├── config/
│   └── config.yaml        # Main configuration
├── scripts/
│   ├── start_nq_agent.sh  # Startup script
│   ├── smoke_test_ibkr.py
│   └── test_telegram.py
└── ibkr/                  # IBKR Java runtime
```

## IBKR Setup

See `docs/IBKR_CONNECTION_SETUP.md` for detailed IBKR Gateway setup instructions.

Key points:
1. Enable API in IB Gateway/TWS settings
2. Set API port (default: 4002)
3. Allow connections from localhost
4. Start Gateway before running the agent

## Telegram Setup

1. Create a bot with [@BotFather](https://t.me/botfather) on Telegram
2. Get your bot token
3. Get your chat ID (use [@userinfobot](https://t.me/userinfobot))
4. Add both to your `.env` file

## Running as a Service

### Systemd (Linux)

Create `/etc/systemd/system/nq-agent.service`:

```ini
[Unit]
Description=NQ Trading Agent
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/pearlalgo-dev-ai-agents
Environment="PATH=/path/to/pearlalgo-dev-ai-agents/.venv/bin"
ExecStart=/path/to/pearlalgo-dev-ai-agents/.venv/bin/python -m pearlalgo.nq_agent.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable nq-agent
sudo systemctl start nq-agent
sudo systemctl status nq-agent
```

## Monitoring

Check logs:
```bash
tail -f logs/nq_agent.log
```

Check service status (if using systemd):
```bash
sudo systemctl status nq-agent
```

## Troubleshooting

### IBKR Connection Issues
- Ensure IB Gateway is running
- Check API settings in Gateway
- Verify port and host in `.env`
- Run `python scripts/smoke_test_ibkr.py` to test

### Telegram Notifications Not Working
- Verify bot token and chat ID in `.env`
- Run `python scripts/test_telegram.py` to test
- Check bot is not blocked

### No Signals Generated
- Check market hours (agent only trades during market hours)
- Verify data is being received from IBKR
- Check logs for errors

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Structure

- `src/pearlalgo/nq_agent/`: Main agent service
- `src/pearlalgo/strategies/nq_intraday/`: NQ strategy implementation
- `src/pearlalgo/data_providers/ibkr/`: IBKR data provider
- `src/pearlalgo/utils/`: Utility functions

## License

See LICENSE file for details.

## Support

For issues and questions, please open an issue on the repository.
