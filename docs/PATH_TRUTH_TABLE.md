# Path Truth Table

Canonical mapping between logical components, Python entry points, shell scripts, and documentation references.

## NQ Agent Service

- **Logical component**: NQ Agent Service (production trading loop)
- **Python entry module**: `pearlalgo.nq_agent.main`
- **Primary service class**: `pearlalgo.nq_agent.service.NQAgentService`
- **Lifecycle scripts**:
  - `scripts/lifecycle/start_nq_agent_service.sh`
  - `scripts/lifecycle/stop_nq_agent_service.sh`
  - `scripts/lifecycle/check_nq_agent_status.sh`
- **Docs**:
  - `docs/NQ_AGENT_GUIDE.md`
  - `docs/PROJECT_SUMMARY.md`

## Telegram Command Handler

- **Logical component**: Telegram Command Handler (interactive bot commands)
- **Python entry module**: `pearlalgo.nq_agent.telegram_command_handler`
- **Shell scripts**:
  - `scripts/telegram/start_command_handler.sh`
  - `scripts/telegram/check_command_handler.sh`
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
  - Startup / shutdown: `start_ibgateway_ibc.sh`, `stop_ibgateway_ibc.sh`, `start_ibgateway_ibc_vnc.sh`
  - Status / checks: `check_gateway_status.sh`, `check_api_ready.sh`, `check_gateway_2fa_status.sh`, `test_api_connection.sh`, `check_tws_conflict.sh`
  - 2FA + VNC helpers: `auto_2fa.sh`, `wait_for_2fa_approval.sh`, `complete_2fa_vnc.sh`, `setup_vnc_for_login.sh`, `configure_gateway_api_vnc.sh`, `monitor_until_ready.sh`
  - System helpers: `disable_auto_sleep.sh`, `setup_ibgateway.sh`
- **Docs**:
  - `docs/GATEWAY.md`
  - `docs/MARKET_DATA_SUBSCRIPTION.md`

## Strategy / Simulation / Testing

- **Logical component**: Strategy logic and automated tests
- **Python modules**:
  - Strategy config/logic: `pearlalgo.strategies.nq_intraday.*`
  - Data quality helpers: `pearlalgo.utils.data_quality`, `pearlalgo.utils.vwap`, `pearlalgo.utils.market_hours`
- **Testing scripts** (`scripts/testing/`):
  - `run_tests.sh` – pytest unit test runner (canonical)
  - `test_all.py` – unified validation runner (telegram / signals / service / arch)
  - `validate_strategy.py`
  - `smoke_test_ibkr.py`
  - `check_no_secrets.py` – secret detection guardrail
  - `test_signal_starvation_fixes.py`
  - `test_data_quality.py`, `test_e2e_simulation.py`
  - `test_mplfinance_chart.py`
  - `backtest_nq_strategy.py`
  - `check_signals.py`
  - `generate_dashboard_baseline.py` – generate deterministic baseline image for visual regression tests
  - `generate_entry_exit_baselines.py` – generate deterministic entry/exit baseline images for visual regression tests
- **Docs**:
  - `docs/TESTING_GUIDE.md`
  - `docs/MOCK_DATA_WARNING.md`
  - Relevant sections of `docs/PROJECT_SUMMARY.md`

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
  - `scripts/monitoring/watchdog_nq_agent.py` – cron/systemd-timer friendly watchdog for stalled state / silent failures (optional)
  - `scripts/monitoring/serve_nq_agent_status.py` – localhost HTTP server exposing `/healthz` and `/metrics` (optional sidecar)
- **Docs**:
  - `docs/NQ_AGENT_GUIDE.md` (monitoring section)
  - `docs/PROJECT_SUMMARY.md` (status server section)
  - `docs/SCRIPTS_TAXONOMY.md` (monitoring section)

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
