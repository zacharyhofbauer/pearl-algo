## Start Here (Single Page)

This repo is a **trading platform** with three hard requirements:

- **Safety-first**: execution is guarded (dry_run/paper/live + arming + risk caps).
- **Observable**: every decision should be explainable from logs + persisted state.
- **Extensible**: new strategies/indicators/data/execution adapters should plug in without rewiring the service.

### What runs in production

- **Service**: `src/pearlalgo/nq_agent/service.py` (orchestrator)
- **Market data**: `src/pearlalgo/data_providers/` (IBKR provider + executor)
- **Strategy**: `src/pearlalgo/strategies/nq_intraday/` (scanner + signal_generator + regime/MTF/order flow)
- **Execution**: `src/pearlalgo/execution/` (adapters; guarded by config + arming)
- **State/metrics**: `src/pearlalgo/nq_agent/state_manager.py`, `performance_tracker.py`
- **Ops/UI**: Telegram notifier + command handler

### The single source of truth

- **Configuration**: `config/config.yaml`
- **System reference**: `docs/PROJECT_SUMMARY.md`

### Persistent memory (SQLite)

We **dual-write** signals/trades to SQLite (queryable, durable) while keeping JSON/JSONL
for compatibility with existing Telegram/mobile views.

- DB: `data/nq_agent_state/trades.db`
- Config: `storage.sqlite_enabled` in `config/config.yaml`

### Quick operational checklist

- **Gateway**: `./scripts/gateway/gateway.sh start`
- **Agent**: `./scripts/lifecycle/start_nq_agent_service.sh`
- **Status**: `./scripts/lifecycle/check_nq_agent_status.sh`

### Fast validation (mobile + CLI)

- **Telegram**: use *Health → Doctor* or `/doctor` for a 24h rollup (signals, rejects, stops, sizing)
- **CLI**: `python scripts/monitoring/doctor_cli.py --hours 24`

### Execution safety model (non-negotiable)

- **Modes**: `execution.mode: dry_run | paper | live`
- **Arming**: execution must be explicitly armed (see docs + Telegram command handler)
- **Caps**: max daily loss, max positions, max orders/day, stop caps, prop-firm guardrails

### How to extend (future-proof path)

- **Add an indicator**: `src/pearlalgo/strategies/nq_intraday/indicators/`
- **Add a strategy**: create a new folder under `src/pearlalgo/strategies/` and implement a scanner/signal generator that emits the same normalized signal schema.
- **Add a data provider**: implement `src/pearlalgo/data_providers/base.py` and register in `factory.py`.
- **Add an execution adapter**: implement `src/pearlalgo/execution/base.py` and register in the execution factory.

### Where to go next

- **Architecture overview**: `docs/ARCHITECTURE.md`
- **Operational runbooks**: `docs/NQ_AGENT_GUIDE.md`, `docs/GATEWAY.md`, `docs/TELEGRAM_GUIDE.md`
- **Testing**: `docs/TESTING_GUIDE.md`

