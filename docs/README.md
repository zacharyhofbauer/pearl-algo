# Minimal NQ Trading Agent

**Ultra-simple NQ futures trading agent** with IBKR connection and Telegram notifications.

## What's Included

### Core Components (30 Python files)
- **NQ Agent** (`src/pearlalgo/nq_agent/`) - Main service (6 files)
- **NQ Strategy** (`src/pearlalgo/strategies/nq_intraday/`) - Trading strategy (5 files)
- **IBKR Provider** (`src/pearlalgo/data_providers/ibkr/`) - IBKR connection (4 files)
- **Utilities** (`src/pearlalgo/utils/`) - Essential utilities (4 files)
- **Config** (`src/pearlalgo/config/`) - Configuration (3 files)

### Essential Scripts (9 files)
- `start_nq_agent_service.sh` - Start the NQ agent (background service)
- `start_nq_agent.sh` - Start the NQ agent (foreground, for testing)
- `smoke_test_ibkr.py` - Test IBKR connection
- `test_telegram_notifications.py` - Test Telegram notifications
- IBKR Gateway setup scripts

### Documentation
- `README.md` - Main documentation
- `docs/IBKR_CONNECTION_SETUP.md` - IBKR setup guide

## Quick Start

```bash
# 1. Install dependencies
pip install -e .

# 2. Configure .env
# Add: IBKR_HOST, IBKR_PORT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 3. Start IB Gateway
./scripts/start_ibgateway.sh

# 4. Test IBKR connection
python scripts/smoke_test_ibkr.py

# 5. Test Telegram
python scripts/test_telegram_notifications.py

# 6. Start NQ agent (background service)
./scripts/start_nq_agent_service.sh
# Or for foreground testing:
# ./scripts/start_nq_agent.sh
```

## Project Structure

```
pearlalgo-dev-ai-agents/
├── src/pearlalgo/
│   ├── nq_agent/              # Main service
│   ├── strategies/nq_intraday/  # NQ strategy
│   ├── data_providers/ibkr/  # IBKR connection
│   ├── utils/                # Utilities
│   └── config/               # Configuration
├── config/
│   └── config.yaml           # NQ-only config
├── scripts/                  # Essential scripts
└── docs/                     # Essential docs
```

That's it! Simple and focused. 🚀
