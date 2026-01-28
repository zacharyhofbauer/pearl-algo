# Repository Inventory Ledger

Generated: 2026-01-21  
Updated: 2026-01-28  
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
| `market_agent/*` | KEEP | Main service loop + Telegram UI + state |
| `trading_bots/pearl_bot_auto.py` | KEEP | Main runtime strategy (single-file, from Pine Scripts) |
| `execution/base.py` | KEEP | Execution interfaces |
| `execution/ibkr/*` | KEEP | IBKR execution adapter |
| `learning/*` | KEEP | Bandit + contextual learning + ML filter + trade DB |
| `storage/*` | KEEP | Async SQLite queue (enabled in config) |
| `utils/*` | KEEP | Cross-cutting helpers |

Note: `trading_bots/` contains only `pearl_bot_auto.py` — all other strategy variants have been consolidated into this single implementation.

### Current Tree Only (NO DELETE ENTRIES)

This ledger tracks the **current tree** only. Historical deletions are recorded in VCS history,
not in this document.

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

## Models (`models/`)

| Path | Decision | Role |
|------|----------|------|
| `signal_filter_v1.joblib` | KEEP | ML filter artifact (shadow mode) |

---

## Resources (`resources/`)

| Path | Decision | Role |
|------|----------|------|
| `misc/pearlLogo.png` | KEEP | Branding asset for docs/visuals |
| `pinescript/pearlbot/*` | KEEP | Source Pine scripts for strategy lineage |

---

## Dev Environment (`.devcontainer/`)

| Path | Decision | Role |
|------|----------|------|
| `devcontainer.json` | KEEP | Dev container configuration |
| `Dockerfile` | KEEP | Dev container image definition |

---

## CI / Automation (`.github/`)

| Path | Decision | Role |
|------|----------|------|
| `workflows/ci.yml` | KEEP | CI pipeline |
| `dependabot.yml` | KEEP | Dependency update policy |

---

## Tests (`tests/`)

All tests under `tests/` are retained as part of the canonical suite.

---

## Root Files (KEEP)

`README.md`, `pyproject.toml`, `Makefile`, `mypy.ini`, `pytest.ini`, `env.example`, `Dockerfile`, `.gitignore`, `.cursorignore`

---

## Runtime/Build Artifacts (DELETE)

`data/`, `logs/`, `.pytest_cache/`, `htmlcov/`, `__pycache__/`, `*.egg-info/`  
Removed via `scripts/maintenance/purge_runtime_artifacts.sh`.
