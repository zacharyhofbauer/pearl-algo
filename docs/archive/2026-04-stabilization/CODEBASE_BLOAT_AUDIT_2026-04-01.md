# Codebase Bloat Audit - 2026-04-01

This audit was performed after the recent revamp while live trading remained online.
The goal is to identify legacy clutter, stale references, duplicated entrypoints,
and generated artifacts without touching strategy logic or interrupting runtime.

## Executive summary

The repo is not structurally out of control, but it has accumulated four distinct
types of bloat:

1. Large local runtime/build artifacts that are correctly ignored by Git but still
   make the workspace feel heavy.
2. Archived and backup files that are useful for forensic recovery but now compete
   with the live path in search results and human memory.
3. Documentation and operational drift: multiple files still describe old workspace
   paths or old state roots.
4. A duplicate launcher situation: `pearl.sh` and `pearlalgo.sh` both exist, and
   the older name is still referenced by active code.

## Current bulk by top-level path

Approximate local disk usage during the audit:

- `.venv/` - `2.2G`
- `apps/pearl-algo-app/` - `815M`
- `data/` - `497M`
- `logs/` - `316M`
- `.git/` - `36M`
- `htmlcov/` - `16M`
- `tests/` - `8.7M`
- `src/` - `4.6M`

Interpretation:

- Most of the size is not source code.
- The repo feels large mainly because it co-locates code, runtime state, logs,
  frontend dependencies, and the Python virtualenv.

## Generated/local artifact bloat

These are large but mostly expected local artifacts:

- Python virtualenv: `.venv/`
- Frontend dependencies: `apps/pearl-algo-app/node_modules/` (`636M`)
- Frontend build output: `apps/pearl-algo-app/.next/` (`177M`)
- Runtime logs: `logs/` (`316M`)
- Runtime state/history: `data/` (`497M`)
- Test coverage artifacts: `.coverage`, `htmlcov/`, `.pytest_cache/`
- `__pycache__/` trees across `src/`, `tests/`, and `scripts/`

Good news:

- These are already mostly ignored by `.gitignore`.
- They are local bloat, not version-control bloat.

## State/history bloat

State storage is the biggest conceptual source of confusion.

Disk usage by state subtree:

- `data/tradovate/paper` - `290M`
- `data/archive/ibkr_virtual` - `180M`
- `data/agent_state/MNQ` - `18M`
- `data/archive/corrupt-feb20` - `7.8M`
- `data/agent_state/TV_PAPER_archived_20260218` - `736K`
- `data/agent_state/NQ` - `440K`
- `data/agent_state/agent_TV_PAPER.db` - `0`

Key observations:

- `data/tradovate/paper` still holds the heaviest legacy state.
- `data/archive/ibkr_virtual` is large but clearly archival.
- `data/agent_state/MNQ` is the current live runtime root.
- `data/agent_state/NQ` is small but dangerous because defaults and docs still
  reference it.
- `data/agent_state/agent_TV_PAPER.db` appears to be an empty orphan file.

## Backup/config sprawl

The `config/` tree contains both live configuration and multiple ignored backup files:

- `config/accounts/tradovate_paper.yaml`
- `config/accounts/tradovate_paper_eval.yaml`
- 6 backup variants of `tradovate_paper.yaml`
- 2 backup variants of `base.yaml`
- 2 backup variants of `config.yaml`

These are ignored by Git, which is good, but they still create search-path and
selection noise for humans and tools.

Update on 2026-04-01:

- the backup copies have now been moved out of the live `config/` tree into
  `~/var/pearl-algo/backups/config/`
- `config/` is now materially cleaner for search and manual edits
- `config/accounts/tradovate_paper_eval.yaml` remains preserved as an alternate
  overlay, but it is not the canonical live account path
- the live agent and API have now been cut over to
  `config/live/tradovate_paper.yaml` and `data/agent_state/MNQ`

## Archived script sprawl

Archived scripts under `scripts/_archived/`:

- file count: `22`

This is acceptable as an archive, but it should be treated as a quarantine zone,
not as a place people casually search for operational truth.

## Documentation drift

The docs surface is fairly large for a single repo:

- total docs files: `28`

Not all of these are problematic, but several are historical, completion-note,
or rollout-specific documents that can become stale fast:

- `DEPLOYMENT_COMPLETE.md`
- `PROJECT_SUMMARY.md`
- `MARKET_AGENT_GUIDE.md`
- `TESTING_GUIDE.md`
- `UI_AUDIT_GUIDE.md`
- `ACCOUNT_GUIDE.md`
- dated notes like `2026-03-25.md` and `2026-03-26.md`

This is not “bad” documentation volume, but it does mean outdated advice can linger.

Update on 2026-04-01:

- a new `docs/archive/` quarantine area is now in place
- clearly historical rollout/setup notes and dated journal entries have been
  moved there so the active `docs/` surface is cleaner
- repo-local coverage and cache artifacts (`htmlcov/`, `.coverage`,
  `.pytest_cache/`, repo `__pycache__/`) were cleaned after the cutover

## Legacy reference counts

Reference counts across `docs/`, `scripts/`, `src/`, and `tests/`:

- `PearlAlgoWorkspace` - `11` files
- `data/tradovate/paper` - `10` files
- `data/agent_state/NQ` - `12` files
- `agent_TV_PAPER` - `6` files

Interpretation:

- The repo still contains a meaningful amount of pre-revamp mental model drift.
- The most dangerous references are not in archive folders; several are in active
  operational docs or helper scripts.

## Duplicate launcher drift

Top-level launchers:

- `pearl.sh`
- `pearlalgo.sh`

These files are not identical.

This matters because `pearlalgo.sh` is still referenced by active code:

- `src/pearlalgo/market_agent/data_fetcher.py` triggers
  `./pearlalgo.sh soft-restart` on stale-bar restart logic.
- `AGENTS.md` still presents `pearlalgo.sh` as the entrypoint.

This makes `pearlalgo.sh` operationally important even though `pearl.sh` appears
to be the better-maintained control script now.

## Tracked workspace/editor bloat

Tracked editor/workspace-specific files:

- `.claude/settings.local.json`
- `.cursor/plans/pearlalgo_major_restructure_eb368845.plan.md`
- `.cursor/rules/rollback-safety.mdc`
- `.cursor/settings.json`

These are version-control bloat rather than disk-usage bloat. They may be useful
to a small local workflow, but they are not core product source.

## Notable operational risk items discovered during bloat audit

These are not “size bloat,” but they are legacy residue that can still cause bad
operational decisions:

- `scripts/health_check.py` still hardcodes both a concrete API key and the old
  `data/tradovate/paper/trades.db` path.
- `scripts/monitoring/doctor_cli.py` still defaults to `data/agent_state/NQ/trades.db`
  and imports the removed learning trade DB path.
- Several docs still describe old state roots as if they were current.
- Service templates previously referenced `/home/pearlalgo/PearlAlgoWorkspace`.

## What is safe to do before the next clean restart

These items are strategy-safe and runtime-safe if done carefully:

1. Keep auditing and documenting canonical paths.
2. Consolidate docs so one file owns “current runtime truth”.
3. Turn `pearlalgo.sh` into a thin compatibility shim to `pearl.sh`, or otherwise
   formally declare which launcher is canonical.
4. Move config backups into a single quarantine folder outside `config/`.
5. Mark archive folders clearly as read-only historical material.
6. Remove tracked editor-specific files from Git if they are not intentionally shared.

## What should wait until a controlled maintenance window

These are cleanup tasks that should be done only when you are comfortable with a
monitored restart window:

1. Delete or relocate non-canonical state roots.
2. Remove stale rotated logs in bulk.
3. Repoint remaining health/doctor/ops scripts to the canonical state root.
4. Retire old launcher names if active code has been updated to the canonical one.
5. Move the repo to `~/projects/pearl-algo` and move runtime state/logs to
   `~/var/pearl-algo/` if you want a truly clean project layout.

## Recommended home-directory structure

The correct end-state is:

- repo: `~/projects/pearl-algo`
- runtime state: `~/var/pearl-algo/state/`
- runtime logs: `~/var/pearl-algo/logs/`
- archives/backups: `~/var/pearl-algo/archive/` and `~/var/pearl-algo/backups/`

This is already partially prepared on disk, but the repo should not be moved
in the same hour as a market reopen unless you have a full rollback window.

## Strong recommendation

Do not change strategy files, signal generation, or execution logic as part of this
cleanup phase.

Treat cleanup in three layers:

1. **Documentation truth**
   - make sure humans read the right path and command names.
2. **Operational truth**
   - make sure launchers, health checks, restart hooks, and APIs agree on one state root.
3. **Storage cleanup**
   - only after the first two are stable, archive or delete old state/log/build clutter.
