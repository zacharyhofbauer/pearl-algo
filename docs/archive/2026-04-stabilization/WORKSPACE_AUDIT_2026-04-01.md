# Workspace Audit - 2026-04-01

This document captures the post-revamp workspace layout while live trading remained online.
It is intentionally operational rather than aspirational: the goal is to reduce confusion
about which paths are active now, which are historical, and which are just generated noise.

## Current ground truth

- Canonical repo root: `/home/pearlalgo/projects/pearl-algo`
- Separate runtime dependency outside the repo: `/home/pearlalgo/ibkr`
- Only one Git repository exists under `/home/pearlalgo`
- Live trading was left running during this audit

## Runtime split discovered

As of 2026-04-01, the running processes were not aligned on the same state directory:

- Live agent process:
  `/home/pearlalgo/pearl-algo-workspace/.venv/bin/python -m pearlalgo.market_agent.main --config /home/pearlalgo/pearl-algo-workspace/config/accounts/tradovate_paper.yaml --data-dir /home/pearlalgo/pearl-algo-workspace/data/agent_state/MNQ`
- Dashboard API process:
  `/home/pearlalgo/pearl-algo-workspace/.venv/bin/python scripts/pearlalgo_web_app/api_server.py --data-dir data/tradovate/paper --port 8001`

This means trading, analytics, and dashboard views can disagree even when each process is
"working" from its own perspective.

## State directory classification

### Active now

- `data/agent_state/MNQ`
  - This is the current live agent state root.
  - `performance.json` contains the current post-revamp trade run.
  - `tradovate_fills.json` is current through the audit window.
  - `trades.db` exists but currently contains only `audit_events`, not the historical
    `trades` table expected by older analytics code.

### Historically active / currently stale

- `data/tradovate/paper`
  - This appears to be the prior Tradovate Paper state root used by the API/web layer and
    earlier operational scripts.
  - It still contains the rich historical SQLite schema (`trades`, `signal_events`,
    `trade_features`, `cycle_diagnostics`, etc.).
  - It is no longer aligned with the live April 1 runtime data.

- `data/agent_state/NQ`
  - Legacy default state path from older market-based defaults.
  - Still referenced by defaults, docs, and utility scripts.
  - Contains an older SQLite database with a `trades` table, but this is not the live path.

### Archived

- `data/archive/ibkr_virtual`
  - Archived IBKR virtual-trading state.
- `data/agent_state/TV_PAPER_archived_20260218`
  - Explicitly archived Tradovate Paper state.
- `scripts/_archived`
  - Historical migration, verification, and one-off maintenance scripts.

## Main sources of confusion

- Launchers disagree about default state roots.
  - `scripts/lifecycle/agent.sh` defaults to `data/agent_state/<MARKET>`
  - `pearl.sh` starts the API against `data/tradovate/paper`
- Docs still describe `data/tradovate/paper` as the single active state directory.
- Some defaults and utilities still assume `data/agent_state/NQ`.
- Legacy service templates still reference `/home/pearlalgo/PearlAlgoWorkspace`, which no
  longer exists.

## Generated artifacts vs. important data

Important runtime/history:

- `data/agent_state/*`
- `data/tradovate/paper`
- `logs/agent_*.log`
- `logs/api_*.log`

Generated and safe to clean:

- `htmlcov/` (already cleaned on 2026-04-01)
- `.pytest_cache/` (already cleaned on 2026-04-01)
- repo-local `__pycache__/` trees outside `.venv/` (already cleaned on 2026-04-01)
- old rotated logs under `logs/`
- stale exports and one-off runtime scratch files

Potentially dangerous to touch while live:

- anything under the live agent's `--data-dir`
- active PID files
- launcher scripts currently responsible for the live process

## Recommended next cleanup sequence

Do not execute this sequence while positions are open or while the user wants zero runtime risk.

1. Choose one canonical runtime state root for Tradovate Paper.
2. Point agent, API, health checks, and diagnostics to that same root.
3. Mark non-canonical state roots as archived/read-only.
4. Repair or remove tools that still assume `data/agent_state/NQ` or `data/tradovate/paper`.
5. Only after runtime alignment, consider moving the repo to a cleaner home layout such as:
   - code: `/home/pearlalgo/projects/pearl-algo`
   - mutable runtime state: `/home/pearlalgo/var/pearl-algo`

## Audit command

Use the read-only runtime audit command added during this audit:

```bash
python3 scripts/ops/audit_runtime_paths.py
python3 scripts/ops/audit_runtime_paths.py --json
```
