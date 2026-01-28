# Scripts Taxonomy and Canonical Entry Points

This document standardizes the roles of all scripts under `scripts/` and identifies the canonical entry points.

## Lifecycle (`scripts/lifecycle/`)

- `agent.sh`
  - **Role**: Canonical market-aware agent lifecycle CLI (start/stop/restart/status).
  - **Behavior**: Sets `PEARLALGO_MARKET`, `PEARLALGO_CONFIG_PATH`, `PEARLALGO_STATE_DIR`; manages PID/log per market in `logs/agent_<MARKET>.pid` and `logs/agent_<MARKET>.log`.
- `check_agent_status.sh`
  - **Role**: Check process and basic state summary for a market (`--market NQ|ES|GC`).

## Gateway (`scripts/gateway/`)

Gateway scripts orchestrate IBKR Gateway lifecycle and 2FA flows. They do **not** contain trading logic.

Canonical script:

- `gateway.sh` – consolidated gateway CLI (subcommands for start/stop/status/2FA/VNC/setup).

## Telegram (`scripts/telegram/`)

- `start_command_handler.sh`
  - **Role**: Canonical entry to start Telegram Command Handler.
  - **Behavior**: Changes to project root, activates `.venv` if present, selects `.venv/bin/python3` when available, verifies `pearlalgo` import, ensures only one handler instance via `pgrep -f "telegram_command_handler"`, then runs `-m pearlalgo.market_agent.telegram_command_handler`.
- `check_command_handler.sh`
  - **Role**: Check if command handler process is running and show PIDs.
- `restart_command_handler.sh`
  - **Role**: Restart the Telegram command handler (thin wrapper around stop/start semantics).
- `set_bot_commands.py`
  - **Role**: Helper to set BotFather commands via Telegram API using `python-telegram-bot`.

## Backtesting (`scripts/backtesting/`)

Backtesting scripts for strategy validation on historical data.

- `strategy_selection.py`
  - **Role**: Generate `strategy_selection_*.json` exports used by Telegram `/analyze` and operator dashboards.
- Backtesting scripts removed - using pearl_bot_auto only
- `train_ml_filter.py`
  - **Role**: Train/update the ML signal filter artifact used by `ml_filter` (offline; no production execution side effects).

## Testing (`scripts/testing/`)

- `test_all.py`
  - **Role**: Unified validation runner supporting modes: `telegram`, `signals`, `service`.
- `run_tests.sh`
  - **Role**: Developer convenience script to run the pytest unit suite under `tests/` (uses `.venv` when present).
- `check_architecture_boundaries.py`
  - **Role**: AST-based module boundary enforcement (warn-only by default; strict mode via `PEARLALGO_ARCH_ENFORCE=1`).
- `smoke_test_ibkr.py`
  - **Role**: Quick connectivity and entitlement smoke test for IBKR.
- `smoke_multi_market.py`
  - **Role**: Multi-market state/config isolation smoke test (NQ/ES/GC).
- `check_no_secrets.py`
  - **Role**: Secret detection guardrail; scans codebase for accidentally committed secrets/tokens.

## Maintenance (`scripts/maintenance/`)

Scripts for repository hygiene and cleanup operations.

- `purge_runtime_artifacts.sh`
  - **Role**: Safe cleanup of runtime/build artifacts (data, logs, telemetry, tmp images, `__pycache__`, egg-info).
  - **Behavior**: Requires explicit `--yes` flag to execute deletions. Supports `--dry-run` to preview what would be removed.

- `reset_30d_performance.py`
  - **Role**: Reset 30-day performance metrics (testing/debugging).

## Monitoring (`scripts/monitoring/`)

External safety nets intended for cron/systemd timers. These scripts validate runtime health/state;
they do **not** contain trading or strategy logic.

- `watchdog_agent.py`
  - **Role**: External watchdog for state freshness + silent failure detection.
  - **Behavior**: Reads `data/agent_state/<MARKET>/state.json`, checks staleness against scan interval and dashboard cadence, and can optionally send Telegram alerts.
  - **Usage**: `python3 scripts/monitoring/watchdog_agent.py --market NQ [--telegram] [--verbose]`

- `serve_agent_status.py`
  - **Role**: Localhost status server for standard tooling integration (curl, Prometheus, systemd health checks).
  - **Behavior**: Reads `data/agent_state/<MARKET>/state.json`; exposes `GET /healthz` (200/503), `GET /metrics` (Prometheus), and `GET /` (simple HTML status page).
  - **Usage**: `python3 scripts/monitoring/serve_agent_status.py --market NQ [--port 9100]`

- `doctor_cli.py`
  - **Role**: Operator CLI “doctor” for a compact rollup of recent behavior (signals, rejects, sizing, stops).
  - **Usage**: `python3 scripts/monitoring/doctor_cli.py --hours 24`

## Ops Shortcuts (`scripts/`)

- `health_check.sh`
  - **Role**: Fast local health snapshot (processes, gateway, state.json, recent signals/log errors). Requires `jq`.

## General Guidelines

When adding new scripts, place them under one of the categories above and follow these patterns:

- Always `cd` to project root at startup.
- Prefer the project virtual environment (`.venv/bin/python3`) when running Python modules.
- Use `python -m pearlalgo...` style entry points; avoid hard‑coded paths.
- Keep business logic in Python modules, not in shell scripts.

This taxonomy should be updated whenever a new script is added or an existing one is retired.
