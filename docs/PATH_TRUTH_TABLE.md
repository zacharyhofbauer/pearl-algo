# Path Truth Table

Canonical mapping between logical components, Python entry points, shell scripts, and documentation references.

## Market Agent Service

- **Logical component**: Market Agent Service (one process per market; production trading loop)
- **Python entry module**: `pearlalgo.market_agent.main`
- **Primary service class**: `pearlalgo.market_agent.service.MarketAgentService`
- **Supporting modules**:
  - `pearlalgo.market_agent.data_fetcher` – Data fetching and buffer management
  - `pearlalgo.market_agent.state_manager` – State persistence (JSON/JSONL)
  - `pearlalgo.market_agent.performance_tracker` – Performance metrics tracking
  - `pearlalgo.market_agent.telegram_notifier` – Telegram notifications
  - `pearlalgo.market_agent.health_monitor` – Health monitoring
  - `pearlalgo.market_agent.chart_generator` – mplfinance chart generation
  - `pearlalgo.market_agent.challenge_tracker` – Challenge/competition tracking
  - `pearlalgo.market_agent.notification_queue` – Notification queuing
  - `pearlalgo.market_agent.trading_circuit_breaker` – Circuit breaker logic
- **Lifecycle scripts**:
  - `scripts/lifecycle/agent.sh` (start/stop/restart/status; `--market NQ|ES|GC`)
  - `scripts/lifecycle/check_agent_status.sh` (state summary; `--market NQ|ES|GC`)
- **Docs**:
  - `docs/MARKET_AGENT_GUIDE.md`
  - `docs/PROJECT_SUMMARY.md`

## Telegram Command Handler

- **Logical component**: Telegram Command Handler (interactive bot commands)
- **Python entry module**: `pearlalgo.market_agent.telegram_command_handler`
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
  - `pearlalgo.data_providers.base` – Abstract data provider interface
  - `pearlalgo.data_providers.factory` – Provider factory (creates provider instances)
  - `pearlalgo.data_providers.ibkr.ibkr_provider` – IBKR data provider implementation
  - `pearlalgo.data_providers.ibkr_executor` – Thread-safe IBKR executor
- **Shell scripts** (`scripts/gateway/`):
  - Canonical entry: `gateway.sh` (subcommands for start/stop/status/2FA/VNC/setup)
- **Docs**:
  - `docs/GATEWAY.md`
  - `docs/MARKET_DATA_SUBSCRIPTION.md`

## Strategy / Simulation / Testing

- **Logical component**: Strategy logic and automated tests
- **Python modules**:
  - Strategy config/logic: `pearlalgo.trading_bots.pearl_bot_auto`
  - Data quality helpers: `pearlalgo.utils.data_quality`, `pearlalgo.utils.vwap`, `pearlalgo.utils.market_hours`
- **Backtesting scripts** (`scripts/backtesting/`):
  - `strategy_selection.py` – generates strategy selection exports (used by Telegram `/analyze`)
  - Backtesting scripts removed - using pearl_bot_auto only
  - `train_ml_filter.py` – offline training for ML signal filter artifacts
- **Testing scripts** (`scripts/testing/`):
  - `run_tests.sh` – pytest unit test runner (canonical)
  - `test_all.py` – unified validation runner (telegram / signals / service)
  - `check_architecture_boundaries.py` – module boundary enforcement (warn-only by default)
  - `smoke_test_ibkr.py`
  - `smoke_multi_market.py`
  - `check_no_secrets.py` – secret detection guardrail
  - `generate_coverage_badge.py` – coverage badge generation
  - `regenerate_chart_baselines.py` – chart visual regression baselines
- **Docs**:
  - `docs/TESTING_GUIDE.md`
  - `docs/MOCK_DATA_WARNING.md`
  - Relevant sections of `docs/PROJECT_SUMMARY.md`

## Execution (ATS)

- **Logical component**: Automated Trading System (execution + learning)
- **Python modules** (Execution layer):
  - `pearlalgo.execution.base` – ExecutionAdapter interface, ExecutionConfig
  - `pearlalgo.execution.ibkr.adapter` – IBKR bracket order implementation
  - `pearlalgo.execution.ibkr.tasks` – Order placement tasks
- **Python modules** (Learning layer):
  - `pearlalgo.learning.bandit_policy` – Thompson sampling policy
  - `pearlalgo.learning.policy_state` – Policy statistics persistence
  - `pearlalgo.learning.contextual_bandit` – Contextual bandit learning
  - `pearlalgo.learning.feature_engineer` – Feature engineering for ML
  - `pearlalgo.learning.ensemble_scorer` – Ensemble scoring system
  - `pearlalgo.learning.ml_signal_filter` – ML-based signal filtering
  - `pearlalgo.learning.trade_database` – Trade database for learning
- **State files** (in `data/agent_state/<MARKET>/`):
  - `policy_state.json` – Per-signal-type bandit statistics
  - `trades.db` – SQLite trade database
- **Docs**:
  - `docs/ATS_ROLLOUT_GUIDE.md` – Safe rollout procedures

## Configuration

- **Logical component**: Configuration and settings
- **Config files**:
  - `config/config.yaml` – primary service + strategy configuration
  - `config/markets/*.yaml` – per-market configuration overlays
  - `.env` (from `env.example`) – environment variables (Telegram, IBKR, provider selection)
- **Python modules**:
  - `pearlalgo.config.config_file` – unified YAML loader with env substitution
  - `pearlalgo.config.config_loader` – service config with defaults
  - `pearlalgo.config.config_schema` – configuration schema validation
  - `pearlalgo.config.config_view` – configuration view/access layer
  - `pearlalgo.config.settings` – Pydantic settings for infrastructure
- **Docs**:
  - `docs/PROJECT_SUMMARY.md` (configuration section)
  - `docs/CONFIGURATION_MAP.md`
  - `docs/MARKET_AGENT_GUIDE.md` (configuration snippets)

## Maintenance

- **Logical component**: Repository hygiene and cleanup
- **Shell scripts** (`scripts/maintenance/`):
  - `purge_runtime_artifacts.sh` – safe cleanup of runtime/build artifacts (requires `--yes` flag)
- **Python scripts**:
  - `scripts/reset_30d_performance.py` – reset 30-day performance (testing/debugging)
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
  - `docs/MARKET_AGENT_GUIDE.md` (monitoring section)
  - `docs/PROJECT_SUMMARY.md` (status server section)
  - `docs/SCRIPTS_TAXONOMY.md` (monitoring section)

## Storage

- **Logical component**: Persistence layer
- **Python modules**:
  - `pearlalgo.storage.async_sqlite_queue` – Async SQLite queue for state management
- **State directories**:
  - `data/agent_state/<MARKET>/` – Per-market service state

## Utilities / Cross‑cutting Concerns

- **Logical component**: Logging, error handling, retry, paths, data quality, and shared helpers
- **Python modules**:
  - `pearlalgo.utils.logger` – Shared logger instance (loguru-backed)
  - `pearlalgo.utils.logging_config` – Logging setup helpers
  - `pearlalgo.utils.error_handler` – Error classification and handling
  - `pearlalgo.utils.retry` – Async retry with exponential backoff
  - `pearlalgo.utils.paths` – Path and timestamp helpers
  - `pearlalgo.utils.data_quality` – Data freshness and validation
  - `pearlalgo.utils.market_hours` – Market hours logic (CME)
  - `pearlalgo.utils.vwap` – VWAP computation
  - `pearlalgo.utils.cadence` – Cadence scheduler and metrics
  - `pearlalgo.utils.sparkline` – Progress bar rendering helpers
  - `pearlalgo.utils.volume_pressure` – Signed-volume pressure computations
  - `pearlalgo.utils.telegram_alerts` – Core Telegram messaging
  - `pearlalgo.utils.telegram_ui_contract` – Telegram UI contract
  - `pearlalgo.utils.openai_client` – OpenAI client wrapper
  - `pearlalgo.utils.service_controller` – Shell/script orchestration (remote control)
  - `pearlalgo.utils.absolute_mode` – Absolute mode utilities
- **Docs**:
  - `docs/PROJECT_SUMMARY.md` (components and cross‑cutting sections)

This table is the canonical reference when adding new scripts, docs, or modules. Any new entry point should be recorded here, and existing docs/scripts should be updated in lock‑step when paths change.
