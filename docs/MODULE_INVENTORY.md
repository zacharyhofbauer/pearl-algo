# Module, Script, and Documentation Inventory

This document records the current structure of the NQ Agent codebase and classifies each file at a high level.
It is descriptive only and does not change runtime behavior.

## Python packages under `src/pearlalgo`

### Core agent (`pearlalgo.nq_agent`)

- `pearlalgo.nq_agent.__init__` – package marker
- `pearlalgo.nq_agent.main` – main entry point for NQ Agent Service (CLI entry)
- `pearlalgo.nq_agent.service` – core 24/7 service orchestration
- `pearlalgo.nq_agent.data_fetcher` – wraps data-provider access and latest bar retrieval
- `pearlalgo.nq_agent.state_manager` – persistence of agent state and signals
- `pearlalgo.nq_agent.performance_tracker` – signal/trade performance tracking
- `pearlalgo.nq_agent.health_monitor` – service health aggregation
- `pearlalgo.nq_agent.telegram_notifier` – high‑level Telegram notification formatting and delivery
- `pearlalgo.nq_agent.telegram_command_handler` – Telegram command handler (interactive bot commands)

### Strategies (`pearlalgo.strategies`)

- `pearlalgo.strategies.__init__` – package marker
- `pearlalgo.strategies.base` – base classes / interfaces for strategies
- `pearlalgo.strategies.nq_intraday.__init__` – NQ intraday strategy package
- `pearlalgo.strategies.nq_intraday.config` – NQ intraday strategy configuration
- `pearlalgo.strategies.nq_intraday.scanner` – bar scanning, orchestrates indicator and signal generation
- `pearlalgo.strategies.nq_intraday.signal_generator` – core signal generation logic
- `pearlalgo.strategies.nq_intraday.signal_quality` – signal quality assessment
- `pearlalgo.strategies.nq_intraday.regime_detector` – market regime detection
- `pearlalgo.strategies.nq_intraday.mtf_analyzer` – multi‑timeframe alignment analysis
- `pearlalgo.strategies.nq_intraday.order_flow` – order‑flow / order‑book context
- `pearlalgo.strategies.nq_intraday.volume_profile` – volume profile utilities
- `pearlalgo.strategies.nq_intraday.strategy` – ties together config, scanner, and signals into a concrete strategy

### Data providers (`pearlalgo.data_providers`)

- `pearlalgo.data_providers.__init__` – package marker
- `pearlalgo.data_providers.base` – abstract data‑provider interface
- `pearlalgo.data_providers.factory` – creates concrete data providers based on configuration
- `pearlalgo.data_providers.ibkr_executor` – thread‑safe executor for IBKR requests and historical data
- `pearlalgo.data_providers.ibkr.__init__` – IBKR provider package
- `pearlalgo.data_providers.ibkr.connection_manager` – manages IBKR API connection lifecycle
- `pearlalgo.data_providers.ibkr.entitlements` – market data entitlement checks
- `pearlalgo.data_providers.ibkr.ibkr_provider` – high‑level IBKR provider implementation

### Configuration (`pearlalgo.config`)

- `pearlalgo.config.__init__` – package marker
- `pearlalgo.config.config_loader` – service configuration loader (`config/config.yaml`)
- `pearlalgo.config.settings` – global settings via Pydantic (environment + defaults)
- `pearlalgo.config.symbols` – symbol metadata and helpers

### Utilities (`pearlalgo.utils`)

- `pearlalgo.utils.__init__` – package marker
- `pearlalgo.utils.logger` – logger helper
- `pearlalgo.utils.logging_config` – logging configuration for console/tests
- `pearlalgo.utils.paths` – filesystem and path helpers
- `pearlalgo.utils.market_hours` – market hours / trading session helpers
- `pearlalgo.utils.vwap` – VWAP calculation utilities
- `pearlalgo.utils.data_quality` – data quality checking utilities
- `pearlalgo.utils.retry` – retry / backoff utilities
- `pearlalgo.utils.error_handler` – standardized error handling for data providers and Telegram
- `pearlalgo.utils.telegram_alerts` – low‑level Telegram Bot wrapper and alert helpers

## Scripts under `scripts/`

### Lifecycle scripts (`scripts/lifecycle/`)

- `start_nq_agent_service.sh` – start NQ Agent Service
- `stop_nq_agent_service.sh` – stop NQ Agent Service
- `check_nq_agent_status.sh` – check if NQ Agent Service is running

### Gateway scripts (`scripts/gateway/`)

Gateway / IBKR‑specific orchestration scripts (start/stop, 2FA workflow, connection checks):

- `start_ibgateway_ibc.sh`, `stop_ibgateway_ibc.sh`
- `start_ibgateway_ibc_vnc.sh`
- `check_gateway_status.sh`, `check_api_ready.sh`, `test_api_connection.sh`
- `auto_2fa.sh`, `wait_for_2fa_approval.sh`, `complete_2fa_vnc.sh`, `setup_vnc_for_login.sh`, `configure_gateway_api_vnc.sh`
- `disable_auto_sleep.sh`
- `monitor_until_ready.sh`
- `check_tws_conflict.sh`
- `setup_ibgateway.sh`
- `fix_api_connection.sh`
- `vnc_terminal_helper.md` (markdown helper, not a script)

### Telegram scripts (`scripts/telegram/`)

- `start_command_handler.sh` – starts Telegram command handler service
- `check_command_handler.sh` – checks if command handler is running
- `set_bot_commands.py` – helper to set Telegram bot commands via API

### Testing scripts (`scripts/testing/`)

- `test_all.py` – master test runner
- `run_tests.sh` – convenience wrapper for running tests
- `test_nq_agent_with_mock.py` – integration tests with mock data provider
- `test_signal_generation.py`, `test_signal_starvation_fixes.py` – strategy tests
- `test_data_quality.py` – data‑quality related tests
- `test_e2e_simulation.py` – end‑to‑end simulation tests
- `test_telegram_notifications.py` – Telegram notification tests
- `smoke_test_ibkr.py` – basic IBKR connectivity smoke test
- `validate_strategy.py` – validation of strategy outputs

## Documentation under `docs/`

- `PROJECT_SUMMARY.md` – system architecture (single source of truth)
- `NQ_AGENT_GUIDE.md` – operational guide for running and monitoring NQ Agent
- `GATEWAY.md` – IBKR Gateway setup and troubleshooting
- `IBKR_DETAILS.md` – additional IBKR‑related notes/details
- `MARKET_DATA_SUBSCRIPTION.md` – IBKR market data subscription and entitlements
- `MOCK_DATA_WARNING.md` – warning and usage notes about the mock data provider
- `TESTING_GUIDE.md` – how to run and interpret tests
- `TELEGRAM_BOT_COMMANDS.md` – Telegram bot command reference and setup
- `TELEGRAM_COMMANDS_QUICKSTART.md` – quick start for Telegram commands and handler
- `archive/CLEANUP_CONSOLIDATION_PLAN.md` – previous cleanup/consolidation notes (historical)

## Initial classification summary

- **Core flow**: `nq_agent.*`, `strategies.nq_intraday.*`, `data_providers.*`
- **Integrations**: `data_providers.ibkr.*`, `utils.telegram_alerts`, `nq_agent.telegram_notifier`, `nq_agent.telegram_command_handler`
- **Utilities**: `utils.*`, `config.*`
- **Operational scripts**: `scripts/lifecycle/*`, `scripts/gateway/*`, `scripts/telegram/*`, `scripts/testing/*`
- **Docs**: architecture, operational, testing, and reference guides as listed above.

A more detailed keep/merge/delete/move matrix will be maintained separately once orphan detection and reference mapping are complete.
