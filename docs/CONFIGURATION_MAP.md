# Configuration Map

This document maps configuration sources (environment variables, config files, and code defaults) to their usage in the NQ Agent system.

## 1. Configuration sources

### 1.1 Environment variables (from `.env`)

Primary environment variables:

- `TELEGRAM_BOT_TOKEN`
  - **Used by**:
    - `config/config.yaml` (`telegram.bot_token`)
    - `pearlalgo.nq_agent.main` (fallback when config.yaml not fully populated)
    - `pearlalgo.nq_agent.telegram_command_handler.main`
  - **Purpose**: Bot token for Telegram notifications and command handler.
- `TELEGRAM_CHAT_ID`
  - **Used by**:
    - `config/config.yaml` (`telegram.chat_id`)
    - `pearlalgo.nq_agent.main`
    - `pearlalgo.nq_agent.telegram_command_handler.main`
  - **Purpose**: Authorized chat ID for notifications and bot commands.
- `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`, `IBKR_DATA_CLIENT_ID`
  - **Used by**:
    - `config/config.yaml` (`ibkr.host`, `ibkr.port`, `ibkr.client_id`, `ibkr.data_client_id` via `${VAR:-default}`)
    - `pearlalgo.config.settings.Settings` (normalization and defaults)
  - **Purpose**: IBKR Gateway connection settings.
- `PEARLALGO_DATA_PROVIDER`
  - **Used by**: `pearlalgo.nq_agent.main` (`provider_name = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr")`)
  - **Purpose**: Selects data provider implementation (default `ibkr`).
- `PEARLALGO_DUMMY_MODE`
  - **Used by**: `pearlalgo.config.settings.Settings` (`dummy_mode` flag)
  - **Purpose**: Enables dummy data mode for testing/development.
- `PEARLALGO_IB_HOST`, `PEARLALGO_IB_PORT`, `PEARLALGO_IB_CLIENT_ID`, `PEARLALGO_IB_DATA_CLIENT_ID`
  - **Used by**: `pearlalgo.config.settings.Settings` (fallbacks when `IBKR_*` are not set).
  - **Purpose**: Alternative namespaced IBKR settings.

Additional environment variables may be used for generic settings (e.g., log level) via `Settings`, but the above are the primary ones wired into the NQ Agent.

### 1.2 Service configuration (`config/config.yaml`)

Key sections and their consumers:

- `symbol`, `timeframe`, `scan_interval`
  - **Used by**: `strategies.nq_intraday.config.NQIntradayConfig` and `pearlalgo.nq_agent.service` via strategy config.
- `ibkr.*`
  - **Used by**: `pearlalgo.data_providers.ibkr.ibkr_provider` / `ibkr_executor` via `Settings` and/or direct config access.
- `telegram.*`
  - **Used by**: `pearlalgo.nq_agent.main` and `pearlalgo.nq_agent.telegram_notifier` (through DI from main and service).
- `risk.*`
  - **Used by**: `strategies.nq_intraday.config.NQIntradayConfig` and downstream strategy components.
- `logging.*`
  - **Used by**: `pearlalgo.utils.logging_config` and startup scripts (log level and destinations).
- `data_provider`
  - **Used by**: `pearlalgo.nq_agent.main` / `data_providers.factory` as provider name (default `ibkr`).
- `service.*`, `circuit_breaker.*`, `alerts.*`, `data.*`, `signals.*`, `performance.*`, `prop_firm.*`
  - **Used by**: `pearlalgo.config.config_loader.load_service_config()` and then by:
    - `pearlalgo.nq_agent.service` (service intervals, circuit breaker thresholds, alert intervals)
    - `pearlalgo.nq_agent.data_fetcher` (data buffer sizes)
    - `pearlalgo.nq_agent.performance_tracker` (performance history limits)
    - `strategies.nq_intraday.*` (signal thresholds, where applicable).

### 1.3 Settings module (`pearlalgo.config.settings`)

- Provides Pydantic‑validated `Settings` via `get_settings()`.
- Loads from `.env` with prefix `PEARLALGO_` and additional normalization of `IBKR_*` variables.
- Intended for **infrastructure** and **deployment** configuration:
  - IBKR host/port/client IDs
  - Data directory / API keys
  - Log level and `dummy_mode`

### 1.4 Strategy config (`strategies/nq_intraday/config.py`)

- Strategy‑specific parameters such as symbol, timeframe, risk parameters, ATR multipliers, R:R ratios.
- May read environment overrides (via `os.getenv` helper) but is primarily driven by `config/config.yaml`.

## 2. What belongs where

- **Environment (`.env`)** – deployment‑specific values:
  - Secrets (Telegram bot token, chat IDs)
  - IBKR host/port/client IDs
  - Provider selection (`PEARLALGO_DATA_PROVIDER`)
  - Dummy mode toggle (`PEARLALGO_DUMMY_MODE`)
- **Service config (`config/config.yaml`)** – behavior of the running service:
  - Trading symbol, timeframe, scan interval
  - Risk and position sizing defaults
  - Service intervals, circuit breaker thresholds, alert intervals
  - Data buffer sizes and history windows
  - Signal thresholds and duplicate windows
  - Performance history limits and prop‑firm assumptions
- **Settings (`settings.py`)** – infrastructure and environment glue:
  - Normalization of env vars
  - Validation of IBKR settings
  - Data directory and profile selection
- **Strategy config (`strategies/nq_intraday/config.py`)** – trading logic parameters:
  - ATR multipliers, risk/reward thresholds
  - Session definitions and regime parameters

## 3. Guidelines for future changes

1. **New deployment‑specific value?**
   - Add as an environment variable (documented in `.env.example`) and wire through `Settings` or direct `os.getenv` in `main`/entry code.
2. **New service behavior toggle or threshold?**
   - Add to `config/config.yaml` and load via `load_service_config()` or strategy config; avoid hard‑coding in multiple modules.
3. **New strategy‑specific parameter?**
   - Add to `strategies/nq_intraday/config.py` and reference from strategy components.
4. **Avoid magic numbers** when they influence trading or service behavior; prefer a named config key with a documented default.

This document is descriptive and does not alter runtime behavior, but it should be kept up to date when configuration wiring changes.