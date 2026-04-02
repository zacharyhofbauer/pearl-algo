# Scripts Taxonomy and Canonical Entry Points

This document standardizes the roles of all scripts under `scripts/` and identifies the canonical entry points.

## Lifecycle (`scripts/lifecycle/`)

- `../pearl.sh`
  - **Role**: Canonical top-level operator entrypoint for start/stop/restart/status.
  - **Behavior**: Orchestrates gateway, agent, API, and web app using the active market and aligned runtime paths.
- `agent.sh`
  - **Role**: Canonical market-aware agent lifecycle CLI (start/stop/restart/status).
  - **Behavior**: Sets `PEARLALGO_MARKET`, `PEARLALGO_CONFIG_PATH`, `PEARLALGO_STATE_DIR`; manages PID/log per market in `logs/agent_<MARKET>.pid` and `logs/agent_<MARKET>.log`.
- `tv_paper_eval.sh`
  - **Role**: Tradovate Paper compatibility lifecycle wrapper for the fixed MNQ paper-eval instance.
  - **Behavior**: Uses `config/live/tradovate_paper.yaml`, runs the API on port `8001`, and writes state to the active `data/agent_state/MNQ/` root unless overridden by environment.

## Gateway (`scripts/gateway/`)

Gateway scripts orchestrate IBKR Gateway lifecycle and 2FA flows. They do **not** contain trading logic.

Canonical script:

- `gateway.sh` – consolidated gateway CLI (subcommands for start/stop/status/2FA/VNC/setup).

## Telegram

Telegram support currently lives inside the Python runtime rather than a dedicated
Telegram scripts directory.

- `src/pearlalgo/market_agent/telegram_notifier.py`
  - **Role**: Outbound Telegram notifications from the market agent.
- `src/pearlalgo/market_agent/telegram_formatters.py`
  - **Role**: Telegram message formatting helpers.

## Backtesting (`scripts/backtesting/`)

Backtesting scripts for strategy validation on historical data.

- `strategy_selection.py`
  - **Role**: Generate `strategy_selection_*.json` exports used by Telegram `/analyze` and operator dashboards.
  - **Usage**: `python3 scripts/backtesting/strategy_selection.py --signals-path data/agent_state/MNQ/signals.jsonl`

## Testing (`scripts/testing/`)

- `test_all.py`
  - **Role**: Unified validation runner supporting modes: `telegram`, `signals`, `service`.
- `run_tests.sh`
  - **Role**: Developer convenience script to run the pytest unit suite under `tests/` (uses `.venv` when present).
- `check_architecture_boundaries.py`
  - **Role**: AST-based module boundary enforcement (warn-only by default; strict mode via `PEARLALGO_ARCH_ENFORCE=1`).
- `smoke_test_ibkr.py`
  - **Role**: Quick connectivity and entitlement smoke test for IBKR.
- `check_no_secrets.py`
  - **Role**: Secret detection guardrail; scans codebase for accidentally committed secrets/tokens.
- `check_doc_references.py`
  - **Role**: Documentation reference audit; verifies doc paths exist in repo.
- `report_orphan_modules.py`
  - **Role**: Orphan-module report; lists src modules not reachable from entry points/tests/scripts.
- `check_config_defaults.py`
  - **Role**: Validates consistency between config defaults and schema (run via `make ci` or manually).

## Maintenance (`scripts/maintenance/`)

Scripts for repository hygiene and cleanup operations.

- `purge_runtime_artifacts.sh`
  - **Role**: Safe cleanup of runtime/build artifacts (data, logs, telemetry, tmp images, `__pycache__`, egg-info).
  - **Behavior**: Requires explicit `--yes` flag to execute deletions. Supports `--dry-run` to preview what would be removed.

- `git_rollback_paths.sh`
  - **Role**: Safe, path-scoped git rollback helper (creates backup branch, restores paths to a target commit/tag, deletes post-target added files, verifies exact match).
  - **Use cases**: Emergency web app UI rollbacks (undo bad refactors without rewriting history).

## Monitoring (`scripts/monitoring/`)

External safety nets intended for cron/systemd timers. These scripts validate runtime health/state;
they do **not** contain trading or strategy logic.

- `monitor.py`
  - **Role**: Automated health monitor with Telegram alerts and structured exit codes. Replaces the former `health_check.py` and `watchdog_agent.py`.
  - **Behavior**: Uses `HealthEvaluator` to check agent state freshness; also probes IBKR Gateway, API server, and web app. Supports alert deduplication via `alert_state.json` and sends Telegram notifications on new failures / recoveries.
  - **Usage**: `python3 scripts/monitoring/monitor.py --market NQ [--telegram] [--verbose] [--json]`
  - **Exit codes**: 0=OK, 1=WARNING, 2=CRITICAL, 3=ERROR

- `serve_agent_status.py`
  - **Role**: Localhost status server for standard tooling integration (curl, Prometheus, systemd health checks).
  - **Behavior**: Reads `data/agent_state/<MARKET>/state.json`; exposes `GET /healthz` (200/503), `GET /metrics` (Prometheus), and `GET /` (simple HTML status page).
  - **Usage**: `python3 scripts/monitoring/serve_agent_status.py --market NQ [--port 9100]`

- `doctor_cli.py`
  - **Role**: Operator CLI "doctor" for a compact rollup of recent behavior (signals, rejects, sizing, stops).
  - **Usage**: `python3 scripts/monitoring/doctor_cli.py --hours 24`
- `incident_report.py`
  - **Role**: Generate incident reports from state/signals for post-mortem analysis.

## Pearl Algo Web App (`apps/pearl-algo-app/`)

Web-based TradingView chart interface for real-time market visualization. Uses Next.js 14 with TypeScript.

**Start/Stop via pearl.sh:**
- `./pearl.sh chart start` - Start API server + Next.js chart
- `./pearl.sh chart stop` - Stop web app services
- `./pearl.sh chart restart` - Restart web app
- `./pearl.sh chart deploy` - Build production bundle + restart (recommended after frontend code changes)
- `./pearl.sh start --no-chart` - Start all services except web app

**pearl.sh auto-sync:**
- `sync_env_local()` merges `PEARL_API_KEY`, `PEARL_WEBAPP_AUTH_ENABLED`, `PEARL_WEBAPP_PASSCODE` into `apps/pearl-algo-app/.env.local` on every start/restart
- Chart auto-builds if no production build exists

**Components:**
- `src/pearlalgo/api/server.py`
  - **Role**: FastAPI server providing OHLCV data, agent state, indicators, and trades to the chart frontend.
  - **Port**: 8001 (Tradovate Paper — the only active account)
  - **Endpoints**: `/api/candles`, `/api/indicators`, `/api/markers`, `/api/state`, `/api/trades`, `/api/analytics`, `/api/market-status`, `/ws`, `/health`
- `apps/pearl-algo-app/`
  - **Role**: Next.js 14 frontend with TypeScript, Zustand state management, and WebSocket real-time updates.
  - **Port**: 3001 (default)

**Note**: The Pearl Algo Web App provides an interactive web view and can be used for Telegram screenshot captures via Playwright. See `docs/PEARL_WEB_APP.md` for details.

## Ops (`scripts/ops/`)

Quick operational utilities for manual/interactive use.

- `status.sh`
  - **Role**: Manual CLI health check — shows process, gateway, state, signal, and log status. Replaces the former `quick_status.sh` and `lifecycle/check_agent_status.sh`.
  - **Usage**: `./scripts/ops/status.sh [--market NQ]`
  - **Requires**: `jq` (optional but recommended for pretty state output).
  - **Note**: For automated monitoring with Telegram alerts, use `scripts/monitoring/monitor.py` instead.

## General Guidelines

When adding new scripts, place them under one of the categories above and follow these patterns:

- Always `cd` to project root at startup.
- Prefer the project virtual environment (`.venv/bin/python3`) when running Python modules.
- Use `python -m pearlalgo...` style entry points; avoid hard‑coded paths.
- Keep business logic in Python modules, not in shell scripts.

This taxonomy should be updated whenever a new script is added or an existing one is retired.
