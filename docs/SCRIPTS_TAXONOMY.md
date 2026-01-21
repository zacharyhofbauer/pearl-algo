# Scripts Taxonomy and Canonical Entry Points

This document standardizes the roles of all scripts under `scripts/` and identifies the canonical entry points.

## Lifecycle (`scripts/lifecycle/`)

- `agent.sh`
  - **Role**: Canonical market-aware agent lifecycle CLI (start/stop/restart/status).
  - **Behavior**: Sets `PEARLALGO_MARKET`, `PEARLALGO_CONFIG_PATH`, `PEARLALGO_STATE_DIR`; manages PID/log per market in `logs/agent_<MARKET>.pid` and `logs/agent_<MARKET>.log`.
- `check_agent_status.sh`
  - **Role**: Check process and basic state summary for a market (`--market NQ|ES|GC`).
- `start_monitor_suite.sh`
  - **Role**: Operator convenience script to start the full local suite (Gateway + Agent + Telegram handler + Monitor UI).
  - **Notes**: Intended for desktop/VNC sessions; pairs with `stop_monitor_suite.sh`.
- `stop_monitor_suite.sh`
  - **Role**: Stop the full local suite started by `start_monitor_suite.sh`.

## Gateway (`scripts/gateway/`)

Gateway scripts orchestrate IBKR Gateway lifecycle and 2FA flows. They do **not** contain trading logic.

Canonical script:

- `gateway.sh` – consolidated gateway CLI (subcommands for start/stop/status/2FA/VNC/setup).

## Telegram (`scripts/telegram/`)

- `start_command_handler.sh`
  - **Role**: Canonical entry to start Telegram Command Handler.
  - **Behavior**: Changes to project root, activates `.venv` if present, selects `.venv/bin/python3` when available, verifies `pearlalgo` import, ensures only one handler instance via `pgrep -f "telegram_command_handler"`, then runs `-m pearlalgo.nq_agent.telegram_command_handler`.
- `check_command_handler.sh`
  - **Role**: Check if command handler process is running and show PIDs.
- `restart_command_handler.sh`
  - **Role**: Restart the Telegram command handler (thin wrapper around stop/start semantics).
- `set_bot_commands.py`
  - **Role**: Helper to set BotFather commands via Telegram API using `python-telegram-bot`.

## Backtesting (`scripts/backtesting/`)

Backtesting scripts for strategy validation on historical data.

- `backtest_cli.py`
  - **Role**: Canonical unified backtest CLI.
  - **Modes**: `signal` (fast signal-only) and `full` (trade simulation with risk-based sizing).
  - **Usage**: `python scripts/backtesting/backtest_cli.py signal --data-path data.parquet`
  - **Features**: Date range slicing, chart generation, HTML reports.
- `signal_sweep.py`
  - **Role**: Sweep signal thresholds / variants (batch experiments; outputs summaries).
- `robustness_cli.py`
  - **Role**: Robustness / stress-testing harness for backtests (parameter and scenario sweeps).
- `strategy_selection.py`
  - **Role**: Generate `strategy_selection_*.json` exports used by Telegram `/analyze` and operator dashboards.
- `backtest_trading_bot.py`
  - **Role**: Backtest a single trading bot variant (including `PearlAutoBot`) on historical data.
- `compare_trading_bots.py`
  - **Role**: Compare trading bot variants across the same period and produce a ranked summary.
- `train_ml_filter.py`
  - **Role**: Train/update the ML signal filter artifact used by `ml_filter` (offline; no production execution side effects).

## Testing (`scripts/testing/`)

- `test_all.py`
  - **Role**: Unified validation runner supporting modes: `telegram`, `signals`, `service`, `arch`.
- `run_tests.sh`
  - **Role**: Developer convenience script to run the pytest unit suite under `tests/` (uses `.venv` when present).
- `check_architecture_boundaries.py`
  - **Role**: AST-based module boundary enforcement (warn-only by default; strict mode via `PEARLALGO_ARCH_ENFORCE=1`).
- `test_signal_starvation_fixes.py`
  - **Role**: Strategy regression validations (anti-starvation fixes).
- `test_data_quality.py`, `test_e2e_simulation.py`
  - **Role**: Data‑quality and end‑to‑end tests.
- `test_mplfinance_chart.py`
  - **Role**: Chart generation smoke test (mplfinance).
- `smoke_test_ibkr.py`
  - **Role**: Quick connectivity and entitlement smoke test for IBKR.
- `validate_strategy.py`
  - **Role**: Validate strategy outputs/assumptions for given historical data.
- `check_signals.py`
  - **Role**: Diagnostic tool to check signals file format, count, and validity. Useful for troubleshooting signal persistence issues.
- `generate_backtest_baseline.py`
  - **Role**: Generate deterministic baseline image for backtest visual regression testing.
- `generate_dashboard_baseline.py`
  - **Role**: Generate deterministic dashboard baseline image for visual regression testing.
  - **Behavior**: Creates fixed synthetic OHLCV data and renders a chart with deterministic parameters; outputs to `tests/fixtures/charts/dashboard_baseline.png`.
- `generate_entry_exit_baselines.py`
  - **Role**: Generate deterministic entry/exit baseline images for visual regression testing.
  - **Behavior**: Renders entry and exit charts; outputs to `tests/fixtures/charts/entry_baseline.png` and `tests/fixtures/charts/exit_baseline.png`.
- `generate_mobile_baseline.py`
  - **Role**: Generate deterministic baseline image for mobile dashboard visual regression testing.
- `generate_on_demand_chart_baseline.py`
  - **Role**: Generate deterministic baseline image for the Telegram `/chart` (on-demand) dashboard chart.
  - **Behavior**: Renders the 12h lookback variant; outputs to `tests/fixtures/charts/on_demand_chart_12h_baseline.png`.
- `check_no_secrets.py`
  - **Role**: Secret detection guardrail; scans codebase for accidentally committed secrets/tokens.
- `live_probe_mnq.py`
  - **Role**: Read-only IBKR MNQ data verification probe.
  - **Behavior**: Validates connection, contract resolution, latest bar fetch, historical data, and data freshness without modifying state.
  - **Usage**: `python3 scripts/testing/live_probe_mnq.py [--verbose]`
- `soak_test_mock_service.py`
  - **Role**: Bounded soak test harness for service loop validation.
  - **Behavior**: Runs the service loop with mock data for a configurable duration; monitors memory drift, cadence metrics, and error rates.
  - **Usage**: `python3 scripts/testing/soak_test_mock_service.py [--duration SECONDS] [--verbose]`

## Maintenance (`scripts/maintenance/`)

Scripts for repository hygiene and cleanup operations.

- `purge_runtime_artifacts.sh`
  - **Role**: Safe cleanup of runtime/build artifacts (data, logs, telemetry, tmp images, `__pycache__`, egg-info).
  - **Behavior**: Requires explicit `--yes` flag to execute deletions. Supports `--dry-run` to preview what would be removed.

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

## Monitor UI (`scripts/monitor/`)

Local GUI tooling (optional). These scripts launch the Qt-based monitor.

- `start_monitor.sh`
  - **Role**: Start the monitor UI (foreground/background).
- `restart_monitor.sh`
  - **Role**: Restart the monitor UI.

## Setup / Migration (`scripts/setup/`)

Environment- and machine-specific helpers (WiFi / network migration / connectivity).
These scripts orchestrate OS configuration; they do not contain trading logic.

- `verify_wifi_connection.sh`, `check_network_settings.sh`, `pre_migration_check.sh`
  - **Role**: Preflight checks and verification helpers for WiFi migrations.
- `connect_xprs.sh`, `ensure_auto_connect.sh`
  - **Role**: Network connection helpers (ISP / captive portal / auto-connect workflows).

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
