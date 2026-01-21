# Repository Inventory Ledger

Generated: 2026-01-21  
Purpose: File-by-file keep/delete decisions grounded in the current tree.

## Decision Legend

- **KEEP**: Active, referenced, required for runtime or documented ops/testing
- **DELETE**: Removed as unused, superseded, or outside canonical scope

---

## Source Code (`src/pearlalgo/`)

### Core Config + Runtime (KEEP)

| Path | Decision | Role |
|------|----------|------|
| `config/*` | KEEP | Config loading + schema + settings |
| `data_providers/*` | KEEP | IBKR data provider + executor |
| `nq_agent/*` | KEEP | Main service loop + Telegram UI + state |
| `strategies/nq_intraday/*` | KEEP | Runtime strategy pipeline |
| `strategies/nq_intraday/signal_policy.py` | KEEP | Central signal gating |
| `strategies/trading_bots/*` | KEEP | Backtesting-only bot variants |
| `execution/base.py` | KEEP | Execution interfaces |
| `execution/ibkr/*` | KEEP | IBKR execution adapter |
| `learning/*` | KEEP | Bandit + contextual learning + ML filter + trade DB |
| `storage/*` | KEEP | Async SQLite queue (enabled in config) |
| `utils/*` | KEEP | Cross-cutting helpers |

### Removed Packages (DELETE)

| Path | Decision | Reason |
|------|----------|--------|
| `agentic/*` | DELETE | Optional subsystem; untested; removed to reduce surface area |
| `monitor/*` | DELETE | Desktop UI not referenced or tested |
| `prop_firm/*` | DELETE | Optional guardrails not active; removed to reduce surface area |
| `policy/*` | DELETE | Replaced by `strategies/nq_intraday/signal_policy.py` |
| `execution/tradovate/*` | DELETE | Unused adapter; IBKR-only execution |
| `learning/meta_learner.py` | DELETE | Unwired scaffold |
| `learning/regime_adaptive.py` | DELETE | Unwired scaffold |
| `learning/risk_metrics.py` | DELETE | Unwired scaffold |
| `backtesting/*` | DELETE | Unused package (scripts do not import) |
| `utils/features.py` | DELETE | Unreferenced |

---

## Scripts (`scripts/`)

All scripts are retained and categorized in `docs/SCRIPTS_TAXONOMY.md`.  
Backtesting scripts remain for offline analysis.

---

## Configuration (`config/`)

| Path | Decision | Role |
|------|----------|------|
| `config.yaml` | KEEP | Primary configuration |
| `markets/*.yaml` | KEEP | Per-market overrides (NQ/ES/GC) |

Split config files were removed (unused by runtime).

---

## Documentation (`docs/`)

All docs listed in `docs/DOC_HIERARCHY.md` are retained and aligned with current paths.  
Non-canonical docs (e.g., GitHub Actions guide, TODO ledger) were removed.

---

## Tests (`tests/`)

All tests are retained except `tests/test_trading_bot_routing.py` (removed with runtime trading-bot routing).

---

## Root Files (KEEP)

`README.md`, `pyproject.toml`, `pytest.ini`, `env.example`, `Dockerfile`, `.gitignore`, `.cursorignore`

---

## Runtime/Build Artifacts (DELETE)

`data/`, `logs/`, `.pytest_cache/`, `htmlcov/`, `__pycache__/`, `*.egg-info/`  
Removed via `scripts/maintenance/purge_runtime_artifacts.sh`.
