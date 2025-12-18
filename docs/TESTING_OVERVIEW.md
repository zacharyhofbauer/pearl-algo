# Testing Overview and Gaps

This document summarizes the current test coverage and highlights areas for future expansion.

## 1. Existing tests

### 1.1 Unified test runner (`scripts/testing/test_all.py`)

- Modes:
  - `all` – runs all integrated tests
  - `telegram` – runs `test_telegram_notifications()`
  - `signals` – runs `test_signal_generation()` with `MockDataProvider`
  - `service` – runs service‑level tests with mock data
- Exercises:
  - Telegram notifier formatting and sending
  - Strategy signal generation with mock data
  - NQ Agent service with mock provider

### 1.2 Tests under `scripts/testing/`

- `test_nq_agent_with_mock.py` – integration tests using mock provider
- `test_signal_generation.py`, `test_signal_starvation_fixes.py` – strategy tests
- `test_data_quality.py` – data quality checks
- `test_e2e_simulation.py` – end‑to‑end simulation
- `test_telegram_notifications.py` – Telegram notifications
- `smoke_test_ibkr.py` – IBKR connectivity smoke test
- `validate_strategy.py` – strategy validation helper

### 1.3 Tests under `tests/`

- `mock_data_provider.py` – common mock provider for unit/integration tests
- `test_edge_cases.py` – edge case placeholders and basic data‑fetch edge tests
- `test_error_recovery.py` – error recovery and circuit‑breaker behavior (partially)

## 2. Observed gaps

These gaps are **observational only** and do not change behavior.

1. **Market hours edge cases** (`test_edge_cases.py`)
   - Several tests are placeholders (e.g., DST transitions, holidays, connection errors) and do not assert concrete behavior yet.
2. **Circuit breaker thresholds** (`test_error_recovery.py`)
   - Tests set thresholds and flags but currently do not drive the full `_run_loop` logic; they mainly assert attribute changes.
3. **Configuration wiring**
   - There are no explicit tests verifying that values from `config/config.yaml` and `Settings` correctly propagate into `NQAgentService` (intervals, thresholds) and data providers.
4. **IBKR entitlements and fallback behavior**
   - `smoke_test_ibkr.py` and docs describe entitlements, but there are no isolated unit tests for `ibkr.entitlements` logic.
5. **Command handler behavior**
   - The Telegram command handler (`telegram_command_handler.py`) is exercised indirectly via manual testing but does not yet have automated tests for `/status`, `/signals`, `/performance` command flows.

## 3. Suggested future tests (no behavior change)

1. **Config propagation tests**
   - New tests that:
     - Load `config/config.yaml` via `load_service_config()`
     - Instantiate `NQAgentService` and assert that service intervals, circuit breaker thresholds, and buffer sizes match config values.
2. **Settings/IBKR normalization tests**
   - Unit tests for `Settings.from_profile` and env normalization paths, ensuring `IBKR_*` and `PEARLALGO_*` precedence behaves as documented.
3. **Circuit breaker integration tests**
   - Controlled tests that simulate repeated errors through a stub data provider and assert:
     - `connection_failures` / `data_fetch_errors` thresholds trigger pause
     - Telegram circuit‑breaker alerts are sent (using a mock notifier).
4. **Command handler tests**
   - Async tests for `TelegramCommandHandler` that mock Telegram `Update` objects and verify:
     - `/status` returns correctly formatted status and buttons
     - `/signals` and `/performance` read from state/performance files and render expected output
     - Unauthorized chat IDs are rejected.
5. **Market hours / data quality edge cases**
   - Replace placeholders in `test_edge_cases.py` with real tests using mocked `market_hours` and timestamped data frames.

## 4. Tests potentially safe to refine

- Placeholder tests in `test_edge_cases.py` and simple attribute‑only assertions in `test_error_recovery.py` can be gradually strengthened to assert real behavior.
- No tests are currently marked for deletion; all files remain part of the suite as of this audit.

This overview should be updated whenever new tests are added or existing tests are significantly refactored.