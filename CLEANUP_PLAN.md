# PearlAlgo Repository Cleanup Plan

**Status**: Planning Phase - No deletions yet, only categorization

**Date**: Created during refactor/cleanup-core branch

---

## Summary

This document categorizes all files in the repository into:
- **KEEP**: Core files essential for current architecture
- **ARCHIVE**: Potentially useful but not daily-use files (move to `docs/legacy/` or `legacy/`)
- **DELETE**: Duplicate, obsolete, or clearly superseded files

---

## Root Markdown Files

| Path | Status | Reason |
|------|--------|--------|
| `START_HERE.md` | **KEEP** | Primary onboarding guide (new, comprehensive) |
| `QUICK_START_COMMANDS.txt` | **KEEP** | Quick reference for commands (new) |
| `IBKR_CONNECTION_FIXES.md` | **KEEP** | IBKR connection documentation (new) |
| `IBKR_FIXES_SUMMARY.md` | **KEEP** | IBKR fixes summary (new) |
| `TODAYS_UPGRADES_SUMMARY.md` | **KEEP** | Recent fixes documentation (new) |
| `README.md` | **KEEP** | Main README (needs update to point to START_HERE.md) |
| `ARCHITECTURE.md` | **KEEP** | Technical architecture documentation |
| `CHEAT_SHEET_SHORT.md` | **KEEP** | Quick reference (useful) |
| `CHEAT_SHEET.md` | **ARCHIVE** | Longer cheat sheet (may be redundant with SHORT version) |
| `GET_STARTED.md` | **ARCHIVE** | Superseded by START_HERE.md |
| `COMPLETE_SETUP_GUIDE.md` | **ARCHIVE** | Superseded by START_HERE.md |
| `TUTORIAL.md` | **ARCHIVE** | Superseded by START_HERE.md |
| `ENV_SETUP.md` | **ARCHIVE** | Superseded by START_HERE.md (ENV section) |
| `FIX_TERMINAL_START.md` | **ARCHIVE** | Specific fix doc, may be obsolete |
| `TERMINAL_FIXES.md` | **ARCHIVE** | Specific fix doc, may be obsolete |
| `TERMINAL_GUIDE.md` | **ARCHIVE** | May be redundant |
| `VENV_EXPLANATION.md` | **ARCHIVE** | Basic venv info, may be redundant |
| `CONNECTION_STATUS.md` | **ARCHIVE** | Old status doc |
| `DASHBOARD_MENU.md` | **ARCHIVE** | May be outdated |
| `DIAGNOSTICS.md` | **ARCHIVE** | May be outdated |
| `FINAL_STATUS.md` | **ARCHIVE** | Old status doc |
| `FIXES_APPLIED.md` | **ARCHIVE** | Old status doc |
| `IMPLEMENTATION_COMPLETE.md` | **ARCHIVE** | Old status doc |
| `IMPLEMENTATION_SUMMARY.md` | **ARCHIVE** | Old status doc |
| `IMPROVEMENTS_SUMMARY.md` | **ARCHIVE** | Old status doc |
| `PHASE_COMPLETION_REPORT.md` | **ARCHIVE** | Old status doc |
| `PLAN_COMPLETION_STATUS.md` | **ARCHIVE** | Old status doc |
| `PLAN_IMPLEMENTATION_COMPLETE.md` | **ARCHIVE** | Old status doc |
| `SETUP_STATUS.md` | **ARCHIVE** | Old status doc |
| `SYSTEM_STATUS.md` | **ARCHIVE** | Old status doc |
| `SUMMARY.md` | **ARCHIVE** | Old status doc |
| `NEXT_STEPS.md` | **ARCHIVE** | Old planning doc |
| `TODO_SUMMARY.md` | **ARCHIVE** | Old planning doc |
| `LANGGRAPH_QUICKSTART.md` | **ARCHIVE** | May be redundant with START_HERE.md |
| `QUICK_START_STRATEGIES.md` | **ARCHIVE** | May be redundant |
| `MICRO_STRATEGIES_GUIDE.md` | **ARCHIVE** | Strategy-specific, may be useful but not core |
| `TESTING_GUIDE.md` | **KEEP** | Testing documentation (useful) |
| `TEST_RESULTS.md` | **ARCHIVE** | Old test results |
| `MASTER_TEST_SUITE.md` | **ARCHIVE** | May be redundant with TESTING_GUIDE.md |
| `PROFESSIONAL_TEST_PLAN.md` | **ARCHIVE** | May be redundant |
| `STEP_BY_STEP_TESTS.md` | **ARCHIVE** | May be redundant |
| `READY_FOR_TESTING.md` | **ARCHIVE** | Old status doc |
| `LLM_MODEL_FIX.md` | **ARCHIVE** | Specific fix doc |
| `LLM_SETUP.md` | **ARCHIVE** | May be redundant |
| `LEGACY_CLEANUP.md` | **ARCHIVE** | Old cleanup doc |
| `LEGACY_DEPENDENCIES.md` | **ARCHIVE** | Old dependencies doc |
| `MIGRATION_GUIDE.md` | **ARCHIVE** | Old migration doc |
| `PROJECT_ORGANIZATION.md` | **ARCHIVE** | May be redundant with ARCHITECTURE.md |
| `README_FUTURES.md` | **ARCHIVE** | May be redundant with README.md |
| `AI_ONBOARDING_GUIDE.md` | **ARCHIVE** | AI-specific, may be redundant |
| `FILES_FOR_AI_ONBOARDING.md` | **ARCHIVE** | AI-specific, may be redundant |
| `.env.REVIEW.md` | **ARCHIVE** | Review doc, may be obsolete |

---

## Scripts Directory

### Core Scripts (KEEP)

| Path | Status | Reason |
|------|--------|--------|
| `scripts/daily_workflow.py` | **KEEP** | Batch daily operations |
| `scripts/run_daily_signals.py` | **KEEP** | Futures signals generation |
| `scripts/health_check.py` | **KEEP** | Periodic health check |
| `scripts/dashboard.py` | **KEEP** | Terminal dashboard (unified) |
| `scripts/daily_report.py` | **KEEP** | Daily report generation |
| `scripts/risk_monitor.py` | **KEEP** | Risk monitoring |
| `scripts/system_health_check.py` | **KEEP** | System health check |

### Debug/Setup Scripts (KEEP or ARCHIVE)

| Path | Status | Reason |
|------|--------|--------|
| `scripts/debug_env.py` | **KEEP** | New - ENV debugging tool (to be created) |
| `scripts/debug_ibkr.py` | **KEEP** | New - IBKR debugging tool (to be created) |
| `scripts/verify_setup.py` | **KEEP** | Setup verification |
| `scripts/setup_assistant.py` | **KEEP** | Setup assistant |
| `scripts/setup_langgraph.py` | **ARCHIVE** | One-time setup, may be obsolete |
| `scripts/debug_trading.py` | **ARCHIVE** | Ad-hoc debug script |
| `scripts/manual_trade_test.py` | **ARCHIVE** | Ad-hoc test script |
| `scripts/test_paper_trading.py` | **ARCHIVE** | May be redundant with pytest |
| `scripts/test_broker_connection.py` | **ARCHIVE** | May be redundant with pytest |
| `scripts/test_contracts.py` | **ARCHIVE** | May be redundant with pytest |
| `scripts/test_all_llm_providers.py` | **ARCHIVE** | May be redundant with pytest |
| `scripts/check_api_logs.py` | **ARCHIVE** | Ad-hoc utility |
| `scripts/check_session_config.py` | **ARCHIVE** | Ad-hoc utility |
| `scripts/verify_order_execution.py` | **ARCHIVE** | Ad-hoc utility |

### Analysis Scripts (ARCHIVE or KEEP)

| Path | Status | Reason |
|------|--------|--------|
| `scripts/analyze_performance.py` | **KEEP** | Performance analysis (useful) |
| `scripts/validate_backtest.py` | **ARCHIVE** | Backtest validation (may be redundant) |
| `scripts/walk_forward_test.py` | **ARCHIVE** | Backtest utility (may be redundant) |
| `scripts/monitor_paper_trading.py` | **ARCHIVE** | May be redundant with dashboard |
| `scripts/streamlit_dashboard.py` | **ARCHIVE** | Alternative dashboard (not core) |

### Shell Scripts (REVIEW)

| Path | Status | Reason |
|------|--------|--------|
| `scripts/start_langgraph_paper.sh` | **KEEP** | Start script (if used) |
| `scripts/ibgateway_status.sh` | **KEEP** | IBKR Gateway status check |
| `scripts/ibgateway_logs.sh` | **KEEP** | IBKR Gateway logs |
| `scripts/kill_my_processes.sh` | **ARCHIVE** | Utility script |
| `scripts/start_all_micro_strategies.sh` | **ARCHIVE** | May be obsolete |
| `scripts/stop_all_micro_strategies.sh` | **ARCHIVE** | May be obsolete |
| `scripts/start_standard.sh` | **ARCHIVE** | May be obsolete |
| `scripts/start_micro.sh` | **ARCHIVE** | May be obsolete |
| `scripts/start_trading_foreground.sh` | **ARCHIVE** | May be obsolete |
| `scripts/watch_trading.sh` | **ARCHIVE** | May be obsolete |
| `scripts/show_live_activity.sh` | **ARCHIVE** | May be obsolete |
| `scripts/test_live_trading.sh` | **ARCHIVE** | May be obsolete |
| `scripts/run_all_strategies.sh` | **ARCHIVE** | May be obsolete |
| `scripts/setup_automated_trading.sh` | **ARCHIVE** | May be obsolete |

### Backup/Service Files

| Path | Status | Reason |
|------|--------|--------|
| `scripts/status_dashboard.py.backup` | **DELETE** | Backup file |
| `scripts/automated_trading.service` | **KEEP** | Systemd service (may be useful) |
| `scripts/ibgateway-ibc.service` | **KEEP** | Systemd service (may be useful) |
| `scripts/ibgateway.service` | **KEEP** | Systemd service (may be useful) |
| `scripts/ibc_config.ini` | **KEEP** | IBKR Gateway config |

---

## Data Directory

| Path | Status | Reason |
|------|--------|--------|
| `data/performance/futures_decisions.csv` | **KEEP** | Production performance data |
| `data/equities/SPY_ib_5m.csv` | **KEEP** | Real data (if used) |
| `data/futures/ES_ib_15m.csv` | **KEEP** | Real data (if used) |
| `data/futures/ES_15m_sample.csv` | **ARCHIVE** | Sample/dummy data |
| `data/futures/NQ_15m_sample.csv` | **ARCHIVE** | Sample/dummy data |

**Note**: Sample CSV files should be moved to `data/samples/` or `legacy/data/` to avoid confusion with real data.

---

## Legacy Directory

| Path | Status | Reason |
|------|--------|--------|
| `legacy/` (entire directory) | **KEEP** | Already archived legacy code |
| `legacy_backup/` (entire directory) | **KEEP** | Backup of legacy code |

---

## Source Code (src/pearlalgo/)

| Path | Status | Reason |
|------|--------|--------|
| `src/pearlalgo/` (entire directory) | **KEEP** | Core application code |

**Note**: All core code should be kept. Review for any dummy/test code that should be removed or made explicit.

---

## Tests Directory

| Path | Status | Reason |
|------|--------|--------|
| `tests/` (entire directory) | **KEEP** | All test files should be kept |
| `test_system.py` | **KEEP** | System test script |

---

## Configuration Files

| Path | Status | Reason |
|------|--------|--------|
| `config/config.yaml` | **KEEP** | Main configuration |
| `config/micro_strategy_config.yaml` | **KEEP** | Strategy configuration |
| `pyproject.toml` | **KEEP** | Python project config |
| `pytest.ini` | **KEEP** | Pytest configuration |
| `.env` | **KEEP** | Environment variables (user file) |
| `.env.example` | **KEEP** | To be created - ENV template |

---

## Other Files

| Path | Status | Reason |
|------|--------|--------|
| `docker-compose.yml` | **KEEP** | Docker deployment |
| `Dockerfile` | **KEEP** | Docker deployment |
| `fix_terminal_start.sh` | **ARCHIVE** | Specific fix script |
| `quick_start.sh` | **ARCHIVE** | May be redundant |
| `start_micro_paper_trading.sh` | **KEEP** | Start script (referenced in docs) |
| `monitor_trades.sh` | **KEEP** | Monitor script (referenced in docs) |
| `ibgateway-latest-standalone-linux-x64.sh` | **KEEP** | IBKR Gateway installer |

---

## Directories to Review

| Path | Status | Reason |
|------|--------|--------|
| `logs/` | **KEEP** | Log files (runtime data) |
| `signals/` | **KEEP** | Signal files (runtime data) |
| `reports/` | **KEEP** | Report files (runtime data) |
| `state_cache/` | **KEEP** | State cache (runtime data) |
| `journal/` | **KEEP** | Trade journal (runtime data) |
| `telemetry/` | **KEEP** | Telemetry data (runtime data) |
| `docs/` | **KEEP** | Documentation directory |

---

## Action Plan

### Phase 1: Documentation Cleanup
1. Archive old markdown files to `docs/legacy/`
2. Update README.md to point to START_HERE.md
3. Ensure all new docs tell coherent story

### Phase 2: Script Cleanup
1. Archive non-core scripts to `legacy/scripts/`
2. Delete backup files
3. Standardize core scripts
4. Create new debug scripts (debug_env.py, debug_ibkr.py)

### Phase 3: Data Cleanup
1. Move sample CSVs to `data/samples/` or `legacy/data/`
2. Document which data files are real vs sample

### Phase 4: Final Review
1. Verify no broken imports after archiving
2. Update CLEANUP_PLAN.md with final status
3. Add postmortem section

---

## Notes

- **No deletions yet** - This is a planning document
- All ARCHIVE items should be moved (not deleted) to preserve history
- All DELETE items should be verified as unused before deletion
- Check for imports/references before archiving/deleting scripts
- Update documentation to reflect changes

---

**Last Updated**: During refactor/cleanup-core branch implementation
**Status**: In Progress

## Implementation Progress

### ✅ Step 0: Safety + Discovery - COMPLETE
- Git branch `refactor/cleanup-core` created
- Baseline tests run (fixed syntax errors)
- Repository scanned and categorized
- CLEANUP_PLAN.md created

### ✅ Step 1: ENV + Settings Unification - COMPLETE
- Settings class refactored with validation
- `dummy_mode` flag added
- IBKR_* and PEARLALGO_* env var normalization implemented
- `.env.example` created
- `scripts/debug_env.py` created and tested
- Tests added for settings validation
- START_HERE.md and QUICK_START_COMMANDS.txt updated

### ✅ Step 2: IBKR Connectivity & Dummy Data Cleanup - COMPLETE
- Market data agent updated to respect `dummy_mode` flag
- Silent dummy fallback removed
- Clear error messages with documentation references
- IBKR_CONNECTION_FIXES.md updated
- `scripts/debug_ibkr.py` created

### 🔄 Step 3: Script & Workflow Simplification - IN PROGRESS
- Scripts enumerated (41 files found)
- Core scripts identified
- Need to: Archive non-core scripts, standardize core scripts

### ⏳ Step 4: Docs & Onboarding Alignment - PENDING
- Need to: Archive old docs, update README.md

### ⏳ Step 5: Final Polishing & Tests - PENDING
- Need to: Run full test suite, verify scripts, update CLEANUP_PLAN.md final status

