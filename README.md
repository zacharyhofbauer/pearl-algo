# PearlAlgo Market Trading Agent

![Coverage](docs/coverage-badge.svg)

Production-ready market trading agent with a modular architecture:
data providers (IBKR), strategy/scanner/signal generation, state + metrics, Telegram UI,
and optional execution + learning layers (disabled/safe by default).

## Pearl Algo Web App (Telegram + Mini App)

![Telegram dashboard](docs/assets/telegram-dashboard.png)

See `docs/PEARL_WEB_APP.md` for Mini App setup (public HTTPS required) and screenshot capture.

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

# Start the market agent
./scripts/lifecycle/agent.sh start --market NQ --background

# Start Telegram command handler (menus)
./scripts/telegram/start_command_handler.sh --background

# Check status
./scripts/ops/status.sh --market NQ
```

## Validation

```bash
# Unit tests (pytest)
./scripts/testing/run_tests.sh

# Validation runner (telegram/signals/service/arch)
python3 scripts/testing/test_all.py

# Pearl AI prompt regression eval (fast, no API calls)
python3 -m pearlalgo.pearl_ai.eval.ci --mock

# Type checking (mypy)
mypy src/pearlalgo

# Coverage + badge
make coverage
```

### Convenience (Makefile)

```bash
# Install deps (editable) + dev tooling
make install

# Run the same checks CI runs locally
make ci

# Pearl AI prompt eval (mock mode)
make eval

# Optional: dependency vulnerability scan
make audit
```

### CI

GitHub Actions workflow lives at `.github/workflows/ci.yml` and runs:
- Unit tests (skipping IBKR / Telegram-credential tests)
- Architecture boundary enforcement
- Secret scan on tracked files
- Multi-market config + state isolation smoke test

Prompt regression testing lives at `.github/workflows/eval.yml` and runs Pearl AI eval suites when prompt-related files change (uploads an eval report artifact and posts a PR summary).

## Docs (start here)

- `docs/START_HERE.md`
- `docs/PROJECT_SUMMARY.md` (single source of truth)
- `docs/MARKET_AGENT_GUIDE.md`
- `docs/TELEGRAM_GUIDE.md`
- `docs/TESTING_GUIDE.md`

## TradingView indicators

TradingView Pine scripts live under `resources/pinescript/`.
