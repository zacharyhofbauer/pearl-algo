# PearlAlgo — Manual TradingView-Alert Trading Toolkit

![Coverage](docs/assets/coverage-badge.svg)

> **2026-06-02 pivot.** The active model is now **manual discretionary futures trading** driven by
> TradingView Pine Script alerts, executed by hand on a **My Funded Futures (MFF)** MNQ account.
> The fully-automated IBKR+Tradovate bot is **dormant**, preserved at tag
> `legacy/automated-mnq-2026-06-02` (parked after −2,026 pts / 717 trades). Read
> [`docs/MANUAL_PIVOT.md`](docs/MANUAL_PIVOT.md) for the why + validation gate.

## Active model (manual)

| Step | Where |
| --- | --- |
| **Signals** — Pine strategies fire TradingView alerts | [`pine/`](pine/) |
| **Delivery** — TradingView webhook → Discord (your phone) | [`alerts/`](alerts/) |
| **Execution** — you place the MNQ order by hand on MFF (TraderSyncer copies demo→live) | manual |
| **Journal** — log + review every manual trade | [`docs/JOURNAL.md`](docs/JOURNAL.md) |
| **Backtest** — vet a Pine idea before trading it | `scripts/backtesting/` |

**Before risking the funded account**, clear the pre-committed validation gate in
[`docs/MANUAL_PIVOT.md`](docs/MANUAL_PIVOT.md): ≥30 trades, positive expectancy net of fees, max
drawdown inside the MFF trailing-DD limit, and rule-adherence.

**Edges baked into the starter strategy** (from the 922-trade analysis): RTH only (overnight loses),
long bias (shorts weak), few robust filters over many.

---

## Legacy automated bot (dormant — preserved at `legacy/automated-mnq-2026-06-02`)

Everything below describes the **parked** automated system. It stays on disk and runnable but is
not part of the active manual model — see [`docs/legacy/README.md`](docs/legacy/README.md) to re-arm it.
`execution.armed` is `false`. Anything outside this path is non-canonical; use `docs/START_HERE.md`
for the old live path and `docs/COMPATIBILITY_SURFACES.md` for retained bridges/wrappers.

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
./pearl.sh tv-paper status
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
