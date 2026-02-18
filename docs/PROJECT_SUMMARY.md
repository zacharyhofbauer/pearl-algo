# Project Summary - PearlAlgo MNQ Trading Agent

**Version:** 0.2.4 (aligns with pyproject.toml)  
**Last Updated:** 2026-02-13 (Single-account consolidation, config consolidation, notifications module)  
**Status:** Production-Ready  
**Trading Style:** Prop Firm - Intraday Swings & Quick Scalps  
**Active account:** Tradovate Paper only; IBKR is data-only (execution inactive).

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
- ✅ **Prop Firm Optimized**: MNQ futures with explicit risk caps and guardrails (see `config/base.yaml` + `config/accounts/tradovate_paper.yaml`)
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
- **Trading session (StrategySessionOpen)**: Prop-firm window 18:00 - 15:45 ET (NY time). Positions must be flat by 15:45.
- **Futures market window (FuturesMarketOpen)**: CME ETH Sun 18:00 ET → Fri 17:00 ET (Mon–Thu 17:00–18:00 ET maintenance break)
- **Market**: CME Group futures exchange
- **Trading Style**: Prop-firm intraday swings and scalps; sizing/risk thresholds are configured in `config/base.yaml` and `config/accounts/tradovate_paper.yaml`

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
   - Historical data cached in buffer (last 300 bars)

3. **Signal Flow**:
   - Strategy → Signal Generator → State Manager → Performance Tracker → Telegram

---

## Core Components

### 1. Market Agent Service (`src/pearlalgo/market_agent/`)

**Main Service** (`service.py`, inherits `ServiceNotificationsMixin`):
- 24/7 service loop with adaptive cadence (5s active, 30s idle, 300s market closed; base scan_interval configurable)
- Circuit breaker (pauses after 10 consecutive errors)
- Connection failure detection and alerts
- Automatic recovery and error handling
- Periodic status updates and heartbeats
- Data quality monitoring
- IB Gateway connection status tracking
- Delegates virtual trade exit processing to `VirtualTradeManager`
- Inherits dashboard/chart methods from `ServiceNotificationsMixin`

**Virtual Trade Manager** (`virtual_trade_manager.py`):
- Processes virtual trade exits by scanning OHLCV bars for TP/SL hits
- Extracted from `service.py` for testability (~450 lines)
- Uses vectorized pandas operations for O(signals) performance
- Records outcomes across all tracking systems (performance, circuit breaker, challenge, learning policies)
- Dependencies injected via constructor

**Data Fetcher** (`data_fetcher.py`):
- Fetches historical and latest bar data
- Maintains data buffer (last 300 bars)
- Handles data provider abstraction
- Error handling and retry logic

**State Manager** (`state_manager.py`):
- Persists service state to JSON
- Saves signals to JSONL file with TTL-cached reads (5s) and tail-read optimization
- Incremental signal count tracking (O(1) vs full-file scan)
- Loads state on startup
- State directory: `data/agent_state/<MARKET>/`
- Provides `async_get_recent_signals()` wrapper for async callers

**State Builder** (`state_builder.py`):
- Constructs structured state snapshots from service components
- Assembles cadence metrics, data quality, circuit breaker status, and session info
- Used by `service.py` to build the `state.json` payload each save cycle

**State Reader** (`state_reader.py`):
- Thread-safe reads of agent state files using fcntl shared locks
- Coordinates with state_manager's exclusive write locks to prevent torn reads
- Used by `api_server.py` and other read-only consumers
- Provides `async_read_state()` / `async_read_signals()` wrappers

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

### 2. Trading Strategy (`src/pearlalgo/trading_bots/pearl_bot_auto.py`)

**PearlBot Auto** (`pearl_bot_auto.py`):
- Single-file, self-contained strategy derived from Pine Script indicators
- Converted from 8 Pine Script files in `resources/pinescript/pearlbot/`:
  - EMA_Crossover.pine
  - VWAP_AA.pine
  - Volume.pine
  - Trading Sessions.pine
  - S&R Power (ChartPrime).pine
  - TBT (ChartPrime).pine
  - Supply & Demand Visible Range (Lux).pine
  - SpacemanBTC Key Level V13.1.pine

**Key Features**:
- **Virtual Broker Mode**: Only generates signals, no real execution (perfect for testing live without real money)
- **Pure Function Design**: All indicators implemented as pure Python functions (portable to Pine Script/C#)
- **Signal Generation**: `generate_signals()` function processes market data and returns trading signals
- **Configuration**: Global `CONFIG` dictionary holds all strategy parameters
- **Indicators Included**:
  - EMA Crossover (fast/slow)
  - VWAP with standard deviation bands
  - Volume analysis
  - Trading session detection
  - Support & Resistance levels
  - Supply & Demand zones
  - Key level detection

**Entry Point**:
- `generate_signals(df, config, current_time)` - Main signal generation function
- `run_pearlbot(df, config, virtual_broker)` - Full bot execution with virtual broker

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

**State I/O** (`state_io.py`):
- Atomic JSON file writes using temp file + rename pattern
- `atomic_write_json()` for crash-safe state persistence
- `load_json_file()` for consistent JSON reads with encoding handling
- Shared by `market_agent`, `api_server`, and `telegram_command_handler`

**Telegram Alerts** (`telegram_alerts.py`):
- Core Telegram messaging functionality
- Rich formatting helpers (currency, percentage, numbers)
- Mobile-friendly message formatting with character limits (`CHAR_LIMIT_HEADER`, `CHAR_LIMIT_BUTTON`)
- `truncate_for_mobile()` and `format_button_label()` for Telegram-safe output

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

**Symbols**: Symbol definitions are in the strategy configuration (`src/pearlalgo/trading_bots/pearl_bot_auto.py` CONFIG). The system supports multiple markets (MNQ, ES, GC, etc.) via market-aware configuration.

### 6. Knowledge Module (`src/pearlalgo/knowledge/`)

**Purpose**: RAG (Retrieval-Augmented Generation) system for knowledge indexing and retrieval, used by CLI-based AI assistance.

**Components**:
- **Indexer** (`indexer.py`): Builds and maintains the knowledge index
- **Retriever** (`retriever.py`): Retrieves relevant context for queries
- **Chunker** (`chunker.py`): Splits documents into indexable chunks
- **Embeddings** (`embeddings.py`): Embedding generation (OpenAI/local models)
- **Scanner** (`scanner.py`): File system scanner for indexable content
- **Index Store** (`index_store.py`): FAISS-based vector index persistence
- **Datasets** (`datasets.py`): Dataset export and management
- **Types** (`types.py`): Shared type definitions

**Features**:
- Automatic codebase indexing
- Semantic search via FAISS
- Support for OpenAI embeddings
- Configurable chunk sizes and overlap
- Used by CLI/terminal AI assistance for context-aware suggestions

**Configuration** (in `config.yaml`):
```yaml
knowledge:
  enabled: true
  index_dir: data/knowledge_index
  chunk_max_chars: 2000
  chunk_overlap_chars: 200
```

### 7. Challenge Tracker (`src/pearlalgo/market_agent/challenge_tracker.py`)

**Purpose**: Prop firm challenge simulation and tracking (e.g., 50k challenge).

**Features**:
- Challenge state management (balance, profit target, drawdown limit)
- Pass/fail rule evaluation
- Automatic attempt reset on failure
- Attempt history tracking
- Integration with performance metrics

**Configuration** (in `config.yaml`):
```yaml
challenge:
  enabled: true
  start_balance: 50000.0
  profit_target: 3000.0
  max_drawdown: 2000.0
```

### 8. Trading Circuit Breaker (`src/pearlalgo/market_agent/trading_circuit_breaker.py`)

**Purpose**: Risk management and trade gating based on session performance.

**Features**:
- **Consecutive loss limits**: Pauses trading after N consecutive losses
- **Session drawdown limits**: Stops trading if session drawdown exceeds threshold
- **Direction gating**: Can block long/short based on recent performance
- **Session filters**: Configurable lunch lull avoidance
- **Regime detection**: Avoids trading in unfavorable market conditions
- **Cooldown periods**: Time-based pause after losses

**Configuration** (in `config.yaml`):
```yaml
trading_circuit_breaker:
  enabled: true
  max_consecutive_losses: 5
  max_session_drawdown: 500.0
  max_daily_drawdown: 1000.0
```

### 9. Notification Queue (`src/pearlalgo/market_agent/notification_queue.py`)

**Purpose**: Async notification delivery with priority, tier filtering, and retry logic.

**Features**:
- Priority queue (high/medium/low)
- **Notification tiers**: `NotificationTier.CRITICAL`, `IMPORTANT`, `DEBUG` for severity-based filtering
- **`min_tier` filtering**: Suppress low-priority notifications when desired (e.g., only deliver CRITICAL during quiet hours)
- **Circuit breaker dedup cooldown**: Suppresses duplicate circuit breaker alerts for 5 minutes
- Automatic retry with exponential backoff
- Rate limiting for Telegram API compliance
- Decoupled delivery (non-blocking main loop)
- Failure tracking and alerts

### 10. Storage Module (`src/pearlalgo/storage/`)

**Purpose**: Async SQLite persistence layer.

**Components**:
- **Async SQLite Queue** (`async_sqlite_queue.py`): Background write queue for SQLite operations
  - Priority-based write queue
  - Background worker thread
  - Prevents blocking the main event loop
  - Used by trade database and state persistence

### 11. Additional Utilities

**Pearl Suggestions** (`utils/pearl_suggestions.py`):
- Contextual trading suggestions based on market conditions
- Used by Telegram command handler

**OpenAI Client** (`utils/openai_client.py`):
- OpenAI API integration wrapper
- Used by CLI/terminal AI assistance
- Supports streaming responses

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
Create MarketAgentService
  ↓
Start Service Loop
```

### 2. Main Service Loop (Every 30 seconds for scalping)

```
Service Loop
  ↓
Data Fetcher.fetch_latest_data()
  ↓
  ├─→ Fetch historical data (last 5 hours)
  ├─→ Update buffer (last 300 bars)
  └─→ Get latest bar
  ↓
pearl_bot_auto.generate_signals(df, config)
  ↓
  ├─→ Calculate indicators (EMA, VWAP, Volume, S&R, etc.)
  └─→ Detect signals (crossover, VWAP position, key levels)
  ↓
For each signal:
  ├─→ Performance Tracker.track_signal_generated()
  ├─→ State Manager.save_signal()
  └─→ Telegram Notifier.send_entry_notification()
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
  └─→ Maintains buffer (300 bars)
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
- **pyarrow**: 16.0+ (Parquet state persistence)
- *(Optional)* **Playwright**: Telegram dashboard chart screenshots (`pip install playwright && playwright install chromium`)

### Development Dependencies

- **pytest**: 8.3+ (Testing framework)
- **pytest-asyncio**: 0.21.0+ (Async testing)
- **pytest-cov**: 4.1+ (Coverage reporting)
- **ruff**: 0.6+ (Linting and formatting)
- **mypy**: 1.11+ (Static type checking)
- **pandas-stubs**: 2.0+ (Type stubs for pandas)
- **types-PyYAML**: 6.0+ (Type stubs for PyYAML)
- **types-pytz**: 2024.1+ (Type stubs for pytz)

### External Services

- **IBKR Gateway**: Interactive Brokers Gateway (headless, port 4002)
- **Telegram Bot API**: Cloud-based messaging service

---

## Project Structure

```
PearlAlgoProject/
├── src/pearlalgo/              # Main source code
│   ├── market_agent/           # Market Agent Service (market-agnostic)
│   │   ├── main.py             # Entry point
│   │   ├── service.py          # Main service loop (inherits ServiceNotificationsMixin)
│   │   ├── virtual_trade_manager.py  # Virtual trade exit processing (extracted from service.py)
│   │   ├── service_notifications.py  # Dashboard/chart mixin for MarketAgentService
│   │   ├── data_fetcher.py     # Data fetching logic
│   │   ├── state_manager.py    # State persistence (with signal cache + incremental count)
│   │   ├── state_builder.py    # State snapshot construction (assembles state.json payload)
│   │   ├── state_reader.py     # Thread-safe locked reads (used by api_server)
│   │   ├── performance_tracker.py  # Performance metrics
│   │   ├── telegram_notifier.py    # Telegram notifications
│   │   ├── telegram_command_handler.py  # Interactive bot (inherits 6 mixins)
│   │   ├── telegram_config_commands.py  # Config command mixin
│   │   ├── telegram_status_commands.py  # Status command mixin
│   │   ├── telegram_trade_commands.py   # Trade command mixin
│   │   ├── telegram_performance_commands.py  # Performance/analytics mixin
│   │   ├── telegram_state_queries.py    # State query mixin
│   │   ├── telegram_formatters.py       # Formatting mixin
│   │   ├── live_chart_screenshot.py  # Live chart screenshot export (optional, Telegram)
│   │   ├── health_monitor.py       # Health monitoring
│   │   └── challenge_tracker.py    # Challenge tracking
│   ├── trading_bots/ # Trading Bot Strategies
│   │   └── pearl_bot_auto.py   # Single-file strategy (only bot)
│   ├── execution/              # ATS Execution Layer (disabled by default)
│   │   ├── base.py             # ExecutionAdapter interface, ExecutionConfig
│   │   └── ibkr/               # IBKR execution implementation
│   │       ├── adapter.py      # IBKR bracket order adapter
│   │       └── tasks.py        # Order placement/cancellation tasks
│   ├── learning/               # Adaptive Learning Layer (shadow mode by default)
│   │   ├── bandit_policy.py    # Thompson sampling policy
│   │   ├── policy_state.py     # Policy statistics persistence
│   │   ├── contextual_bandit.py # Contextual bandit scoring
│   │   ├── feature_engineer.py # Feature extraction for ML
│   │   ├── ensemble_scorer.py  # Ensemble scoring logic
│   │   ├── ml_signal_filter.py # ML signal filter (shadow mode)
│   │   └── trade_database.py   # Trade database for learning
│   ├── data_providers/         # Data Providers
│   │   ├── base.py             # Abstract interface
│   │   ├── factory.py          # Provider factory
│   │   ├── ibkr/               # IBKR provider
│   │   │   └── ibkr_provider.py
│   │   └── ibkr_executor.py    # Thread-safe executor
│   ├── utils/                  # Utilities (cross-cutting)
│   │   ├── state_io.py         # Atomic JSON I/O (load_json_file, atomic_write_json)
│   │   ├── telegram_alerts.py  # Telegram core (mobile-friendly formatting)
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
│   └── config/                 # Configuration (7 files: settings, config_loader, config_file, config_schema, config_view, adapters, defaults)
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
│   │   └── (status checks moved to ops/status.sh)
│   ├── gateway/                    # IBKR Gateway scripts
│   │   └── gateway.sh                  # Gateway CLI (start/stop/status/2FA/VNC/setup)
│   ├── telegram/                   # Telegram command-handler scripts
│   │   ├── start_command_handler.sh     # Start handler (foreground/background)
│   │   ├── check_command_handler.sh     # Check handler status
│   │   └── set_bot_commands.py          # Push BotFather commands via API
│   ├── monitoring/                 # Monitoring scripts (external safety nets)
│   │   ├── monitor.py                   # Automated health monitor + Telegram alerts (replaces health_check.py + watchdog_agent.py)
│   │   └── serve_agent_status.py        # Localhost /healthz + /metrics sidecar (optional)
│   ├── maintenance/                # Maintenance/hygiene scripts
│   │   ├── purge_runtime_artifacts.sh   # Safe cleanup (requires --yes)
│   │   └── reset_30d_performance.py     # Reset 30-day performance to specific value
│   ├── backtesting/               # Backtesting scripts
│   │   ├── strategy_selection.py       # Strategy selection exports
│   │   └── train_ml_filter.py          # Offline ML filter training
│   │   # backtest_trading_bot.py and compare_trading_bots.py removed - using pearl_bot_auto only
│   └── testing/                    # Testing and validation scripts
│       ├── test_all.py                  # Unified test runner
│       ├── run_tests.sh                 # Run pytest unit tests
│       ├── check_architecture_boundaries.py  # Module boundary enforcement
│       ├── smoke_test_ibkr.py           # IBKR smoke test
│       ├── smoke_multi_market.py        # Multi-market isolation smoke
│       └── check_no_secrets.py          # Secret detection guardrail
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
│   ├── test_service_pause.py   # Service pause: circuit breaker, connection failures, manual pause/resume
│   ├── test_telegram_authorization.py  # Telegram auth guards
│   └── test_telegram_message_limits.py # Telegram message sizing
│
├── docs/                        # Documentation
│   ├── PROJECT_SUMMARY.md      # This file (single source of truth)
│   ├── MARKET_AGENT_GUIDE.md   # Operational guide (how to run and operate)
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
├── ibkr/                        # Placeholder only; external install via PEARLALGO_IBKR_HOME
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
| `utils`          | `pearlalgo.utils.*`, stdlib, third-party        | `config`, `data_providers`, `trading_bots`, `market_agent` |
| `config`         | `pearlalgo.config.*`, `pearlalgo.utils.*`       | `data_providers`, `trading_bots`, `market_agent` |
| `data_providers` | `pearlalgo.data_providers.*`, `config`, `utils` | `trading_bots`, `market_agent`     |
| `trading_bots`   | `pearlalgo.trading_bots.*`, `config`, `utils`, `learning` | `data_providers`, `market_agent` |
| `execution`      | `pearlalgo.execution.*`, `config`, `utils`      | `data_providers`, `trading_bots`, `learning`, `market_agent` |
| `learning`       | `pearlalgo.learning.*`, `config`, `utils`       | `data_providers`, `trading_bots`, `execution`, `market_agent` |
| `market_agent`   | Any internal layer (orchestration layer)        | —                            |

#### Rationale

- **`utils`** is the lowest layer: pure helpers with no domain awareness.
- **`config`** provides settings and loaders; it may use utils for logging but must stay agnostic to higher layers.
- **`data_providers`** abstract market data sources; they must not know about trading bots or the agent orchestration.
- **`trading_bots`** contain trading logic; they must remain independent of specific data providers and the orchestrating agent so they can be tested in isolation or reused elsewhere. Trading bots may optionally import from `learning` for ML signal filtering (guarded with try/except for graceful degradation).
- **`execution`** contains ATS execution logic (IBKR bracket orders, safety guards); independent of strategy and agent orchestration.
- **`learning`** contains adaptive policy logic (Thompson sampling bandit); independent of strategy and agent orchestration.
- **`market_agent`** is the top-level orchestration layer that wires everything together.

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
2. **Base config + optional overlay**:
   - Base: `config/config.yaml`
   - Optional overlay: `PEARLALGO_CONFIG_PATH` (e.g., `config/markets/nq.yaml`)
   - Overlay values override base values (used by `scripts/lifecycle/agent.sh`)
3. **Code defaults** in:
   - `src/pearlalgo/trading_bots/pearl_bot_auto.py` (`CONFIG` dictionary)
   - `pearlalgo.config.config_loader.load_service_config`
   - `pearlalgo.config.settings.Settings`

   act as a safety net when a key is missing from `config.yaml`. They are kept in sync with the example
   snippets above but should be treated as **fallbacks**, not the primary place to change behavior.

In practice:
- **Change behavior** (symbol, session, thresholds) in `config/config.yaml`, and use `config/markets/<market>.yaml`
  for per-market overrides.
- **Change infrastructure or secrets** (IBKR, Telegram, provider selection) by editing `.env`.
- The agent entrypoint (`pearlalgo.market_agent.main`) reads the resolved config (base + overlay) and maps:
  - `signals.min_confidence` → `pearl_bot_auto.CONFIG.min_confidence`
  - `signals.min_risk_reward` → `pearl_bot_auto.CONFIG.min_risk_reward`
  - `session.start_time/end_time` → `start_hour/start_minute/end_hour/end_minute`
  - `risk.stop_loss_atr_multiplier` → `stop_loss_atr_mult`
  - `risk.take_profit_risk_reward` → `take_profit_atr_mult` (derived: stop_loss_atr_mult × risk_reward)
- The Telegram command handler (`pearlalgo.market_agent.telegram_command_handler`) requires Telegram credentials
  in `.env` / environment variables.
- `TelegramCommandHandler` inherits from 6 mixin classes for code organization:
  `TelegramConfigCommandsMixin`, `TelegramStatusCommandsMixin`, `TelegramTradeCommandsMixin`,
  `TelegramPerformanceCommandsMixin`, `TelegramStateQueriesMixin`, `TelegramFormattersMixin`.

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
   - `check_architecture_boundaries.py`: Module boundary enforcement (warn-only by default)
   - `smoke_test_ibkr.py`: IBKR connectivity + entitlement smoke test
   - `smoke_multi_market.py`: Multi-market config + state isolation smoke
   - `check_no_secrets.py`: Secret detection guardrail
   - `python -m pearlalgo.pearl_ai.eval.ci --mock`: Pearl AI prompt regression eval (golden suite; see `.github/workflows/eval.yml`)

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
cd /path/to/PearlAlgoProject

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
./scripts/ops/status.sh --market NQ
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
WorkingDirectory=/path/to/PearlAlgoProject
Environment=\"PYTHONUNBUFFERED=1\"
EnvironmentFile=/path/to/PearlAlgoProject/.env
ExecStart=/path/to/PearlAlgoProject/.venv/bin/python -m pearlalgo.market_agent.main
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

A minimal `Dockerfile` is provided in the project root (runtime deps only; not intended for development). To build and run:

```bash
cd /path/to/PearlAlgoProject
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
2. Check service status: `./scripts/ops/status.sh --market NQ`
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
./scripts/ops/status.sh --market NQ
ps aux | grep "pearlalgo.market_agent.main"
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
# Use /stats command in Telegram, or:
ls -la data/agent_state/NQ/exports/
```

### External Watchdog

The watchdog script validates state freshness from outside the agent process:

```bash
# Check health (exit codes: 0=OK, 1=Warning, 2=Critical, 3=Error)
python3 scripts/monitoring/monitor.py --market NQ --verbose

# Send alerts to Telegram on issues
python3 scripts/monitoring/monitor.py --market NQ --telegram
```

Add to cron for continuous monitoring (every 5 minutes):
```cron
*/5 * * * * cd /path/to/PearlAlgoProject && python3 scripts/monitoring/monitor.py --market NQ --telegram
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

The following opportunity clusters are ranked by leverage and risk, updated as of 2026-02-12.
Use this document as the canonical reference for improvement iterations.

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

- ~~Operator-focused dashboards~~ **Done (v0.2.5)**: `SystemStatusPanel` with readiness, kill switch, session P&L, status badges with tooltips.
- ~~"Quiet reasons" in dashboard~~ **Done (v0.2.5)**: Agent offline/execution disabled banner, status badges show data level and market state.
- Restart cause tracking and correlation with `run_id`.

#### 4. Risk Management & Circuit Breakers

- ~~More explicit pause/resume semantics~~ **Improved (v0.2.5)**: `NotificationTier` filtering, circuit breaker dedup cooldown, manual pause/resume tested in `test_service_pause.py`.
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
   - Only generates signals during the configured strategy session window (default 18:00–15:45 ET, NY time)
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
4. **Volume Profile Robustness**: Fixed — `inf` values in volume profile calculations are now sanitized
5. **Testing Coverage**: Good coverage, but could be expanded

---

## Trust Assessment (2026-02-12)

- **Status**: High trust after cleanup, state refactor, and verification.
- **Evidence**:
  - CI guardrails enforced (doc reference audit, boundary checks, secrets scan, smoke tests, unit tests).
  - IBKR Gateway install externalized with CI guard against re-vendoring.
  - State module refactored: `pearlalgo.state` package eliminated; I/O moved to `utils/state_io.py`, state management consolidated under `market_agent/`.
  - All unit tests pass (`make ci`), with coverage above the 40% gate.

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
./scripts/ops/status.sh --market NQ

# Run Tests
python3 scripts/testing/test_all.py

# Multi-market smoke check
python3 scripts/testing/smoke_multi_market.py

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

- **Complete Guide**: `docs/MARKET_AGENT_GUIDE.md` (includes prop firm configuration)
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
- `docs/MARKET_AGENT_GUIDE.md` - Operational guide (how to run and operate)
- `docs/TESTING_GUIDE.md` - Complete testing guide (all testing procedures, mypy type checking)
- `docs/GATEWAY.md` - IBKR Gateway setup
- `docs/MARKET_DATA_SUBSCRIPTION.md` - How to get live market data (fix Error 354)

**Last Updated:** 2026-02-12  
**Current Configuration:** MNQ (Mini NQ) - Prop Firm Style Trading

---

## Recent Updates (v0.2.5)

### State Module Refactor + Dashboard Overhaul (2026-02-12)

**State management consolidation:**
- Eliminated `src/pearlalgo/state/` package entirely
- `state_io.py` (atomic JSON read/write) moved to `src/pearlalgo/utils/state_io.py`
- `state_builder.py` (state snapshot assembly) moved to `src/pearlalgo/market_agent/state_builder.py`
- `state_manager.py` and `state_reader.py` remain in `src/pearlalgo/market_agent/`
- `state_helpers.py` removed (functionality inlined or no longer needed)

**Web dashboard enhancements:**
- **SystemStatusPanel**: New comprehensive status panel showing readiness (Offline/Paused/Cooldown/Disarmed/Armed), execution state, circuit breaker, direction, session, errors
- **Kill switch with operator lock**: Requires `PEARL_OPERATOR_PASSPHRASE` for critical operations
- **Session P&L summary**: Real-time P&L in status panel
- **Status badges**: Header badges for Agent, GW, AI, Market, Data, ML, Shadow savings with hover tooltips
- **Agent offline / execution disabled banner**: Clear visual indicator when agent is not trading
- **Pull-to-refresh**: Mobile gesture support for dashboard refresh
- **Ultrawide layout**: `SystemStatusPanel` positioned in sidebar for wide screens

**Notification system improvements:**
- `NotificationTier` enum: `CRITICAL`, `IMPORTANT`, `DEBUG` for severity-based filtering
- `min_tier` filtering: Suppress low-priority notifications
- Circuit breaker dedup cooldown: 5-minute suppression of duplicate alerts

**Tradovate adapter improvements:**
- `_pending_fills` tracking for partial fill reconciliation
- `_contract_id` caching for efficient contract resolution
- `_open_orders` / `_orders_lock` for order reconciliation

**Execution orchestrator:**
- Uses `MarketAgentStateManager` for state management (was using raw state dict)
- Docstring notes on migrated vs non-migrated logic

**Telegram improvements:**
- Mobile-friendly character limits (`CHAR_LIMIT_HEADER`, `CHAR_LIMIT_BUTTON`)
- `truncate_for_mobile()` and `format_button_label()` helpers
- Uses `load_json_file()` from `pearlalgo.utils.state_io` for consistent file reads

**API server improvements:**
- Uses `pearlalgo.utils.state_io` (`load_json_file`) for consistent JSON reads
- Uses `pearlalgo.market_agent.state_reader.StateReader` for locked reads
- Audit router: TTL cache for historical queries with `_is_recent_query()` skip for recent data

**pearl.sh improvements:**
- `sync_env_local()`: Merges `PEARL_API_KEY`, `PEARL_WEBAPP_AUTH_ENABLED`, `PEARL_WEBAPP_PASSCODE` into `.env.local`
- `--no-chart` flag: Skip web app startup
- Chart auto-build: Builds production bundle if none exists
- `chart deploy`: Build + restart recommended after frontend code changes

**Testing:**
- `test_circuit_breaker.py` replaced by `test_service_pause.py` with expanded coverage:
  - Connection failure pause
  - Consecutive errors pause
  - Data fetch errors (backoff only, not pause)
  - Counter reset on success
  - Manual pause/resume
  - Status reflects circuit breaker state
  - Edge cases for thresholds

---

### Previous Updates (v0.2.4)

### Pearl Algo Web App Enhancements (2026-01-29)
- **Web-based TradingView-style chart** using lightweight-charts library
- **Features:**
  - Timeframe selector (1m, 5m, 15m, 1h)
  - Dynamic viewport (bar count adjusts to screen width automatically)
  - Fit All / Go Live buttons for quick navigation
  - EMA9 (cyan), EMA21 (yellow), VWAP (purple dashed) indicators
  - Trade markers with hover tooltips showing signal details
  - WebSocket real-time updates with authentication
  - Zustand state management with 3 stores (agent, chart, UI)
  - Jest/React Testing Library test suite (71 tests)
  - Error boundaries for graceful component failures
- **Port change:** Now runs on port 3001 (was 3000)
- **Requires:** Node.js 20.x for Next.js 14.1.0

### Cloudflare Tunnel Integration
- **Named tunnel support** for persistent HTTPS URLs (Telegram Mini App)
- Setup guide: Create tunnel, route DNS, configure ingress
- Example domain: `pearlalgo.io` and `www.pearlalgo.io`
- Config file: `~/.cloudflared/config.yml`

### New Maintenance Scripts
- **`reset_30d_performance.py`**: Reset 30-day performance to a specific value
  - Deletes all trades from the last 30 days
  - Inserts a single trade with the specified PNL
  - Useful for prop firm account resets

### Infrastructure
- Node.js 20.x now required for Pearl Algo Web App (Next.js 14)
- Cloudflared installed for tunnel management

---

## Previous Updates (v0.2.3)

### Type Checking (mypy)
- Added mypy configuration (`mypy.ini`) for static type checking
- Type stubs installed for pandas, PyYAML, and pytz
- CI pipeline includes mypy (informational mode)
- Fixed critical type errors in health_monitor.py and execution/ibkr/tasks.py

### Prometheus Metrics Expansion
- **50+ metrics** now exposed via `/metrics` endpoint
- New metric categories:
  - Challenge tracker (balance, progress, drawdown)
  - ML/Learning (filter mode, signals evaluated/passed/blocked)
  - Cadence/Latency (cycle duration p50/p99, missed cycles)
  - Enhanced trading metrics (cumulative P&L, session signals)
  - Data quality (age, buffer size vs target)

### Test Coverage Expansion
- Added comprehensive test suites:
  - `test_prometheus_metrics.py` - 25 tests for metrics generation
  - `test_health_monitor.py` - Health component testing
  - `test_error_handler.py` - Error classification and handling
  - `test_sparkline.py` - UI rendering utilities
  - `test_logging_config.py` - Logging setup validation
  - `test_retry.py` - Async retry logic
  - `test_service_core.py` - 20 tests for VirtualTradeManager, save_state, service init, connection failure, stop
  - `test_tradovate_client.py` - 22 tests for Tradovate REST/WebSocket client (mocked APIs)
  - `test_ibkr_adapter_unit.py` - 10 tests for IBKR adapter (mocked ib_insync)
  - `test_signal_pipeline_integration.py` - Extended with 5 execution pipeline scenarios
- Added web app tests:
  - `middleware.test.ts` - 22 tests for Next.js auth middleware
  - `useWebSocket.test.ts` - 32 tests for WebSocket hook
  - `login-actions.test.ts` - 20 tests for login/logout flow

















