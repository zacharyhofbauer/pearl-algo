# Documentation Hierarchy

This file defines the canonical documentation structure for the NQ Agent repository.

## 1. Architecture (single source of truth)

- `PROJECT_SUMMARY.md`
  - Overall system architecture
  - Component responsibilities
  - High‑level data flow
  - Configuration overview

All other documents must remain consistent with this summary.

## 2. Operational Guides

- `CHEAT_SHEET.md`
  - One-page PEARLalgo operational quick reference
  - Daily startup flow, core scripts, Telegram expectations, fast troubleshooting
- `NQ_AGENT_GUIDE.md`
  - How to start/stop/check the NQ Agent Service
  - Daily operations and monitoring
  - Troubleshooting specific to the agent service
- `GATEWAY.md`
  - IBKR Gateway setup and lifecycle
  - 2FA flows and VNC usage
  - Common IBKR connection issues
- `MPLFINANCE_QUICK_START.md`
  - **Canonical charting reference** (mplfinance-based chart generator)
  - Data contract and local verification script
- `TELEGRAM_GUIDE.md`
  - Single canonical Telegram integration guide
  - Quick start, command handler startup, command behavior reference
  - Remote control (service control commands)
  - Chart visualization and UI features
  - Menu system and button navigation

## 3. Testing and Validation

- `TESTING_GUIDE.md`
  - How to run tests via `scripts/testing/test_all.py` and `run_tests.sh`
  - Explanation of major test suites (integration, IBKR, Telegram, strategy)
  - Includes guidance on when and how to use the mock data provider
  - Test coverage and gaps analysis

## 4. Supporting / Historical Docs

- `archive/CLEANUP_CONSOLIDATION_PLAN.md`
  - Historical cleanup and consolidation notes
- `archive/MIGRATION_TO_MPLFINANCE.md`
  - Historical mplfinance migration documentation
- `archive/CHART_VISUALIZATION_BUILD_EXPLANATION.md`
  - Historical chart generator implementation notes
- `archive/CHART_DATA_FORMAT.md`
  - Historical chart data format documentation
- `archive/ADDITIONAL_FIXES.md`
  - Historical fix documentation
- `archive/FIXES_SUMMARY.md`
  - Historical fix documentation
- `archive/SIGNAL_PERSISTENCE_FIX.md`
  - Historical fix documentation
- `archive/MENU_NAVIGATION_FIX.md`
  - Historical fix documentation

## 5. Cross‑references

- Operational docs should link back to:
  - `PROJECT_SUMMARY.md` for architecture context
  - `PATH_TRUTH_TABLE.md` for canonical scripts and entry points
  - `SCRIPTS_TAXONOMY.md` for script roles

When adding or updating documentation:

1. Decide which category the new information belongs to.
2. Either update the existing document for that category or add a clearly linked sub‑section.
3. Avoid duplicating content across documents; prefer linking to the authoritative section.
4. Ensure all paths and commands you mention exist and are listed in `PATH_TRUTH_TABLE.md`.
