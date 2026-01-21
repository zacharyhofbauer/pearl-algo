# Repository Inventory Ledger

Generated: 2026-01-21
Purpose: File-by-file keep/merge/delete decisions with proofs

## Decision Legend

- **KEEP**: Active, referenced, necessary for system behavior
- **SCAFFOLD**: Implemented but not wired/tested; future capability
- **DELETE**: Confirmed unreferenced/duplicate/superseded

---

## Source Code (`src/pearlalgo/`)

### Core Modules (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `__init__.py` | KEEP | Package marker | All imports |
| `config/config_file.py` | KEEP | YAML loader + env substitution | config_loader, tests |
| `config/config_loader.py` | KEEP | Service config with defaults | service, strategy |
| `config/settings.py` | KEEP | Pydantic infrastructure settings | tests, config_loader |

### NQ Agent (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `nq_agent/main.py` | KEEP | Production entry point | lifecycle scripts |
| `nq_agent/service.py` | KEEP | Main trading loop | main, tests |
| `nq_agent/data_fetcher.py` | KEEP | IBKR data fetch | service |
| `nq_agent/state_manager.py` | KEEP | State persistence | service, tests |
| `nq_agent/telegram_notifier.py` | KEEP | Telegram notifications | service, tests |
| `nq_agent/telegram_command_handler.py` | KEEP | Interactive bot | telegram scripts |
| `nq_agent/chart_generator.py` | KEEP | mplfinance charts | notifier, tests |
| `nq_agent/performance_tracker.py` | KEEP | PnL tracking | service |
| `nq_agent/challenge_tracker.py` | KEEP | 50k challenge tracking | service |
| `nq_agent/health_monitor.py` | KEEP | Health check | service |

### Data Providers (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `data_providers/base.py` | KEEP | Provider interface | all providers |
| `data_providers/factory.py` | KEEP | Provider factory | service, tests |
| `data_providers/ibkr_executor.py` | KEEP | IBKR order execution | execution adapter |
| `data_providers/ibkr/ibkr_provider.py` | KEEP | IBKR data provider | factory |

### Execution (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `execution/base.py` | KEEP | Adapter interface | service |
| `execution/ibkr/adapter.py` | KEEP | IBKR bracket orders | service |
| `execution/ibkr/tasks.py` | KEEP | Order placement | adapter |
| `execution/tradovate/adapter.py` | KEEP | Tradovate adapter | service (conditional) |

### Strategies (KEEP / SCAFFOLD)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `strategies/nq_intraday/*.py` | KEEP | Core strategy logic | service, tests |
| `strategies/pearl_bots/*.py` | KEEP | Trading bot variants + backtest harness | telegram, backtest |
| `strategies/trading_bot_manager.py` | KEEP | Single trading bot manager integration | signal_generator, telegram |
| `strategies/agent_manager.py` | **DELETED** | Unused multi-agent scaffold | None (deleted) |

### Learning (KEEP / SCAFFOLD)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `learning/bandit_policy.py` | KEEP | Thompson sampling | service |
| `learning/policy_state.py` | KEEP | Policy persistence | bandit_policy |
| `learning/contextual_bandit.py` | KEEP | Context-aware bandit | service, ml_filter |
| `learning/feature_engineer.py` | KEEP | 50+ feature extraction | signal_generator |
| `learning/ml_signal_filter.py` | KEEP | ML signal filtering | signal_generator |
| `learning/trade_database.py` | KEEP | SQLite trade history | service, tracker |
| `learning/ensemble_scorer.py` | KEEP | Ensemble ML scoring | __init__.py (exported) |
| `learning/meta_learner.py` | SCAFFOLD | Experience replay | __init__.py only, no tests |
| `learning/regime_adaptive.py` | SCAFFOLD | HMM regime detection | __init__.py only, no tests |
| `learning/risk_metrics.py` | SCAFFOLD | Risk analytics | __init__.py only, no tests |

### Policy (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `policy/drift_guard.py` | KEEP | Drift detection | service |
| `policy/signal_policy.py` | KEEP | Signal filtering policy | signal_generator |

### Prop Firm (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `prop_firm/guard.py` | KEEP | Risk guardrails | service |

### Storage (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `storage/async_sqlite_queue.py` | KEEP | Async write queue | service |

### Utils (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `utils/logger.py` | KEEP | Structured logging | All modules |
| `utils/logging_config.py` | KEEP | Log configuration | logger |
| `utils/error_handler.py` | KEEP | Error handling | service, data_fetcher |
| `utils/retry.py` | KEEP | Retry decorator | data_fetcher, providers |
| `utils/paths.py` | KEEP | Path resolution | service, state_manager |
| `utils/data_quality.py` | KEEP | Data validation | data_fetcher, tests |
| `utils/market_hours.py` | KEEP | Session timing | strategy, service |
| `utils/cadence.py` | KEEP | Polling cadence | service |
| `utils/telegram_alerts.py` | KEEP | Alert utilities | notifier |
| `utils/vwap.py` | KEEP | VWAP calculation | strategy |
| `utils/volume_pressure.py` | KEEP | Volume analysis | strategy |
| `utils/sparkline.py` | KEEP | Sparkline rendering | notifier |
| `utils/openai_client.py` | KEEP | AI patch client | telegram_command_handler |
| `utils/absolute_mode.py` | KEEP | Mode detection | config |
| `utils/service_controller.py` | KEEP | Service control | telegram_command_handler |

### Monitor (KEEP - Optional)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `monitor/app.py` | KEEP | Qt monitor UI | __main__ |
| `monitor/main.py` | KEEP | Monitor entry | app |
| `monitor/__main__.py` | KEEP | CLI entry | scripts |

### Agentic (KEEP)

| File | Decision | Role | Referenced By |
|------|----------|------|---------------|
| `agentic/hub.py` | KEEP | Agent coordination | service |
| `agentic/memory_store.py` | KEEP | Memory persistence | hub |

---

## Scripts (`scripts/`)

### All Scripts (KEEP)

All scripts in `scripts/` are documented in `SCRIPTS_TAXONOMY.md` and actively used.
No scripts flagged for deletion.

---

## Configuration (`config/`)

| File | Decision | Role |
|------|----------|------|
| `config.yaml` | KEEP | Primary configuration |
| `markets/` | KEEP | Per-market config examples (NQ/ES/GC) |

---

## Documentation (`docs/`)

### Active Documentation (KEEP)

| File | Decision | Role |
|------|----------|------|
| `PROJECT_SUMMARY.md` | KEEP | Single source of truth |
| `DOC_HIERARCHY.md` | KEEP | Doc organization |
| `PATH_TRUTH_TABLE.md` | KEEP | Path canonicalization |
| `SCRIPTS_TAXONOMY.md` | KEEP | Script roles |
| `CONFIGURATION_MAP.md` | KEEP | Config reference |
| `START_HERE.md` | KEEP | Operator quickstart |
| `CHEAT_SHEET.md` | KEEP | Daily operations |
| `NQ_AGENT_GUIDE.md` | KEEP | Agent operations |
| `RESTART_GUIDE.md` | KEEP | Restart procedures |
| `GATEWAY.md` | KEEP | IBKR Gateway |
| `TELEGRAM_GUIDE.md` | KEEP | Telegram integration |
| `AI_PATCH_GUIDE.md` | KEEP | AI patch workflow |
| `ATS_ROLLOUT_GUIDE.md` | KEEP | Execution rollout |
| `TESTING_GUIDE.md` | KEEP | Test procedures |
| `MOCK_DATA_WARNING.md` | KEEP | Mock data caveats |
| `MARKET_DATA_SUBSCRIPTION.md` | KEEP | IBKR subscriptions |
| `MPLFINANCE_QUICK_START.md` | KEEP | Chart reference |
| `CHART_VISUAL_SCHEMA.md` | KEEP | Chart contracts |
| `CHART_STRATEGY.md` | KEEP | Chart strategy |
| `TRADING_BOT_GUIDE.md` | KEEP | Single trading bot (AutoBot) reference |
| `ARCHITECTURE.md` | KEEP | System architecture |
| `AGENT_BRAIN_GUIDE.md` | KEEP | Agent internals |
| `LINUX_MONITOR.md` | KEEP | Monitor UI guide |
| `WIFI_MIGRATION_GUIDE.md` | KEEP | Network migration |
| `ROADMAP.md` | KEEP | Future plans |
| `TRADINGVIEW_INDICATOR_PORTING.md` | KEEP | Indicator porting |

### Prompts (KEEP)

| File | Decision | Role |
|------|----------|------|
| `prompts/promptbook_engineering.md` | KEEP | Engineering prompts |
| `prompts/promptbook_trading.md` | KEEP | Trading prompts |
| `prompts/promptbook_ux.md` | KEEP | UX prompts |
| `prompts/MSGODSCRIPT.md` | KEEP | Script reference |

---

## Tests (`tests/`)

All test files are actively run by pytest and pass. No test files flagged for deletion.

---

## Root Files

| File | Decision | Role |
|------|----------|------|
| `README.md` | KEEP | Quick-start guide |
| `pyproject.toml` | KEEP | Package definition |
| `pytest.ini` | KEEP | Test configuration |
| `env.example` | KEEP | Environment template |
| `Dockerfile` | KEEP | Container definition |
| `.gitignore` | KEEP | Git ignore patterns |
| `.cursorignore` | KEEP | Cursor ignore patterns |

---

## Other Directories

| Directory | Decision | Role |
|-----------|----------|------|
| `indicators/` | KEEP | Pine Script indicators (reference) |
| `resources/` | KEEP | Assets (logo) |
| `ibkr/` | KEEP | IBKR Gateway installation (external) |

---

## Summary

### Deleted Files
1. `src/pearlalgo/strategies/agent_manager.py` - Unused multi-agent scaffold (no imports)

### Scaffold/Unfinished Components
1. `src/pearlalgo/learning/meta_learner.py` - Exported but not wired
2. `src/pearlalgo/learning/regime_adaptive.py` - Exported but not wired
3. `src/pearlalgo/learning/risk_metrics.py` - Exported but not wired

### Do-Not-Change List
- `docs/PROJECT_SUMMARY.md` - Source of truth
- `config/config.yaml` - Production configuration
- All files under `src/pearlalgo/nq_agent/` - Core runtime
- All files under `src/pearlalgo/execution/` - Order execution
