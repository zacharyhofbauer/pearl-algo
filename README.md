# PearlAlgo Market Trading Agent

![Coverage](docs/assets/coverage-badge.svg)

Production-ready market trading agent with a modular architecture:
data providers (IBKR), strategy/signal generation with aggressive entry triggers, state + metrics,
and execution via Tradovate. Canonical frontend: Next.js dashboard web app.

The current operating model is intentionally narrow:
- market data from IBKR
- strategy via `strategies.composite_intraday`
- execution on a single Tradovate Paper account
- operator control through `./pearl.sh`
- dashboard/frontend in `apps/pearl-algo-app/`

Anything outside that path should be treated as non-canonical until proven
otherwise. Use `docs/START_HERE.md` for the live path and
`docs/COMPATIBILITY_SURFACES.md` for retained legacy bridges, wrappers, and
fallbacks.

## Pearl Algo Web App

The canonical frontend is a Next.js application in `apps/pearl-algo-app/`.
Run with `./pearl.sh start` to launch on port 3001.

## Quick start (local)

### Prereqs

- Python **3.12+**
- Node.js **20+** (for frontend)
- IBKR Gateway reachable (see `docs/GATEWAY.md`)

### Install

```bash
cd ~/projects/pearl-algo
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure

```bash
cp env.example .env
# Edit .env with IBKR_* values for account access
```

Service behavior is configured in `config/live/tradovate_paper.yaml` (use `--config config/live/tradovate_paper.yaml` when starting the agent).

Strategy parameters (EMA periods, entry triggers, confidence thresholds) are configured under `strategies.composite_intraday` in `config/live/tradovate_paper.yaml`.

### Run (operator scripts)

```bash
# Audit the live runtime layout first after a revamp
python3 scripts/ops/audit_runtime_paths.py

# Start everything
./pearl.sh start

# One-line health check
./pearl.sh quick

# Start without the chart if needed
./pearl.sh start --no-chart

# Tradovate Paper only
./pearl.sh tv_paper status
```

## Operating model

- **Operator entrypoint**: `./pearl.sh`
- **Canonical config**: `config/live/tradovate_paper.yaml`
- **Runtime topology**: singleton agent lock; `--market` selects the state/log namespace, not concurrent agents
- **Service**: `src/pearlalgo/market_agent/service.py`
- **Strategy**: `src/pearlalgo/strategies/composite_intraday/`
- **Execution**: `src/pearlalgo/execution/tradovate/`
- **Frontend**: `apps/pearl-algo-app/`
- **Compatibility leftovers**: `docs/COMPATIBILITY_SURFACES.md`

New runtime logic should be added to the operating-model paths above, not to
legacy wrappers or compatibility namespaces.

## Validation

```bash
# Unit tests (pytest)
./scripts/testing/run_tests.sh

# Validation runner (signals/service/arch)
python3 scripts/testing/test_all.py

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
- Unit tests (skipping environment-dependent IBKR integration paths)
- Architecture boundary enforcement
- Secret scan on tracked files

## Docs (start here)

- `docs/START_HERE.md`
- `docs/PATH_TRUTH_TABLE.md`
- `docs/COMPATIBILITY_SURFACES.md`
- `docs/GATEWAY.md`
- `docs/TESTING_GUIDE.md`

## TradingView indicators

TradingView Pine scripts live under `resources/pinescript/`.
