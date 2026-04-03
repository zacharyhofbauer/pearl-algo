# Path Truth Table

Canonical mapping between logical components, Python entry points, shell scripts, and documentation references.

## Top-Level Control

- **Canonical operator entrypoint**: `./pearl.sh`
- **Runtime audit**: `python3 scripts/ops/audit_runtime_paths.py`
- **Operating model**: `docs/START_HERE.md`
- **Retained compatibility surfaces**: `docs/COMPATIBILITY_SURFACES.md`

## Market Agent Service

- **Logical component**: Market Agent Service (singleton production trading loop; selected market/state dir)
- **Python entry module**: `pearlalgo.market_agent.main`
- **Primary service class**: `pearlalgo.market_agent.service.MarketAgentService`
- **Supporting modules**:
  - `pearlalgo.market_agent.service_lifecycle` – service start/stop lifecycle helpers
  - `pearlalgo.market_agent.service_loop` – scan-loop/runtime cadence helpers
  - `pearlalgo.market_agent.service_status` – operator/PEARL status snapshot and review-message helpers
  - `pearlalgo.market_agent.virtual_trade_manager` – Virtual trade exit processing (extracted from service.py)
  - `pearlalgo.market_agent.data_fetcher` – Data fetching and buffer management
  - `pearlalgo.market_agent.state_builder` – dashboard/export state assembly
  - `pearlalgo.market_agent.state_manager` – State persistence (JSON/JSONL, signal cache, incremental count)
  - `pearlalgo.market_agent.state_reader` – Thread-safe locked reads for external consumers
  - `pearlalgo.market_agent.performance_tracker` – Performance metrics tracking
  - `pearlalgo.market_agent.signal_handler` – signal normalization and execution handoff
  - `pearlalgo.market_agent.order_manager` – order/position control helpers
  - `pearlalgo.market_agent.operator_handler` – operator command handling
  - `pearlalgo.market_agent.health_monitor` – Health monitoring
  - `pearlalgo.market_agent.live_chart_screenshot` – Live chart screenshot export (Playwright)
  - `pearlalgo.market_agent.notification_queue` – no-op notification compatibility surface
  - `pearlalgo.market_agent.tv_paper_eval_tracker` – prop-firm evaluation tracking
  - `pearlalgo.market_agent.trading_circuit_breaker` – runtime guardrail and signal-veto evaluation
- **Lifecycle scripts**:
  - `scripts/lifecycle/agent.sh` (start/stop/status; `--market <MARKET>` selects state/log namespace, but runtime stays singleton)
  - `scripts/ops/status.sh` (manual CLI health check; `--market <MARKET>`)
- **Docs**:
  - `docs/START_HERE.md`
  - `docs/PATH_TRUTH_TABLE.md`

## Notifications

- **Logical component**: Runtime notification compatibility surface
- **Python modules**:
  - `pearlalgo.market_agent.notification_queue` – no-op queue retained so service/runtime callers keep a stable contract
- **Notes**:
  - Active Telegram delivery modules were removed.
  - New runtime work should not depend on outbound notification delivery.

## IBKR Gateway / API

- **Logical component**: IBKR Gateway + API connectivity
- **Install location**: `PEARLALGO_IBKR_HOME` (external install path; required if not using repo-local `ibkr/`)
- **Python modules**:
  - `pearlalgo.data_providers.base` – Abstract data provider interface
  - `pearlalgo.data_providers.factory` – Provider factory (creates provider instances)
  - `pearlalgo.data_providers.ibkr.ibkr_provider` – IBKR data provider implementation
  - `pearlalgo.data_providers.ibkr_data_executor` – Thread-safe IBKR executor
- **Shell scripts** (`scripts/gateway/`):
  - Canonical entry: `gateway.sh` (subcommands for start/stop/status/2FA/VNC/setup)
- **Docs**:
  - `docs/GATEWAY.md`
  - `docs/MARKET_DATA_SUBSCRIPTION.md`

## Strategy / Simulation / Testing

- **Logical component**: Strategy logic and automated tests
- **Python modules**:
  - Canonical strategy config/logic: `pearlalgo.strategies.composite_intraday`
  - Retained bridge namespace: `pearlalgo.trading_bots` (legacy implementation surface; do not add new strategy entrypoints there)
  - Data quality helpers: `pearlalgo.utils.data_quality`, `pearlalgo.utils.vwap`, `pearlalgo.utils.market_hours`
- **Backtesting scripts** (`scripts/backtesting/`):
  - `strategy_selection.py` – generates strategy selection exports for operator review flows and dashboards
- **Testing scripts** (`scripts/testing/`):
  - `run_tests.sh` – pytest unit test runner (canonical)
  - `test_all.py` – unified validation runner (signals / service / arch)
  - `check_architecture_boundaries.py` – module boundary enforcement (warn-only by default)
  - `smoke_test_ibkr.py`
  - `check_no_secrets.py` – secret detection guardrail
  - `check_doc_references.py` – documentation path reference audit
  - `report_orphan_modules.py` – orphan module report (reachability from entrypoints/tests)
  - `generate_coverage_badge.py` – coverage badge generation
- **Docs**:
  - `docs/TESTING_GUIDE.md`
  - `docs/MOCK_DATA_WARNING.md`
  - `docs/COMPATIBILITY_SURFACES.md`

## Execution

- **Logical component**: Execution adapters and live order handling
- **Python modules**:
  - `pearlalgo.execution.base` – ExecutionAdapter interface, ExecutionConfig
  - `pearlalgo.execution.tradovate.adapter` – Tradovate execution adapter
  - `pearlalgo.execution.tradovate.client` – Tradovate API client
- **State files** (in `data/agent_state/<MARKET>/`):
  - `trades.db` – SQLite runtime database
  - `performance.json` – current performance/export snapshot
- **Docs**:
  - `docs/COMPATIBILITY_SURFACES.md` – retained compatibility and rollout leftovers that still affect current paths

## Configuration

- **Logical component**: Configuration and settings
- **Config files**:
  - `config/live/tradovate_paper.yaml` – canonical active Tradovate Paper runtime config
  - `config/config.yaml` – auxiliary application config
  - `.env` (from `env.example`) – non-secret local environment defaults
  - `~/.config/pearlalgo/secrets.env` – machine-local secrets and runtime credentials
- **Python modules**:
  - `pearlalgo.config.config_file` – unified YAML loader with env substitution
  - `pearlalgo.config.config_loader` – service config with defaults
  - `pearlalgo.config.runtime_validation` – runtime validation entrypoints used by startup and config mutation paths
  - `pearlalgo.config.schema_v2` – Pydantic schema models for config validation
  - `pearlalgo.config.migration` – config migration helpers
  - `pearlalgo.config.config_view` – configuration view/access layer
  - `pearlalgo.config.settings` – Pydantic settings for infrastructure
- **Docs**:
  - `docs/START_HERE.md`
  - `docs/COMPATIBILITY_SURFACES.md`

## Maintenance

- **Logical component**: Repository hygiene and cleanup
- **Shell scripts** (`scripts/maintenance/`):
  - `purge_runtime_artifacts.sh` – safe cleanup of runtime/build artifacts (requires `--yes` flag)
  - `git_rollback_paths.sh` – safe, path-scoped git rollback helper (creates backup branch, restores paths to a target commit/tag, deletes post-target added files)
- **Docs**:
  - `docs/SCRIPTS_TAXONOMY.md` (maintenance section)
  - `docs/PEARL_WEB_APP.md` (optional UI-specific rollback section)

## Monitoring

- **Logical component**: External watchdog / state freshness validator + optional localhost status server
- **Scripts**:
  - `scripts/monitoring/monitor.py` – automated health monitor with structured exit codes and optional legacy alert bridge
  - `scripts/monitoring/serve_agent_status.py` – localhost HTTP server exposing `/healthz` and `/metrics` (optional sidecar)
  - `scripts/monitoring/doctor_cli.py` – operator CLI rollup (signals, rejects, sizing, stops)
  - `scripts/monitoring/incident_report.py` – incident report generation
- **Ops scripts** (`scripts/ops/`):
  - `status.sh` – manual CLI health check (replaces `quick_status.sh` + `check_agent_status.sh`)
- **Docs**:
  - `docs/START_HERE.md`
  - `docs/SCRIPTS_TAXONOMY.md` (monitoring section)

## Storage

- **Logical component**: Persistence layer
- **Python modules**:
  - `pearlalgo.storage.async_sqlite_queue` – Async SQLite queue for state management
- **State directories**:
  - `data/agent_state/<MARKET>/` – repo symlink into live runtime state
  - `/home/pearlalgo/var/pearl-algo/state/data/agent_state/<MARKET>/` – canonical live state location

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
  - `pearlalgo.utils.service_controller` – Shell/script orchestration (remote control)
  - `pearlalgo.utils.pearl_suggestions` – Pearl suggestions engine
- **Docs**:
  - `docs/START_HERE.md`

This table is the canonical reference when adding new scripts, docs, or modules. Any new entry point should be recorded here, and existing docs/scripts should be updated in lock‑step when paths change.

If a path is retained only as an alias, wrapper, migration bridge, or
backward-compatibility layer, record it in `docs/COMPATIBILITY_SURFACES.md`
instead of treating it as part of the operating model.
