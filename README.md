# pearlalgo-dev-ai-agents

US equities/options/futures research and backtesting scaffold inspired by Moon Dev’s agent architecture. Modular agents for research, backtesting, and risk, with clean separation of config, data, strategies, and models. Backtest- and paper-first; live trading must be explicitly enabled with safeguards.

## Features
- Universes: large-cap equities/ETFs (SPY, QQQ), index futures (ES, NQ, YM, etc.), and educational options examples
- Pluggable strategies via a registry/factory
- Backtesting through backtesting.py (optional backtrader extra)
- Typed config with Pydantic; structured logging with Rich
- Safe-by-default posture: backtest/paper as defaults; live trading is opt-in and guarded
- IBKR integration: see `README_IBKR.md` for headless Gateway + ib_insync usage.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

## 🚀 Quickstart (Easy Workflow)

**NEW: Interactive Menu System**
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/workflow.py
```

This opens an interactive menu where you can:
- Generate daily signals & reports
- View status dashboard
- Run paper trading loops
- Manage IB Gateway
- View latest signals/reports

**Setup & Management Assistant:**
```bash
# Interactive setup and management
python scripts/setup_assistant.py

# Quick commands
python scripts/setup_assistant.py --status          # Show system status
python scripts/setup_assistant.py --quick-start    # Ensure Gateway is running
python scripts/setup_assistant.py --start-gateway   # Start IB Gateway
python scripts/setup_assistant.py --restart-gateway # Restart Gateway
python scripts/setup_assistant.py --test-connection # Test API connection
```

**Quick Commands:**
```bash
# Generate signals (default: sr strategy)
python scripts/workflow.py --signals

# View dashboard
python scripts/workflow.py --dashboard

# View live-updating dashboard
python scripts/status_dashboard.py --live
```

Backtest a registered strategy (defaults to backtest profile):
```bash
python -m pearlalgo.cli backtest --data data/futures/ES_15m_sample.csv --strategy es_breakout --symbol ES --cash 100000 --commission 0.0
```

Pick a profile/config file (still paper/backtest-safe unless profile=live):
```bash
python -m pearlalgo.cli backtest --data path/to.csv --strategy equity_momentum --profile paper --config-file settings.json
```

Use the lightweight naive engine (runs through DummyBacktestBroker/Portfolio):
```bash
python -m pearlalgo.cli backtest --data data/futures/ES_15m_sample.csv --strategy es_breakout --engine naive
```

Scan multiple symbols (expects CSVs named by symbol under data_dir):
```bash
python -m pearlalgo.cli scan --symbols ES NQ --strategy es_breakout
```

## Futures core entrypoints
- `python scripts/run_daily_signals.py` — fetch ES/NQ/GC (IBKR or CSV), run MA-cross, and log decisions to `data/performance/futures_decisions.csv`.
- `python scripts/live_paper_loop.py --mode ibkr-paper` — paper loop: fetch data, generate signals, size via prop profile, route tiny orders via IBKR paper or dummy broker.
- `python scripts/risk_monitor.py --max-daily-loss 2500` — monitor performance/journal PnL and write `RISK_HALT` when breached.
- `python scripts/daily_workflow.py` — wrapper: run signals then build the markdown daily report.
- `python scripts/daily_report.py` — generate markdown report from signals + performance log.

Legacy (moon-era) CLI/backtesting: archived under `legacy/src/pearlalgo/` with the original CLI (`legacy/src/pearlalgo/cli.py`), agents, backtesting, and live scaffolding preserved for reference.


## Structure
- `src/pearlalgo/futures`: futures-focused config, contracts, signals, risk, and performance logging
- `src/pearlalgo/data_providers`: IBKR + CSV providers
- `src/pearlalgo/brokers`: IBKR broker + contract helpers
- `src/pearlalgo/config`: env/settings
- `legacy/`: archived moon-era agents/backtesting/live CLI + unused scripts/tests (kept for reference)

## Roadmap (live trading)
1. Add Interactive Brokers adapter via `ib_insync` (connection mgmt, contract builders for ES/NQ/GC/ZN/CL, order routing).
2. Implement account/portfolio sync and risk checks (per-symbol risk budget, max DD guard).
3. Add execution venue abstraction for multiple brokers (IB, Tradovate, CQG).
4. Add data adapters for continuous futures/roll logic.
5. Integrate feature store and ML pipelines (optional).

## Notes
- Keep everything scoped to equities/options/index futures; avoid crypto symbols.
- Strategies are educational examples—swap in your own logic and risk management.
- Sample data: `data/futures/ES_15m_sample.csv` (synthetic OHLCV for testing).
- Required env for live trading (example keys only; do not commit secrets):
  - `PEARLALGO_BROKER_API_KEY`, `PEARLALGO_BROKER_API_SECRET`, `PEARLALGO_BROKER_BASE_URL`
  - `PEARLALGO_DATA_API_KEY` if your data provider needs it
  - `PEARLALGO_PROFILE` (backtest | paper | live)
 - IBKR integration: see `README_IBKR.md` for headless Gateway + ib_insync usage.

## Testing
```bash
pip install -e .[dev]
pytest
```

See `docs/TESTING.md` for CI and lint details. Ops runbook in `docs/OPS.md`.
