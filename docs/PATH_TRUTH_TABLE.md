# Path Truth Table

Canonical mapping between logical components, Python entry points, shell scripts, and documentation references.

## Market Agent Service

- **Logical component**: Market Agent Service (one process per market; production trading loop)
- **Python entry module**: `pearlalgo.nq_agent.main`
- **Primary service class**: `pearlalgo.nq_agent.service.NQAgentService`
- **Lifecycle scripts**:
  - `scripts/lifecycle/agent.sh` (start/stop/restart/status; `--market NQ|ES|GC`)
  - `scripts/lifecycle/check_agent_status.sh` (state summary; `--market NQ|ES|GC`)
- **Docs**:
  - `docs/NQ_AGENT_GUIDE.md`
  - `docs/PROJECT_SUMMARY.md`

## Telegram Command Handler

- **Logical component**: Telegram Command Handler (interactive bot commands)
- **Python entry module**: `pearlalgo.nq_agent.telegram_command_handler`
- **Shell scripts**:
  - `scripts/telegram/start_command_handler.sh`
  - `scripts/telegram/check_command_handler.sh`
  - `scripts/telegram/restart_command_handler.sh`
- **Supporting script**:
  - `scripts/telegram/set_bot_commands.py` (sets BotFather commands via API)
- **Docs**:
  - `docs/TELEGRAM_GUIDE.md`

## IBKR Gateway / API

- **Logical component**: IBKR Gateway + API connectivity
- **Python modules**:
  - `pearlalgo.data_providers.ibkr.ibkr_provider`
  - `pearlalgo.data_providers.ibkr_executor`
- **Shell scripts** (`scripts/gateway/`):
  - Canonical entry: `gateway.sh` (subcommands for start/stop/status/2FA/VNC/setup)
- **Docs**:
  - `docs/GATEWAY.md`
  - `docs/MARKET_DATA_SUBSCRIPTION.md`

## Strategy / Simulation / Testing

- **Logical component**: Strategy logic and automated tests
- **Python modules**:
  - Strategy config/logic: `pearlalgo.strategies.nq_intraday.*`
  - Data quality helpers: `pearlalgo.utils.data_quality`, `pearlalgo.utils.vwap`, `pearlalgo.utils.market_hours`
- **Backtesting scripts** (`scripts/backtesting/`):
  - `backtest_cli.py` – canonical unified backtest CLI (signal + full trade modes)
  - `signal_sweep.py` – sweep signal thresholds / variants (optional)
  - `robustness_cli.py` – robustness runs (optional)
  - `strategy_selection.py` – generates strategy selection exports (used by Telegram `/analyze`)
  - `backtest_trading_bot.py`, `compare_trading_bots.py` – trading bot variant backtests (optional; see `docs/TRADING_BOT_GUIDE.md`)
- **Testing scripts** (`scripts/testing/`):
  - `run_tests.sh` – pytest unit test runner (canonical)
  - `test_all.py` – unified validation runner (telegram / signals / service / arch)
  - `validate_strategy.py`
  - `smoke_test_ibkr.py`
  - `check_no_secrets.py` – secret detection guardrail
  - `test_signal_starvation_fixes.py`
  - `test_data_quality.py`, `test_e2e_simulation.py`
  - `test_mplfinance_chart.py`
  - `check_signals.py`
  - `generate_dashboard_baseline.py` – generate deterministic baseline image for visual regression tests
  - `generate_entry_exit_baselines.py` – generate deterministic entry/exit baseline images for visual regression tests
  - `generate_on_demand_chart_baseline.py` – generate deterministic `/chart` (on-demand) baseline image (12h lookback)
  - `live_probe_mnq.py` – read-only IBKR MNQ data verification probe (connection, contract, freshness)
  - `soak_test_mock_service.py` – bounded soak test harness (memory drift, cadence, error rate monitoring)
- **Docs**:
  - `docs/TESTING_GUIDE.md`
  - `docs/MOCK_DATA_WARNING.md`
  - Relevant sections of `docs/PROJECT_SUMMARY.md`

## Execution (ATS)

- **Logical component**: Automated Trading System (execution + learning)
- **Python modules**:
  - `pearlalgo.execution.base` – ExecutionAdapter interface, ExecutionConfig
  - `pearlalgo.execution.ibkr.adapter` – IBKR bracket order implementation
  - `pearlalgo.execution.ibkr.tasks` – Order placement tasks
  - `pearlalgo.learning.bandit_policy` – Thompson sampling policy
  - `pearlalgo.learning.policy_state` – Policy statistics persistence
- **State files** (in `data/agent_state/<MARKET>/`):
  - `policy_state.json` – Per-signal-type bandit statistics
- **Docs**:
  - `docs/ATS_ROLLOUT_GUIDE.md` – Safe rollout procedures

## Configuration

- **Logical component**: Configuration and settings
- **Config files**:
  - `config/config.yaml` – primary service + strategy configuration
  - `.env` (from `env.example`) – environment variables (Telegram, IBKR, provider selection)
- **Python modules**:
  - `pearlalgo.config.config_file` – unified YAML loader with env substitution
  - `pearlalgo.config.config_loader` – service config with defaults
  - `pearlalgo.config.settings` – Pydantic settings for infrastructure
- **Docs**:
  - `docs/PROJECT_SUMMARY.md` (configuration section)
  - `docs/NQ_AGENT_GUIDE.md` (configuration snippets)

## Maintenance

- **Logical component**: Repository hygiene and cleanup
- **Shell scripts** (`scripts/maintenance/`):
  - `purge_runtime_artifacts.sh` – safe cleanup of runtime/build artifacts (requires `--yes` flag)
- **Docs**:
  - `docs/SCRIPTS_TAXONOMY.md` (maintenance section)

## Monitoring

- **Logical component**: External watchdog / state freshness validator + optional localhost status server
- **Scripts**:
  - `scripts/monitoring/watchdog_agent.py` – cron/systemd-timer friendly watchdog for stalled state / silent failures (optional)
  - `scripts/monitoring/serve_agent_status.py` – localhost HTTP server exposing `/healthz` and `/metrics` (optional sidecar)
  - `scripts/monitoring/doctor_cli.py` – operator CLI rollup (signals, rejects, sizing, stops)
  - `scripts/health_check.sh` – fast local health snapshot (requires `jq`)
- **Docs**:
  - `docs/NQ_AGENT_GUIDE.md` (monitoring section)
  - `docs/PROJECT_SUMMARY.md` (status server section)
  - `docs/SCRIPTS_TAXONOMY.md` (monitoring section)

## Monitor UI (Optional)

- **Logical component**: Local desktop monitoring UI (Qt-based)
- **Python entry module**: `pearlalgo.monitor` (run via `python -m pearlalgo.monitor`)
- **Scripts**:
  - `scripts/monitor/start_monitor.sh`, `scripts/monitor/restart_monitor.sh`
  - `scripts/lifecycle/start_monitor_suite.sh`, `scripts/lifecycle/stop_monitor_suite.sh`

## Utilities / Cross‑cutting Concerns

- **Logical component**: Logging, error handling, retry, paths, data quality
- **Python modules**:
  - `pearlalgo.utils.logger`, `pearlalgo.utils.logging_config`
  - `pearlalgo.utils.error_handler`
  - `pearlalgo.utils.retry`
  - `pearlalgo.utils.paths`
  - `pearlalgo.utils.data_quality`
  - `pearlalgo.utils.market_hours`
  - `pearlalgo.utils.vwap`
  - `pearlalgo.utils.telegram_alerts`
- **Docs**:
  - `docs/PROJECT_SUMMARY.md` (components and cross‑cutting sections)

This table is the canonical reference when adding new scripts, docs, or modules. Any new entry point should be recorded here, and existing docs/scripts should be updated in lock‑step when paths change.
