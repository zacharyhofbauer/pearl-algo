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
    - `pearlalgo.config.settings.Settings` (normalization and defaults)
  - **Purpose**: IBKR Gateway connection settings.
- `PEARLALGO_DATA_PROVIDER`
  - **Used by**: `pearlalgo.nq_agent.main` (`provider_name = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr")`)
  - **Purpose**: Selects data provider implementation (default `ibkr`).
- `PEARLALGO_IB_HOST`, `PEARLALGO_IB_PORT`, `PEARLALGO_IB_CLIENT_ID`, `PEARLALGO_IB_DATA_CLIENT_ID`
  - **Used by**: `pearlalgo.config.settings.Settings` (fallbacks when `IBKR_*` are not set).
  - **Purpose**: Alternative namespaced IBKR settings.

Optional logging environment variables (for systemd/journald):

- `PEARLALGO_LOG_LEVEL`
  - **Used by**: `pearlalgo.utils.logging_config.setup_logging()`
  - **Purpose**: Override log level (DEBUG, INFO, WARNING, ERROR). Default: `INFO`.
- `PEARLALGO_LOG_JSON`
  - **Used by**: `pearlalgo.utils.logging_config.setup_logging()`
  - **Purpose**: Set to `true` or `1` to emit JSON logs to stdout (useful for log aggregation). Default: `false`.
- `PEARLALGO_LOG_EXTRA`
  - **Used by**: `pearlalgo.utils.logging_config.setup_logging()`
  - **Purpose**: Set to `true` or `1` to include `extra={...}` context in text log lines. Default: `false`.

Optional AI/LLM environment variables (for OpenAI integration):

- `OPENAI_API_KEY`
  - **Used by**: `pearlalgo.nq_agent.telegram_command_handler` (AI Patch Wizard)
  - **Purpose**: API key for OpenAI code generation. Only required if using the AI patch feature.

No other environment variables are required by the running agent; keep any additions explicit and documented here.

### 1.2 Service configuration (`config/config.yaml`)

Key sections and their consumers:

- `symbol`, `timeframe`, `scan_interval`
  - **Used by**: `strategies.nq_intraday.config.NQIntradayConfig` and `pearlalgo.nq_agent.service` via strategy config.
- `telegram.*`
  - **Used by**: `pearlalgo.nq_agent.main` and `pearlalgo.nq_agent.telegram_notifier` (through DI from main and service).
- `risk.*`
  - **Used by**: `strategies.nq_intraday.config.NQIntradayConfig` and downstream strategy components.
- `service.*`, `circuit_breaker.*`, `data.*`, `signals.*`, `performance.*`
  - **Used by**: `pearlalgo.config.config_loader.load_service_config()` and then by:
    - `pearlalgo.nq_agent.service` (service intervals + alert throttles, circuit breaker thresholds)
    - `pearlalgo.nq_agent.data_fetcher` (data buffer sizes)
    - `pearlalgo.nq_agent.performance_tracker` (performance history limits)
    - `strategies.nq_intraday.*` (signal thresholds, where applicable).
- `strategy`, `strategy_variants`
  - **Used by**: `strategies.nq_intraday.config.NQIntradayConfig` for advanced strategy configuration.
  - **Purpose**: Allow runtime strategy parameter overrides and define strategy variants for backtesting/experimentation.
- `market_hours`
  - **Used by**: `pearlalgo.utils.market_hours` and strategy session logic.
  - **Purpose**: Define market hours and session windows for trading logic.
- `execution.*` (ATS; disabled by default)
  - **Used by**: `pearlalgo.execution.ibkr.adapter`, `pearlalgo.nq_agent.service`
  - **Purpose**: Automated execution configuration (enabled, armed, mode, limits, whitelist).
  - **Defaults**: `enabled: false`, `armed: false`, `mode: dry_run`
- `learning.*` (ATS; shadow mode by default)
  - **Used by**: `pearlalgo.learning.bandit_policy`, `pearlalgo.nq_agent.service`
  - **Purpose**: Adaptive learning policy configuration (mode, thresholds, priors).
  - **Defaults**: `enabled: true`, `mode: shadow`

Notes:
- `data.enable_mtf_cache`, `data.mtf_refresh_seconds_5m`, `data.mtf_refresh_seconds_15m` (default OFF) control how often 5m/15m history is refreshed.
  This reduces repeated IBKR historical requests when the service runs with a fast scan interval.

### 1.3 Settings module (`pearlalgo.config.settings`)

- Provides Pydantic‑validated `Settings` via `get_settings()`.
- Loads from `.env` with prefix `PEARLALGO_` and additional normalization of `IBKR_*` variables.
- Intended for **infrastructure** and **deployment** configuration:
  - IBKR host/port/client IDs

### 1.4 Strategy config (`pearlalgo.strategies.nq_intraday.config`)

- Strategy‑specific parameters such as symbol, timeframe, risk parameters, ATR multipliers, R:R ratios.
- May read environment overrides (via `os.getenv` helper) but is primarily driven by `config/config.yaml`.

## 2. What belongs where

- **Environment (`.env`)** – deployment‑specific values:
  - Secrets (Telegram bot token, chat IDs)
  - IBKR host/port/client IDs
  - Provider selection (`PEARLALGO_DATA_PROVIDER`)
  - Logging overrides (`PEARLALGO_LOG_LEVEL`, `PEARLALGO_LOG_JSON`, `PEARLALGO_LOG_EXTRA`)
- **Service config (`config/config.yaml`)** – behavior of the running service:
  - Trading symbol, timeframe, scan interval
  - Risk and position sizing defaults
  - Service intervals, circuit breaker thresholds, alert throttles
  - Data buffer sizes and history windows
  - Signal thresholds and duplicate windows
  - Performance history limits
- **Settings (`pearlalgo.config.settings`)** – infrastructure and environment glue (`src/pearlalgo/config/settings.py`):
  - Normalization of env vars
  - Validation of IBKR settings
- **Strategy config (`pearlalgo.strategies.nq_intraday.config`)** – trading logic parameters (`src/pearlalgo/strategies/nq_intraday/config.py`):
  - ATR multipliers, risk/reward thresholds
  - Session definitions and regime parameters

## 3. Guidelines for future changes

1. **New deployment‑specific value?**
   - Add as an environment variable (documented in `env.example`) and wire through `Settings` or direct `os.getenv` in `main`/entry code.
2. **New service behavior toggle or threshold?**
   - Add to `config/config.yaml` and load via `load_service_config()` or strategy config; avoid hard‑coding in multiple modules.
3. **New strategy‑specific parameter?**
   - Add to `src/pearlalgo/strategies/nq_intraday/config.py` and reference from strategy components.
4. **Avoid magic numbers** when they influence trading or service behavior; prefer a named config key with a documented default.

This document is descriptive and does not alter runtime behavior, but it should be kept up to date when configuration wiring changes.
