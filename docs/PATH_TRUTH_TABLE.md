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
  - `pearlalgo.market_agent.live_chart_screenshot` – Live chart screenshot export (Playwright)
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
- **Install location**: `PEARLALGO_IBKR_HOME` (external install path; required if not using repo-local `ibkr/`)
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
  - `train_ml_filter.py` – offline training for ML signal filter artifacts
- **Testing scripts** (`scripts/testing/`):
  - `run_tests.sh` – pytest unit test runner (canonical)
  - `test_all.py` – unified validation runner (telegram / signals / service)
  - `check_architecture_boundaries.py` – module boundary enforcement (warn-only by default)
  - `smoke_test_ibkr.py`
  - `smoke_multi_market.py`
  - `check_no_secrets.py` – secret detection guardrail
  - `check_doc_references.py` – documentation path reference audit
  - `report_orphan_modules.py` – orphan module report (reachability from entrypoints/tests)
  - `generate_coverage_badge.py` – coverage badge generation
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
  - `git_rollback_paths.sh` – safe, path-scoped git rollback helper (creates backup branch, restores paths to a target commit/tag, deletes post-target added files)
- **Python scripts**:
  - `scripts/maintenance/reset_30d_performance.py` – reset 30-day performance (testing/debugging)
- **Docs**:
  - `docs/SCRIPTS_TAXONOMY.md` (maintenance section)
  - `docs/PEARL_WEB_APP.md` (emergency UI rollback section)

## Monitoring

- **Logical component**: External watchdog / state freshness validator + optional localhost status server
- **Scripts**:
  - `scripts/monitoring/watchdog_agent.py` – cron/systemd-timer friendly watchdog for stalled state / silent failures (optional)
  - `scripts/monitoring/serve_agent_status.py` – localhost HTTP server exposing `/healthz` and `/metrics` (optional sidecar)
  - `scripts/monitoring/doctor_cli.py` – operator CLI rollup (signals, rejects, sizing, stops)
  - `scripts/monitoring/incident_report.py` – incident report generation
  - `scripts/monitoring/health_check.py` – automated health check with Telegram alerts (for cron/systemd)
- **Ops scripts** (`scripts/ops/`):
  - `quick_status.sh` – fast local health snapshot for manual use (requires `jq`)
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

## Knowledge / RAG

- **Logical component**: Knowledge indexing and retrieval for AI-assisted features
- **Python modules**:
  - `pearlalgo.knowledge.indexer` – Knowledge index builder
  - `pearlalgo.knowledge.retriever` – Context retrieval for queries
  - `pearlalgo.knowledge.chunker` – Document chunking
  - `pearlalgo.knowledge.embeddings` – Embedding generation
  - `pearlalgo.knowledge.scanner` – File system scanner
  - `pearlalgo.knowledge.index_store` – FAISS index persistence
  - `pearlalgo.knowledge.datasets` – Dataset management
  - `pearlalgo.knowledge.types` – Shared types
- **Scripts** (`scripts/knowledge/`):
  - `build_index.py` – Build/rebuild knowledge index
  - `export_datasets.py` – Export datasets for analysis
  - `watch_repo.py` – Watch repository for changes and re-index
- **Configuration**: `config.yaml` → `knowledge.*`
- **Docs**: *(AI_PATCH_GUIDE.md removed - AI features moved to CLI)*

## AI Modules

There are two separate AI-related modules in this repository, serving different purposes:

### `pearl_ai/` (Top-level Module)

- **Logical component**: Pearl AI 3.0 - Data-grounded trading analyst with RAG
- **Purpose**: Comprehensive AI system for CLI/terminal and web app usage
- **Python modules**:
  - `pearl_ai.brain` – Core AI orchestrator (routes between local/Claude)
  - `pearl_ai.narrator` – Narrative generation for briefings
  - `pearl_ai.memory` – Conversation persistence
  - `pearl_ai.data_access` – Trade database RAG integration
  - `pearl_ai.cache` – Response caching with semantic hashing
  - `pearl_ai.tools` – Tool execution for structured queries
  - `pearl_ai.metrics` – Observability and cost tracking
  - `pearl_ai.llm_claude` – Claude API integration
  - `pearl_ai.llm_local` – Local LLM (Ollama) integration
  - `pearl_ai.llm_mock` – Mock LLM for testing
  - `pearl_ai.config` – Configuration management
  - `pearl_ai.api_router` – FastAPI router for AI endpoints
- **Features**: RAG, tool use, streaming, caching, cost tracking
- **Tests**: `tests/test_pearl_brain.py`, `tests/test_pearl_cache.py`, `tests/test_pearl_tools.py`

### `src/pearlalgo/ai/` (In-package Module)

- **Logical component**: Telegram AI integration and shadow tracking
- **Purpose**: Telegram-specific AI wrappers and suggestion tracking
- **Python modules**:
  - `pearlalgo.ai.chat` – PearlAIChat class for conversational AI
  - `pearlalgo.ai.shadow_tracker` – Shadow tracking for AI suggestion outcomes
- **Features**: Telegram integration, outcome tracking
- **Note**: AI chat features have been removed from Telegram; this module provides shadow tracking for ML signal evaluation

### Relationship

- `pearl_ai/` is the newer, more comprehensive AI system (v3.0) for CLI and web app
- `src/pearlalgo/ai/` provides lightweight wrappers for Telegram integration and outcome tracking
- Both modules can coexist; they serve different integration points
- `pearl_ai/` has its own versioning (`__version__ = "3.0.0"`) and is kept separate intentionally

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
  - `pearlalgo.utils.service_controller` – Shell/script orchestration (remote control)
  - `pearlalgo.utils.absolute_mode` – Absolute mode utilities
  - `pearlalgo.utils.pearl_suggestions` – Pearl suggestions engine
- **Docs**:
  - `docs/PROJECT_SUMMARY.md` (components and cross‑cutting sections)

This table is the canonical reference when adding new scripts, docs, or modules. Any new entry point should be recorded here, and existing docs/scripts should be updated in lock‑step when paths change.
