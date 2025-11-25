# pearlalgo-dev-ai-agents

US equities/options/futures research and backtesting scaffold inspired by Moon Dev’s agent architecture. Modular agents for research, backtesting, and risk, with clean separation of config, data, strategies, and models. Backtest- and paper-first; live trading must be explicitly enabled with safeguards.

## Features
- Universes: large-cap equities/ETFs (SPY, QQQ), index futures (ES, NQ, YM, etc.), and educational options examples
- Pluggable strategies via a registry/factory
- Backtesting through backtesting.py (optional backtrader extra)
- Typed config with Pydantic; structured logging with Rich
- Safe-by-default posture: backtest/paper as defaults; live trading is opt-in and guarded

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

## Quickstart
```bash
python -m pearlalgo.cli list-strategies
python -m pearlalgo.cli backtest --data data/futures/ES_15m_sample.csv --strategy es_breakout --symbol ES
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


## Structure
- `src/pearlalgo/config`: settings, symbol metadata
- `src/pearlalgo/data`: loaders, cleaning, feature scaffolds
- `src/pearlalgo/data_providers`: provider interfaces (local CSV, REST stubs)
- `src/pearlalgo/brokers`: broker interfaces (dummy backtest, REST stub)
- `src/pearlalgo/core`: events and portfolio tracking
- `src/pearlalgo/strategies`: base + examples
- `src/pearlalgo/agents`: backtest, research, risk, strategy, execution
- `src/pearlalgo/models`: signal/order types
- `src/pearlalgo/utils`: logging, calendars

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

## Testing
```bash
pip install -e .[dev]
pytest
```
