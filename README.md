# PearlAlgo MNQ Trading Agent

Production-ready MNQ trading agent with a modular architecture:
data providers (IBKR), strategy/scanner/signal generation, state + metrics, Telegram UI,
and optional execution + learning layers (disabled/safe by default).

## Quick start (local)

### Prereqs

- Python **3.12+**
- IBKR Gateway reachable (see `docs/GATEWAY.md`)
- Telegram bot credentials (see `env.example`)

### Install

```bash
cd ~/pearlalgo-dev-ai-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure

```bash
cp env.example .env
# Edit .env with TELEGRAM_* and IBKR_* values
```

Service behavior is configured in `config/config.yaml`.

### Run (operator scripts)

```bash
# Start IBKR Gateway
./scripts/gateway/gateway.sh start

# Start the MNQ agent
./scripts/lifecycle/agent.sh start --market NQ --background

# Start Telegram command handler (menus)
./scripts/telegram/start_command_handler.sh --background

# Check status
./scripts/lifecycle/check_agent_status.sh --market NQ
```

## Validation

```bash
# Unit tests (pytest)
./scripts/testing/run_tests.sh

# Validation runner (telegram/signals/service/arch)
python3 scripts/testing/test_all.py
```

## Docs (start here)

- `docs/START_HERE.md`
- `docs/PROJECT_SUMMARY.md` (single source of truth)
- `docs/MARKET_AGENT_GUIDE.md`
- `docs/TELEGRAM_GUIDE.md`
- `docs/TESTING_GUIDE.md`

## TradingView indicators

TradingView Pine scripts live under `resources/pinescript/`.
