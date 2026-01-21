# Project Summary - PearlAlgo MNQ Trading Agent

**Version:** 0.2.2  
**Last Updated:** 2025-12-31 (IBKR Data Quality & Observability)  
**Status:** Production-Ready  
**Trading Style:** Prop Firm - Intraday Swings & Quick Scalps

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Project Overview](#project-overview)
3. [System Architecture](#system-architecture)
4. [Core Components](#core-components)
5. [Data Flow](#data-flow)
6. [Technology Stack](#technology-stack)
7. [Project Structure](#project-structure)
8. [Configuration](#configuration)
9. [Key Features](#key-features)
10. [Testing Strategy](#testing-strategy)
11. [Deployment & Operations](#deployment--operations)
12. [Monitoring & Alerts](#monitoring--alerts)
13. [Roadmap & Future Enhancements](#roadmap--future-enhancements)
14. [Known Limitations](#known-limitations)

---

## Executive Summary

**PearlAlgo MNQ Trading Agent** is an automated, production-ready trading system optimized for **prop firm style trading** with **Mini NQ (MNQ)** futures. The system operates 24/7, automatically scanning market data, generating trading signals for intraday swings and quick scalps, and sending notifications via Telegram. It's built with a modular architecture that separates data providers, strategies, and execution logic, making it easy to extend and maintain.

### Key Highlights

- ✅ **Fully Automated**: Runs 24/7 with minimal intervention
- ✅ **Prop Firm Optimized**: MNQ futures with explicit risk caps and guardrails (see `config/config.yaml`)
- ✅ **Scalping Focus**: Adaptive cadence (5s active, 30s idle, 300s closed) + confidence/R:R filters + adaptive stops/sizing
- ✅ **Real-time Data**: Connects to Interactive Brokers (IBKR) Gateway for live market data
- ✅ **Intelligent Signals**: Uses technical analysis to generate high-confidence trading signals
- ✅ **Mobile-Friendly Notifications**: Rich Telegram notifications optimized for mobile viewing
- ✅ **Robust Error Handling**: Circuit breakers, connection monitoring, automatic recovery
- ✅ **Performance Tracking**: Built-in performance metrics and signal tracking
- ✅ **Production-Ready**: Comprehensive testing, logging, and monitoring

---

## Project Overview

### Purpose

The MNQ Trading Agent is designed to:
1. **Monitor** Mini NQ (MNQ) futures market data in real-time
2. **Analyze** market conditions using technical indicators
3. **Generate** trading signals optimized for prop firm trading (intraday swings & quick scalps)
4. **Notify** users via Telegram with mobile-optimized messages
5. **Track** performance and maintain state across restarts

### Target Market

- **Symbol**: Mini E-mini NASDAQ-100 Futures (MNQ) - 1/10th size of NQ
- **Timeframe**: 1-minute decision stream (configurable), with 5m/15m for MTF context
- **Trading session (StrategySessionOpen)**: Prop-firm window 18:00 - 16:10 ET (NY time). Positions must be flat by 16:10.
- **Futures market window (FuturesMarketOpen)**: CME ETH Sun 18:00 ET → Fri 17:00 ET (Mon–Thu 17:00–18:00 ET maintenance break)
- **Market**: CME Group futures exchange
- **Trading Style**: Prop-firm intraday swings and scalps; sizing/risk thresholds are configured in `config/config.yaml`

### Design Philosophy

- **Simplicity**: Focused on MNQ futures (prop firm friendly, can be extended)
- **Reliability**: Robust error handling, connection monitoring, and automatic recovery
- **Transparency**: Comprehensive logging and Telegram notifications
- **Modularity**: Clean separation of concerns (data, strategy, execution)
- **Testability**: Mock data providers for testing without live market data
- **Prop Firm Focus**: Configurable risk (default 1.5% per trade), dynamic position sizing, quick scalps

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MNQ Agent Service                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Data Fetcher │→ │   Strategy   │→ │ Signal Proc. │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         ↓                  ↓                  ↓               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ State Mgr    │  │ Performance  │  │ Telegram     │      │
│  │              │  │ Tracker      │  │ Notifier     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
         ↓                    ↓                    ↓
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ IBKR Gateway │    │ State Files  │    │ Telegram API │
│  (Port 4002) │    │ (JSON/JSONL) │    │   (Cloud)    │
└──────────────┘    └──────────────┘    └──────────────┘
```

### Component Interaction Flow

1. **Service Loop** (adaptive cadence: 5s during active session, 30s during idle, 300s when market closed):
   - Fetches latest market data via Data Fetcher
   - Monitors IB Gateway connection status
   - Analyzes data using Strategy
   - Generates signals if conditions are met (prop firm optimized)
   - Processes signals (save, track, notify with position sizing)
   - Updates state and sends periodic status updates

2. **Data Flow**:
   - IBKR Gateway → IBKR Provider → Data Fetcher → Strategy
   - Historical data cached in buffer (last 100 bars)

3. **Signal Flow**:
   - Strategy → Signal Generator → State Manager → Performance Tracker → Telegram

---

## Core Components

### 1. NQ Agent Service (`src/pearlalgo/nq_agent/`)

**Main Service** (`service.py`):
- 24/7 service loop with adaptive cadence (5s active, 30s idle, 300s market closed; base scan_interval configurable)
- Circuit breaker (pauses after 10 consecutive errors)
- Connection failure detection and alerts
- Automatic recovery and error handling
- Periodic status updates and heartbeats
- Data quality monitoring
- IB Gateway connection status tracking

**Data Fetcher** (`data_fetcher.py`):
- Fetches historical and latest bar data
- Maintains data buffer (last 100 bars)
- Handles data provider abstraction
- Error handling and retry logic

**State Manager** (`state_manager.py`):
- Persists service state to JSON
- Saves signals to JSONL file
- Loads state on startup
- State directory: `data/agent_state/<MARKET>/`

**Performance Tracker** (`performance_tracker.py`):
- Tracks signal generation → entry → exit lifecycle
- Calculates win rate, P&L, average hold time
- Stores performance metrics in JSON
- Provides 7-day rolling metrics

**Telegram Notifier** (`telegram_notifier.py`):
- Sends all notification types:
  - Signal notifications (entry, stop, target, R:R)
  - Dashboard updates (configurable via `dashboard_chart_interval`, default 1 hour)
  - Data quality alerts
  - Performance summaries
  - Startup/shutdown notifications
  - Circuit breaker alerts
  - Recovery notifications
- Mobile-optimized formatting (no long separators, vertical layout)

**Health Monitor** (`health_monitor.py`):
- Monitors component health
- Checks data provider connectivity
- Validates Telegram connectivity
- File system health checks

**Main Entry Point** (`main.py`):
- Initializes service with configuration
- Loads environment variables
- Creates data provider via factory
- Handles graceful shutdown

### 2. NQ Strategy (`src/pearlalgo/strategies/nq_intraday/`)

**Strategy** (`strategy.py`):
- Coordinates scanner and signal generator
- Main entry point for strategy analysis

**Scanner** (`scanner.py`):
- Strategy session detection (configurable; default 18:00–16:10 ET, NY time)
- Technical indicator calculations:
  - RSI (Relative Strength Index)
  - MACD (Moving Average Convergence Divergence)
  - ATR (Average True Range)
  - EMA (Exponential Moving Averages)
  - Bollinger Bands
- Pattern detection:
  - Unified strategy (EMA crossover + VWAP bias + RSI confirmation + ATR stops)

**Signal Generator** (`signal_generator.py`):
- Validates scanner results
- Filters signals by confidence threshold (minimum 50% for prop firm)
- Calculates entry, stop-loss, and take-profit levels
- Risk/reward ratio validation (minimum 1.2:1 R:R filter, configurable via `signals.min_risk_reward`)
- Position sizing calculation (5-15 MNQ contracts)
- Risk amount calculation (MNQ tick value: $2/point)
- Duplicate signal prevention (5-minute window)

**Config** (`config.py`):
- Strategy configuration (symbol: MNQ, timeframe, risk parameters)
- Prop firm defaults: Risk/stops/sizing configurable via `config/config.yaml` (see Configuration section)
- Loads from `config/config.yaml` or uses defaults

### 3. Data Providers (`src/pearlalgo/data_providers/`)

**Base Provider** (`base.py`):
- Abstract interface for data providers
- Methods: `fetch_historical()`, `get_latest_bar()`

**IBKR Provider** (`src/pearlalgo/data_providers/ibkr/ibkr_provider.py`):
- Production-ready IBKR data provider
- Uses `ib_insync` library for IB Gateway connection
- Thread-safe executor for IBKR API calls
- Connection lifecycle management
- Market data validation
- Stale data detection
- Automatic contract resolution (front month futures)

**IBKR Executor** (`ibkr_executor.py`):
- Dedicated thread for IBKR API calls
- Manages connection lifecycle
- Handles reconnection logic
- Task queue for async operations

**Factory** (`factory.py`):
- Creates data provider instances
- Currently supports: `ibkr`
- Extensible for additional providers

### 4. Utilities (`src/pearlalgo/utils/`)

**Telegram Alerts** (`telegram_alerts.py`):
- Core Telegram messaging functionality
- Rich formatting helpers (currency, percentage, numbers)
- Mobile-friendly message formatting

**Market Hours** (`market_hours.py`):
- Market hours detection
- Timezone handling (ET)

**Retry Logic** (`retry.py`):
- Async retry with exponential backoff
- Configurable retry attempts

**Logging** (`logger.py`, `logging_config.py`):
- `logger.py`: shared logger instance (loguru-backed when available)
- `logging_config.py`: logging setup helpers (structured logging, correlation IDs, timing)
- **Systemd-friendly**: ANSI colors auto-disabled when stdout is not a TTY
- **Per-run correlation**: Each process start gets a unique `run_id` for log grouping
- **Environment variables** (optional):
  - `PEARLALGO_LOG_LEVEL`: Override log level (DEBUG, INFO, WARNING, ERROR)
  - `PEARLALGO_LOG_JSON`: Set to `true` for JSON logs (useful for log aggregation)
  - `PEARLALGO_LOG_EXTRA`: Set to `true` to include `extra={...}` context in text logs

### 5. Configuration (`src/pearlalgo/config/`)

**Settings** (`settings.py`):
- Pydantic-based settings management
- Loads from environment variables
- Type validation

**Symbols**: Symbol definitions are embedded in strategy configuration (`src/pearlalgo/strategies/nq_intraday/config.py`). The system currently uses MNQ (Mini NQ) futures.

---

## Data Flow

### 1. Service Startup

```
main.py
  ↓
Load .env and config.yaml
  ↓
Create Data Provider (via factory)
  ↓
Create NQAgentService
  ↓
Start Service Loop
```

### 2. Main Service Loop (Every 30 seconds for scalping)

```
Service Loop
  ↓
Data Fetcher.fetch_latest_data()
  ↓
  ├─→ Fetch historical data (last 2 hours)
  ├─→ Update buffer (last 100 bars)
  └─→ Get latest bar
  ↓
Strategy.analyze(market_data)
  ↓
  ├─→ Scanner.scan() → Technical indicators
  └─→ Signal Generator.generate() → Validated signals
  ↓
For each signal:
  ├─→ Performance Tracker.track_signal_generated()
  ├─→ State Manager.save_signal()
  └─→ Telegram Notifier.send_signal()
  ↓
Periodic Updates:
  ├─→ Dashboard Update (hourly by default)
  └─→ State Save (every 10 cycles)
```

### 3. Data Provider Flow

```
IBKR Gateway (Port 4002)
  ↓
IBKR Executor (Thread-safe)
  ↓
IBKR Provider
  ├─→ fetch_historical() → DataFrame
  └─→ get_latest_bar() → Dict
  ↓
Data Fetcher
  └─→ Maintains buffer (100 bars)
```

### 4. Signal Processing Flow

```
Signal Generated
  ↓
Performance Tracker (assign signal_id)
  ↓
State Manager (save to signals.jsonl)
  ↓
Telegram Notifier (format and send)
  ↓
Signal Count Incremented
```

---

## Technology Stack

### Core Dependencies

- **Python**: 3.12+
- **pandas**: 2.2+ (DataFrame operations)
- **numpy**: 2.0+ (Numerical computations)
- **pydantic**: 2.8+ (Configuration validation)
- **pydantic-settings**: 2.6+ (Environment-based settings)
- **python-dotenv**: 1.0+ (Environment file loading)
- **ib-insync**: 0.9.86+ (IBKR API client)
- **python-telegram-bot**: 20.0+ (Telegram notifications)
- **loguru**: 0.7.0+ (Logging)
- **PyYAML**: 6.0+ (Configuration files)
- **pytz**: 2024.1+ (Timezone handling)
- **matplotlib**: 3.8+ (Charting backend)
- **mplfinance**: 0.12+ (Financial charts)
- **pyarrow**: 16.0+ (Parquet state persistence)

### Development Dependencies

- **pytest**: 8.3+ (Testing framework)
- **pytest-asyncio**: 0.21.0+ (Async testing)
- **ruff**: 0.6+ (Linting and formatting)

### External Services

- **IBKR Gateway**: Interactive Brokers Gateway (headless, port 4002)
- **Telegram Bot API**: Cloud-based messaging service

---

## Project Structure

```
pearlalgo-dev-ai-agents/
├── src/pearlalgo/              # Main source code
│   ├── nq_agent/               # MNQ Agent Service
│   │   ├── main.py             # Entry point
│   │   ├── service.py          # Main service loop
│   │   ├── data_fetcher.py     # Data fetching logic
│   │   ├── state_manager.py    # State persistence
│   │   ├── performance_tracker.py  # Performance metrics
│   │   ├── telegram_notifier.py    # Telegram notifications
│   │   ├── telegram_command_handler.py  # Interactive Telegram bot commands (separate service)
│   │   ├── chart_generator.py    # mplfinance chart generation (optional, Telegram)
│   │   └── health_monitor.py       # Health monitoring
│   ├── strategies/nq_intraday/ # MNQ Strategy (prop firm optimized)
│   │   ├── strategy.py         # Main strategy class
│   │   ├── scanner.py          # Market scanning
│   │   ├── signal_generator.py # Signal generation
│   │   ├── signal_quality.py   # Signal quality scoring
│   │   ├── config.py           # Strategy configuration
│   │   ├── hud_context.py      # HUD/display context builder
│   │   ├── mtf_analyzer.py     # Multi-timeframe analysis
│   │   ├── regime_detector.py  # Market regime detection
│   │   ├── volume_profile.py   # Volume profile analysis
│   │   ├── order_flow.py       # Order flow analysis
│   │   └── backtest_adapter.py # Backtesting adapter
│   ├── execution/              # ATS Execution Layer (disabled by default)
│   │   ├── base.py             # ExecutionAdapter interface, ExecutionConfig
│   │   └── ibkr/               # IBKR execution implementation
│   │       ├── adapter.py      # IBKR bracket order adapter
│   │       └── tasks.py        # Order placement/cancellation tasks
│   ├── learning/               # Adaptive Learning Layer (shadow mode by default)
│   │   ├── bandit_policy.py    # Thompson sampling policy
│   │   └── policy_state.py     # Policy statistics persistence
│   │   ├── monitor_service.py  # Main monitor service loop
│   │   ├── analysis_engine.py  # Analysis orchestration
│   │   ├── analyzers/          # Domain-specific analyzers (signal, system, market, code)
│   │   ├── suggestion_engine.py # Configuration suggestions
│   │   └── alert_manager.py    # Alert deduplication and delivery
│   ├── data_providers/         # Data Providers
│   │   ├── base.py             # Abstract interface
│   │   ├── factory.py          # Provider factory
│   │   ├── ibkr/               # IBKR provider
│   │   │   └── ibkr_provider.py
│   │   └── ibkr_executor.py    # Thread-safe executor
│   ├── utils/                  # Utilities (cross-cutting)
│   │   ├── telegram_alerts.py  # Telegram core
│   │   ├── cadence.py          # Cadence scheduler + metrics
│   │   ├── market_hours.py     # Market hours logic
│   │   ├── retry.py            # Retry logic
│   │   ├── logger.py           # Shared logger instance
│   │   ├── logging_config.py   # Logging setup helpers
│   │   ├── error_handler.py    # Error classification + handling helpers
│   │   ├── data_quality.py     # Data freshness + validation helpers
│   │   ├── service_controller.py # Shell/script orchestration (Telegram remote control)
│   │   ├── sparkline.py        # Compact sparkline rendering helpers
│   │   ├── volume_pressure.py  # Signed-volume pressure computations
│   │   ├── paths.py            # Timestamp/path helpers
│   │   └── vwap.py             # VWAP computation
│   └── config/                 # Configuration (3 files)
│       ├── settings.py          # Settings management
│       ├── config_loader.py     # Service config loader
│       └── config_file.py       # YAML loader + env substitution + validation warnings
│
├── config/                     # Configuration files
│   └── config.yaml             # Main configuration
│
├── scripts/                     # Utility scripts (organized by category)
│   ├── lifecycle/                  # Service lifecycle scripts
│   │   ├── agent.sh                     # Start/stop/restart/status (market-aware)
│   │   └── check_agent_status.sh        # Check status (market-aware)
│   ├── gateway/                    # IBKR Gateway scripts
│   │   └── gateway.sh                  # Gateway CLI (start/stop/status/2FA/VNC/setup)
│   ├── telegram/                   # Telegram command-handler scripts
│   │   ├── start_command_handler.sh     # Start handler (foreground/background)
│   │   ├── check_command_handler.sh     # Check handler status
│   │   └── set_bot_commands.py          # Push BotFather commands via API
│   ├── monitoring/                 # Monitoring scripts (external safety nets)
│   │   ├── watchdog_agent.py            # State freshness watchdog (cron/systemd timer)
│   │   └── serve_agent_status.py        # Localhost /healthz + /metrics sidecar (optional)
│   ├── maintenance/                # Maintenance/hygiene scripts
│   │   └── purge_runtime_artifacts.sh   # Safe cleanup (requires --yes)
│   ├── backtesting/               # Backtesting scripts
│   │   └── backtest_cli.py            # Canonical backtest CLI (signal + full modes)
│   └── testing/                    # Testing and validation scripts
│       ├── test_all.py                  # Unified test runner
│       ├── validate_strategy.py         # Comprehensive validation
│       ├── run_tests.sh                 # Run pytest unit tests
│       ├── smoke_test_ibkr.py           # IBKR smoke test
│       ├── check_no_secrets.py          # Secret detection guardrail
│       ├── test_data_quality.py         # Data quality validation
│       └── test_e2e_simulation.py       # End-to-end simulation
│
├── tests/                       # Pytest suite (fast, assertion-driven)
│   ├── mock_data_provider.py   # Synthetic OHLCV for tests (no external deps)
│   ├── test_config_loader.py   # Config loading/merging tests
│   ├── test_config_wiring.py   # Config wiring to service/data fetcher
│   ├── test_market_hours.py    # CME market hours logic
│   ├── test_strategy_session_hours.py  # Strategy session window tests
│   ├── test_mtf_cache.py       # Multi-timeframe cache behavior
│   ├── test_edge_cases.py      # Data fetcher + short-run service lifecycle
│   ├── test_error_recovery.py  # Circuit breaker / pause behavior
│   ├── test_telegram_authorization.py  # Telegram auth guards
│   └── test_telegram_message_limits.py # Telegram message sizing
│
├── docs/                        # Documentation
│   ├── PROJECT_SUMMARY.md      # This file (single source of truth)
│   ├── NQ_AGENT_GUIDE.md       # Operational guide (how to run and operate)
│   ├── TESTING_GUIDE.md        # Unified testing guide (all testing procedures)
│   ├── GATEWAY.md              # IBKR Gateway setup
│   └── MOCK_DATA_WARNING.md    # Mock data testing notes
│
├── data/                        # Data storage
│   ├── agent_state/            # Per-market service state (see State Schema below)
│   │   ├── state.json          # Current state (authoritative for /status + watchdog)
│   │   ├── signals.jsonl       # Signal history (JSONL, all signals)
│   │   └── exports/            # Performance exports (7d metrics, signals snapshots)
│   ├── buffers/                 # Data buffers (pickle files)
│   └── historical/              # Historical data (parquet)
│
├── logs/                        # PID + handler logs (runtime artifacts; gitignored)
│   └── agent_NQ.pid            # Process ID (per market: agent_<MARKET>.pid)
│
├── ibkr/                        # IBKR Gateway files
│   ├── ibc/                    # IBC (Interactive Brokers Controller)
│   └── Jts/                    # Gateway installation
│
├── pyproject.toml               # Project metadata & dependencies
├── pytest.ini                   # Pytest configuration
└── README.md                    # Quick start guide
```

### Module Boundaries

The `src/pearlalgo/` package follows a layered architecture with explicit dependency rules.
These boundaries prevent accidental coupling, keep strategies portable, and make the codebase easier to reason about.

#### Dependency Matrix

| Source Layer     | May Import                                      | Must NOT Import              |
|------------------|-------------------------------------------------|------------------------------|
| `utils`          | `pearlalgo.utils.*`, stdlib, third-party        | `config`, `data_providers`, `strategies`, `nq_agent` |
| `config`         | `pearlalgo.config.*`, `pearlalgo.utils.*`       | `data_providers`, `strategies`, `nq_agent` |
| `data_providers` | `pearlalgo.data_providers.*`, `config`, `utils` | `strategies`, `nq_agent`     |
| `strategies`     | `pearlalgo.strategies.*`, `config`, `utils`, `learning` | `data_providers`, `nq_agent` |
| `execution`      | `pearlalgo.execution.*`, `config`, `utils`      | `data_providers`, `strategies`, `learning`, `nq_agent` |
| `learning`       | `pearlalgo.learning.*`, `config`, `utils`       | `data_providers`, `strategies`, `execution`, `nq_agent` |
| `nq_agent`       | Any internal layer (orchestration layer)        | —                            |

#### Rationale

- **`utils`** is the lowest layer: pure helpers with no domain awareness.
- **`config`** provides settings and loaders; it may use utils for logging but must stay agnostic to higher layers.
- **`data_providers`** abstract market data sources; they must not know about strategies or the agent orchestration.
- **`strategies`** contain trading logic; they must remain independent of specific data providers and the orchestrating agent so they can be tested in isolation or reused elsewhere. Strategies may optionally import from `learning` for ML signal filtering (guarded with try/except for graceful degradation).
- **`execution`** contains ATS execution logic (IBKR bracket orders, safety guards); independent of strategy and agent orchestration.
- **`learning`** contains adaptive policy logic (Thompson sampling bandit); independent of strategy and agent orchestration.
- **`nq_agent`** is the top-level orchestration layer that wires everything together.

#### Enforcement

Boundary violations are detected by `scripts/testing/check_architecture_boundaries.py` (AST-based, no external deps).
Run it via the unified test runner:

```bash
# Warn-only (default in test_all.py)
python3 scripts/testing/test_all.py arch

# Strict enforcement (exit 1 on violations)
PEARLALGO_ARCH_ENFORCE=1 python3 scripts/testing/test_all.py arch
```

### State Schema (`data/agent_state/<MARKET>/state.json`)

The `state.json` file is the authoritative source of truth for the agent's operational state.
It is read by the Telegram command handler (`/status`), the external watchdog, and the optional status server.

**Stable fields** (safe for external tools to depend on):

| Field | Type | Description |
|-------|------|-------------|
| `running` | bool | Agent process is actively running |
| `paused` | bool | Agent paused by circuit breaker |
| `pause_reason` | string\|null | Reason for pause (e.g., "consecutive_errors", "connection_failures") |
| `start_time` | ISO string | When the agent started |
| `last_updated` | ISO string | When state.json was last written |
| `last_successful_cycle` | ISO string\|null | When the last successful scan cycle completed |
| `cycle_count` | int | Total scan cycles since first start |
| `signal_count` | int | Total signals generated |
| `signals_sent` | int | Total signals successfully sent to Telegram |
| `signals_send_failures` | int | Total Telegram send failures |
| `error_count` | int | Total errors encountered |
| `consecutive_errors` | int | Current consecutive error count (resets on success) |
| `connection_failures` | int | Current IB Gateway connection failure count |
| `data_fetch_errors` | int | Current data fetch error count |
| `buffer_size` | int | Current number of bars in data buffer |
| `buffer_size_target` | int | Target buffer size from config |
| `data_fresh` | bool\|null | Whether market data is fresh (within threshold) |
| `latest_bar_timestamp` | ISO string\|null | Timestamp of latest bar |
| `latest_bar_age_minutes` | float\|null | Age of latest bar in minutes |
| `futures_market_open` | bool\|null | CME futures market is open |
| `strategy_session_open` | bool\|null | Strategy trading session is open |
| `data_stale_threshold_minutes` | float | Threshold for stale data alerts (from config) |
| `connection_timeout_minutes` | float | Connection timeout threshold (from config) |
| `run_id` | string\|null | Unique ID for this process run (for log correlation) |
| `version` | string\|null | Agent version |

**Session-scoped fields** (reset each agent start):

| Field | Type | Description |
|-------|------|-------------|
| `cycle_count_session` | int\|null | Cycles since this agent start |
| `signal_count_session` | int\|null | Signals since this agent start |
| `signals_sent_session` | int\|null | Signals sent since this agent start |
| `signals_send_failures_session` | int\|null | Send failures since this agent start |

**Nested fields**:
- `config.symbol`, `config.timeframe`, `config.scan_interval` - Trading config
- `cadence_metrics.*` - Cycle timing metrics (duration, percentiles, missed cycles)
- `latest_bar.*` - Latest bar OHLCV data (for order book transparency)
  - `latest_bar._data_level` - Data source indicator: `"level1"` (live real-time), `"historical"` (delayed fallback), `"error"`, or `"unknown"`
  - `latest_bar._data_source` - Internal data source tracking: `"real-time"`, `"historical"`, `"historical_fallback"`, `"provider"`, `"fallback"`, `"unknown"`
- `buy_sell_pressure`, `buy_sell_pressure_raw` - Volume pressure indicators

---

## Configuration

### Environment Variables

Create `.env` file in project root:

```bash
# IBKR Connection
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Data Provider
PEARLALGO_DATA_PROVIDER=ibkr
```

### Configuration File (`config/config.yaml`)

```yaml
# Trading Symbol (Prop Firm Style)
symbol: "MNQ"  # Mini NQ (1/10th size of NQ, better for prop firms)

# Timeframe
timeframe: "1m"  # 1-minute decision stream (5m/15m for MTF context)

# Scan Interval (seconds) - base interval; adaptive cadence overrides dynamically
scan_interval: 30  # Base scan interval (adaptive cadence uses 5s active, 30s idle, 300s closed)

# Telegram Notifications
telegram:
  enabled: true
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"

# Risk Management (Prop Firm Style)
risk:
  max_risk_per_trade: 0.015     # Max risk per trade (fraction of account; configurable)
  max_drawdown: 0.10            # 10% account drawdown limit (prop firm typical)
  stop_loss_atr_multiplier: 4.0 # ATR-based stop shaping (additional adaptive stops may apply)
  take_profit_risk_reward: 1.5  # Target R:R for TP calculation (filter uses signals.min_risk_reward)
  min_position_size: 5          # Minimum contracts per trade
  max_position_size: 50         # Maximum contracts per trade (additional per-signal caps may apply)

# Signal Filtering (actual R:R filter threshold)
signals:
  min_confidence: 0.55          # Minimum confidence to pass filter
  min_risk_reward: 1.3          # Minimum R:R to pass filter
```

### Configuration Precedence

Configuration is resolved using the following precedence rules:

1. **Environment variables** (from `.env` or process env) are the primary source for:
   - IBKR connection (`IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`, `IBKR_DATA_CLIENT_ID`)
   - Telegram bot token and chat ID (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
   - Provider selection (`PEARLALGO_DATA_PROVIDER`)
2. **`config/config.yaml`** provides the **default behavior** for the MNQ agent:
   - Trading symbol, timeframe, scan interval
   - Risk/position sizing and prop‑firm assumptions
   - Service intervals, data buffers, and signal thresholds
3. **Code defaults** in:
   - `src/pearlalgo/strategies/nq_intraday/config.py` (`NQIntradayConfig`)
   - `pearlalgo.config.config_loader.load_service_config`
   - `pearlalgo.config.settings.Settings`

   act as a safety net when a key is missing from `config.yaml`. They are kept in sync with the example
   snippets above but should be treated as **fallbacks**, not the primary place to change behavior.

In practice:
- **Change behavior** (symbol, risk, scan intervals, thresholds) by editing `config/config.yaml`.
- **Change infrastructure or secrets** (IBKR, Telegram, provider selection) by editing `.env`.
- The agent entrypoint (`pearlalgo.nq_agent.main`) reads from the environment and uses `config/config.yaml`
  for service/strategy defaults (and Telegram enablement when env vars are missing).
- The Telegram command handler (`pearlalgo.nq_agent.telegram_command_handler`) requires Telegram credentials
  in `.env` / environment variables.

---

## Key Features

### 1. Automated Trading Signal Generation (Prop Firm Optimized)

- **Real-time Analysis**: Adaptive cadence (5s active session, 30s idle, 300s market closed)
- **Technical Indicators**: RSI, MACD, ATR, EMA, Bollinger Bands, VWAP, Volume Profile
- **Pattern Detection**: Unified strategy (EMA crossover + VWAP bias + RSI confirmation + ATR stops)
- **Confidence Filtering**: Configurable via `signals.min_confidence`
- **Risk/Reward Validation**: Configurable via `signals.min_risk_reward`
- **Position Sizing**: Configurable via `risk.*` and `strategy.*` (dynamic sizing supported)
- **Session Filters**: Configurable lunch lull avoidance (disabled by default)

### 2. Mobile-Optimized Telegram Notifications

- **Signal Notifications**: Entry, stop-loss, take-profit, R:R ratio
- **Dashboard Updates**: Hourly (configurable) with performance metrics
- **Data Quality Alerts**: Stale data, buffer issues, fetch failures
- **Performance Summaries**: Daily/weekly statistics
- **Service Notifications**: Startup, shutdown, recovery, circuit breaker

### 3. Robust Error Handling

- **Circuit Breaker**: Pauses service after 10 consecutive errors
- **Connection Monitoring**: Detects IB Gateway connection failures
- **Connection Alerts**: Sends Telegram alerts when gateway is down
- **Automatic Recovery**: Resumes after errors are resolved
- **Data Fetch Error Handling**: Retries with exponential backoff
- **Connection Management**: Automatic reconnection to IB Gateway
- **Error Tracking**: Comprehensive error logging and notifications

### 4. State Management

- **Persistent State**: Service state saved to JSON
- **Signal History**: All signals saved to JSONL file
- **Performance Tracking**: Metrics stored in JSON
- **State Recovery**: Loads state on startup

### 5. Performance Tracking

- **Signal Lifecycle**: Tracks generation → entry → exit
- **Win/Loss Tracking**: Calculates win rate
- **P&L Calculation**: Tracks profit and loss
- **Hold Time**: Average time in position
- **7-Day Rolling Metrics**: Recent performance summary

### 6. Health Monitoring

- **Component Health**: Monitors all service components
- **Data Provider Health**: Connection status, data freshness
- **Telegram Health**: Connectivity validation
- **File System Health**: State directory checks

### 7. Testing Infrastructure

- **Mock Data Provider**: Test without live market data
- **Unit Tests**: Individual component testing
- **Integration Tests**: End-to-end service testing
- **Test Scripts**: Easy testing via command line

---

## Testing Strategy

### Test Types

1. **Unit Tests** (`tests/`):
   - Individual component testing
   - Mock dependencies
   - Fast execution

2. **Integration Tests**:
   - Full service with mock data
   - Signal generation testing
   - Telegram notification testing

3. **Testing & Validation Scripts** (`scripts/testing/`):
   - `test_all.py`: Unified runner (telegram / signals / short-run service / arch)
   - `validate_strategy.py`: Strategy validation helper
   - `smoke_test_ibkr.py`: IBKR connectivity + entitlement smoke test
   - `test_data_quality.py`, `test_e2e_simulation.py`, `test_signal_starvation_fixes.py`: Targeted validations

### Running Tests

**Quick Test (All Tests)**:
```bash
# Unified test runner (recommended)
python3 scripts/testing/test_all.py

# Unit tests (pytest)
./scripts/testing/run_tests.sh
```

**Individual Test Modes**:
```bash
# Test notifications only
python3 scripts/testing/test_all.py telegram

# Test signal generation only
python3 scripts/testing/test_all.py signals

# Test full service only
python3 scripts/testing/test_all.py service
```

**Unit Tests**:
```bash
pytest tests/
```

### Mock Data Provider

The `tests/mock_data_provider.py` provides:
- Realistic OHLCV data generation (MNQ price range: ~17,500)
- Configurable volatility and trend
- No external dependencies
- Fast and reliable testing
- **Note**: Uses synthetic data - prices are NOT real market data

---

## Deployment & Operations

### Prerequisites

1. **IBKR Account**: Active Interactive Brokers account
2. **IBKR Gateway**: Installed and configured (see `docs/GATEWAY.md`)
3. **Python 3.12+**: Installed on system
4. **Telegram Bot**: Created and configured (bot token and chat ID)

### Installation

```bash
# 1. Clone repository
cd /path/to/pearlalgo-dev-ai-agents

# 2. Install dependencies
pip install -e .

# 3. Configure .env file
# Add IBKR_HOST, IBKR_PORT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 4. Start IBKR Gateway
./scripts/gateway/gateway.sh start

# 5. Verify Gateway
./scripts/gateway/gateway.sh status
```

### Running the Service

**Start Service (Foreground - default)**:
```bash
./scripts/lifecycle/agent.sh start --market NQ
```

**Start Service (Background)**:
```bash
./scripts/lifecycle/agent.sh start --market NQ --background
```

**Stop Service**:
```bash
./scripts/lifecycle/agent.sh stop --market NQ
```

**Check Status**:
```bash
./scripts/lifecycle/check_agent_status.sh --market NQ
```

**View Logs**:
- Foreground mode: logs are printed in your terminal.
- systemd: `journalctl -u pearlalgo-mnq.service -f`
- Docker: `docker logs -f <container>`

### Example `systemd` Unit (VPS / server)

To run the agent as a managed service on a Linux VPS, you can use a simple `systemd` unit:

```ini
[Unit]
Description=PearlAlgo MNQ Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/pearlalgo-dev-ai-agents
Environment=\"PYTHONUNBUFFERED=1\"
EnvironmentFile=/path/to/pearlalgo-dev-ai-agents/.env
ExecStart=/path/to/pearlalgo-dev-ai-agents/.venv/bin/python -m pearlalgo.nq_agent.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pearlalgo-mnq.service
sudo systemctl status pearlalgo-mnq.service
```

### Docker Deployment (optional)

A minimal `Dockerfile` is provided in the project root. To build and run:

```bash
cd /path/to/pearlalgo-dev-ai-agents
docker build -t pearlalgo-mnq .

# IBKR Gateway must be reachable from inside the container (host network or a separate container)
docker run --rm -it \\
  --env-file .env \\
  --network host \\
  pearlalgo-mnq
```

### Service Management

- **PID File**: `logs/agent_<MARKET>.pid` (for process management)
- **Logs**: stdout/stderr (systemd journal, Docker logs) and Telegram notifications
- **State Directory**: `data/agent_state/<MARKET>/` (persistent state)

### Daily Operations

**Morning Checklist**:
1. Verify IBKR Gateway is running: `./scripts/gateway/gateway.sh status`
2. Check service status: `./scripts/lifecycle/check_agent_status.sh --market NQ`
3. Review overnight errors/status (Telegram and/or `journalctl -u pearlalgo-mnq.service --since yesterday`)

**During Trading**:
- Monitor Telegram for signals
- Check performance via Telegram notifications
- Watch for error notifications

**End of Day**:
- Review daily performance via Telegram summary
- Check signal count and win rate
- Review any error messages

---

## Monitoring & Alerts

### Automatic Monitoring

- **Dashboard Updates**: Hourly (configurable)
- **Data Quality Alerts**: When issues detected
- **Error Alerts**: Circuit breaker, consecutive errors
- **Recovery Notifications**: When service recovers

### Manual Monitoring

**Check Service Status**:
```bash
./scripts/lifecycle/check_agent_status.sh --market NQ
ps aux | grep "pearlalgo.nq_agent.main"
```

**View State**:
```bash
cat data/agent_state/NQ/state.json | jq
```

**View Recent Signals**:
```bash
tail -20 data/agent_state/NQ/signals.jsonl | jq
```

**View Performance**:
```bash
# Performance metrics are computed on-demand and exported to data/agent_state/<MARKET>/exports/
# Use /performance command in Telegram, or:
ls -la data/agent_state/NQ/exports/
```

### External Watchdog

The watchdog script validates state freshness from outside the agent process:

```bash
# Check health (exit codes: 0=OK, 1=Warning, 2=Critical, 3=Error)
python3 scripts/monitoring/watchdog_agent.py --market NQ --verbose

# Send alerts to Telegram on issues
python3 scripts/monitoring/watchdog_agent.py --market NQ --telegram
```

Add to cron for continuous monitoring (every 5 minutes):
```cron
*/5 * * * * cd /path/to/pearlalgo-dev-ai-agents && python3 scripts/monitoring/watchdog_agent.py --market NQ --telegram
```

### Status Server (Optional)

A lightweight localhost HTTP server for standard tooling integration:

```bash
# Start the status server (default port 9100)
python3 scripts/monitoring/serve_agent_status.py --market NQ

# Custom port
python3 scripts/monitoring/serve_agent_status.py --market NQ --port 9200
```

**Endpoints:**
- `GET /` - Simple status page (HTML)
- `GET /healthz` - Health check (JSON, 200 OK or 503 Unhealthy)
- `GET /metrics` - Prometheus text exposition format

**Example usage:**
```bash
# Health check
curl http://localhost:9100/healthz

# Prometheus scrape
curl http://localhost:9100/metrics

# systemd health check
ExecStartPost=/bin/sh -c 'until curl -sf http://localhost:9100/healthz; do sleep 1; done'
```

**Metrics exposed:**
- `pearlalgo_agent_running` - Agent process running (1/0)
- `pearlalgo_agent_paused` - Agent paused by circuit breaker (1/0)
- `pearlalgo_state_age_seconds` - Seconds since state.json update
- `pearlalgo_cycle_age_seconds` - Seconds since last successful cycle
- `pearlalgo_data_fresh` - Market data is fresh (1/0)
- `pearlalgo_signals_sent_total` - Total signals sent to Telegram
- `pearlalgo_errors_total` - Total errors encountered
- `pearlalgo_consecutive_errors` - Current consecutive error count

### Alert Types

1. **Signal Notifications**: New trading signals
2. **Heartbeat**: Service is alive
3. **Status Update**: Performance metrics
4. **Data Quality Alert**: Stale data, buffer issues
5. **Circuit Breaker Alert**: Too many errors, service paused
6. **Recovery Notification**: Service recovered from errors
7. **Startup/Shutdown**: Service lifecycle events

---

## Roadmap & Future Enhancements

### Ranked Opportunity Clusters

The following opportunity clusters are ranked by leverage and risk, updated as of 2025-12-30.
Use `docs/prompts/promptbook_engineering.md` for structured improvement iterations.

#### 1. Operational Risk (Highest Leverage)

**Why first**: IBKR data quality impacts correctness, reliability, observability, and operator trust.

- **IBKR connectivity + entitlement clarity**: Reduce "silent degradation" to historical fallback; make data-level visible in logs and state.
- **Market-open truth source**: Single implementation reused across agent + IBKR executor (see `utils/market_hours.py`).
- **Error 354 handling**: Clear guidance in `docs/MARKET_DATA_SUBSCRIPTION.md`; executor messaging should not hard-code entitlement claims.

#### 2. Correctness: Market-Hours + Holiday/Early-Close Coverage

- Move beyond fixed-date holidays; add observance rules (weekend → Monday).
- Enable configurable overrides via `config.yaml` (`market_hours.enable_config_overrides`).
- Handle variable holidays: Good Friday, Memorial Day, Labor Day, Thanksgiving.

#### 3. Observability & Ops Maturity

- Operator-focused dashboards: data-level, freshness buckets, cache hit rates.
- "Quiet reasons" in dashboard (why no signals: session closed, no opportunity, stale data).
- Restart cause tracking and correlation with `run_id`.

#### 4. Risk Management & Circuit Breakers

- More explicit pause/resume semantics ("degradation mode" vs "hard stop").
- Stronger containment for partial failures (data vs execution vs notifications).
- Clearer recovery criteria before auto-resume.

#### 5. Signal Quality & Correctness

- Calibration workflow: confidence distribution analysis, false-positive tracking.
- Duplicate suppression tuning (price threshold, time window).
- Regime gating (trending vs ranging market detection).

#### 6. Security Hardening

- Telegram auth tightening (command authorization, rate limiting).
- Secrets hygiene audit (no credentials in logs, state files, or error messages).
- Dependency pinning policy and supply-chain review.

#### 7. DevEx & Test Velocity

- Faster test tiers (unit < 1s, integration < 10s, smoke < 30s).
- Deterministic fixtures (no network calls in unit tests).
- Clearer local run workflows and CI ergonomics.

---

### Detailed Enhancement Backlog

#### High Priority

1. **Market Hours Improvements**:
   - Market holiday calendar + early closes/observance rules (DST is already handled; calendar coverage is the gap)
   - Pre-market/post-market scanning option

2. **Signal Quality Enhancements**:
   - Fine-tune confidence thresholds based on backtesting
   - Additional confirmation signals
   - Multi-timeframe confirmation
   - Trend filter (avoid trading against major trend)

3. **Telegram Enhancements**:
   - Signal charts/graphs (optional)
   - Signal history command
   - Performance charts

4. **Data Quality**:
   - Enhanced data validation
   - Gap detection and handling
   - Better stale data detection
   - Data source health monitoring

#### Medium Priority

5. **Performance Tracking**:
   - Detailed analytics dashboard
   - Win rate by signal type
   - Risk-adjusted returns (Sharpe ratio)
   - Average hold times by signal type

6. **Strategy Refinements**:
   - Advanced indicators (Volume Profile, Order Flow)
   - Position sizing based on volatility
   - Trailing stop loss logic
   - Multiple timeframe analysis

7. **Monitoring & Alerts**:
   - Health check endpoint (REST API)
   - Email alerts for critical errors
   - Daily performance summary emails
   - Service restart notifications

#### Low Priority / Future

8. **Backtesting Integration**:
   - Historical backtesting framework
   - Strategy optimization
   - Walk-forward analysis

9. **Advanced Features**:
   - Multi-symbol support
   - Portfolio-level risk management
   - Correlation analysis
   - Machine learning signal filters

10. **Execution Integration**:
    - Automatic order execution (via IBKR)
    - Position management
    - Order tracking and fills

---

## Known Limitations

### Current Limitations

1. **Market Data Subscription**:
   - Level 1 real-time data is preferred when available
   - Error 354 ("not subscribed") may occur if:
     - Market is closed (expected behavior during non-trading hours)
     - Subscription not active/paid, or API acknowledgment not signed
   - **Fallback behavior**: When Level 1 fails, system uses historical bars (degradation mode — data may be stale)
   - **Solution**: Ensure CME Real-Time (Level 1) subscription is active + acknowledged for API
   - **Guide**: See [MARKET_DATA_SUBSCRIPTION.md](MARKET_DATA_SUBSCRIPTION.md) for detailed instructions
   - **Metadata**: Data source is tracked via `_data_level` field in latest_bar (`level1` vs `historical`)

2. **Signal Generation**:
   - Only generates signals during the configured strategy session window (default 18:00–16:10 ET, NY time)
   - **Status**: Working as designed
   - Signals require specific market conditions

3. **Single Symbol**:
   - Currently focused on MNQ futures (prop firm optimized)
   - **Future**: Multi-symbol support planned

4. **Automated Execution (ATS)** - Disabled by Default:
   - ATS execution and learning layers are **implemented and wired** in `src/pearlalgo/execution/` and `src/pearlalgo/learning/`
   - **Default**: `execution.enabled: false` and `learning.mode: shadow` (observe-only)
   - When enabled, supports IBKR bracket orders (entry + stop + take profit)
   - Adaptive bandit policy learns from signal type outcomes
   - See `docs/ATS_ROLLOUT_GUIDE.md` for safe rollout procedures
   - Telegram commands: `/arm`, `/disarm`, `/kill`, `/positions`, `/policy`

### Technical Debt

1. **Market Calendar Coverage**: Holiday/early-close coverage is intentionally incomplete by default; optional overrides exist (disabled by default).
2. **Error Recovery**: Basic recovery (could be more sophisticated)
3. **Data Validation**: Good baseline validation, but edge-case hardening is ongoing (see testing notes)
4. **Volume Profile Robustness**: Fixed — `inf` values in volume profile calculations are now sanitized (see `test_signal_generation_edge_cases.py`)
5. **Testing Coverage**: Good coverage, but could be expanded

---

## Quick Reference

### Essential Commands

```bash
# Start IBKR Gateway
./scripts/gateway/gateway.sh start

# Check Gateway Status
./scripts/gateway/gateway.sh status

# Setup IBKR Gateway (first time)
./scripts/gateway/gateway.sh setup

# Start MNQ Agent Service
./scripts/lifecycle/agent.sh start --market NQ

# Stop MNQ Agent Service
./scripts/lifecycle/agent.sh stop --market NQ

# Check Service Status
./scripts/lifecycle/check_agent_status.sh --market NQ

# Run Tests
python3 scripts/testing/test_all.py

# Validate Strategy
python3 scripts/testing/validate_strategy.py

# View Logs (foreground: printed in terminal; systemd: journal)
journalctl -u pearlalgo-mnq.service -f

# Run All Unit Tests
./scripts/testing/run_tests.sh
```

### File Locations

- **Logs**: stdout/stderr (systemd journal, Docker logs) + `logs/telegram_handler.log` (handler background mode)
- **State**: `data/agent_state/<MARKET>/state.json`
- **Signals**: `data/agent_state/<MARKET>/signals.jsonl`
- **Performance exports**: `data/agent_state/<MARKET>/exports/` (7d metrics, signals snapshots)
- **Config**: `config/config.yaml`
- **PID**: `logs/agent_<MARKET>.pid`

### Documentation

- **Complete Guide**: `docs/NQ_AGENT_GUIDE.md` (includes prop firm configuration)
- **Testing Guide**: `docs/TESTING_GUIDE.md`
- **Gateway Setup**: `docs/GATEWAY.md`
- **Project Summary**: `docs/PROJECT_SUMMARY.md` (this file)

---

## Prop Firm Trading Configuration

### MNQ vs NQ

- **MNQ (Mini NQ)**: $2 per point, 1/10th size of NQ
- **NQ**: $20 per point
- **Benefits**: Lower margin, configurable position sizing, prop firm friendly

### Position Sizing

- **Range**: 5-15 MNQ contracts per trade
- **Default**: 10 contracts
- **Risk Calculation**: Stop Loss Points × $2 (MNQ tick value) × Contracts

### Risk Parameters

- **Max Risk/Trade**: 1% of account (prop firm conservative)
- **Max Drawdown**: 10% daily (prop firm typical)
- **Stop Loss**: 1.5x ATR (tighter for scalping)
- **Take Profit**: Target uses 1.5:1 R:R; filter minimum is 1.2:1
- **Scan Interval**: Adaptive cadence (5s active, 30s idle, 300s market closed)

### Example Trade

```
Entry: $17,500.00
Stop: $17,496.25 (3.75 points)
Target: $17,505.50 (5.5 points)
Position: 10 MNQ contracts

Risk: 3.75 × $2 × 10 = $75 (0.15% of $50k account)
Reward: 5.5 × $2 × 10 = $110
R:R: 1.47:1
```

## Conclusion

The **PearlAlgo MNQ Trading Agent** is a production-ready, automated trading system optimized for **prop firm style trading** that provides:

- ✅ **Reliable Operation**: 24/7 service with robust error handling and connection monitoring
- ✅ **Prop Firm Optimized**: MNQ contracts, configurable position sizing/risk, quick scalps
- ✅ **Intelligent Signals**: Technical analysis-based signal generation with multi-timeframe confirmation
- ✅ **Mobile-Friendly Notifications**: Rich Telegram notifications with position sizing and risk calculations
- ✅ **Performance Tracking**: Comprehensive metrics and tracking
- ✅ **Easy Testing**: Mock data providers for testing without live data
- ✅ **Extensible Architecture**: Modular design for easy extension

The system is ready for production use and optimized for prop firm trading with MNQ futures.

---

**For detailed guides, see:**
- `docs/NQ_AGENT_GUIDE.md` - Operational guide (how to run and operate)
- `docs/TESTING_GUIDE.md` - Complete testing guide (all testing procedures)
- `docs/GATEWAY.md` - IBKR Gateway setup
- `docs/MARKET_DATA_SUBSCRIPTION.md` - How to get live market data (fix Error 354)

**Last Updated:** 2025-12-31  
**Current Configuration:** MNQ (Mini NQ) - Prop Firm Style Trading









