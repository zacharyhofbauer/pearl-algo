# Repository Inventory Ledger

Generated: 2026-01-21  
Updated: 2026-01-28  
Purpose: File-by-file keep/rewrite/delete decisions grounded in the current tree.

## Decision Legend

- **KEEP**: Active, referenced, required for runtime or documented ops/testing
- **REWRITE**: Changed to align with current architecture/ownership
- **DELETE**: Removed as unused, superseded, or outside canonical scope

---

## Root

| Path | Decision | Role |
|------|----------|------|
| `README.md` | KEEP | Quick start and operator overview |
| `pyproject.toml` | KEEP | Project metadata + dependencies |
| `Makefile` | KEEP | Local developer/CI command wrappers |
| `pytest.ini` | KEEP | Pytest configuration |
| `mypy.ini` | KEEP | Mypy configuration |
| `env.example` | REWRITE | Adds `PEARLALGO_IBKR_HOME` guidance |
| `Dockerfile` | REWRITE | Runtime-only container install |
| `.gitignore` | REWRITE | Externalize `ibkr/` vendor tree |
| `.cursorignore` | REWRITE | Hide vendor subtrees only |

---

## `.devcontainer/`

| Path | Decision | Role |
|------|----------|------|
| `.devcontainer/devcontainer.json` | KEEP | Dev container configuration |
| `.devcontainer/Dockerfile` | KEEP | Dev container image |

---

## `.github/`

| Path | Decision | Role |
|------|----------|------|
| `.github/workflows/ci.yml` | REWRITE | Adds IBKR vendor guard |
| `.github/dependabot.yml` | KEEP | Dependency update policy |

---

## `config/`

| Path | Decision | Role |
|------|----------|------|
| `config/config.yaml` | KEEP | Primary configuration |
| `config/markets/nq.yaml` | KEEP | Market overlay |
| `config/markets/es.yaml` | KEEP | Market overlay |
| `config/markets/gc.yaml` | KEEP | Market overlay |

---

## `docs/`

| Path | Decision | Role |
|------|----------|------|
| `docs/DOC_HIERARCHY.md` | KEEP | Documentation hierarchy |
| `docs/PROJECT_SUMMARY.md` | REWRITE | Source of truth; IBKR path clarification |
| `docs/TESTING_GUIDE.md` | KEEP | Testing guide |
| `docs/PATH_TRUTH_TABLE.md` | REWRITE | Adds IBKR external path + orphan report |
| `docs/START_HERE.md` | REWRITE | Gateway env var note |
| `docs/CHEAT_SHEET.md` | REWRITE | Gateway env var note |
| `docs/SCRIPTS_TAXONOMY.md` | REWRITE | Adds orphan report |
| `docs/CONFIGURATION_MAP.md` | KEEP | Config mapping |
| `docs/TRADING_BOT_GUIDE.md` | KEEP | Strategy guide |
| `docs/PEARL_WEB_APP.md` | KEEP | Pearl Algo Web App + Telegram Mini App |
| `docs/MARKET_AGENT_GUIDE.md` | KEEP | Operator guide |
| `docs/TELEGRAM_GUIDE.md` | KEEP | Telegram guide |
| `docs/GATEWAY.md` | REWRITE | External IBKR install guidance |
| `docs/MARKET_DATA_SUBSCRIPTION.md` | KEEP | Error 354 guide |
| `docs/ATS_ROLLOUT_GUIDE.md` | KEEP | ATS rollout |
| `docs/MOCK_DATA_WARNING.md` | KEEP | Mock data warning |
| `docs/RESTART_GUIDE.md` | KEEP | Restart guide |
| `docs/AI_PATCH_GUIDE.md` | REWRITE | AI features moved to CLI (deprecated) |
| `docs/CODESPACES.md` | KEEP | Codespaces guide |
| `docs/INVENTORY_LEDGER.md` | REWRITE | File-level ledger |
| `docs/coverage-badge.svg` | KEEP | Coverage badge |

---

## `scripts/`

| Path | Decision | Role |
|------|----------|------|
| `scripts/gateway/gateway.sh` | REWRITE | External IBKR install support |
| `scripts/lifecycle/agent.sh` | KEEP | Agent lifecycle |
| `scripts/lifecycle/check_agent_status.sh` | KEEP | Agent status |
| `scripts/telegram/start_command_handler.sh` | KEEP | Telegram handler |
| `scripts/telegram/check_command_handler.sh` | KEEP | Telegram handler status |
| `scripts/telegram/restart_command_handler.sh` | KEEP | Telegram handler restart |
| `scripts/telegram/set_bot_commands.py` | KEEP | Telegram BotFather config |
| `scripts/monitoring/watchdog_agent.py` | KEEP | External watchdog |
| `scripts/monitoring/serve_agent_status.py` | KEEP | Local status server |
| `scripts/monitoring/doctor_cli.py` | KEEP | Operator rollup |
| `scripts/maintenance/purge_runtime_artifacts.sh` | KEEP | Safe cleanup |
| `scripts/maintenance/reset_30d_performance.py` | KEEP | Metrics reset |
| `scripts/backtesting/strategy_selection.py` | KEEP | Strategy export |
| `scripts/backtesting/train_ml_filter.py` | KEEP | ML filter training |
| `scripts/testing/test_all.py` | KEEP | Unified test runner |
| `scripts/testing/run_tests.sh` | KEEP | Pytest runner |
| `scripts/testing/check_architecture_boundaries.py` | KEEP | Boundary enforcement |
| `scripts/testing/check_doc_references.py` | KEEP | Doc reference audit |
| `scripts/testing/check_no_secrets.py` | KEEP | Secret scan |
| `scripts/testing/smoke_multi_market.py` | KEEP | Multi-market smoke |
| `scripts/testing/smoke_test_ibkr.py` | KEEP | IBKR smoke |
| `scripts/testing/generate_coverage_badge.py` | KEEP | Coverage badge |
| `scripts/testing/report_orphan_modules.py` | KEEP | Orphan module report |
| `scripts/health_check.sh` | KEEP | Fast health snapshot |

---

## `src/pearlalgo/`

All source modules are retained.

| Path | Decision | Role |
|------|----------|------|
| `src/pearlalgo/__init__.py` | KEEP | Package root |
| `src/pearlalgo/config/__init__.py` | KEEP | Config package |
| `src/pearlalgo/config/config_file.py` | KEEP | Config loader |
| `src/pearlalgo/config/config_loader.py` | KEEP | Config defaults |
| `src/pearlalgo/config/config_schema.py` | KEEP | Schema validation |
| `src/pearlalgo/config/config_view.py` | KEEP | Config view |
| `src/pearlalgo/config/settings.py` | KEEP | Pydantic settings |
| `src/pearlalgo/data_providers/__init__.py` | KEEP | Data providers |
| `src/pearlalgo/data_providers/base.py` | KEEP | Provider interface |
| `src/pearlalgo/data_providers/factory.py` | KEEP | Provider factory |
| `src/pearlalgo/data_providers/ibkr/__init__.py` | KEEP | IBKR provider package |
| `src/pearlalgo/data_providers/ibkr/ibkr_provider.py` | KEEP | IBKR provider |
| `src/pearlalgo/data_providers/ibkr_executor.py` | KEEP | IBKR executor |
| `src/pearlalgo/execution/__init__.py` | KEEP | Execution package |
| `src/pearlalgo/execution/base.py` | KEEP | Execution interfaces |
| `src/pearlalgo/execution/ibkr/__init__.py` | KEEP | IBKR execution |
| `src/pearlalgo/execution/ibkr/adapter.py` | KEEP | IBKR adapter |
| `src/pearlalgo/execution/ibkr/tasks.py` | KEEP | IBKR tasks |
| `src/pearlalgo/learning/__init__.py` | KEEP | Learning package |
| `src/pearlalgo/learning/bandit_policy.py` | KEEP | Bandit policy |
| `src/pearlalgo/learning/contextual_bandit.py` | KEEP | Contextual bandit |
| `src/pearlalgo/learning/ensemble_scorer.py` | KEEP | Ensemble scoring |
| `src/pearlalgo/learning/feature_engineer.py` | KEEP | Feature engineering |
| `src/pearlalgo/learning/ml_signal_filter.py` | KEEP | ML signal filter |
| `src/pearlalgo/learning/policy_state.py` | KEEP | Policy state |
| `src/pearlalgo/learning/trade_database.py` | KEEP | Trade DB |
| `src/pearlalgo/market_agent/__init__.py` | KEEP | Market agent |
| `src/pearlalgo/market_agent/challenge_tracker.py` | KEEP | Challenge tracking |
| `src/pearlalgo/market_agent/live_chart_screenshot.py` | KEEP | Live chart screenshot export |
| `src/pearlalgo/market_agent/data_fetcher.py` | KEEP | Data fetcher |
| `src/pearlalgo/market_agent/health_monitor.py` | KEEP | Health monitor |
| `src/pearlalgo/market_agent/main.py` | KEEP | Agent entrypoint |
| `src/pearlalgo/market_agent/notification_queue.py` | KEEP | Notification queue |
| `src/pearlalgo/market_agent/performance_tracker.py` | KEEP | Performance tracking |
| `src/pearlalgo/market_agent/service.py` | KEEP | Service loop |
| `src/pearlalgo/market_agent/state_manager.py` | KEEP | State manager |
| `src/pearlalgo/market_agent/telegram_command_handler.py` | KEEP | Telegram handler |
| `src/pearlalgo/market_agent/telegram_notifier.py` | KEEP | Telegram notifier |
| `src/pearlalgo/market_agent/trading_circuit_breaker.py` | KEEP | Circuit breaker |
| `src/pearlalgo/storage/__init__.py` | KEEP | Storage package |
| `src/pearlalgo/storage/async_sqlite_queue.py` | KEEP | Async SQLite |
| `src/pearlalgo/trading_bots/__init__.py` | KEEP | Trading bots |
| `src/pearlalgo/trading_bots/pearl_bot_auto.py` | KEEP | Strategy |
| `src/pearlalgo/utils/__init__.py` | KEEP | Utilities |
| `src/pearlalgo/utils/absolute_mode.py` | KEEP | Absolute mode |
| `src/pearlalgo/utils/cadence.py` | KEEP | Cadence helpers |
| `src/pearlalgo/utils/data_quality.py` | KEEP | Data quality |
| `src/pearlalgo/utils/error_handler.py` | KEEP | Error handling |
| `src/pearlalgo/utils/logger.py` | KEEP | Logger |
| `src/pearlalgo/utils/logging_config.py` | KEEP | Logging config |
| `src/pearlalgo/utils/market_hours.py` | KEEP | Market hours |
| `src/pearlalgo/utils/openai_client.py` | KEEP | OpenAI wrapper |
| `src/pearlalgo/utils/paths.py` | KEEP | Path helpers |
| `src/pearlalgo/utils/pearl_suggestions.py` | KEEP | Suggestions |
| `src/pearlalgo/utils/retry.py` | KEEP | Retry helpers |
| `src/pearlalgo/utils/service_controller.py` | KEEP | Service controller |
| `src/pearlalgo/utils/sparkline.py` | KEEP | Sparkline |
| `src/pearlalgo/utils/telegram_alerts.py` | KEEP | Telegram alerts |
| `src/pearlalgo/utils/telegram_ui_contract.py` | KEEP | Telegram UI contract |
| `src/pearlalgo/utils/volume_pressure.py` | KEEP | Volume pressure |
| `src/pearlalgo/utils/vwap.py` | KEEP | VWAP |

---

## `tests/`

Core tests are retained. Legacy **mplfinance chart visual regression** suites were removed
in favor of the web-based Live Main Chart.

| Path | Decision | Role |
|------|----------|------|
| `tests/__init__.py` | KEEP | Test package |
| `tests/conftest.py` | KEEP | Pytest fixtures |
| `tests/mock_data_provider.py` | KEEP | Mock data |
| `tests/fixtures/__init__.py` | KEEP | Test fixtures |
| `tests/test_ai_patch.py` | KEEP | AI patch tests |
| `tests/test_async_sqlite_queue.py` | KEEP | Async SQLite tests |
| `tests/test_bandit_policy.py` | KEEP | Bandit tests |
| `tests/test_base_cache.py` | KEEP | Cache tests |
| `tests/test_cadence.py` | KEEP | Cadence tests |
| `tests/test_config_file.py` | KEEP | Config file tests |
| `tests/test_config_loader.py` | KEEP | Config loader tests |
| `tests/test_config_schema.py` | KEEP | Config schema tests |
| `tests/test_config_wiring.py` | KEEP | Config wiring tests |
| `tests/test_data_level_dashboard.py` | KEEP | Data level UI |
| `tests/test_data_level_state.py` | KEEP | Data level state |
| `tests/test_data_provider_factory.py` | KEEP | Provider factory |
| `tests/test_data_quality_checker.py` | KEEP | Data quality |
| `tests/test_dashboard_pressure_in_home_card.py` | KEEP | Dashboard pressure |
| `tests/test_edge_cases.py` | KEEP | Edge cases |
| `tests/test_error_handler.py` | KEEP | Error handler |
| `tests/test_error_recovery.py` | KEEP | Error recovery |
| `tests/test_execution_adapter.py` | KEEP | Execution adapter |
| `tests/test_health_monitor.py` | KEEP | Health monitor |
| `tests/test_ibkr_executor_formatting.py` | KEEP | IBKR executor formatting |
| `tests/test_logging_config.py` | KEEP | Logging config |
| `tests/test_market_hours.py` | KEEP | Market hours |
| `tests/test_market_hours_config.py` | KEEP | Market hours config |
| `tests/test_ml_contextual_bandit.py` | KEEP | ML contextual bandit |
| `tests/test_ml_ensemble.py` | KEEP | ML ensemble |
| `tests/test_ml_feature_engineer.py` | KEEP | ML feature engineer |
| `tests/test_ml_filter_artifact.py` | KEEP | ML artifact |
| `tests/test_ml_trade_database.py` | KEEP | ML trade DB |
| `tests/test_mtf_cache.py` | KEEP | MTF cache |
| `tests/test_new_bar_gating.py` | KEEP | New bar gating |
| `tests/test_paths.py` | KEEP | Paths tests |
| `tests/test_prometheus_metrics.py` | KEEP | Metrics |
| `tests/test_quiet_dashboard.py` | KEEP | Quiet dashboard |
| `tests/test_quiet_reason.py` | KEEP | Quiet reason |
| `tests/test_retry.py` | KEEP | Retry |
| `tests/test_service_controller.py` | KEEP | Service controller |
| `tests/test_signal_expiry.py` | KEEP | Signal expiry |
| `tests/test_sparkline.py` | KEEP | Sparkline |
| `tests/test_state_persistence.py` | KEEP | State persistence |
| `tests/test_state_schema.py` | KEEP | State schema |
| `tests/test_staleness_market_aware.py` | KEEP | Staleness |
| `tests/test_telegram_authorization.py` | KEEP | Telegram auth |
| `tests/test_telegram_command_handler_flows.py` | KEEP | Telegram command flows |
| `tests/test_telegram_doctor.py` | KEEP | Telegram doctor |
| `tests/test_telegram_markdown_safety.py` | KEEP | Telegram markdown |
| `tests/test_telegram_message_limits.py` | KEEP | Telegram message limits |
| `tests/test_telegram_notifier_edge_cases.py` | KEEP | Telegram notifier |
| `tests/test_telegram_reporting.py` | KEEP | Telegram reporting |
| `tests/test_telegram_ui_contract.py` | KEEP | Telegram UI |
| `tests/test_trade_transparency_notifications.py` | KEEP | Trade transparency |
| `tests/test_trading_circuit_breaker_sessions.py` | KEEP | Circuit breaker sessions |
| `tests/test_vwap.py` | KEEP | VWAP |
| `tests/test_virtual_pnl_tiebreak.py` | KEEP | Virtual PnL |
| `tests/test_volume_pressure.py` | KEEP | Volume pressure |

---

## `models/`

| Path | Decision | Role |
|------|----------|------|
| `models/signal_filter_v1.joblib` | KEEP | ML filter artifact (shadow mode) |

---

## `resources/`

| Path | Decision | Role |
|------|----------|------|
| `resources/misc/pearlLogo.png` | KEEP | Branding asset |
| `resources/pinescript/pearlbot/EMA_Crossover.pine` | KEEP | Strategy lineage |
| `resources/pinescript/pearlbot/VWAP_AA.pine` | KEEP | Strategy lineage |
| `resources/pinescript/pearlbot/Volume.pine` | KEEP | Strategy lineage |
| resources/pinescript/pearlbot/Trading Sessions.pine | KEEP | Strategy lineage |
| resources/pinescript/pearlbot/S&R Power (ChartPrime).pine | KEEP | Strategy lineage |
| resources/pinescript/pearlbot/TBT (ChartPrime).pine | KEEP | Strategy lineage |
| resources/pinescript/pearlbot/Supply & Demand Visible Range (Lux).pine | KEEP | Strategy lineage |
| resources/pinescript/pearlbot/SpacemanBTC Key Level V13.1.pine | KEEP | Strategy lineage |

---

## `ibkr/`

| Path | Decision | Role |
|------|----------|------|
| `ibkr/README.md` | KEEP | External install guidance |
| `ibkr/.gitkeep` | KEEP | Placeholder directory |
| `ibkr/**` | DELETE | Vendored binaries and runtime artifacts (externalized) |

---

## Runtime/Build Artifacts (policy)

Delete on sight (not source-of-truth):
`data/`, `logs/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `*.egg-info/`, `htmlcov/`, `coverage.xml`.

---

## Orphan Module Report

- **Script**: `scripts/testing/report_orphan_modules.py`
- **Purpose**: Report modules in `src/pearlalgo/` not reachable from entrypoints/tests/scripts.
- **Policy**: Any orphan must be justified (dynamic import/entrypoint) or removed.
