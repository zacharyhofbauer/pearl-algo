# PearlAlgo MNQ Trading Agent

**Production-ready MNQ futures signal-generation system** optimized for prop-firm style intraday trading (scalps + short swings).

## Quick Start

```bash
# 1. Install dependencies
pip install -e .

# 2. Configure environment
# Copy the example env file, then edit values:
cp env.example .env
# Required keys: IBKR_HOST, IBKR_PORT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 3. Setup IBKR Gateway (first time)
./scripts/gateway/setup_ibgateway.sh

# 4. Start IBKR Gateway
./scripts/gateway/start_ibgateway_ibc.sh

# 5. Start MNQ Agent Service
./scripts/lifecycle/start_nq_agent_service.sh

# 6. Check status
./scripts/lifecycle/check_nq_agent_status.sh
```

## Documentation

- **[PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md)** - Complete system reference (single source of truth)
- **[NQ_AGENT_GUIDE.md](docs/NQ_AGENT_GUIDE.md)** - Operational guide (how to run and operate)
- **[TESTING_GUIDE.md](docs/TESTING_GUIDE.md)** - Complete testing guide
- **[GATEWAY.md](docs/GATEWAY.md)** - IBKR Gateway setup

## Key Features

- ✅ **Prop Firm Optimized**: MNQ contracts (5-15 per trade), 1% risk, quick scalps
- ✅ **Real-time Data**: IBKR Gateway integration
- ✅ **Signal Generation**: Technical analysis-based signals
- ✅ **Telegram Notifications**: Mobile-optimized alerts
- ✅ **Robust Error Handling**: Circuit breakers, automatic recovery
- ✅ **Performance Tracking**: Built-in metrics and analytics

## Project Structure

```
pearlalgo-dev-ai-agents/
├── src/pearlalgo/           # Source code
│   ├── nq_agent/            # Main service
│   ├── strategies/          # Trading strategies
│   ├── data_providers/      # Data providers (IBKR)
│   ├── utils/              # Utilities
│   └── config/              # Configuration
├── scripts/                 # Organized by category
│   ├── lifecycle/           # Service management
│   ├── gateway/             # IBKR Gateway
│   └── testing/             # Testing scripts
├── config/                  # Configuration files
├── docs/                    # Documentation
└── tests/                   # Test suite
```

For complete documentation, see [PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md).
