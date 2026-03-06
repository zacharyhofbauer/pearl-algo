# PearlAlgo Project Context — Full Codebase Guide

## Project Overview

PearlAlgo is a production algorithmic trading system for futures markets (primarily NQ/MNQ). It consists of:

1. **Python trading agent** (`src/pearlalgo/`) — market-agnostic service that generates signals, manages virtual trades, executes bracket orders, and tracks performance
2. **Next.js web dashboard** (`pearlalgo_web_app/`) — Telegram Mini App / PWA for monitoring and control
3. **Telegram bot** — command interface for monitoring, stats, and trading controls
4. **Scripts & systemd services** — lifecycle management, monitoring, IBKR Gateway management

**Tech stack:**
- Python 3.12+, pandas, numpy, pydantic, loguru, aiohttp, ib-insync
- Next.js 14.1.0, React 18, TypeScript, Zustand, lightweight-charts
- IBKR Gateway (market data), Tradovate (execution), Telegram Bot API
- SQLite + JSON dual-write for persistence
- pytest, ruff, mypy, Jest, ESLint for quality
- GitHub Actions CI/CD

**Version:** 0.2.4
**Package config:** `pyproject.toml` (setuptools)
**Python entry point:** `python -m pearlalgo.market_agent.main`

---

## Directory Structure

```
PearlAlgoProject/
├── src/pearlalgo/                  # Main Python package
│   ├── market_agent/               # Core trading service (33 files)
│   │   ├── main.py                 # Entry point (CLI args, config loading)
│   │   ├── service.py              # MarketAgentService (orchestrator, uses mixins)
│   │   ├── service_factory.py      # Dependency injection factory
│   │   ├── service_lifecycle.py    # Start/stop mixin
│   │   ├── service_loop.py         # Main trading loop mixin
│   │   ├── signal_handler.py       # Signal processing pipeline (10 stages)
│   │   ├── signal_orchestrator.py  # Signal coordination
│   │   ├── virtual_trade_manager.py# Virtual trade exit processing (TP/SL detection)
│   │   ├── order_manager.py        # Position sizing
│   │   ├── execution_orchestrator.py# Execution coordination
│   │   ├── position_tracker.py     # Position tracking
│   │   ├── state_manager.py        # State persistence (JSON + SQLite dual-write)
│   │   ├── state_reader.py         # State reading utilities
│   │   ├── state_builder.py        # State construction helpers
│   │   ├── performance_tracker.py  # Performance metrics (O(1) running aggregates)
│   │   ├── stats_computation.py    # Statistics calculations
│   │   ├── data_fetcher.py         # Market data fetching with caching
│   │   ├── health_monitor.py       # Health monitoring
│   │   ├── trading_circuit_breaker.py # Risk circuit breaker
│   │   ├── challenge_tracker.py    # 50K challenge tracking
│   │   ├── tv_paper_eval_tracker.py# Tradovate Paper evaluation tracking
│   │   ├── ml_manager.py           # ML model management
│   │   ├── telegram_notifier.py    # Telegram integration
│   │   ├── telegram_formatters.py  # Telegram message formatting
│   │   ├── notification_queue.py   # Async notification queue
│   │   ├── audit_logger.py         # Audit event logging
│   │   ├── scheduled_tasks.py      # Scheduled tasks (daily reset, briefings)
│   │   ├── reconciliation.py       # Data reconciliation
│   │   ├── operator_handler.py     # Operator commands
│   │   └── live_chart_screenshot.py# Chart screenshots
│   │
│   ├── trading_bots/               # Strategy layer
│   │   └── pearl_bot_auto.py       # Main strategy (~2000 lines, 8 indicators)
│   │
│   ├── execution/                  # Execution adapters
│   │   ├── base.py                 # Abstract ExecutionAdapter
│   │   └── tradovate/              # Tradovate adapter (placeOSO, WebSocket sync)
│   │       ├── adapter.py
│   │       ├── client.py
│   │       └── config.py
│   │
│   ├── learning/                   # ML/adaptive learning
│   │   ├── bandit_policy.py        # Thompson Sampling per signal type
│   │   ├── contextual_bandit.py    # Context-aware bandit (regime, vol, time)
│   │   ├── ml_signal_filter.py     # XGBoost/LightGBM signal quality predictor
│   │   ├── ensemble_scorer.py      # Logistic + GBM + bandit ensemble
│   │   ├── feature_engineer.py     # 50+ predictive features
│   │   ├── trade_database.py       # SQLite trade history
│   │   └── policy_state.py         # Persistent bandit state
│   │
│   ├── data_providers/             # Data abstraction
│   │   ├── base.py                 # Abstract DataProvider
│   │   ├── factory.py              # Provider factory with fallback
│   │   └── ibkr/                   # IBKR implementation
│   │
│   ├── config/                     # Configuration management
│   │   ├── schema_v2.py            # Pydantic config schema
│   │   ├── config_loader.py        # YAML loader with mtime caching
│   │   ├── defaults.py             # Single source of truth for defaults
│   │   └── settings.py             # Environment-based settings
│   │
│   ├── api/                        # FastAPI REST API
│   │   ├── server.py               # Main server (candles, state, trades, performance)
│   │   ├── data_layer.py           # Data access with TTL caching
│   │   ├── metrics.py              # Risk metrics computation
│   │   └── indicator_service.py    # Indicator computation endpoints
│   │
│   ├── telegram/                   # Telegram bot (commands & handlers)
│   │   ├── main.py                 # Bot router
│   │   └── handlers/               # /status, /stats, /trades, /health, /doctor, /settings
│   │
│   ├── notifications/              # Alert system
│   ├── analytics/                  # Analytics and reporting
│   └── utils/                      # Cross-cutting utilities (27 files)
│       ├── logger.py, state_io.py, formatting.py, market_hours.py
│       ├── time_utils.py, error_handler.py, rate_limiter.py, retry.py
│       └── paths.py, data_quality.py, model_integrity.py, etc.
│
├── pearlalgo_web_app/              # Next.js 14 web dashboard
│   ├── app/                        # App Router pages
│   │   ├── layout.tsx              # Root layout with NavBar
│   │   ├── page.tsx                # Landing page (account cards)
│   │   └── dashboard/              # Main dashboard (chart, trades, performance)
│   ├── components/                 # React components
│   │   ├── CandlestickChart.tsx    # Lightweight Charts
│   │   ├── SystemStatusPanel.tsx   # System readiness + kill switch
│   │   ├── TradeDockPanel.tsx      # Trade management
│   │   └── DataPanelsContainer.tsx # Performance/risk panels
│   ├── stores/                     # Zustand state management
│   │   ├── agentStore.ts           # Agent state, P&L, challenge, execution
│   │   ├── chartStore.ts           # Candles, indicators, markers
│   │   └── uiStore.ts             # WebSocket status, theme
│   ├── hooks/                      # Custom hooks
│   │   ├── useDashboardData.ts     # Data fetching + HTTP polling fallback
│   │   └── useWebSocket.ts         # WebSocket connection management
│   └── types/agent.ts              # TypeScript type definitions
│
├── config/                         # YAML configuration
│   ├── base.yaml                   # Base config (MNQ, 1m, session 18:00-15:45 ET)
│   └── accounts/
│       └── tradovate_paper.yaml    # Tradovate Paper (50K challenge, execution enabled)
│
├── scripts/                        # Operational scripts
│   ├── lifecycle/                  # agent.sh, tv_paper_eval.sh
│   ├── systemd/                    # Systemd service files
│   ├── monitoring/                 # Health monitor, Prometheus metrics
│   ├── gateway/                    # IBKR Gateway management
│   ├── telegram/                   # Telegram bot lifecycle
│   ├── maintenance/                # Maintenance utilities
│   └── testing/                    # Test runners
│
├── tests/                          # Pytest test suite
├── docs/                           # Documentation
├── pyproject.toml                  # Python project config (v0.2.4)
├── Makefile                        # Build/test automation
├── Dockerfile                      # Container image
├── env.example                     # Environment variable template
└── .github/workflows/              # CI/CD (Python CI + Web App CI)
```

---

## Architecture & Data Flow

### Layered Architecture (strict dependency boundaries)

```
Utils (pure) → Config → Data Providers → Trading Bots → Market Agent → Execution → Learning
```

### Main Trading Loop Cycle (every 30s default, adaptive cadence)

1. **Pre-cycle checks** — daily reset, briefings, health, signal pruning
2. **Data fetch** — OHLCV from IBKR via data_fetcher (with caching + multi-timeframe)
3. **New-bar gating** — skip analysis if bar unchanged (perf optimization)
4. **Signal generation** — `pearl_bot_auto.analyze()` runs 8 indicators (EMA crossover, VWAP, volume, S&R, TBT trendlines, supply/demand, key levels, regime detection)
5. **Signal processing pipeline** (10 stages in `signal_handler.py`):
   - Circuit breaker check → Position sizing → ML filter (shadow) → ML opportunity sizing → Track generation → Validate entry price → Virtual entry → Bandit policy → Contextual policy → Execution (bracket order)
6. **Virtual trade exit processing** — `VirtualTradeManager.process_exits()` scans active trades with vectorized TP/SL detection against bar data
7. **Exit recording** — updates performance tracker, circuit breaker, challenge tracker, learning policies, sends notifications
8. **Dashboard & state persistence** — saves state (JSON + SQLite dual-write)

### Signal Lifecycle

1. **Generated** → saved to `signals.jsonl` with status "generated"
2. **Entered** → status updated to "entered" (virtual entry)
3. **Exited** → status updated to "exited" with P&L calculations

### Execution Safety Layers

1. Config defaults: `enabled=False`, `armed=False`, `mode=dry_run`
2. Preconditions: symbol whitelist, max positions, daily limits, cooldowns
3. Kill switch: auto-disarm on daily loss limit, manual cancel/flatten
4. Circuit breakers: consecutive losses (5), session drawdown ($500), win rate filter, volatility/chop filter
5. Learning system: shadow mode by default (learns without affecting execution)

### State Persistence

- **Primary:** JSON files (`signals.jsonl`, `state.json`, `events.jsonl`, `performance.json`)
- **Secondary:** SQLite (`trades.db`) via async queue
- **Caching:** 15s TTL for signals, 30s TTL for metrics, O(1) running aggregates

---

## Key Configuration

### `config/base.yaml` defaults

- Symbol: MNQ, Timeframe: 1m, Scan interval: 30s
- Session: 18:00–15:45 ET (prop firm window)
- Risk: 1.5% per trade, 10% max drawdown
- Adaptive cadence: 5s active / 30s idle / 300s market closed
- ML filter: enabled, mode: shadow
- Learning: enabled: false, mode: shadow

### `config/accounts/tradovate_paper.yaml`

- 50K Rapid Evaluation challenge (profit target: $3000, max drawdown: $2000)
- Execution: enabled + armed, adapter: tradovate, mode: paper

### Environment variables (see `env.example`)

- IBKR Gateway connectivity
- Telegram bot credentials
- Tradovate API credentials
- Data provider selection
- API server auth

---

## Strategy: pearl_bot_auto.py

The strategy (`src/pearlalgo/trading_bots/pearl_bot_auto.py`, ~2000 lines) combines 8 indicators:

1. **EMA Crossover (9/21)** — core trend signal
2. **VWAP Position** — above/below volume-weighted average price
3. **Volume Confirmation** — volume exceeds moving average
4. **S&R Power Channel** — support/resistance breakouts
5. **TBT Trendlines** — trendline break detection
6. **Supply & Demand Zones** — high-volume price level identification
7. **SpacemanBTC Key Levels** — multi-timeframe S/R (PDH/PDL, PWH/PWL, PMH/PML)
8. **Market Regime Detection** — classifies trending/ranging/volatile

Confidence scoring: base 0.5 + additive boosts from each confirming indicator. Regime-adaptive stops (wider in volatile, tighter in ranging).

---

## Web Dashboard (pearlalgo_web_app/)

- **Framework:** Next.js 14 App Router, TypeScript, React 18
- **State:** Zustand stores (agentStore, chartStore, uiStore)
- **Charts:** lightweight-charts for candlestick + indicators
- **Real-time:** WebSocket connection to API server + HTTP polling fallback
- **PWA:** Installable via @ducanh2912/next-pwa
- **Proxy:** `/tv_paper/*` routes to port 8001 (Tradovate Paper API)
- **Key pages:** Landing (account cards) → Dashboard (chart, system status, trade dock, performance panels)

---

## Running the Project

### Start agent

```bash
# Tradovate Paper evaluation
./scripts/lifecycle/tv_paper_eval.sh start

# Generic agent
./scripts/lifecycle/agent.sh start --market MNQ --config config/accounts/tradovate_paper.yaml
```

### Start web app

```bash
cd pearlalgo_web_app && npm run dev   # Development
cd pearlalgo_web_app && NODE_OPTIONS="--max-old-space-size=4096" npm run build  # Build
cp -r .next/static .next/standalone/.next/static && cp -r public .next/standalone/public  # Copy assets
node .next/standalone/server.js  # Production (or use systemd: sudo systemctl restart pearlalgo-webapp)
```

### Testing

```bash
make test          # Python unit tests
make ci            # Full CI (lint, type check, arch boundaries, tests)
cd pearlalgo_web_app && npm test      # Web app tests
cd pearlalgo_web_app && npm run build # Build verification
```

### Key Makefile targets

```bash
make install   # Install package (editable + dev extras)
make test      # pytest (skips credential-dependent tests)
make coverage  # Coverage report + badge
make arch      # Architecture boundary enforcement
make secrets   # Secret scanning
make smoke     # Multi-market smoke test
make ci        # All CI checks
```

---

## Current State (as of Mar 6, 2026)

### Branch: `master`

### Recent changes

- **Web app production upgrade (Mar 6)**: Fixed default API port (8000→8001), added CSP/HSTS security headers, switched systemd service to standalone server.js, added Cloudflare tunnel `/ws` WebSocket route, rebuilt production bundle
- **Bug fixes (Mar 6)**: Signal record lookup, regime key name, startup notification tier, duplicate process prevention
- **Process management**: All services managed by systemd (`pearlalgo-agent`, `pearlalgo-api`, `pearlalgo-telegram`, `pearlalgo-webapp`, `cloudflared-pearlalgo`). IBKR gateway is NOT systemd-managed.

---

## Important Conventions

1. **Safety first:** Never edit `master` during market hours. Work on branches for risky changes.
2. **Preflight builds:** Run `cd pearlalgo_web_app && npm run build` before and after web app changes.
3. **Rollback script:** `./scripts/maintenance/git_rollback_paths.sh` for emergency path-scoped rollbacks.
4. **Architecture boundaries:** Utils layer must not import from config/strategy layers. Enforced via `make arch`.
5. **Config system:** Base YAML + account overlay. Defaults live in `src/pearlalgo/config/defaults.py`.
6. **Execution is off by default:** Must explicitly enable + arm + set mode in account config.
7. **Learning in shadow mode:** ML filter and bandit policies observe but don't block signals by default.
