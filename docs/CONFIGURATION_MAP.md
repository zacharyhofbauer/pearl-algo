# Configuration Map

This document maps configuration sources (environment variables, config files, and code defaults) to their usage in the Market Agent system.

## 1. Configuration sources

### 1.1 Environment variables (from `.env`)

Primary environment variables:

- `TELEGRAM_BOT_TOKEN`
  - **Used by**:
    - `config/config.yaml` (`telegram.bot_token`)
    - `pearlalgo.market_agent.main` (fallback when config.yaml not fully populated)
    - `pearlalgo.market_agent.telegram_command_handler.main`
  - **Purpose**: Bot token for Telegram notifications and command handler.
- `TELEGRAM_CHAT_ID`
  - **Used by**:
    - `config/config.yaml` (`telegram.chat_id`)
    - `pearlalgo.market_agent.main`
    - `pearlalgo.market_agent.telegram_command_handler.main`
  - **Purpose**: Authorized chat ID for notifications and bot commands.
- `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`, `IBKR_DATA_CLIENT_ID`
  - **Used by**:
    - `pearlalgo.config.settings.Settings` (normalization and defaults)
  - **Purpose**: IBKR Gateway connection settings.
- `PEARLALGO_DATA_PROVIDER`
  - **Used by**: `pearlalgo.market_agent.main` (`provider_name = os.getenv("PEARLALGO_DATA_PROVIDER", "ibkr")`)
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
  - **Used by**: `pearlalgo.market_agent.telegram_command_handler` (AI Patch Wizard)
  - **Purpose**: API key for OpenAI code generation. Only required if using the AI patch feature.

No other environment variables are required by the running agent; keep any additions explicit and documented here.

### 1.2 Service configuration (`config/config.yaml`)

Key sections and their consumers:

- `symbol`, `timeframe`, `scan_interval`
  - **Used by**: `pearlalgo.market_agent.main` (strategy config builder) and `pearlalgo.market_agent.service`.
- `telegram.*`
  - **Used by**: `pearlalgo.market_agent.main` and `pearlalgo.market_agent.telegram_notifier` (through DI from main and service).
- `risk.*`
  - **Used by**: `pearlalgo.market_agent.main` to derive strategy parameters (see mapping below).
- `service.*`, `circuit_breaker.*`, `data.*`, `signals.*`, `performance.*`
  - **Used by**: `pearlalgo.config.config_loader.load_service_config()` and then by:
    - `pearlalgo.market_agent.service` (service intervals + alert throttles, circuit breaker thresholds)
    - `pearlalgo.market_agent.data_fetcher` (data buffer sizes)
    - `pearlalgo.market_agent.performance_tracker` (performance history limits)
    - `trading_bots.pearl_bot_auto` (signal thresholds, where applicable).
- `strategy`, `strategy_variants`
  - **Used by**: `trading_bots.pearl_bot_auto.CONFIG` for advanced strategy configuration.
  - **Purpose**: Allow runtime strategy parameter overrides and define strategy variants for backtesting/experimentation.
- `market_hours`
  - **Used by**: `pearlalgo.utils.market_hours` and strategy session logic.
  - **Purpose**: Define market hours and session windows for trading logic.
- `execution.*` (ATS; disabled by default)
  - **Used by**: `pearlalgo.execution.ibkr.adapter`, `pearlalgo.market_agent.service`
  - **Purpose**: Automated execution configuration (enabled, armed, mode, limits, whitelist).
  - **Defaults**: `enabled: false`, `armed: false`, `mode: dry_run`
- `learning.*` (ATS; shadow mode by default)
  - **Used by**: `pearlalgo.learning.bandit_policy`, `pearlalgo.market_agent.service`
  - **Purpose**: Adaptive learning policy configuration (mode, thresholds, priors).
  - **Defaults**: `enabled: true`, `mode: shadow`
- `ml_filter.*` (shadow mode by default)
  - **Used by**: `pearlalgo.learning.ml_signal_filter`, `pearlalgo.market_agent.service`
  - **Purpose**: ML scoring, lift measurement, and optional sizing/priority adjustments.
  - **Key fields**:
    - `mode`: `shadow` or `live` (blocking only in `live`)
    - `high_probability`: threshold for “high opportunity”
    - `adjust_sizing`: enable ML-driven sizing/priority (no gate bypass)
    - `size_multiplier_min`, `size_multiplier_max`: bounds for ML sizing multiplier

Notes:
- Base config `config/config.yaml` is merged with optional overlays from `PEARLALGO_CONFIG_PATH`
  (e.g., `config/markets/nq.yaml`). Overlay values override base values.
- `data.enable_mtf_cache`, `data.mtf_refresh_seconds_5m`, `data.mtf_refresh_seconds_15m` (default OFF)
  control how often 5m/15m history is refreshed.
  This reduces repeated IBKR historical requests when the service runs with a fast scan interval.

#### Strategy mapping (config.yaml → pearl_bot_auto)

- `signals.min_confidence` → `pearl_bot_auto.CONFIG.min_confidence`
- `signals.min_risk_reward` → `pearl_bot_auto.CONFIG.min_risk_reward`
- `session.start_time/end_time` → `start_hour/start_minute/end_hour/end_minute`
- `risk.stop_loss_atr_multiplier` → `stop_loss_atr_mult`
- `risk.take_profit_risk_reward` → `take_profit_atr_mult` (derived: stop_loss_atr_mult × risk_reward)

### 1.3 Settings module (`pearlalgo.config.settings`)

- Provides Pydantic‑validated `Settings` via `get_settings()`.
- Loads from `.env` with prefix `PEARLALGO_` and additional normalization of `IBKR_*` variables.
- Intended for **infrastructure** and **deployment** configuration:
  - IBKR host/port/client IDs

### 1.4 Strategy config (`pearlalgo.trading_bots.pearl_bot_auto`)

- Strategy‑specific parameters such as symbol, timeframe, risk parameters, ATR multipliers, R:R ratios.
- May read environment overrides (via `os.getenv` helper) but is primarily driven by `config/config.yaml`.



### 1.2 Tradovate environment variables (from `~/.config/pearlalgo/secrets.env`)

These are used by the MFFU evaluation instance only:

- `TRADOVATE_USERNAME` -- Tradovate account username
- `TRADOVATE_PASSWORD` -- Tradovate account password
- `TRADOVATE_CID` -- Client app ID (integer, from Tradovate API key)
- `TRADOVATE_SEC` -- API secret (UUID, from Tradovate API key)
- `TRADOVATE_APP_ID` -- Free-form app name (default: "PearlAlgo")
- `TRADOVATE_APP_VERSION` -- App version (default: "1.0")
- `TRADOVATE_ENV` -- "demo" or "live" (default: "demo")
- `TRADOVATE_ACCOUNT_NAME` -- Optional account name filter (e.g., "DEMO6315448")
- `TRADOVATE_DEVICE_ID` -- Unique device UUID (auto-generated if not set)

**Used by**: `src/pearlalgo/execution/tradovate/config.py` (`TradovateConfig.from_env()`)

### 1.3 MFFU-specific environment variables (from `scripts/lifecycle/mffu_eval.sh`)

- `IBKR_CLIENT_ID=50` -- IBKR client ID for MFFU agent (avoids clash with inception=10)
- `IBKR_DATA_CLIENT_ID=51` -- IBKR data client ID for MFFU (avoids clash with inception=11)
- `IB_CLIENT_ID_LIVE_CHART=97` -- Chart data client ID for MFFU API (avoids clash with inception=96)
- `PEARLALGO_STATE_DIR=data/agent_state/MFFU_EVAL` -- Isolated state directory
- `PEARLALGO_CONFIG_PATH=config/markets/mffu_eval.yaml` -- MFFU config overlay
- `API_PORT=8001` -- MFFU API server port

### 1.4 Config files

| File | Purpose |
|------|---------|
| `config/config.yaml` | Base config (inception). All settings. |
| `config/markets/mffu_eval.yaml` | MFFU overlay. Merged on top of base via deep merge. |
| `~/.config/pearlalgo/secrets.env` | Secrets (Telegram, Tradovate, API keys). Never committed. |
| `.env` | Non-sensitive defaults (IBKR ports, data provider). |
| `pearlalgo_web_app/.env.local` | Web app API key (auto-synced from secrets by pearl.sh). |

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
- **Strategy config (`pearlalgo.trading_bots.pearl_bot_auto`)** – trading logic parameters (`src/pearlalgo/trading_bots/pearl_bot_auto.py`):
  - ATR multipliers, risk/reward thresholds
  - Session definitions and regime parameters

## 3. Guidelines for future changes

1. **New deployment‑specific value?**
   - Add as an environment variable (documented in `env.example`) and wire through `Settings` or direct `os.getenv` in `main`/entry code.
2. **New service behavior toggle or threshold?**
   - Add to `config/config.yaml` and load via `load_service_config()` or strategy config; avoid hard‑coding in multiple modules.
3. **New strategy‑specific parameter?**
   - Add to `src/pearlalgo/trading_bots/pearl_bot_auto.py` CONFIG dictionary and reference from strategy functions.
4. **Avoid magic numbers** when they influence trading or service behavior; prefer a named config key with a documented default.

This document is descriptive and does not alter runtime behavior, but it should be kept up to date when configuration wiring changes.
